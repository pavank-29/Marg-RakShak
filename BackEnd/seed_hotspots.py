"""Unified Hotspots Seeding Script for MargRakshak AI.
Loads verified 102 Nashik accident blackspots from app/seed_hotspots.json
into the database with SRID 4326 PostGIS geometry and deduplication.

Usage:
    python seed_hotspots.py
    python seed_hotspots.py --reset
"""
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from geoalchemy2.elements import WKTElement
from sqlalchemy import func

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Ensure BackEnd root is on sys.path
backend_root = Path(__file__).resolve().parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from app.core.database import SessionLocal, init_db
from app.models.hotspot import Hotspot
from app.services.hotspot_service import HotspotService


def load_seed_data() -> list:
    seed_path = backend_root / "app" / "seed_hotspots.json"
    if not seed_path.exists():
        raise FileNotFoundError(f"Hotspot seed data file not found: {seed_path}")
    with open(seed_path, "r", encoding="utf-8") as f:
        return json.load(f)


def seed(reset: bool = False):
    init_db()
    db = SessionLocal()
    try:
        hotspots_data = load_seed_data()
        logger.info(f"Loaded {len(hotspots_data)} hotspot definitions from seed_hotspots.json")

        if reset:
            logger.warning("Reset flag detected: clearing existing hotspots table...")
            db.query(Hotspot).delete()
            db.commit()

        existing_spots = {h.name.lower().strip(): h for h in db.query(Hotspot).all()}
        logger.info(f"Existing hotspots in DB: {len(existing_spots)}")

        added_count = 0
        updated_count = 0

        for item in hotspots_data:
            name_key = item["name"].lower().strip()
            lat = float(item["lat"])
            lng = float(item["lng"])
            if 9.0 < lat < 11.0:
                lat += 10.0

            geom_wkt = WKTElement(f"POINT({lng} {lat})", srid=4326)
            risk_level = str(item.get("riskLevel", "HIGH")).upper()
            risk_score = float(item.get("riskScore", 0.75))
            accident_count = int(item.get("accidentCount", 0))
            fatalities = int(item.get("fatalities", 0))
            density = float(item.get("density", 0.0))
            radius = float(item.get("radius", 200.0))
            recommendation = item.get("safetyRecommendation", "")
            risk_factors = item.get("riskFactors", [])
            algorithm = item.get("algorithm", "HDBSCAN / Traffic Police")

            if name_key in existing_spots:
                spot = existing_spots[name_key]
                spot.latitude = lat
                spot.longitude = lng
                spot.geom = geom_wkt
                spot.risk_level = risk_level
                spot.risk_score = risk_score
                spot.density = density
                spot.accident_count = accident_count
                spot.fatalities = fatalities
                spot.radius_meters = radius
                spot.safety_recommendation = recommendation
                spot.risk_factors = risk_factors
                spot.algorithm = algorithm
                spot.source = "KNOWN_BLACKSPOT"
                spot.is_active = True
                spot.last_updated = datetime.now(timezone.utc)
                updated_count += 1
            else:
                spot = Hotspot(
                    id=item.get("id"),
                    name=item["name"],
                    latitude=lat,
                    longitude=lng,
                    geom=geom_wkt,
                    risk_level=risk_level,
                    risk_score=risk_score,
                    density=density,
                    accident_count=accident_count,
                    fatalities=fatalities,
                    radius_meters=radius,
                    safety_recommendation=recommendation,
                    risk_factors=risk_factors,
                    algorithm=algorithm,
                    source="KNOWN_BLACKSPOT",
                    is_active=True,
                    last_updated=datetime.now(timezone.utc),
                )
                db.add(spot)
                added_count += 1

        db.commit()

        # Enforce spatial deduplication
        dedup_res = HotspotService.deduplicate_hotspots(db, tolerance_meters=250.0)
        logger.info(f"Spatial deduplication: {dedup_res['before_count']} -> {dedup_res['after_count']}")

        total_count = db.query(func.count(Hotspot.id)).scalar()
        logger.info(
            f"Seeding completed successfully: {added_count} added, {updated_count} updated. "
            f"Total active hotspots: {total_count}"
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Error during seeding: {e}", exc_info=True)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    reset_flag = "--reset" in sys.argv or "-r" in sys.argv
    seed(reset=reset_flag)
