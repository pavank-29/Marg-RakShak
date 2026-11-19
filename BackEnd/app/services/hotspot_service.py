"""Hotspot business logic service for MargRakshak AI.
Handles CRUD operations, PostGIS spatial queries (ST_DWithin, ST_Distance), and Leaflet-compatible GeoJSON generation.
"""
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, Tuple, Dict, Any
from sqlalchemy import select, func, cast, or_
from sqlalchemy.orm import Session
from geoalchemy2 import Geography
from geoalchemy2.elements import WKTElement

logger = logging.getLogger(__name__)

from app.models.hotspot import Hotspot
from app.models.accident import Accident
from app.models.risk_zone import RiskZone
from app.schemas.hotspot import (
    HotspotCreate,
    HotspotUpdate,
    HotspotResponse,
    HotspotNearbyResponse,
    HotspotDetailResponse,
    PaginatedHotspotResponse,
)
from app.schemas.accident import (
    GeoJSONFeatureCollection,
    GeoJSONFeature,
    GeoJSONGeometry,
)


from fastapi import HTTPException, status

# Bounding box for verified Nashik City & Highway Project Scope
NASHIK_LAT_MIN = 19.50
NASHIK_LAT_MAX = 20.50
NASHIK_LON_MIN = 73.40
NASHIK_LON_MAX = 74.50

# Spatial deduplication thresholds in meters
DUPLICATE_PROXIMITY_THRESHOLD_METERS = 50.0
NAME_MATCH_PROXIMITY_METERS = 300.0


