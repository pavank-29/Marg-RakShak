"""Road Network Routing Service.
Provides genuine road network routing, multi-route alternative generation,
and travel distance/duration computation without real-time traffic dependencies.
"""
import logging
import math
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import requests

from app.core.config import settings

logger = logging.getLogger(__name__)

# Strategic Arterial Corridors for Realistic Multi-Route Alternatives in Nashik
NASHIK_ARTERIAL_WAYPOINTS = [
    {"name": "Highway Corridor (NH-3 Uddanpul)", "lat": 19.9915, "lng": 73.8015},
    {"name": "City Center Corridor (Old Agra Rd / CBS)", "lat": 19.9982, "lng": 73.7844},
    {"name": "Heritage Corridor (Shalimar / Panchavati)", "lat": 20.0015, "lng": 73.7870},
    {"name": "Inner Arterial (Kathe Galli / Old Adgaon)", "lat": 19.9980, "lng": 73.8080},
    {"name": "Ring Bypass (Untwadi / City Centre)", "lat": 19.9830, "lng": 73.7620},
    {"name": "Western Arterial (Gangapur Rd / Jehan Circle)", "lat": 20.0210, "lng": 73.7635},
    {"name": "Commercial Corridor (College Road / Canada Corner)", "lat": 20.0041, "lng": 73.7661},
    {"name": "Southern Corridor (Nashik Road / Bitco)", "lat": 19.9575, "lng": 73.8340},
    {"name": "Industrial Link (Satpur MIDC)", "lat": 19.9663, "lng": 73.7325},
    {"name": "Southern Industrial Link (Ambad MIDC)", "lat": 19.9460, "lng": 73.7430},
    {"name": "East Panchavati Arterial (Nimani Chowk)", "lat": 20.0105, "lng": 73.7990},
    {"name": "Northern Bypass (Makhmalabad / Peth Road)", "lat": 20.0270, "lng": 73.7920},
]

