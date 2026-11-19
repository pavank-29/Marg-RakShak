"""Real-Time Fleet & Vehicle Tracking Endpoints.
Architecture inspired by TrackPulse 1-second GPS stream and LERP engine.
Provides high-frequency WebSocket real-time telemetry streaming and REST fleet status.
"""
import asyncio
import logging
import time
from typing import Dict, List, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.ml.model_manager import ml_manager
from app.ml.schemas import RiskPredictionRequest
from app.ml.feature_engineering import haversine_distance

logger = logging.getLogger(__name__)

router = APIRouter()


class VehicleLocationPayload(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = "Fleet Vehicle"
    vehicleType: Optional[str] = "car"
    color: Optional[str] = "#3b82f6"
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    speed: Optional[float] = 0.0
    heading: Optional[float] = 0.0
    accuracy: Optional[float] = 10.0
    altitude: Optional[float] = None
    timestamp: Optional[float] = None


# In-memory active tracker registry: id -> dict
active_trackers: Dict[str, dict] = {}
active_connections: Dict[str, WebSocket] = {}
tracker_risk_cache: Dict[str, dict] = {}
client_rate_limits: Dict[str, List[float]] = {}

INACTIVITY_TIMEOUT_SEC = 60
RISK_EVAL_INTERVAL_SEC = 3.0
RISK_EVAL_MIN_DISTANCE_M = 25.0
MAX_PACKETS_PER_SEC = 35


def _compute_risk_sync(lat: float, lng: float, speed: float, vehicle_type: str) -> dict:
    """Synchronous risk calculation executed in worker thread to prevent event loop blocking."""
    try:
        req = RiskPredictionRequest(
            latitude=lat,
            longitude=lng,
            current_speed=max(0.0, float(speed or 0.0)),
            vehicle_type=vehicle_type or "CAR",
            speed_limit=40.0,
        )
        pred = ml_manager.predict_risk(req)
        return {
            "riskScore": pred.risk_score,
            "riskLevel": pred.risk_level,
            "alertRequired": pred.alert_required,
            "nearestHotspot": pred.nearest_hotspot.model_dump() if pred.nearest_hotspot else None,
            "contributingFactors": pred.contributing_factors or [],
        }
    except Exception as e:
        logger.warning(f"Error computing tracker risk: {e}")
        return {}


async def evaluate_tracker_risk_async(
    tracker_id: str, lat: float, lng: float, speed: float, vehicle_type: str
) -> dict:
    """Evaluate real-time risk with spatial/temporal throttling, offloaded to worker thread."""
    now = time.time()
    cached = tracker_risk_cache.get(tracker_id)
    if cached:
        time_elapsed = now - cached.get("evaluated_at", 0)
        dist_moved = haversine_distance(lat, lng, cached.get("lat", lat), cached.get("lng", lng))
        if time_elapsed < RISK_EVAL_INTERVAL_SEC and dist_moved < RISK_EVAL_MIN_DISTANCE_M:
            return cached.get("result", {})

    res = await run_in_threadpool(_compute_risk_sync, lat, lng, speed, vehicle_type)
    tracker_risk_cache[tracker_id] = {
        "evaluated_at": now,
        "lat": lat,
        "lng": lng,
        "result": res,
    }
    return res


def prune_inactive_trackers() -> List[str]:
    """Remove vehicles that have not transmitted in over 60 seconds."""
    now = time.time()
    stale_ids = [
        uid for uid, info in list(active_trackers.items())
        if now - info.get("updatedAt", now) > INACTIVITY_TIMEOUT_SEC
    ]
    for uid in stale_ids:
        active_trackers.pop(uid, None)
        tracker_risk_cache.pop(uid, None)
        client_rate_limits.pop(uid, None)
    return stale_ids


async def broadcast_to_all(message: dict, skip_id: Optional[str] = None):
    """Concurrent, non-blocking broadcast to all active WebSockets with per-socket timeout."""
    connections = [(cid, conn) for cid, conn in list(active_connections.items()) if cid != skip_id]
    if not connections:
        return

    async def _safe_send(cid: str, conn: WebSocket):
        try:
            await asyncio.wait_for(conn.send_json(message), timeout=0.8)
            return None
        except Exception:
            return cid

    results = await asyncio.gather(*[_safe_send(cid, conn) for cid, conn in connections], return_exceptions=True)
    for res in results:
        if isinstance(res, str):
            active_connections.pop(res, None)
            client_rate_limits.pop(res, None)


async def tracker_sweeper_task():
    """Background periodic task running every 15s to prune inactive trackers and notify clients."""
    while True:
        try:
            await asyncio.sleep(15.0)
            stale_ids = prune_inactive_trackers()
            for uid in stale_ids:
                await broadcast_to_all({"type": "user-disconnected", "id": uid})
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Exception in tracker sweeper task: {e}")


@router.get("/fleet", summary="List active real-time fleet trackers")
def get_active_fleet():
    """Returns all currently transmitting fleet vehicles and their telemetry."""
    prune_inactive_trackers()
    return {
        "success": True,
        "count": len(active_trackers),
        "timestamp": time.time(),
        "fleet": list(active_trackers.values()),
    }


@router.post("/update", summary="REST endpoint to push single location telemetry update")
async def push_location_update(payload: VehicleLocationPayload):
    """Fallback REST endpoint for devices without WebSocket support."""
    now = time.time()
    tracker_id = payload.id or f"vehicle-{int(now)}"

    risk_info = await evaluate_tracker_risk_async(
        tracker_id, payload.latitude, payload.longitude,
        float(payload.speed or 0.0), payload.vehicleType or "car"
    )

    existing = active_trackers.get(tracker_id, {})
    history = existing.get("history", [])
    history.append({
        "lat": payload.latitude,
        "lng": payload.longitude,
        "heading": float(payload.heading or 0.0),
        "timestamp": now,
    })
    if len(history) > 20:
        history.pop(0)

    tracker_info = {
        "id": tracker_id,
        "name": payload.name or existing.get("name") or "Fleet Vehicle",
        "vehicleType": payload.vehicleType or existing.get("vehicleType") or "car",
        "color": payload.color or existing.get("color") or "#3b82f6",
        "latitude": payload.latitude,
        "longitude": payload.longitude,
        "speed": round(payload.speed or 0.0, 1),
        "heading": round(payload.heading or 0.0, 1),
        "accuracy": round(payload.accuracy or 10.0, 1),
        "altitude": payload.altitude,
        "timestamp": payload.timestamp or now,
        "updatedAt": now,
        "history": history,
        "riskScore": risk_info.get("riskScore", 0.0),
        "riskLevel": risk_info.get("riskLevel", "LOW"),
        "alertRequired": risk_info.get("alertRequired", False),
        "nearestHotspot": risk_info.get("nearestHotspot"),
        "contributingFactors": risk_info.get("contributingFactors", []),
    }

    active_trackers[tracker_id] = tracker_info

    # Broadcast to all connected clients
    await broadcast_to_all({"type": "location-update", "data": tracker_info})

    return {"success": True, "tracker": tracker_info}


@router.websocket("/ws/{client_id}")
async def tracking_websocket(websocket: WebSocket, client_id: str):
    """High-frequency WebSocket stream for 1-second GPS location broadcast."""
    await websocket.accept()
    active_connections[client_id] = websocket

    try:
        # Send initial active fleet snapshot
        prune_inactive_trackers()
        await websocket.send_json({
            "type": "init-fleet",
            "fleet": list(active_trackers.values()),
        })

        while True:
            data = await websocket.receive_json()
            now = time.time()

            # Handle ping-pong latency check
            if data.get("type") == "ping":
                await websocket.send_json({
                    "type": "pong",
                    "timestamp": now,
                })
                continue

            # Rate-limiting check to prevent network flooding (up to 35 packets/sec)
            times = client_rate_limits.get(client_id, [])
            recent_times = [t for t in times if now - t < 1.0]
            if len(recent_times) >= MAX_PACKETS_PER_SEC:
                continue
            recent_times.append(now)
            client_rate_limits[client_id] = recent_times

            # Validate coordinates (-90 to 90 lat, -180 to 180 lng)
            try:
                lat = float(data.get("latitude"))
                lng = float(data.get("longitude"))
            except (TypeError, ValueError):
                continue

            if lat < -90 or lat > 90 or lng < -180 or lng > 180:
                continue

            existing = active_trackers.get(client_id, {})
            history = existing.get("history", [])
            history.append({
                "lat": lat,
                "lng": lng,
                "heading": float(data.get("heading") or 0.0),
                "timestamp": now,
            })
            if len(history) > 20:
                history.pop(0)

            vtype = data.get("vehicleType") or existing.get("vehicleType") or "car"
            vspeed = float(data.get("speed") or 0.0)
            risk_info = await evaluate_tracker_risk_async(client_id, lat, lng, vspeed, vtype)

            tracker_info = {
                "id": client_id,
                "name": data.get("name") or existing.get("name") or f"Fleet #{client_id[:6]}",
                "vehicleType": vtype,
                "color": data.get("color") or existing.get("color") or "#3b82f6",
                "latitude": lat,
                "longitude": lng,
                "speed": round(vspeed, 1),
                "heading": round(float(data.get("heading") or 0.0), 1),
                "accuracy": round(float(data.get("accuracy") or 10.0), 1),
                "altitude": data.get("altitude"),
                "timestamp": data.get("timestamp") or now,
                "updatedAt": now,
                "history": history,
                "riskScore": risk_info.get("riskScore", 0.0),
                "riskLevel": risk_info.get("riskLevel", "LOW"),
                "alertRequired": risk_info.get("alertRequired", False),
                "nearestHotspot": risk_info.get("nearestHotspot"),
                "contributingFactors": risk_info.get("contributingFactors", []),
            }
            active_trackers[client_id] = tracker_info

            # Broadcast to all connected clients concurrently
            await broadcast_to_all({"type": "location-update", "data": tracker_info})

    except WebSocketDisconnect:
        active_connections.pop(client_id, None)
        active_trackers.pop(client_id, None)
        tracker_risk_cache.pop(client_id, None)
        client_rate_limits.pop(client_id, None)

        # Notify others
        await broadcast_to_all({"type": "user-disconnected", "id": client_id})
    except Exception as e:
        logger.warning(f"WebSocket client {client_id} disconnected with exception: {e}")
        active_connections.pop(client_id, None)
        active_trackers.pop(client_id, None)
        tracker_risk_cache.pop(client_id, None)
        client_rate_limits.pop(client_id, None)
        await broadcast_to_all({"type": "user-disconnected", "id": client_id})
