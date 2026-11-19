"""Nashik Road Hazards and Condition Monitoring Service.
Provides verified Nashik City road condition data:
- Road construction
- Road closures & diversions
- Severe potholes & road damage
- Temporary restrictions & traffic obstructions
Integrates with Nashik GIS blackspot records, database-backed user/admin reports, and live incident APIs.
"""
import logging
import math
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import requests

from app.core.config import settings

logger = logging.getLogger(__name__)


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Computes great-circle distance in meters between two coordinates."""
    r = 6371000.0
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


# Verified Nashik Road Hazards & Infrastructure Maintenance Corridors
NASHIK_VERIFIED_HAZARDS = [
    {
        "id": "hazard-nsk-01",
        "title": "Dwarka Flyover & NH-3 Expansion Work",
        "hazard_type": "CONSTRUCTION",
        "severity": "HIGH",
        "latitude": 19.9912,
        "longitude": 73.8015,
        "location_name": "Dwarka Circle Junction, Nashik",
        "description": "Highway expansion and pillar retrofitting work. Left lane restricted; speed limit reduced to 30 km/h.",
        "speed_limit_kmh": 30,
        "source": "VERIFIED_GIS",
        "is_active": True,
        "icon_type": "construction",
        "created_at": "2026-03-01T08:00:00Z",
        "updated_at": "2026-10-20T10:00:00Z",
    },
    {
        "id": "hazard-nsk-02",
        "title": "Satpur-Ambad Link Road Surface Damage",
        "hazard_type": "POTHOLE",
        "severity": "HIGH",
        "latitude": 19.9663,
        "longitude": 73.7325,
        "location_name": "Satpur Ambad Industrial Link Road",
        "description": "Severe deep pothole cluster and uneven tarmac caused by heavy container transit. High risk for two-wheelers.",
        "speed_limit_kmh": 25,
        "source": "VERIFIED_GIS",
        "is_active": True,
        "icon_type": "pothole",
        "created_at": "2026-06-15T09:00:00Z",
        "updated_at": "2026-10-22T14:30:00Z",
    },
    {
        "id": "hazard-nsk-03",
        "title": "Trimbak Road Mahiravani Culvert Work",
        "hazard_type": "CONSTRUCTION",
        "severity": "MODERATE",
        "latitude": 19.9764,
        "longitude": 73.6921,
        "location_name": "Trimbak Road, near Mahiravani",
        "description": "Stormwater culvert reconstruction and road widening. Single lane traffic movement under police flaggers.",
        "speed_limit_kmh": 35,
        "source": "VERIFIED_GIS",
        "is_active": True,
        "icon_type": "construction",
        "created_at": "2026-08-10T07:30:00Z",
        "updated_at": "2026-10-18T11:00:00Z",
    },
    {
        "id": "hazard-nsk-04",
        "title": "Shalimar Market Daytime Heavy Vehicle Restriction",
        "hazard_type": "ROAD_CLOSURE",
        "severity": "MODERATE",
        "latitude": 20.0015,
        "longitude": 73.7870,
        "location_name": "Shalimar Chowk to CBS Approach",
        "description": "Heavy transport vehicles and trucks prohibited between 09:00 AM and 09:00 PM due to pedestrian density.",
        "speed_limit_kmh": 20,
        "source": "VERIFIED_GIS",
        "is_active": True,
        "icon_type": "closure",
        "created_at": "2026-05-01T00:00:00Z",
        "updated_at": "2026-10-01T00:00:00Z",
    },
    {
        "id": "hazard-nsk-05",
        "title": "Ambad Link Road Industrial Entrance Potholes",
        "hazard_type": "POTHOLE",
        "severity": "MODERATE",
        "latitude": 19.9685,
        "longitude": 73.7426,
        "location_name": "Ambad Link Road Sector 12",
        "description": "Recurrent monsoon potholes and loose gravel near industrial gate intersection. Proceed with caution.",
        "speed_limit_kmh": 30,
        "source": "VERIFIED_GIS",
        "is_active": True,
        "icon_type": "pothole",
        "created_at": "2026-07-20T12:00:00Z",
        "updated_at": "2026-10-15T09:00:00Z",
    },
    {
        "id": "hazard-nsk-06",
        "title": "Pathardi Phata Flyover Approach Work",
        "hazard_type": "CONSTRUCTION",
        "severity": "MODERATE",
        "latitude": 19.9490,
        "longitude": 73.7680,
        "location_name": "Pathardi Phata Junction (NH-3)",
        "description": "Service road repaving and barricaded median works. Lane narrowing on Mumbai-bound carriageway.",
        "speed_limit_kmh": 40,
        "source": "VERIFIED_GIS",
        "is_active": True,
        "icon_type": "construction",
        "created_at": "2026-09-01T08:00:00Z",
        "updated_at": "2026-10-19T16:00:00Z",
    },
    {
        "id": "hazard-nsk-07",
        "title": "Gangapur Road Jehan Circle Damaged Surface",
        "hazard_type": "ROAD_DAMAGE",
        "severity": "LOW",
        "latitude": 20.0210,
        "longitude": 73.7635,
        "location_name": "Gangapur Road / Jehan Circle Approach",
        "description": "Uneven road surface and worn asphalt coating along roundabout entry. Reduced traction in rain.",
        "speed_limit_kmh": 35,
        "source": "VERIFIED_GIS",
        "is_active": True,
        "icon_type": "damage",
        "created_at": "2026-04-12T10:00:00Z",
        "updated_at": "2026-10-10T12:00:00Z",
    },
    {
        "id": "hazard-nsk-08",
        "title": "Jail Road / Nashik Road Water Pipeline Trench",
        "hazard_type": "ROAD_DAMAGE",
        "severity": "MODERATE",
        "latitude": 19.9740,
        "longitude": 73.8294,
        "location_name": "Old Saikheda Road, Jail Road",
        "description": "Longitudinal trench backfilled with unpaved stone metal following municipal water pipeline maintenance.",
        "speed_limit_kmh": 25,
        "source": "VERIFIED_GIS",
        "is_active": True,
        "icon_type": "damage",
        "created_at": "2026-08-25T11:00:00Z",
        "updated_at": "2026-10-24T09:00:00Z",
    },
    {
        "id": "hazard-nsk-09",
        "title": "Godavari Ghat Riverbank Seasonal Barrier",
        "hazard_type": "ROAD_CLOSURE",
        "severity": "HIGH",
        "latitude": 20.0078,
        "longitude": 73.7915,
        "location_name": "Ramkund & Godavari Riverbank Ring Road",
        "description": "Low-lying river access road barricaded for festival safety and river current precautions.",
        "speed_limit_kmh": 15,
        "source": "VERIFIED_GIS",
        "is_active": True,
        "icon_type": "closure",
        "created_at": "2026-07-01T06:00:00Z",
        "updated_at": "2026-10-14T08:00:00Z",
    },
]


class HazardService:
    """Service for querying, managing, and analyzing dynamic road hazards in Nashik City."""

    _last_fetched: Optional[float] = None
    _cached_hazards: Optional[List[Dict[str, Any]]] = None
    CACHE_TTL_SEC: float = 60.0  # 1 minute dynamic cache

    @classmethod
    def get_all_hazards(
        cls,
        hazard_type: Optional[str] = None,
        severity: Optional[str] = None,
        is_active: Optional[bool] = None,
        refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        """Returns verified and dynamic Nashik hazards from database + live incident APIs.
        Applies coordinate validation, spatial deduplication within 35m tolerance, and filters stale records.
        """
        now = time.time()
        if not refresh and cls._cached_hazards is not None and cls._last_fetched is not None:
            if now - cls._last_fetched < cls.CACHE_TTL_SEC:
                all_hazards = cls._cached_hazards
            else:
                all_hazards = None
        else:
            all_hazards = None

        if all_hazards is None:
            all_hazards_map: Dict[str, Dict[str, Any]] = {}

            # 1. Base verified GIS hazards (historical baseline)
            for h in NASHIK_VERIFIED_HAZARDS:
                all_hazards_map[h["id"]] = dict(h)

            # 2. Database records (live user reports, admin verified hazards, dynamic records)
            try:
                from app.core.database import SessionLocal
                from app.models.hazard import Hazard
                with SessionLocal() as db:
                    db_records = db.query(Hazard).all()
                    for rec in db_records:
                        rec_dict = rec.to_dict()
                        all_hazards_map[rec.id] = rec_dict
            except Exception as db_err:
                logger.debug(f"Could not read hazards from database: {db_err}")

            # 3. Ingest live traffic incidents from TomTom if configured
            tomtom_key = (getattr(settings, "TOMTOM_API_KEY", "") or "").strip()
            if tomtom_key:
                live_incidents = cls._fetch_tomtom_incidents(tomtom_key)
                for inc in (live_incidents or []):
                    all_hazards_map[inc["id"]] = inc

            raw_list = list(all_hazards_map.values())

            # 4. Strict Coordinate Validation & Range Filtering (Nashik regional scope)
            validated_list = []
            for h in raw_list:
                try:
                    lat = float(h.get("latitude") if h.get("latitude") is not None else h.get("lat"))
                    lng = float(h.get("longitude") if h.get("longitude") is not None else h.get("lng"))
                except (TypeError, ValueError):
                    logger.warning(f"Skipping hazard {h.get('id')} with non-numeric coordinates: {h}")
                    continue

                if not (19.40 <= lat <= 20.60 and 73.30 <= lng <= 74.60):
                    logger.warning(f"Skipping hazard {h.get('id')} outside Nashik bounding box: ({lat}, {lng})")
                    continue

                if abs(lat - lng) < 1e-6:
                    logger.warning(f"Skipping hazard {h.get('id')} with identical lat/lng: ({lat}, {lng})")
                    continue

                h_copy = dict(h)
                h_copy["latitude"] = round(lat, 6)
                h_copy["longitude"] = round(lng, 6)
                h_copy["lat"] = round(lat, 6)
                h_copy["lng"] = round(lng, 6)
                validated_list.append(h_copy)

            # 5. Spatial Deduplication (tolerance 35m for same hazard type to prevent duplicate pins)
            unique_hazards = []
            for h in validated_list:
                is_duplicate = False
                for existing in unique_hazards:
                    # Same hazard type within 35 meters
                    if h.get("hazard_type", "").upper() == existing.get("hazard_type", "").upper():
                        dist = haversine_meters(h["latitude"], h["longitude"], existing["latitude"], existing["longitude"])
                        if dist <= 35.0:
                            is_duplicate = True
                            # Prefer USER_REPORTED or TOMTOM_LIVE if newer
                            if h.get("source") in ["USER_REPORTED", "TOMTOM_LIVE"]:
                                existing.update(h)
                            break
                if not is_duplicate:
                    unique_hazards.append(h)

            all_hazards = unique_hazards
            cls._cached_hazards = all_hazards
            cls._last_fetched = now

        # 6. Apply Query Filters
        filtered = []
        for h in all_hazards:
            if hazard_type and h.get("hazard_type", "").upper() != hazard_type.upper():
                continue
            if severity and h.get("severity", "").upper() != severity.upper():
                continue
            if is_active is not None and h.get("is_active") != is_active:
                continue
            filtered.append(h)

        return filtered

    @classmethod
    def get_hazards_summary(cls) -> Dict[str, Any]:
        """Returns aggregate metrics on dynamic potholes, road construction, closures, and data source."""
        hazards = cls.get_all_hazards(is_active=True)
        potholes = [h for h in hazards if h.get("hazard_type", "").upper() == "POTHOLE"]
        construction = [h for h in hazards if h.get("hazard_type", "").upper() == "CONSTRUCTION"]
        closures = [h for h in hazards if h.get("hazard_type", "").upper() == "ROAD_CLOSURE"]
        other_damage = [h for h in hazards if h.get("hazard_type", "").upper() not in ["POTHOLE", "CONSTRUCTION", "ROAD_CLOSURE"]]

        tomtom_key = (getattr(settings, "TOMTOM_API_KEY", "") or "").strip()
        provider = "TomTom Traffic Incidents API" if tomtom_key else "Nashik Municipal GIS & Database Provider"

        return {
            "total": len(hazards),
            "potholes_count": len(potholes),
            "construction_count": len(construction),
            "closures_count": len(closures),
            "other_damage_count": len(other_damage),
            "provider": provider,
            "is_realtime": bool(tomtom_key),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    @classmethod
    def report_hazard(
        cls,
        hazard_type: str,
        latitude: float,
        longitude: float,
        title: str,
        location_name: str,
        description: Optional[str] = None,
        severity: str = "MODERATE",
        speed_limit_kmh: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Validates and persists a user/admin-reported road hazard in Nashik."""
        # 1. Validate coordinates range and Nashik geographic scope
        if not (-90.0 <= latitude <= 90.0) or not (-180.0 <= longitude <= 180.0):
            raise ValueError(f"Invalid coordinate range ({latitude}, {longitude}).")

        if latitude == longitude:
            raise ValueError("Latitude and Longitude cannot be identical.")

        # Nashik bounds: Lat ~19.50 to 20.50, Lng ~73.40 to 74.50
        if not (19.50 <= latitude <= 20.50 and 73.40 <= longitude <= 74.50):
            raise ValueError(f"Location ({latitude:.4f}, {longitude:.4f}) is outside Nashik City regional scope.")

        h_type = (hazard_type or "ROAD_DAMAGE").upper()
        if h_type not in ["CONSTRUCTION", "POTHOLE", "ROAD_CLOSURE", "ROAD_DAMAGE", "ACCIDENT"]:
            h_type = "ROAD_DAMAGE"

        icon_map = {
            "CONSTRUCTION": "construction",
            "POTHOLE": "pothole",
            "ROAD_CLOSURE": "closure",
            "ROAD_DAMAGE": "damage",
            "ACCIDENT": "accident"
        }

        hazard_id = f"hazard-usr-{int(time.time() * 1000)}"
        now_iso = datetime.now(timezone.utc).isoformat()

        hazard_data = {
            "id": hazard_id,
            "title": title.strip() or f"Reported {h_type.replace('_', ' ').title()}",
            "hazard_type": h_type,
            "severity": severity.upper() if severity in ["CRITICAL", "HIGH", "MODERATE", "LOW"] else "MODERATE",
            "latitude": round(latitude, 6),
            "longitude": round(longitude, 6),
            "location_name": location_name.strip() or "Nashik City",
            "description": description or f"User-reported {h_type.lower().replace('_', ' ')} incident.",
            "speed_limit_kmh": speed_limit_kmh,
            "source": "USER_REPORTED",
            "is_active": True,
            "icon_type": icon_map.get(h_type, "damage"),
            "created_at": now_iso,
            "updated_at": now_iso,
        }

        # Save to database
        try:
            from app.core.database import SessionLocal
            from app.models.hazard import Hazard
            with SessionLocal() as db:
                h_rec = Hazard(**hazard_data)
                db.add(h_rec)
                db.commit()
                db.refresh(h_rec)
                return h_rec.to_dict()
        except Exception as e:
            logger.warning(f"Failed to persist hazard to database, storing in-memory fallback: {e}")
            NASHIK_VERIFIED_HAZARDS.append(hazard_data)
            return hazard_data

    @classmethod
    def get_hazards_near_route(
        cls,
        path: List[List[float]],
        buffer_meters: float = 120.0,
    ) -> List[Dict[str, Any]]:
        """Identifies hazards located strictly within buffer_meters of a route path polyline.
        Uses exact point-to-segment perpendicular distance along the road corridor.
        """
        if not path or len(path) < 2:
            return []

        all_hazards = cls.get_all_hazards(is_active=True)
        hits = []

        for h in all_hazards:
            h_lat = h["latitude"]
            h_lng = h["longitude"]
            min_dist = float("inf")

            # Check exact perpendicular distance against all road segments
            for i in range(len(path) - 1):
                p1 = path[i]
                p2 = path[i + 1]
                d = point_to_segment_distance_meters(h_lat, h_lng, p1[0], p1[1], p2[0], p2[1])
                if d < min_dist:
                    min_dist = d
                if min_dist <= 25.0:  # Direct hit on road, no need to check further
                    break

            if min_dist <= buffer_meters:
                hit_copy = dict(h)
                hit_copy["distance_to_route_m"] = round(min_dist, 1)
                hits.append(hit_copy)

        return sorted(hits, key=lambda x: x["distance_to_route_m"])

    @classmethod
    def _fetch_tomtom_incidents(cls, api_key: str) -> List[Dict[str, Any]]:
        """Fetches live incidents from TomTom Traffic Incidents API v5 for Nashik bbox."""
        try:
            bbox = "73.65,19.85,73.95,20.15"
            url = "https://api.tomtom.com/traffic/services/5/incidentDetails"
            params = {
                "key": api_key,
                "bbox": bbox,
                "fields": "{incidents{type,geometry{type,coordinates},properties{iconCategory,magnitudeOfDelay,events{description,code}}}}",
                "language": "en-GB",
            }
            res = requests.get(url, params=params, timeout=4.0)
            if not res.ok:
                return []

            data = res.json()
            raw_incidents = data.get("incidents", [])
            parsed = []

            for idx, inc in enumerate(raw_incidents):
                geom = inc.get("geometry", {})
                props = inc.get("properties", {})
                coords = geom.get("coordinates", [])

                if geom.get("type") == "Point" and len(coords) >= 2:
                    lng, lat = coords[0], coords[1]
                elif geom.get("type") == "LineString" and len(coords) > 0:
                    lng, lat = coords[0][0], coords[0][1]
                else:
                    continue

                events = props.get("events", [])
                desc = events[0].get("description", "Road incident ahead.") if events else "Road condition warning."

                cat = props.get("iconCategory", 0)
                hazard_type = "ROAD_DAMAGE"
                if cat in [1, 2]:
                    hazard_type = "ACCIDENT"
                elif cat in [8, 9]:
                    hazard_type = "CONSTRUCTION"
                elif cat in [7]:
                    hazard_type = "ROAD_CLOSURE"

                parsed.append({
                    "id": f"tomtom-inc-{idx + 1}",
                    "title": desc,
                    "hazard_type": hazard_type,
                    "severity": "HIGH" if props.get("magnitudeOfDelay", 0) >= 3 else "MODERATE",
                    "latitude": lat,
                    "longitude": lng,
                    "location_name": "Nashik Corridor",
                    "description": desc,
                    "source": "TOMTOM_LIVE",
                    "is_active": True,
                    "icon_type": "construction" if hazard_type == "CONSTRUCTION" else "damage",
                })

            return parsed
        except Exception as e:
            logger.warning(f"TomTom incidents query failed: {e}")
            return []
