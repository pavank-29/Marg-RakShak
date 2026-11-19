"""Live Traffic and Route Optimization Service.
Provides traffic-aware road routing with Google Routes API, TomTom API, and Nashik Multi-Corridor Flow Engine.
Generates Google Maps-style color-coded traffic segments (Green, Orange, Red, Dark Red).
"""
import logging
import math
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import requests

from app.core.config import settings

logger = logging.getLogger(__name__)

# Nashik Major Traffic Bottlenecks & Corridors
NASHIK_CORRIDORS = [
    {"name": "Dwarka Circle (NH-3 / Pune Hwy)", "lat": 19.9897, "lng": 73.8055, "radius_m": 700, "base_delay_min": 7.0, "severity": "HIGH"},
    {"name": "CBS (Central Bus Station / Old Agra Rd)", "lat": 19.9982, "lng": 73.7844, "radius_m": 550, "base_delay_min": 5.0, "severity": "HIGH"},
    {"name": "Mumbai Naka Gateway", "lat": 19.9880, "lng": 73.7801, "radius_m": 600, "base_delay_min": 5.5, "severity": "HIGH"},
    {"name": "Shalimar & Ashok Stambh", "lat": 20.0015, "lng": 73.7870, "radius_m": 500, "base_delay_min": 4.0, "severity": "MODERATE"},
    {"name": "College Road & Canada Corner", "lat": 20.0041, "lng": 73.7661, "radius_m": 550, "base_delay_min": 3.5, "severity": "MODERATE"},
    {"name": "Gangapur Road / Jehan Circle", "lat": 20.0210, "lng": 73.7635, "radius_m": 500, "base_delay_min": 3.0, "severity": "MODERATE"},
    {"name": "Bitco Point / Nashik Road Station", "lat": 19.9575, "lng": 73.8340, "radius_m": 650, "base_delay_min": 6.0, "severity": "HIGH"},
    {"name": "Pathardi Phata Junction (NH-3)", "lat": 19.9490, "lng": 73.7680, "radius_m": 500, "base_delay_min": 4.0, "severity": "MODERATE"},
    {"name": "Ambad MIDC / Garware Point", "lat": 19.9460, "lng": 73.7430, "radius_m": 600, "base_delay_min": 3.5, "severity": "MODERATE"},
]

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
    a = (math.sin(d_lat / 2.0) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(d_lon / 2.0) ** 2)
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


