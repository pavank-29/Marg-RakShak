"""Road Routing and Alternative Route Navigation API Endpoints with Real-Time Traffic."""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.services.routing_service import RoutingService
from app.services.traffic_service import TrafficService

logger = logging.getLogger(__name__)

router = APIRouter()


class CoordinatePoint(BaseModel):
    lat: float = Field(..., ge=-90.0, le=90.0, description="Latitude in decimal degrees")
    lng: float = Field(..., ge=-180.0, le=180.0, description="Longitude in decimal degrees")
    name: Optional[str] = Field(None, description="Optional human-readable label")


class RouteCalculationRequest(BaseModel):
    source: CoordinatePoint
    destination: CoordinatePoint
    waypoints: Optional[List[CoordinatePoint]] = Field(default=[], description="Optional intermediate stops in sequence")
    vehicle_type: Optional[str] = Field(default="car", description="car, bike, or emergency")
    alternatives: Optional[bool] = Field(default=True, description="Whether to compute feasible road alternative options")
    with_traffic: Optional[bool] = Field(default=True, description="Whether to compute real-time segment-based traffic congestion")


class RouteCalculationResponse(BaseModel):
    success: bool = True
    routes: List[Dict[str, Any]]
    traffic_enabled: bool = True
    provider: str
    timestamp: str


@router.post(
    "/calculate",
    response_model=RouteCalculationResponse,
    status_code=status.HTTP_200_OK,
    summary="Calculate road-following route options and alternatives with real-time traffic",
    description="Calculates genuine road routes connecting source and destination with road-segment based traffic congestion."
)
def calculate_route_post(payload: RouteCalculationRequest):
    """Calculates practical road route options and alternatives considering road network, waypoints, and real-time traffic."""
    # Validate source and destination
    if payload.source.lat == payload.destination.lat and payload.source.lng == payload.destination.lng:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source and destination coordinates cannot be identical."
        )

    try:
        source_dict = {"lat": payload.source.lat, "lng": payload.source.lng}
        destination_dict = {"lat": payload.destination.lat, "lng": payload.destination.lng}
        waypoints_list = [{"lat": wp.lat, "lng": wp.lng} for wp in (payload.waypoints or [])]

        if payload.with_traffic is not False:
            routes = TrafficService.calculate_traffic_routes(
                source=source_dict,
                destination=destination_dict,
                waypoints=waypoints_list,
                vehicle_type=payload.vehicle_type or "car",
                alternatives=payload.alternatives if payload.alternatives is not None else True,
            )
            traffic_enabled = True
        else:
            routes = RoutingService.calculate_routes(
                source=source_dict,
                destination=destination_dict,
                waypoints=waypoints_list,
                vehicle_type=payload.vehicle_type or "car",
                alternatives=payload.alternatives if payload.alternatives is not None else True,
            )
            traffic_enabled = False

        provider = routes[0].get("provider", "nashik_corridor_engine") if routes else "unknown"

        return RouteCalculationResponse(
            success=True,
            routes=routes,
            traffic_enabled=traffic_enabled,
            provider=provider,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )
    except Exception as e:
        logger.error(f"Route calculation failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Route calculation error: {str(e)}"
        )


@router.get(
    "",
    summary="Convenience GET endpoint for route calculation",
    description="Allows querying routes with query parameters: ?from=lat,lng&to=lat,lng&alternatives=true&with_traffic=true"
)
@router.get("/traffic", summary="Calculate route options with real-time traffic congestion")
def calculate_route_get(
    from_coord: str = Query(..., alias="from", description="Source as 'lat,lng'"),
    to_coord: str = Query(..., alias="to", description="Destination as 'lat,lng'"),
    alternatives: bool = Query(True, description="Request genuine alternatives"),
    vehicle_type: str = Query("car", description="Vehicle type (car, bike, emergency)"),
    with_traffic: bool = Query(True, description="Include real-time segment-based traffic")
):
    """GET endpoint compatible with standard web query format."""
    try:
        from_parts = [float(x.strip()) for x in from_coord.split(",")]
        to_parts = [float(x.strip()) for x in to_coord.split(",")]

        if len(from_parts) != 2 or len(to_parts) != 2:
            raise ValueError("Coordinates must be in 'lat,lng' format.")

        source_dict = {"lat": from_parts[0], "lng": from_parts[1]}
        destination_dict = {"lat": to_parts[0], "lng": to_parts[1]}

        if with_traffic:
            routes = TrafficService.calculate_traffic_routes(
                source=source_dict,
                destination=destination_dict,
                waypoints=[],
                vehicle_type=vehicle_type,
                alternatives=alternatives,
            )
        else:
            routes = RoutingService.calculate_routes(
                source=source_dict,
                destination=destination_dict,
                waypoints=[],
                vehicle_type=vehicle_type,
                alternatives=alternatives,
            )

        provider = routes[0].get("provider", "nashik_corridor_engine") if routes else "unknown"

        return {
            "success": True,
            "primaryRoute": routes[0] if routes else None,
            "routes": routes,
            "traffic_enabled": with_traffic,
            "provider": provider,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"GET route query failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not calculate route: {str(e)}"
        )


@router.get(
    "/corridors",
    summary="Live traffic corridors and bottleneck telemetry across Nashik City",
    description="Returns live flow telemetry and congestion indicators for key Nashik corridors."
)
def get_traffic_corridors():
    """Returns dynamic flow indicators and bottleneck telemetry for key Nashik corridors."""
    try:
        corridors = TrafficService.get_nashik_corridors()
        return {
            "success": True,
            "count": len(corridors),
            "corridors": corridors,
            "traffic_enabled": True,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.warning(f"Error fetching dynamic corridors: {e}")
        # Safe fallback
        return {
            "success": True,
            "count": 0,
            "corridors": [],
            "traffic_enabled": False,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

