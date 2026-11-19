"""Route Safety Engine.
Evaluates navigation corridor safety using spatial proximity to known blackspots,
ML-discovered clusters, and dynamic multi-factor risk inference along sampled route coordinates.
Categorizes routes into 'Fastest Route', 'Safest Route', and 'Balanced Route'.
"""
import logging
import math
from typing import List, Dict, Any, Optional
import numpy as np
from app.ml.feature_engineering import haversine_distance
from app.ml.risk_model import RiskModel
from app.ml.schemas import RouteInput, ScoredRoute, RouteRiskResponse

logger = logging.getLogger(__name__)


class RouteSafetyEngine:
    """Computes comprehensive safety metrics across alternative navigation paths."""

    def __init__(self, risk_model: RiskModel):
        self.risk_model = risk_model

    def sample_path_coordinates(
        self,
        path: List[List[float]],
        sample_step_meters: float = 200.0,
        max_samples: int = 50
    ) -> List[List[float]]:
        """Sub-sample path coordinates at regular distance intervals to avoid excessive evaluation."""
        if not path:
            return []
        if len(path) <= 10:
            return path

        sampled = [path[0]]
        accumulated_dist = 0.0

        for i in range(len(path) - 1):
            p1 = path[i]
            p2 = path[i + 1]
            dist = haversine_distance(p1[0], p1[1], p2[0], p2[1])
            accumulated_dist += dist

            if accumulated_dist >= sample_step_meters:
                sampled.append(p2)
                accumulated_dist = 0.0

            if len(sampled) >= max_samples:
                break

        if path[-1] not in sampled:
            sampled.append(path[-1])

        return sampled

    def evaluate_route(
        self,
        route: RouteInput,
        known_hotspots: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Evaluate spatial and dynamic risk along a single navigation corridor,
        and dynamically generate ML-predicted elevated risk hotspots distinct from verified blackspots.
        """
        context = context or {}
        # Sub-sample path coordinates every ~180 meters
        sampled_coords = self.sample_path_coordinates(route.path, sample_step_meters=180.0, max_samples=75)

        # 1. Identify existing verified blackspots within 200m corridor of the route
        CORRIDOR_BUFFER_METERS = 200.0
        encountered_known: List[Dict[str, Any]] = []

        for spot in known_hotspots:
            s_lat = spot.get("latitude") or spot.get("lat")
            s_lng = spot.get("longitude") or spot.get("lng")
            if s_lat is None or s_lng is None:
                continue

            # Check perpendicular distance or haversine to sampled path points
            min_dist = float("inf")
            for pt in sampled_coords:
                d = haversine_distance(pt[0], pt[1], float(s_lat), float(s_lng))
                if d < min_dist:
                    min_dist = d
                if min_dist <= CORRIDOR_BUFFER_METERS:
                    break

            if min_dist <= CORRIDOR_BUFFER_METERS:
                encountered_known.append({
                    "id": spot.get("id"),
                    "name": spot.get("name", "Verified Blackspot"),
                    "latitude": round(float(s_lat), 6),
                    "longitude": round(float(s_lng), 6),
                    "risk_level": str(spot.get("risk_level") or spot.get("riskLevel") or "HIGH").upper(),
                    "risk_score": round(float(spot.get("risk_score") or spot.get("riskScore") or 0.75), 3),
                    "accident_count": int(spot.get("accident_count") or spot.get("Total Accidents") or 0),
                    "fatalities": int(spot.get("fatalities") or spot.get("Total Fatalities") or 0),
                    "injuries": int(spot.get("injuries") or spot.get("Injuries") or 0),
                    "police_station": spot.get("police_station") or spot.get("Police Station", ""),
                    "road_no": spot.get("road_no") or spot.get("Road Class / No.", ""),
                    "safety_recommendation": spot.get("safety_recommendation") or spot.get("Safety Recommendation", "Exercise caution in verified blackspot corridor."),
                    "source": "KNOWN_BLACKSPOT",
                    "is_predicted": False,
                    "distance_to_route_meters": round(min_dist, 1)
                })

        # 2. Dynamic ML inference along sampled route coordinates
        sampled_predictions: List[Dict[str, Any]] = []
        candidate_risk_points: List[Dict[str, Any]] = []

        for pt in sampled_coords:
            point_data = {
                "latitude": pt[0],
                "longitude": pt[1],
                "current_speed": context.get("current_speed", 35.0),
                "speed_limit": context.get("speed_limit", 40.0),
                "vehicle_type": context.get("vehicle_type", "CAR"),
                "weather": context.get("weather", "CLEAR"),
                "road_condition": context.get("road_condition", "NORMAL"),
                "lighting": context.get("lighting", "DAYLIGHT"),
            }
            pred = self.risk_model.predict(point_data, known_hotspots=known_hotspots)
            sampled_predictions.append({
                "lat": pt[0],
                "lng": pt[1],
                "risk_score": pred.risk_score,
                "risk_level": pred.risk_level,
                "confidence": pred.confidence,
                "factors": pred.contributing_factors
            })

            # Check if this road segment exhibits elevated risk (score >= 0.48 or HIGH/CRITICAL)
            if pred.risk_score >= 0.48 or pred.risk_level in ("HIGH", "CRITICAL"):
                # Filter out points that fall within 250m of an existing verified blackspot
                near_existing = False
                for k_spot in encountered_known:
                    d_k = haversine_distance(pt[0], pt[1], k_spot["latitude"], k_spot["longitude"])
                    if d_k <= 250.0:
                        near_existing = True
                        break

                if not near_existing:
                    candidate_risk_points.append({
                        "lat": pt[0],
                        "lng": pt[1],
                        "risk_score": pred.risk_score,
                        "risk_level": pred.risk_level,
                        "confidence": pred.confidence,
                        "factors": pred.contributing_factors
                    })

        # 3. Spatial Clustering & Deduplication of predicted risk segments
        # Merge adjacent high-risk points within 300m into a single cohesive hotspot
        predicted_hotspots: List[Dict[str, Any]] = []
        clustered_points: List[List[Dict[str, Any]]] = []

        for p in candidate_risk_points:
            assigned = False
            for cluster in clustered_points:
                # Check distance to any point in the cluster
                if any(haversine_distance(p["lat"], p["lng"], cp["lat"], cp["lng"]) <= 300.0 for cp in cluster):
                    cluster.append(p)
                    assigned = True
                    break
            if not assigned:
                clustered_points.append([p])

        # Convert clusters to structured predicted hotspots
        for c_idx, cluster in enumerate(clustered_points):
            # Pick the point with highest risk score as representative
            peak_point = max(cluster, key=lambda x: x["risk_score"])
            combined_factors: List[str] = []
            for cp in cluster:
                for f in cp.get("factors", []):
                    if f not in combined_factors:
                        combined_factors.append(f)

            avg_conf = float(np.mean([cp["confidence"] for cp in cluster]))
            peak_score = float(peak_point["risk_score"])
            peak_level = peak_point["risk_level"]

            # Calculate shortest distance from hotspot centroid to the route polyline
            min_dist_to_route = min(
                haversine_distance(peak_point["lat"], peak_point["lng"], pt[0], pt[1])
                for pt in sampled_coords
            )

            # Classify into meaningful risk categories
            if peak_score >= 0.75:
                cat_desc = "CRITICAL"
                rec_text = "Caution: Machine-learning model detects critical accident risk in this corridor. Significantly reduce speed and maintain high vigilance."
            elif peak_score >= 0.50:
                cat_desc = "HIGH"
                rec_text = "Advisory: Machine-learning model indicates elevated collision probability. Exercise caution and avoid sudden lane changes."
            else:
                cat_desc = "MEDIUM"
                rec_text = "Notice: Moderate risk area predicted along this road stretch. Maintain standard caution."

            predicted_hotspots.append({
                "id": f"pred-{route.route_id}-{c_idx + 1}",
                "name": f"ML Predicted Risk Area #{c_idx + 1}",
                "latitude": round(peak_point["lat"], 6),
                "longitude": round(peak_point["lng"], 6),
                "risk_score": round(peak_score, 3),
                "risk_level": cat_desc,
                "confidence": round(avg_conf, 2),
                "source": "ML_PREDICTED",
                "is_predicted": True,
                "contributing_factors": combined_factors[:4],
                "safety_recommendation": rec_text,
                "uncertainty_note": "Estimated by ML risk model based on roadway geometry, spatial collision density, and operational factors. Not a verified historical blackspot.",
                "distance_to_route_meters": round(min_dist_to_route, 1)
            })

        # 4. Aggregate Route Safety Score & Risk Level
        sampled_risk_scores = [p["risk_score"] for p in sampled_predictions]
        avg_risk = float(np.mean(sampled_risk_scores)) if sampled_risk_scores else 0.20
        max_risk = float(np.max(sampled_risk_scores)) if sampled_risk_scores else 0.20
        aggregate_risk = round(0.70 * avg_risk + 0.30 * max_risk, 3)

        # Hazard penalties: Verified blackspots + Predicted hotspots
        crit_count = sum(1 for h in encountered_known if h["risk_level"] == "CRITICAL")
        high_count = sum(1 for h in encountered_known if h["risk_level"] == "HIGH")
        pred_crit = sum(1 for p in predicted_hotspots if p["risk_level"] == "CRITICAL")
        pred_high = sum(1 for p in predicted_hotspots if p["risk_level"] == "HIGH")

        hotspot_penalty = (crit_count * 12.0) + (high_count * 6.0) + (pred_crit * 8.0) + (pred_high * 4.0) + (len(encountered_known) * 2.0)
        raw_safety = 100.0 - (aggregate_risk * 45.0) - hotspot_penalty
        safety_score = int(max(10, min(98, round(raw_safety))))

        if safety_score >= 80:
            route_risk_level = "LOW"
        elif safety_score >= 60:
            route_risk_level = "MEDIUM"
        elif safety_score >= 40:
            route_risk_level = "HIGH"
        else:
            route_risk_level = "CRITICAL"

        # Explainable factors for the route as a whole
        route_factors = []
        if crit_count > 0:
            route_factors.append(f"Passes {crit_count} verified CRITICAL blackspot(s)")
        if high_count > 0:
            route_factors.append(f"Passes {high_count} verified HIGH-risk corridor(s)")
        if len(encountered_known) > 0 and crit_count == 0 and high_count == 0:
            route_factors.append(f"Passes {len(encountered_known)} verified blackspot(s)")
        if len(predicted_hotspots) > 0:
            route_factors.append(f"{len(predicted_hotspots)} additional elevated-risk area(s) predicted by ML model")

        weather = str(context.get("weather", "CLEAR")).upper()
        if "RAIN" in weather:
            route_factors.append("Adverse weather: Wet roadway reduces surface friction")
        if not route_factors:
            route_factors.append("Clear corridor with minimal accident hazard exposure")

        return {
            "route_id": route.route_id,
            "label": route.label or f"Route {route.route_id}",
            "distance_km": round(float(route.distance_km), 2),
            "duration_minutes": round(float(route.duration_minutes), 1),
            "risk_score": aggregate_risk,
            "safety_score": safety_score,
            "risk_level": route_risk_level,
            "blackspots_count": len(encountered_known),
            "ml_hotspots_count": len(predicted_hotspots),
            "existing_blackspots_count": len(encountered_known),
            "predicted_hotspots_count": len(predicted_hotspots),
            "total_hotspots_count": len(encountered_known) + len(predicted_hotspots),
            "existing_blackspots": encountered_known,
            "predicted_hotspots": predicted_hotspots,
            "contributing_factors": route_factors
        }

    def evaluate_routes(
        self,
        routes: List[RouteInput],
        known_hotspots: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None
    ) -> RouteRiskResponse:
        """Evaluate and classify multiple candidate routes into Fastest, Safest, and Balanced."""
        from datetime import datetime, timezone

        if not routes:
            return RouteRiskResponse(
                routes=[],
                recommended_route_id="",
                evaluation_timestamp=datetime.now(timezone.utc).isoformat()
            )

        scored_list: List[Dict[str, Any]] = []
        for r in routes:
            scored = self.evaluate_route(r, known_hotspots, context)
            scored_list.append(scored)

        # 1. Identify Fastest (minimum duration)
        fastest_route = min(scored_list, key=lambda x: x["duration_minutes"])

        # 2. Identify Safest (highest safety score, lowest risk)
        safest_route = max(scored_list, key=lambda x: x["safety_score"])

        # 3. Identify Balanced (Pareto trade-off between travel time and safety)
        min_time = min(r["duration_minutes"] for r in scored_list)
        max_time = max(max(r["duration_minutes"] for r in scored_list), min_time + 0.1)

        def balanced_score(r):
            time_penalty = (r["duration_minutes"] - min_time) / (max_time - min_time)  # 0 to 1
            safety_norm = r["safety_score"] / 100.0  # 0 to 1
            # 60% safety weight + 40% time efficiency weight
            return (0.60 * safety_norm) + (0.40 * (1.0 - time_penalty))

        balanced_route = max(scored_list, key=balanced_score)

        # Assign categories cleanly
        final_routes: List[ScoredRoute] = []
        for r in scored_list:
            is_fastest = r["route_id"] == fastest_route["route_id"]
            is_safest = r["route_id"] == safest_route["route_id"]
            is_balanced = r["route_id"] == balanced_route["route_id"]

            if is_fastest and is_safest:
                category = "Safest & Fastest Route"
            elif is_safest:
                category = "Safest Route"
            elif is_fastest:
                category = "Fastest Route"
            elif is_balanced:
                category = "Balanced Route"
            else:
                category = "Alternative Corridor"

            final_routes.append(
                ScoredRoute(
                    route_id=r["route_id"],
                    label=r["label"],
                    category=category,
                    distance_km=r["distance_km"],
                    duration_minutes=r["duration_minutes"],
                    risk_score=r["risk_score"],
                    safety_score=r["safety_score"],
                    risk_level=r["risk_level"],
                    blackspots_count=r["blackspots_count"],
                    ml_hotspots_count=r["ml_hotspots_count"],
                    existing_blackspots_count=r.get("existing_blackspots_count", r["blackspots_count"]),
                    predicted_hotspots_count=r.get("predicted_hotspots_count", r["ml_hotspots_count"]),
                    total_hotspots_count=r.get("total_hotspots_count", r["blackspots_count"] + r["ml_hotspots_count"]),
                    existing_blackspots=r.get("existing_blackspots", []),
                    predicted_hotspots=r.get("predicted_hotspots", []),
                    contributing_factors=r["contributing_factors"]
                )
            )

        # Recommended route: Safest route if detour is <= 25%, otherwise Balanced
        time_detour_ratio = (safest_route["duration_minutes"] - fastest_route["duration_minutes"]) / max(1.0, fastest_route["duration_minutes"])
        if time_detour_ratio <= 0.25:
            rec_id = safest_route["route_id"]
        else:
            rec_id = balanced_route["route_id"]

        return RouteRiskResponse(
            routes=final_routes,
            recommended_route_id=rec_id,
            evaluation_timestamp=datetime.now(timezone.utc).isoformat()
        )