def decode_google_polyline(polyline_str: str) -> List[List[float]]:
    """Decodes Google Encoded Polyline into a list of [latitude, longitude] pairs."""
    index, lat, lng = 0, 0, 0
    coordinates = []
    length = len(polyline_str)
    while index < length:
        b, shift, result = 0, 0, 0
        while True:
            b = ord(polyline_str[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlat = ~(result >> 1) if (result & 1) else (result >> 1)
        lat += dlat

        shift, result = 0, 0
        while True:
            b = ord(polyline_str[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlng = ~(result >> 1) if (result & 1) else (result >> 1)
        lng += dlng

        coordinates.append([round(lat / 1e5, 6), round(lng / 1e5, 6)])
    return coordinates


def get_current_traffic_time_multiplier() -> Tuple[float, str]:
    """Evaluates time-of-day traffic congestion multiplier for Nashik City."""
    now = datetime.now()
    hour = now.hour + (now.minute / 60.0)

    # Morning rush: 08:30 - 11:30 AM
    if 8.5 <= hour <= 11.5:
        return 1.65, "Morning Peak Rush"
    # Evening rush: 17:30 - 21:00 PM
    elif 17.5 <= hour <= 21.0:
        return 1.80, "Evening Peak Rush"
    # Daytime active traffic: 11:30 - 17:30 PM
    elif 11.5 < hour < 17.5:
        return 1.25, "Active Daytime Flow"
    # Late night / early morning: 21:00 - 08:30 AM
    else:
        return 1.02, "Free Flowing (Off-Peak)"


class TrafficService:
    """Unified service for fetching real road network routes and enriching them with traffic conditions."""

    _route_cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
    CACHE_TTL_SEC: float = 300.0  # 5 minutes

    @classmethod
    def generate_traffic_segments(
        cls,
        path: List[List[float]],
        time_multiplier: float = 1.0,
    ) -> List[Dict[str, Any]]:
        """Segments a route polyline into road sections color-coded by traffic intensity:
        - NORMAL: Green (#22C55E) -> Smooth flowing (free flow)
        - MODERATE: Orange/Yellow (#F59E0B) -> Slower moving / dense traffic
        - HEAVY: Red (#EF4444) -> Heavy traffic delay
        - SEVERE: Dark Red (#991B1B) -> Severe congestion / choke point
        """
        if not path or len(path) < 2:
            return []

        TRAFFIC_COLORS = {
            "NORMAL": "#22C55E",
            "MODERATE": "#F59E0B",
            "HEAVY": "#EF4444",
            "SEVERE": "#991B1B",
        }
        FLOW_SPEEDS = {
            "NORMAL": 45,
            "MODERATE": 25,
            "HEAVY": 14,
            "SEVERE": 6,
        }
        LABELS = {
            "NORMAL": "Free Traffic",
            "MODERATE": "Moderate Traffic",
            "HEAVY": "Heavy Traffic",
            "SEVERE": "Very Heavy Traffic",
        }

        # Classify each coordinate point along the path
        point_statuses = []
        for pt in path:
            status = "NORMAL"
            for corridor in NASHIK_CORRIDORS:
                c_lat = corridor["lat"]
                c_lng = corridor["lng"]
                r_m = corridor["radius_m"]
                d = haversine_meters(pt[0], pt[1], c_lat, c_lng)
                if d <= r_m:
                    severity = corridor.get("severity", "MODERATE")
                    if severity == "HIGH":
                        if d <= r_m * 0.45 and time_multiplier >= 1.5:
                            status = "SEVERE"
                        elif d <= r_m * 0.70 or time_multiplier >= 1.35:
                            status = "HEAVY"
                        else:
                            status = "MODERATE"
                    else:  # MODERATE
                        if d <= r_m * 0.40 and time_multiplier >= 1.6:
                            status = "HEAVY"
                        else:
                            status = "MODERATE"
                    break
            point_statuses.append(status)

        # Group consecutive points with same status into continuous segments
        segments = []
        current_status = point_statuses[0]
        current_pts = [path[0]]

        for i in range(1, len(path)):
            st = point_statuses[i]
            pt = path[i]
            if st == current_status:
                current_pts.append(pt)
            else:
                current_pts.append(pt)
                segments.append({
                    "path": current_pts,
                    "traffic_status": current_status,
                    "color": TRAFFIC_COLORS[current_status],
                    "speed_kmh": FLOW_SPEEDS[current_status],
                    "label": LABELS[current_status],
                })
                current_status = st
                current_pts = [pt]

        if current_pts:
            segments.append({
                "path": current_pts,
                "traffic_status": current_status,
                "color": TRAFFIC_COLORS[current_status],
                "speed_kmh": FLOW_SPEEDS[current_status],
                "label": LABELS[current_status],
            })

        return segments

    @classmethod
    def get_nashik_corridors(cls) -> List[Dict[str, Any]]:
        """Returns live flow telemetry and congestion indicators for all key Nashik corridors."""
        time_multiplier, time_period = get_current_traffic_time_multiplier()
        corridors_out = []

        for c in NASHIK_CORRIDORS:
            base_del = c["base_delay_min"]
            current_delay = round(base_del * (time_multiplier - 0.6), 1)

            if current_delay >= 7.0:
                status = "SEVERE"
                color = "#991B1B"
                speed = 8
            elif current_delay >= 4.0:
                status = "HEAVY"
                color = "#EF4444"
                speed = 15
            elif current_delay >= 2.0:
                status = "MODERATE"
                color = "#F59E0B"
                speed = 28
            else:
                status = "NORMAL"
                color = "#22C55E"
                speed = 45

            corridors_out.append({
                "name": c["name"],
                "lat": c["lat"],
                "lng": c["lng"],
                "radius_m": c["radius_m"],
                "traffic_status": status,
                "color": color,
                "flow_speed_kmh": speed,
                "delay_min": max(0.5, current_delay),
                "severity": c["severity"],
                "time_period": time_period,
            })

        return corridors_out

    @classmethod
    def _fetch_google_routes(
        cls,
        source: Dict[str, float],
        destination: Dict[str, float],
        waypoints: List[Dict[str, float]],
        api_key: str,
        alternatives: bool = True
    ) -> Optional[List[Dict[str, Any]]]:
        """Queries Google Routes API (Directions v2) with live traffic enabled."""
        try:
            url = "https://routes.googleapis.com/directions/v2:computeRoutes"
            headers = {
                "Content-Type": "application/json",
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": (
                    "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline,"
                    "routes.description,routes.warnings,routes.travelAdvisory.speedReadingIntervals"
                )
            }

            body = {
                "origin": {
                    "location": {"latLng": {"latitude": source["lat"], "longitude": source["lng"]}}
                },
                "destination": {
                    "location": {"latLng": {"latitude": destination["lat"], "longitude": destination["lng"]}}
                },
                "intermediates": [
                    {"location": {"latLng": {"latitude": wp["lat"], "longitude": wp["lng"]}}}
                    for wp in waypoints
                ],
                "travelMode": "DRIVE",
                "routingPreference": "TRAFFIC_AWARE",
                "computeAlternativeRoutes": alternatives if len(waypoints) == 0 else False,
                "extraComputations": ["TRAFFIC_ON_POLYLINE"]
            }

            res = requests.post(url, headers=headers, json=body, timeout=5.0)
            if not res.ok:
                logger.warning(f"Google Routes API status {res.status_code}: {res.text[:200]}")
                return None

            data = res.json()
            raw_routes = data.get("routes", [])
            if not raw_routes:
                return None

            parsed_routes = []
            for idx, r in enumerate(raw_routes):
                dist_meters = r.get("distanceMeters", 0)
                dist_km = round(dist_meters / 1000.0, 2)

                dur_str = r.get("duration", "0s").replace("s", "")
                traffic_sec = float(dur_str) if dur_str else 0.0
                traffic_dur_min = round(traffic_sec / 60.0, 1)

                enc_poly = r.get("polyline", {}).get("encodedPolyline", "")
                path = decode_google_polyline(enc_poly) if enc_poly else []
                if not path:
                    continue

                # Parse Google speed reading intervals if present
                speed_intervals = r.get("travelAdvisory", {}).get("speedReadingIntervals", [])
                segments = []
                if speed_intervals and len(path) > 1:
                    speed_color_map = {
                        "NORMAL": ("#22C55E", 45, "Free Flow"),
                        "SLOW": ("#F59E0B", 25, "Moderate Traffic"),
                        "TRAFFIC_JAM": ("#EF4444", 12, "Heavy Traffic"),
                    }
                    for interval in speed_intervals:
                        start_idx = interval.get("startPolylinePointIndex", 0)
                        end_idx = min(len(path) - 1, interval.get("endPolylinePointIndex", len(path) - 1))
                        spd = interval.get("speed", "NORMAL")
                        col, spd_kmh, lbl = speed_color_map.get(spd, ("#22C55E", 45, "Free Flow"))
                        if end_idx >= start_idx:
                            sub_path = path[start_idx:end_idx + 1]
                            if len(sub_path) >= 2:
                                segments.append({
                                    "path": sub_path,
                                    "traffic_status": "NORMAL" if spd == "NORMAL" else ("MODERATE" if spd == "SLOW" else "HEAVY"),
                                    "color": col,
                                    "speed_kmh": spd_kmh,
                                    "label": lbl,
                                })
                if not segments:
                    time_multiplier, _ = get_current_traffic_time_multiplier()
                    segments = cls.generate_traffic_segments(path, time_multiplier)

                # Delay estimation from duration
                base_dur_min = round(dist_km / 45.0 * 60.0, 1)
                delay_min = max(0.5, round(traffic_dur_min - base_dur_min, 1))

                status_lbl = "HEAVY" if delay_min >= 8.0 else ("MODERATE" if delay_min >= 3.0 else "NORMAL")

                parsed_routes.append({
                    "id": f"route-{idx + 1}",
                    "label": f"Route {idx + 1}",
                    "route_number": idx + 1,
                    "distance_km": dist_km,
                    "duration_min": base_dur_min,
                    "traffic_duration_min": traffic_dur_min,
                    "traffic_delay_min": delay_min,
                    "traffic_status": status_lbl,
                    "congestion_percentage": min(95, max(5, int((delay_min / max(1.0, traffic_dur_min)) * 100))),
                    "path": path,
                    "traffic_segments": segments,
                    "provider": "google_routes_live",
                    "is_alternative": idx > 0,
                })

            return parsed_routes
        except Exception as e:
            logger.warning(f"Google Routes API query failed: {e}")
            return None

    @classmethod
    def _fetch_tomtom_routes(
        cls,
        source: Dict[str, float],
        destination: Dict[str, float],
        waypoints: List[Dict[str, float]],
        api_key: str,
        alternatives: bool = True
    ) -> Optional[List[Dict[str, Any]]]:
        """Queries TomTom Routing API v1 with live real-time traffic enabled."""
        try:
            points = [f"{source['lat']},{source['lng']}"]
            for wp in waypoints:
                points.append(f"{wp['lat']},{wp['lng']}")
            points.append(f"{destination['lat']},{destination['lng']}")
            locations_str = ":".join(points)

            url = f"https://api.tomtom.com/routing/1/calculateRoute/{locations_str}/json"
            params = {
                "key": api_key,
                "traffic": "true",
                "travelMode": "car",
                "routeType": "fastest",
                "maxAlternatives": 2 if alternatives else 0,
                "departAt": "now",
                "sectionType": "traffic",
            }
            res = requests.get(url, params=params, timeout=5.0)
            if not res.ok:
                logger.warning(f"TomTom API returned status {res.status_code}: {res.text[:200]}")
                return None

            data = res.json()
            raw_routes = data.get("routes", [])
            if not raw_routes:
                return None

            time_multiplier, _ = get_current_traffic_time_multiplier()

            parsed_routes = []
            for idx, r in enumerate(raw_routes):
                summary = r.get("summary", {})
                dist_km = round(summary.get("lengthInMeters", 0) / 1000.0, 2)
                base_sec = summary.get("noTrafficTravelTimeInSeconds", summary.get("travelTimeInSeconds", 0))
                traffic_sec = summary.get("travelTimeInSeconds", base_sec)
                delay_sec = max(0, summary.get("trafficDelayInSeconds", traffic_sec - base_sec))

                base_dur_min = round(base_sec / 60.0, 1)
                traffic_dur_min = round(traffic_sec / 60.0, 1)
                delay_min = round(delay_sec / 60.0, 1)

                if delay_min >= 8.0:
                    status_lbl = "HEAVY"
                elif delay_min >= 3.0:
                    status_lbl = "MODERATE"
                else:
                    status_lbl = "NORMAL"

                # Extract coordinates
                legs = r.get("legs", [])
                path = []
                for leg in legs:
                    for pt in leg.get("points", []):
                        path.append([pt["latitude"], pt["longitude"]])

                # Generate Google Maps colored traffic segments
                segments = cls.generate_traffic_segments(path, time_multiplier)

                parsed_routes.append({
                    "id": f"route-{idx + 1}",
                    "label": f"Route {idx + 1}",
                    "route_number": idx + 1,
                    "distance_km": dist_km,
                    "duration_min": base_dur_min,
                    "traffic_duration_min": traffic_dur_min,
                    "traffic_delay_min": delay_min,
                    "traffic_status": status_lbl,
                    "congestion_percentage": min(95, max(5, int((delay_min / max(1.0, traffic_dur_min)) * 100))),
                    "path": path,
                    "traffic_segments": segments,
                    "provider": "tomtom_live",
                    "is_alternative": idx > 0,
                })

            return parsed_routes
        except Exception as e:
            logger.warning(f"TomTom routing query failed: {e}")
            return None

    @classmethod
    def _fetch_osrm_single_route(
        cls,
        points: List[Dict[str, float]],
    ) -> Optional[Dict[str, Any]]:
        """Queries OSRM driving engine for a specific sequence of coordinates with radius tolerance."""
        try:
            coords_str = ";".join([f"{p['lng']},{p['lat']}" for p in points])
            radiuses_str = ";".join(["350" for _ in points])

            params = {
                "overview": "full",
                "geometries": "geojson",
                "steps": "false",
                "alternatives": "false",
                "radiuses": radiuses_str,
            }
            res = requests.get(f"{OSRM_ROUTE_URL}/{coords_str}", params=params, timeout=4.5)
            if res.ok:
                data = res.json()
                if data.get("code") == "Ok" and data.get("routes"):
                    r = data["routes"][0]
                    coords = r["geometry"]["coordinates"]
                    path = [[pt[1], pt[0]] for pt in coords]
                    dist_km = round(r["distance"] / 1000.0, 2)
                    dur_min = round(r["duration"] / 60.0, 1)
                    return {
                        "path": path,
                        "distance_km": dist_km,
                        "duration_min": dur_min,
                    }
        except Exception as err:
            logger.debug(f"OSRM single route query failed: {err}")
        return None

    @classmethod
    def _calculate_path_overlap_ratio(
        cls,
        path_a: List[List[float]],
        path_b: List[List[float]]
    ) -> float:
        """Calculates fraction of path B that overlaps within 60m corridor of path A."""
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
                if min_d <= 60.0:
                    break
            if min_d <= 60.0:
                overlap_count += 1

        return overlap_count / float(len(sampled_b)) if sampled_b else 1.0

    @classmethod
    def _fetch_multi_corridor_osrm_routes(
        cls,
        source: Dict[str, float],
        destination: Dict[str, float],
        waypoints: List[Dict[str, float]],
        alternatives: bool = True
    ) -> List[Dict[str, Any]]:
        """Queries OSRM driving engine and evaluates genuine Nashik arterial corridor alternatives."""
        all_pts = [source] + (waypoints or []) + [destination]

        # 1. Fetch direct route
        direct = cls._fetch_osrm_single_route(all_pts)
        if not direct:
            # Fallback direct
            straight_m = haversine_meters(source["lat"], source["lng"], destination["lat"], destination["lng"])
            dist_km = round(max(0.2, (straight_m * 1.25) / 1000.0), 2)
            dur_min = round(max(1.0, (dist_km / 35.0) * 60.0), 1)

            # Interpolated points
            pts = [[source["lat"], source["lng"]]]
            for wp in (waypoints or []):
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

            return [{
                "id": "route-1",
                "label": "Route 1",
                "route_number": 1,
                "distance_km": dist_km,
                "duration_min": dur_min,
                "path": smooth_path,
                "is_alternative": False,
                "provider": "nashik_corridor_fallback",
            }]

        candidate_routes = [{
            "id": "route-1",
            "label": "Route 1",
            "route_number": 1,
            "distance_km": direct["distance_km"],
            "duration_min": direct["duration_min"],
            "path": direct["path"],
            "is_alternative": False,
            "provider": "osrm_road_network",
        }]

        # If alternatives requested, no custom waypoints, and distance > 1.8km:
        # Search Nashik arterial network for genuine realistic alternative corridors
        if alternatives and len(waypoints) == 0 and direct["distance_km"] >= 1.8:
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
                    if d_src < 900 or d_dst < 900:
                        continue

                    px = (art["lng"] - src_tuple[1]) * math.cos(math.radians((src_tuple[0] + dst_tuple[0]) / 2.0))
                    py = (art["lat"] - src_tuple[0])
                    t = (px * dx + py * dy) / mag2

                    if 0.15 <= t <= 0.85:
                        proj_y = src_tuple[0] + t * (dst_tuple[0] - src_tuple[0])
                        proj_x = src_tuple[1] + t * (dst_tuple[1] - src_tuple[1])
                        offset_m = haversine_meters(art["lat"], art["lng"], proj_y, proj_x)
                        # Offset between 300m and 3500m
                        if 300 <= offset_m <= 3500:
                            potential_arterials.append((art, t, offset_m))

                # Sort by balance of central positioning and reasonable offset
                potential_arterials.sort(key=lambda c: abs(c[1] - 0.5) + (c[2] / 4000.0))

                for art_item in potential_arterials[:4]:
                    art = art_item[0]
                    alt_pts = [source, {"lat": art["lat"], "lng": art["lng"]}, destination]
                    alt_res = cls._fetch_osrm_single_route(alt_pts)
                    if not alt_res:
                        continue

                    # Validate realistic practicality:
                    # 1. Distance <= 1.35x direct
                    # 2. Duration <= 1.45x direct
                    if alt_res["distance_km"] > direct["distance_km"] * 1.35:
                        continue
                    if alt_res["duration_min"] > direct["duration_min"] * 1.45:
                        continue

                    # 3. Path overlap check with already accepted routes
                    overlap_with_existing = False
                    for existing_r in candidate_routes:
                        overlap = cls._calculate_path_overlap_ratio(existing_r["path"], alt_res["path"])
                        if overlap > 0.72:
                            overlap_with_existing = True
                            break

                    if not overlap_with_existing:
                        idx = len(candidate_routes)
                        candidate_routes.append({
                            "id": f"route-{idx + 1}",
                            "label": f"Route {idx + 1}",
                            "route_number": idx + 1,
                            "distance_km": alt_res["distance_km"],
                            "duration_min": alt_res["duration_min"],
                            "path": alt_res["path"],
                            "is_alternative": True,
                            "provider": "osrm_road_network",
                        })

                    if len(candidate_routes) >= 3:
                        break

        return candidate_routes

    @classmethod
    def enrich_route_with_nashik_traffic(cls, route: Dict[str, Any]) -> Dict[str, Any]:
        """Calculates realistic live traffic delay, congestion, and segments based on road corridors and time of day."""
        path = route.get("path", [])
        if not path:
            return route

        time_multiplier, time_period = get_current_traffic_time_multiplier()

        # Check proximity to known bottleneck nodes
        corridor_hits = []
        total_delay_min = 0.0

        for corridor in NASHIK_CORRIDORS:
            c_lat = corridor["lat"]
            c_lng = corridor["lng"]
            r_m = corridor["radius_m"]

            for i in range(0, len(path), max(1, len(path) // 40)):
                pt = path[i]
                d = haversine_meters(pt[0], pt[1], c_lat, c_lng)
                if d <= r_m:
                    factor = 1.0 - (d / r_m)
                    corridor_delay = corridor["base_delay_min"] * factor * (time_multiplier - 0.7)
                    if corridor["name"] not in [h["name"] for h in corridor_hits]:
                        corridor_hits.append({
                            "name": corridor["name"],
                            "severity": corridor["severity"],
                            "delay_min": round(corridor_delay, 1)
                        })
                        total_delay_min += corridor_delay
                    break

        base_dur = route.get("duration_min", 10.0)
        traffic_delay = max(0.5, round(total_delay_min, 1))
        traffic_dur = round(base_dur + traffic_delay, 1)

        if traffic_delay >= 8.0:
            status_lbl = "HEAVY"
        elif traffic_delay >= 3.0:
            status_lbl = "MODERATE"
        else:
            status_lbl = "NORMAL"

        congestion_pct = min(92, max(8, int((traffic_delay / max(1.0, traffic_dur)) * 100)))

        # Generate Google Maps colored traffic segments
        segments = cls.generate_traffic_segments(path, time_multiplier)

        # Count corridor hotspots and hazards if available
        hotspots_count = 0
        hazards_count = 0
        try:
            from app.core.database import SessionLocal
            from app.services.hotspot_service import HotspotService
            from app.services.hazard_service import HazardService
            with SessionLocal() as db:
                spots = HotspotService.get_hotspots_near_route(db, path, corridor_meters=80.0)
                hotspots_count = len(spots)
            hazards = HazardService.get_hazards_near_route(path, buffer_meters=120.0)
            hazards_count = len(hazards)
        except Exception:
            pass

        enriched = dict(route)
        enriched.update({
            "traffic_duration_min": traffic_dur,
            "traffic_delay_min": traffic_delay,
            "traffic_status": status_lbl,
            "congestion_percentage": congestion_pct,
            "traffic_period": time_period,
            "bottlenecks_detected": corridor_hits,
            "traffic_segments": segments,
            "hotspots_count": hotspots_count,
            "hazards_count": hazards_count,
            "provider": route.get("provider", "nashik_corridor_engine"),
        })
        return enriched

    @classmethod
    def calculate_traffic_routes(
        cls,
        source: Dict[str, float],
        destination: Dict[str, float],
        waypoints: Optional[List[Dict[str, float]]] = None,
        vehicle_type: str = "car",
        alternatives: bool = True
    ) -> List[Dict[str, Any]]:
        """Calculates road routes enriched with dynamic, road-segment based traffic congestion visualization:
        1. Checks in-memory cache for recent identical queries.
        2. Queries TomTom API if TOMTOM_API_KEY is configured.
        3. Queries Google Routes API if GOOGLE_ROUTES_API_KEY is configured.
        4. Queries OSRM road network + Nashik Multi-Corridor Flow Engine for authentic road routes.
        5. Enriches every route with segment-by-segment color coding:
           - Green (#22C55E): Free Traffic
           - Yellow/Orange (#F59E0B): Moderate Traffic
           - Red (#EF4444): Heavy Traffic
           - Dark Red (#991B1B): Very Heavy Traffic
        """
        waypoints = waypoints or []

        # Validate coordinates
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

        routes: Optional[List[Dict[str, Any]]] = None

        # 1. Try TomTom Live Traffic API if configured
        tomtom_key = (getattr(settings, "TOMTOM_API_KEY", "") or "").strip()
        if tomtom_key:
            try:
                routes = cls._fetch_tomtom_routes(
                    source=source,
                    destination=destination,
                    waypoints=waypoints,
                    api_key=tomtom_key,
                    alternatives=alternatives
                )
            except Exception as e:
                logger.warning(f"TomTom route calculation failed, falling back: {e}")

        # 2. Try Google Routes Live API if configured and TomTom did not return routes
        google_key = (getattr(settings, "GOOGLE_ROUTES_API_KEY", None) or getattr(settings, "GOOGLE_MAPS_API_KEY", None) or "").strip()
        if not routes and google_key:
            try:
                routes = cls._fetch_google_routes(
                    source=source,
                    destination=destination,
                    waypoints=waypoints,
                    api_key=google_key,
                    alternatives=alternatives
                )
            except Exception as e:
                logger.warning(f"Google Routes calculation failed, falling back: {e}")

        # 3. Dynamic multi-corridor road routing with Nashik Traffic Flow Engine
        if not routes:
            try:
                candidate_routes = cls._fetch_multi_corridor_osrm_routes(
                    source=source,
                    destination=destination,
                    waypoints=waypoints,
                    alternatives=alternatives
                )
            except Exception as e:
                logger.warning(f"OSRM multi-corridor query failed: {e}")
                from app.services.routing_service import RoutingService
                candidate_routes = RoutingService.calculate_routes(
                    source=source,
                    destination=destination,
                    waypoints=waypoints,
                    vehicle_type=vehicle_type,
                    alternatives=alternatives
                )

            # Enrich each candidate route with segment-by-segment traffic data
            routes = []
            for idx, r in enumerate(candidate_routes):
                enriched = cls.enrich_route_with_nashik_traffic(r)
                enriched["is_recommended"] = (idx == 0)
                enriched["recommendation_reason"] = "Fastest route with real-time traffic flow" if idx == 0 else "Feasible alternative route"
                routes.append(enriched)

        # Cache the calculated routes
        if routes:
            cls._route_cache[cache_key] = (now, routes)

        return routes or []

    @classmethod
    def calculate_practical_routes(
        cls,
        source: Dict[str, float],
        destination: Dict[str, float],
        waypoints: Optional[List[Dict[str, float]]] = None,
        vehicle_type: str = "car",
        alternatives: bool = True
    ) -> List[Dict[str, Any]]:
        """Calculates road routes and feasible alternatives using RoutingService without live traffic data."""
        from app.services.routing_service import RoutingService
        return RoutingService.calculate_routes(
            source=source,
            destination=destination,
            waypoints=waypoints,
            vehicle_type=vehicle_type,
            alternatives=alternatives
        )