class HotspotService:
    """Service encapsulating database transactions and PostGIS operations for accident hotspots."""

    @staticmethod
    def _haversine_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate great-circle distance between two points in meters using Haversine formula."""
        import math
        r = 6371000.0  # Earth radius in meters
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)
        a = (
            math.sin(delta_phi / 2.0) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
        )
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return r * c

    @staticmethod
    def validate_hotspot_data(
        db: Session,
        name: str,
        latitude: float,
        longitude: float,
        exclude_id: Optional[int] = None
    ) -> None:
        """Validate coordinates, geographic scope, and enforce zero duplicate hotspots."""
        if not (-90.0 <= latitude <= 90.0):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Latitude {latitude} is outside valid geographic range [-90, 90]."
            )
        if not (-180.0 <= longitude <= 180.0):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Longitude {longitude} is outside valid geographic range [-180, 180]."
            )

        # Enforce Nashik City regional scope
        if not (NASHIK_LAT_MIN <= latitude <= NASHIK_LAT_MAX and NASHIK_LON_MIN <= longitude <= NASHIK_LON_MAX):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Coordinates ({latitude}, {longitude}) are outside the verified Nashik City scope [{NASHIK_LAT_MIN}-{NASHIK_LAT_MAX} N, {NASHIK_LON_MIN}-{NASHIK_LON_MAX} E]."
            )

        # Check existing records for duplicates
        query = select(Hotspot).where(Hotspot.is_active == True)
        if exclude_id is not None:
            query = query.where(Hotspot.id != exclude_id)

        existing_spots = list(db.scalars(query).all())
        clean_name = name.strip().lower()

        for spot in existing_spots:
            dist = HotspotService._haversine_distance_meters(latitude, longitude, spot.latitude, spot.longitude)
            if dist < DUPLICATE_PROXIMITY_THRESHOLD_METERS:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Duplicate hotspot rejected: Physical location already represented by '{spot.name}' (ID {spot.id}, {round(dist, 1)}m away)."
                )
            if spot.name.strip().lower() == clean_name and dist < NAME_MATCH_PROXIMITY_METERS:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Duplicate hotspot rejected: A hotspot named '{spot.name}' already exists within {round(dist, 1)}m (ID {spot.id})."
                )

    @staticmethod
    def create_hotspot(
        db: Session,
        hotspot_in: HotspotCreate
    ) -> Hotspot:
        """Create a new accident hotspot record with validation and PostGIS Point geometry (SRID 4326)."""
        # Run strict validation and deduplication check
        HotspotService.validate_hotspot_data(
            db=db,
            name=hotspot_in.name,
            latitude=hotspot_in.latitude,
            longitude=hotspot_in.longitude
        )

        risk_level_str = (
            hotspot_in.risk_level.value
            if isinstance(hotspot_in.risk_level, Enum)
            else str(hotspot_in.risk_level)
        )
        source_str = (
            hotspot_in.source.value
            if isinstance(hotspot_in.source, Enum)
            else str(hotspot_in.source)
        )

        # Build PostGIS Point geometry: SRID 4326 with (longitude, latitude) order
        geom_wkt = WKTElement(f"POINT({hotspot_in.longitude} {hotspot_in.latitude})", srid=4326)

        db_hotspot = Hotspot(
            name=hotspot_in.name,
            latitude=hotspot_in.latitude,
            longitude=hotspot_in.longitude,
            geom=geom_wkt,
            risk_level=risk_level_str.upper(),
            risk_score=hotspot_in.risk_score,
            density=hotspot_in.density,
            accident_count=hotspot_in.accident_count,
            fatalities=hotspot_in.fatalities,
            radius_meters=hotspot_in.radius_meters,
            safety_recommendation=hotspot_in.safety_recommendation,
            risk_factors=hotspot_in.risk_factors or [],
            algorithm=hotspot_in.algorithm,
            source=source_str.upper(),
            description=hotspot_in.description,
            is_active=hotspot_in.is_active,
            last_updated=datetime.now(timezone.utc),
        )
        db.add(db_hotspot)
        db.commit()
        db.refresh(db_hotspot)
        return db_hotspot

    @staticmethod
    def get_hotspot_by_id(db: Session, hotspot_id: int) -> Optional[Hotspot]:
        """Fetch single hotspot by primary key ID."""
        return db.get(Hotspot, hotspot_id)

    @staticmethod
    def get_hotspot_detail(db: Session, hotspot_id: int) -> Optional[HotspotDetailResponse]:
        """Fetch single hotspot with list of associated accident IDs."""
        db_hotspot = db.get(Hotspot, hotspot_id)
        if not db_hotspot:
            return None

        # Query associated accident IDs
        acc_ids_stmt = select(Accident.id).where(Accident.hotspot_id == hotspot_id)
        linked_accident_ids = list(db.scalars(acc_ids_stmt).all())

        base_resp = HotspotResponse.model_validate(db_hotspot)
        return HotspotDetailResponse(
            **base_resp.model_dump(),
            linked_accident_ids=linked_accident_ids
        )

    @staticmethod
    def get_hotspots(
        db: Session,
        *,
        risk_level: Optional[str] = None,
        min_risk_score: Optional[float] = None,
        algorithm: Optional[str] = None,
        source: Optional[str] = None,
        search: Optional[str] = None,
        is_active: Optional[bool] = None,
        page: int = 1,
        limit: int = 200,
    ) -> Tuple[List[Hotspot], int]:
        """Retrieve paginated hotspots with optional filtering."""
        stmt = select(Hotspot)

        if risk_level:
            rl_val = risk_level.value if isinstance(risk_level, Enum) else str(risk_level)
            stmt = stmt.where(Hotspot.risk_level == rl_val.upper())

        if min_risk_score is not None:
            stmt = stmt.where(Hotspot.risk_score >= min_risk_score)

        if algorithm:
            stmt = stmt.where(Hotspot.algorithm.ilike(f"%{algorithm}%"))

        if source:
            src_val = source.value if isinstance(source, Enum) else str(source)
            stmt = stmt.where(Hotspot.source.ilike(f"%{src_val}%"))

        if is_active is not None:
            stmt = stmt.where(Hotspot.is_active == is_active)

        if search:
            stmt = stmt.where(
                or_(
                    Hotspot.name.ilike(f"%{search}%"),
                    Hotspot.description.ilike(f"%{search}%"),
                    Hotspot.safety_recommendation.ilike(f"%{search}%")
                )
            )

        # Count total records matching filter criteria
        count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
        total = db.scalar(count_stmt) or 0

        # Sort by risk_score desc, id asc
        offset = (page - 1) * limit
        stmt = stmt.order_by(Hotspot.risk_score.desc(), Hotspot.id.asc()).offset(offset).limit(limit)

        items = list(db.scalars(stmt).all())
        return items, total

    @staticmethod
    def update_hotspot(
        db: Session,
        hotspot_id: int,
        hotspot_in: HotspotUpdate
    ) -> Optional[Hotspot]:
        """Update existing hotspot attributes and recalculate PostGIS Point if coordinates change."""
        db_hotspot = db.get(Hotspot, hotspot_id)
        if not db_hotspot:
            return None

        update_data = hotspot_in.model_dump(exclude_unset=True)

        lat_changed = "latitude" in update_data
        lon_changed = "longitude" in update_data

        if lat_changed or lon_changed:
            new_lat = float(update_data.get("latitude", db_hotspot.latitude))
            new_lon = float(update_data.get("longitude", db_hotspot.longitude))
            new_name = update_data.get("name", db_hotspot.name)
            HotspotService.validate_hotspot_data(
                db=db,
                name=new_name,
                latitude=new_lat,
                longitude=new_lon,
                exclude_id=hotspot_id
            )
            db_hotspot.geom = WKTElement(f"POINT({new_lon} {new_lat})", srid=4326)

        if "risk_level" in update_data and update_data["risk_level"] is not None:
            rl = update_data["risk_level"]
            update_data["risk_level"] = rl.value if isinstance(rl, Enum) else str(rl).upper()

        if "source" in update_data and update_data["source"] is not None:
            src = update_data["source"]
            update_data["source"] = src.value if isinstance(src, Enum) else str(src).upper()

        for key, value in update_data.items():
            setattr(db_hotspot, key, value)

        db_hotspot.last_updated = datetime.now(timezone.utc)
        db.commit()
        db.refresh(db_hotspot)
        return db_hotspot

    @staticmethod
    def delete_hotspot(db: Session, hotspot_id: int) -> bool:
        """Delete hotspot record by ID, unlinking associated accidents and risk zones."""
        db_hotspot = db.get(Hotspot, hotspot_id)
        if not db_hotspot:
            return False

        # Unlink associated accidents to avoid foreign key integrity errors
        accidents = list(db.scalars(select(Accident).where(Accident.hotspot_id == hotspot_id)).all())
        for acc in accidents:
            acc.hotspot_id = None

        # Unlink associated risk zones
        risk_zones = list(db.scalars(select(RiskZone).where(RiskZone.hotspot_id == hotspot_id)).all())
        for rz in risk_zones:
            rz.hotspot_id = None

        db.delete(db_hotspot)
        db.commit()
        return True

    @staticmethod
    def _haversine_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate great-circle distance between two points in meters using Haversine formula."""
        import math
        r = 6371000.0  # Earth radius in meters
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)
        a = (
            math.sin(delta_phi / 2.0) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
        )
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return r * c

    @staticmethod
    def get_nearby_hotspots(
        db: Session,
        latitude: float,
        longitude: float,
        radius_meters: float,
        limit: int = 50,
    ) -> List[HotspotNearbyResponse]:
        """Find hotspots within radius in meters using PostGIS ST_DWithin or mathematical haversine."""
        bind_dialect = db.bind.dialect.name if db.bind else "sqlite"
        if bind_dialect == "postgresql":
            try:
                point_geom = func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), 4326)
                geog_point = cast(point_geom, Geography)
                geog_hotspot = cast(Hotspot.geom, Geography)
                distance_expr = func.ST_Distance(geog_hotspot, geog_point).label("distance_meters")

                stmt = (
                    select(Hotspot, distance_expr)
                    .where(Hotspot.is_active == True)
                    .where(func.ST_DWithin(geog_hotspot, geog_point, radius_meters))
                    .order_by(distance_expr.asc())
                    .limit(limit)
                )
                rows = db.execute(stmt).all()
                results: List[HotspotNearbyResponse] = []
                for hotspot, dist in rows:
                    hotspot_resp = HotspotResponse.model_validate(hotspot)
                    nearby_resp = HotspotNearbyResponse(
                        **hotspot_resp.model_dump(),
                        distance_meters=round(float(dist), 2) if dist is not None else 0.0
                    )
                    results.append(nearby_resp)
                return results
            except Exception:
                pass  # Fall back to Python haversine below

        # Universal fallback for SQLite and non-PostGIS deployments
        active_hotspots = list(db.scalars(select(Hotspot).where(Hotspot.is_active == True)).all())
        nearby_list = []
        for h in active_hotspots:
            dist = HotspotService._haversine_distance_meters(latitude, longitude, h.latitude, h.longitude)
            if dist <= radius_meters:
                hotspot_resp = HotspotResponse.model_validate(h)
                nearby_list.append((dist, HotspotNearbyResponse(
                    **hotspot_resp.model_dump(),
                    distance_meters=round(dist, 2)
                )))

        nearby_list.sort(key=lambda x: x[0])
        return [item[1] for item in nearby_list[:limit]]

    @staticmethod
    def get_hotspots_geojson(
        db: Session,
        *,
        risk_level: Optional[str] = None,
        min_risk_score: Optional[float] = None,
        limit: int = 500,
    ) -> GeoJSONFeatureCollection:
        """Export hotspots as RFC 7946 GeoJSON FeatureCollection with [longitude, latitude] Point coordinates for Leaflet."""
        stmt = select(Hotspot)

        if risk_level:
            rl_val = risk_level.value if isinstance(risk_level, Enum) else str(risk_level)
            stmt = stmt.where(Hotspot.risk_level == rl_val.upper())

        if min_risk_score is not None:
            stmt = stmt.where(Hotspot.risk_score >= min_risk_score)

        stmt = stmt.order_by(Hotspot.risk_score.desc()).limit(limit)
        hotspots = list(db.scalars(stmt).all())

        features: List[GeoJSONFeature] = []
        for h in hotspots:
            feature = GeoJSONFeature(
                type="Feature",
                geometry=GeoJSONGeometry(
                    type="Point",
                    # RFC 7946 strictly requires [longitude, latitude] order
                    coordinates=[float(h.longitude), float(h.latitude)]
                ),
                properties={
                    "id": h.id,
                    "name": h.name,
                    "risk_level": h.risk_level,
                    "riskLevel": h.risk_level,
                    "risk_score": h.risk_score,
                    "riskScore": h.risk_score,
                    "density": h.density,
                    "accident_count": h.accident_count,
                    "accidentCount": h.accident_count,
                    "fatalities": h.fatalities,
                    "radius": h.radius_meters,
                    "radius_meters": h.radius_meters,
                    "safety_recommendation": h.safety_recommendation,
                    "safetyRecommendation": h.safety_recommendation,
                    "risk_factors": h.risk_factors or [],
                    "riskFactors": h.risk_factors or [],
                    "algorithm": h.algorithm,
                    "source": h.source,
                    "description": h.description,
                    "is_active": h.is_active,
                    "last_updated": h.last_updated.isoformat() if h.last_updated else None,
                    "lastUpdated": h.last_updated.strftime("%Y-%m-%d %H:%M") if h.last_updated else None,
                }
            )
            features.append(feature)

        return GeoJSONFeatureCollection(
            type="FeatureCollection",
            features=features
        )

    @staticmethod
    def deduplicate_hotspots(db: Session, tolerance_meters: float = 250.0) -> Dict[str, Any]:
        """Group hotspots by physical coordinates within defined tolerance and remove duplicates.
        Ensures each physical location maps to exactly one hotspot.
        Prioritizes verified KNOWN_BLACKSPOT records, then higher accident/fatality counts.
        Logs counts before and after deduplication.
        """
        all_active = list(db.scalars(select(Hotspot).where(Hotspot.is_active == True)).all())
        count_before = len(all_active)

        def sort_priority(h: Hotspot):
            is_known = 1 if (h.source and "KNOWN" in str(h.source).upper()) else 0
            acc = h.accident_count or 0
            fat = h.fatalities or 0
            score = h.risk_score or 0.0
            return (is_known, acc, fat, score, -h.id)

        sorted_spots = sorted(all_active, key=sort_priority, reverse=True)

        kept_spots: List[Hotspot] = []
        removed_spots: List[Hotspot] = []

        for spot in sorted_spots:
            duplicate_of = None
            for kept in kept_spots:
                dist = HotspotService._haversine_distance_meters(
                    spot.latitude, spot.longitude, kept.latitude, kept.longitude
                )
                if dist < tolerance_meters:
                    duplicate_of = kept
                    break

            if duplicate_of:
                logger.info(
                    f"[Hotspot Deduplication] Duplicate hotspot #{spot.id} '{spot.name}' ({spot.source}) "
                    f"is within {dist:.1f}m of canonical hotspot #{duplicate_of.id} '{duplicate_of.name}' ({duplicate_of.source}). "
                    f"Deactivating duplicate."
                )
                spot.is_active = False
                removed_spots.append(spot)
            else:
                kept_spots.append(spot)

        db.commit()
        count_after = len(kept_spots)
        removed_count = len(removed_spots)

        logger.info(
            f"[Hotspot Deduplication] Deduplication completed with tolerance {tolerance_meters}m: "
            f"Count before = {count_before}, Count after = {count_after}, Duplicates removed = {removed_count}"
        )

        return {
            "status": "success",
            "tolerance_meters": tolerance_meters,
            "before_count": count_before,
            "after_count": count_after,
            "removed_count": removed_count,
            "canonical_count": count_after,
            "removed_ids": [h.id for h in removed_spots],
        }

    @staticmethod
    def _point_to_segment_distance_meters(
        p_lat: float, p_lng: float,
        a_lat: float, a_lng: float,
        b_lat: float, b_lng: float
    ) -> float:
        """Calculates perpendicular shortest distance in meters from point P to segment [A, B]."""
        import math
        seg_len = HotspotService._haversine_distance_meters(a_lat, a_lng, b_lat, b_lng)
        if seg_len == 0.0:
            return HotspotService._haversine_distance_meters(p_lat, p_lng, a_lat, a_lng)

        mid_lat = math.radians((a_lat + b_lat + p_lat) / 3.0)
        cos_lat = math.cos(mid_lat)
        dx = (b_lng - a_lng) * cos_lat
        dy = (b_lat - a_lat)
        px = (p_lng - a_lng) * cos_lat
        py = (p_lat - a_lat)

        denom = dx * dx + dy * dy
        if denom == 0.0:
            return HotspotService._haversine_distance_meters(p_lat, p_lng, a_lat, a_lng)

        t = max(0.0, min(1.0, (px * dx + py * dy) / denom))
        proj_lat = a_lat + t * (b_lat - a_lat)
        proj_lng = a_lng + t * (b_lng - a_lng)
        return HotspotService._haversine_distance_meters(p_lat, p_lng, proj_lat, proj_lng)

    @classmethod
    def get_hotspots_near_route(
        cls,
        db: Session,
        path: List[List[float]],
        corridor_meters: float = 80.0
    ) -> List[Dict[str, Any]]:
        """Identifies active hotspots located strictly within corridor_meters of a route path polyline."""
        if not path or len(path) < 2:
            return []

        all_spots = list(db.scalars(select(Hotspot).where(Hotspot.is_active == True)).all())
        hits = []

        # Bounding box pre-filter for efficiency
        lats = [p[0] for p in path]
        lngs = [p[1] for p in path]
        deg_pad = (corridor_meters + 150) / 111000.0
        min_lat, max_lat = min(lats) - deg_pad, max(lats) + deg_pad
        min_lng, max_lng = min(lngs) - deg_pad, max(lngs) + deg_pad

        for spot in all_spots:
            if not (min_lat <= spot.latitude <= max_lat and min_lng <= spot.longitude <= max_lng):
                continue

            min_dist = float("inf")
            for i in range(len(path) - 1):
                p1 = path[i]
                p2 = path[i + 1]
                d = cls._point_to_segment_distance_meters(
                    spot.latitude, spot.longitude,
                    p1[0], p1[1], p2[0], p2[1]
                )
                if d < min_dist:
                    min_dist = d
                if min_dist <= 15.0:
                    break

            if min_dist <= corridor_meters:
                hits.append({
                    "id": spot.id,
                    "name": spot.name,
                    "latitude": spot.latitude,
                    "longitude": spot.longitude,
                    "risk_level": spot.risk_level,
                    "risk_score": spot.risk_score,
                    "accident_count": spot.accident_count,
                    "fatalities": spot.fatalities,
                    "distance_to_route_m": round(min_dist, 1),
                    "safety_recommendation": spot.safety_recommendation,
                    "source": spot.source,
                })

        return sorted(hits, key=lambda x: x["distance_to_route_m"])