OSRM_ROUTE_URL = "https://router.project-osrm.org/route/v1/driving"


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Computes great-circle distance in meters between two coordinates."""
    r = 6371000.0  # Earth radius in meters
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2.0) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return r * c


def point_to_segment_distance_meters(
    p_lat: float, p_lng: float,
    a_lat: float, a_lng: float,
    b_lat: float, b_lng: float
) -> float:
    """Calculates perpendicular shortest distance in meters from point P to segment [A, B]."""
    seg_len = haversine_meters(a_lat, a_lng, b_lat, b_lng)
    if seg_len == 0.0:
        return haversine_meters(p_lat, p_lng, a_lat, a_lng)

    mid_lat = math.radians((a_lat + b_lat + p_lat) / 3.0)
    cos_lat = math.cos(mid_lat)
    dx = (b_lng - a_lng) * cos_lat
    dy = (b_lat - a_lat)
    px = (p_lng - a_lng) * cos_lat
    py = (p_lat - a_lat)

    denom = dx * dx + dy * dy
    if denom == 0.0:
        return haversine_meters(p_lat, p_lng, a_lat, a_lng)

    t = max(0.0, min(1.0, (px * dx + py * dy) / denom))
    proj_lat = a_lat + t * (b_lat - a_lat)
    proj_lng = a_lng + t * (b_lng - a_lng)
    return haversine_meters(p_lat, p_lng, proj_lat, proj_lng)


def calculate_path_overlap_ratio(
    path_a: List[List[float]],
    path_b: List[List[float]]
) -> float:
    """Calculates fraction of path B that overlaps within 75m corridor of path A."""
    if not path_a or not path_b:
        return 1.0

    sample_step = max(1, len(path_b) // 40)
    sampled_b = [path_b[i] for i in range(0, len(path_b), sample_step)]
    overlap_count = 0

    for pt in sampled_b:
        min_d = float("inf")
        for i in range(len(path_a) - 1):
            p1 = path_a[i]
            p2 = path_a[i + 1]
            d = point_to_segment_distance_meters(pt[0], pt[1], p1[0], p1[1], p2[0], p2[1])
            if d < min_d:
                min_d = d
            if min_d <= 75.0:
                break
        if min_d <= 75.0:
            overlap_count += 1

    return overlap_count / float(len(sampled_b)) if sampled_b else 1.0


class RoutingService:
    """Service responsible for calculating practical road routes and feasible alternatives.
    Real-time traffic dependencies have been removed from navigation. Travel duration is
    based on standard road network navigation speeds.
    """

    _route_cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
    CACHE_TTL_SEC: float = 300.0  # 5 minutes in-memory cache

    @classmethod
    def _fetch_osrm_route(
        cls,
        points: List[Dict[str, float]],
        alternatives: bool = False
    ) -> List[Dict[str, Any]]:
        """Queries OSRM driving engine for a given coordinate sequence."""
        try:
            coords_str = ";".join([f"{p['lng']},{p['lat']}" for p in points])
            radiuses_str = ";".join(["350" for _ in points])

            params = {
                "overview": "full",
                "geometries": "geojson",
                "steps": "false",
                "alternatives": "true" if alternatives else "false",
                "radiuses": radiuses_str,
            }
            res = requests.get(f"{OSRM_ROUTE_URL}/{coords_str}", params=params, timeout=5.0)
            if res.ok:
                data = res.json()
                if data.get("code") == "Ok" and data.get("routes"):
                    out = []
                    for idx, r in enumerate(data["routes"]):
                        coords = r["geometry"]["coordinates"]
                        path = [[pt[1], pt[0]] for pt in coords]
                        dist_km = round(r["distance"] / 1000.0, 2)
                        dur_min = round(r["duration"] / 60.0, 1)
                        out.append({
                            "path": path,
                            "distance_km": dist_km,
                            "duration_min": dur_min,
                            "provider": "osrm_road_network",
                        })
                    return out
        except Exception as err:
            logger.debug(f"OSRM route query failed: {err}")
        return []

    @classmethod
    def calculate_routes(
        cls,
        source: Dict[str, float],
        destination: Dict[str, float],
        waypoints: Optional[List[Dict[str, float]]] = None,
        vehicle_type: str = "car",
        alternatives: bool = True
    ) -> List[Dict[str, Any]]:
        """Calculate primary and alternative road routes without live traffic data.
        Returns up to 2 distinct, feasible routes connecting source and destination.
        """
        waypoints = waypoints or []

        # Validate input
        if (
            abs(source["lat"] - destination["lat"]) < 1e-6
            and abs(source["lng"] - destination["lng"]) < 1e-6
        ):
            raise ValueError("Source and destination coordinates cannot be identical.")

        # Cache check
        cache_key = (
            f"{round(source['lat'], 4)},{round(source['lng'], 4)}->"
            f"{round(destination['lat'], 4)},{round(destination['lng'], 4)}:"
            f"alt={alternatives}:wp={len(waypoints)}:v={vehicle_type}"
        )
        now = time.time()
        if cache_key in cls._route_cache:
            ts, cached_routes = cls._route_cache[cache_key]
            if now - ts < cls.CACHE_TTL_SEC:
                return cached_routes

        all_pts = [source] + waypoints + [destination]

        # 1. Fetch direct route (and any native alternatives returned by OSRM)
        osrm_routes = cls._fetch_osrm_route(all_pts, alternatives=alternatives and len(waypoints) == 0)

        candidate_routes: List[Dict[str, Any]] = []

        if osrm_routes:
            # Primary route
            direct = osrm_routes[0]
            candidate_routes.append({
                "id": "route-1",
                "label": "Route 1",
                "route_number": 1,
                "distance_km": direct["distance_km"],
                "duration_min": direct["duration_min"],
                "path": direct["path"],
                "is_recommended": True,
                "is_alternative": False,
                "provider": "osrm_road_network",
            })

            # Check if OSRM returned a valid distinct secondary route
            if alternatives and len(osrm_routes) > 1 and len(waypoints) == 0:
                for alt_r in osrm_routes[1:3]:
                    overlap = calculate_path_overlap_ratio(direct["path"], alt_r["path"])
                    if (
                        overlap <= 0.75
                        and alt_r["distance_km"] <= direct["distance_km"] * 1.35
                        and alt_r["duration_min"] <= direct["duration_min"] * 1.45
                    ):
                        candidate_routes.append({
                            "id": "route-2",
                            "label": "Route 2",
                            "route_number": 2,
                            "distance_km": alt_r["distance_km"],
                            "duration_min": alt_r["duration_min"],
                            "path": alt_r["path"],
                            "is_recommended": False,
                            "is_alternative": True,
                            "provider": "osrm_road_network",
                        })
                        break

            # If no distinct alternative was found by OSRM and distance >= 1.5km,
            # evaluate arterial waypoints across Nashik road network
            if alternatives and len(candidate_routes) < 2 and len(waypoints) == 0 and direct["distance_km"] >= 1.5:
                src_tuple = (source["lat"], source["lng"])
                dst_tuple = (destination["lat"], destination["lng"])

                dx = (dst_tuple[1] - src_tuple[1]) * math.cos(math.radians((src_tuple[0] + dst_tuple[0]) / 2.0))
                dy = (dst_tuple[0] - src_tuple[0])
                mag2 = dx * dx + dy * dy

                if mag2 > 0:
                    potential_arterials = []
                    for art in NASHIK_ARTERIAL_WAYPOINTS:
                        d_src = haversine_meters(src_tuple[0], src_tuple[1], art["lat"], art["lng"])
                        d_dst = haversine_meters(dst_tuple[0], dst_tuple[1], art["lat"], art["lng"])
                        if d_src < 800 or d_dst < 800:
                            continue

                        px = (art["lng"] - src_tuple[1]) * math.cos(math.radians((src_tuple[0] + dst_tuple[0]) / 2.0))
                        py = (art["lat"] - src_tuple[0])
                        t = (px * dx + py * dy) / mag2

                        if 0.15 <= t <= 0.85:
                            proj_y = src_tuple[0] + t * (dst_tuple[0] - src_tuple[0])
                            proj_x = src_tuple[1] + t * (dst_tuple[1] - src_tuple[1])
                            offset_m = haversine_meters(art["lat"], art["lng"], proj_y, proj_x)
                            if 300 <= offset_m <= 3500:
                                potential_arterials.append((art, t, offset_m))

                    potential_arterials.sort(key=lambda c: abs(c[1] - 0.5) + (c[2] / 4000.0))

                    for art_item in potential_arterials[:4]:
                        art = art_item[0]
                        alt_pts = [source, {"lat": art["lat"], "lng": art["lng"]}, destination]
                        alt_osrm = cls._fetch_osrm_route(alt_pts, alternatives=False)
                        if not alt_osrm:
                            continue

                        alt_res = alt_osrm[0]
                        if alt_res["distance_km"] > direct["distance_km"] * 1.35:
                            continue
                        if alt_res["duration_min"] > direct["duration_min"] * 1.45:
                            continue

                        overlap = calculate_path_overlap_ratio(direct["path"], alt_res["path"])
                        if overlap <= 0.75:
                            candidate_routes.append({
                                "id": "route-2",
                                "label": "Route 2",
                                "route_number": 2,
                                "distance_km": alt_res["distance_km"],
                                "duration_min": alt_res["duration_min"],
                                "path": alt_res["path"],
                                "is_recommended": False,
                                "is_alternative": True,
                                "provider": "osrm_road_network",
                            })
                            break
        else:
            # Fallback interpolated direct route if network service is unreachable
            straight_m = haversine_meters(source["lat"], source["lng"], destination["lat"], destination["lng"])
            dist_km = round(max(0.2, (straight_m * 1.25) / 1000.0), 2)
            dur_min = round(max(1.0, (dist_km / 35.0) * 60.0), 1)

            pts = [[source["lat"], source["lng"]]]
            for wp in waypoints:
                pts.append([wp["lat"], wp["lng"]])
            pts.append([destination["lat"], destination["lng"]])

            smooth_path = []
            for i in range(len(pts) - 1):
                p1, p2 = pts[i], pts[i + 1]
                smooth_path.append(p1)
                for s in range(1, 10):
                    smooth_path.append([
                        p1[0] + (p2[0] - p1[0]) * (s / 10),
                        p1[1] + (p2[1] - p1[1]) * (s / 10)
                    ])
            smooth_path.append(pts[-1])

            candidate_routes.append({
                "id": "route-1",
                "label": "Route 1",
                "route_number": 1,
                "distance_km": dist_km,
                "duration_min": dur_min,
                "path": smooth_path,
                "is_recommended": True,
                "is_alternative": False,
                "provider": "nashik_corridor_fallback",
            })

        # Enrich each route with standard fields and backward-compatible properties
        # Real-time traffic has been removed from navigation.
        # Notice: traffic_duration_min equals duration_min and traffic_delay_min is 0.0.
        final_routes: List[Dict[str, Any]] = []
        for idx, r in enumerate(candidate_routes[:2]):
            enriched = {
                "id": r.get("id", f"route-{idx + 1}"),
                "label": r.get("label", f"Route {idx + 1}"),
                "route_number": idx + 1,
                "distance_km": r["distance_km"],
                "duration_min": r["duration_min"],
                "path": r["path"],
                "is_recommended": (idx == 0),
                "is_alternative": (idx > 0),
                "provider": r.get("provider", "osrm_road_network"),
                # Backward-compatibility fields without live traffic data
                "traffic_duration_min": r["duration_min"],
                "traffic_delay_min": 0.0,
                "traffic_status": "NORMAL",
                "congestion_percentage": 0,
                "traffic_segments": [],
                "recommendation_reason": (
                    "Recommended: Primary direct road route with optimal navigation time."
                    if idx == 0
                    else "Alternative: Feasible arterial road corridor option."
                ),
            }
            final_routes.append(enriched)

        # Cache results (prune oldest if cache exceeds 100 entries)
        if len(cls._route_cache) > 100:
            oldest_key = min(cls._route_cache.keys(), key=lambda k: cls._route_cache[k][0])
            cls._route_cache.pop(oldest_key, None)
        cls._route_cache[cache_key] = (now, final_routes)

        return final_routes
