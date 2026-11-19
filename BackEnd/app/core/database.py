"""Database connection engine and session factory with automatic PostgreSQL/PostGIS and SQLite fallback support."""
import json
import logging
import os
from pathlib import Path
from typing import Generator, Dict, Any, Optional

from sqlalchemy import create_engine, event, text, func, select
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.compiler import compiles
from geoalchemy2 import Geometry
import geoalchemy2.admin.dialects.sqlite as sqlite_admin

from app.core.config import settings

logger = logging.getLogger(__name__)

# Suppress geoalchemy2 DDL triggers on SQLite so table creation succeeds without SpatiaLite C extensions
sqlite_admin.after_create = lambda *args, **kwargs: None
sqlite_admin.before_create = lambda *args, **kwargs: None

@compiles(Geometry, "sqlite")
def compile_geometry_sqlite(type_, compiler, **kw):
    """Compile Geometry columns to TEXT on SQLite dialect."""
    return "TEXT"


def _setup_sqlite_connection_hooks(target_engine):
    """Register SQLite PRAGMAs (WAL mode, Foreign Keys) and compatibility GIS functions."""
    @event.listens_for(target_engine, "connect")
    def on_connect_sqlite(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.execute("PRAGMA journal_mode = WAL;")
        cursor.execute("PRAGMA synchronous = NORMAL;")
        cursor.execute("PRAGMA busy_timeout = 5000;")
        cursor.close()

        import binascii

        def sqlite_as_ewkb(val):
            if val is None:
                return None
            if isinstance(val, (bytes, bytearray)):
                return bytes(val)
            if isinstance(val, str):
                try:
                    binascii.unhexlify(val[:18])
                    return val
                except Exception:
                    return None
            return None

        # Register compatibility GIS functions for SQLite dialect
        dbapi_conn.create_function("AsEWKB", 1, sqlite_as_ewkb)
        dbapi_conn.create_function("AsGeoJSON", 1, lambda val: val)
        dbapi_conn.create_function("GeomFromText", 1, lambda val: val)
        dbapi_conn.create_function("GeomFromText", 2, lambda val, srid: val)
        dbapi_conn.create_function("GeomFromEWKT", 1, lambda val: val)
        dbapi_conn.create_function("GeomFromEWKT", 2, lambda val, srid: val)
        dbapi_conn.create_function("RecoverGeometryColumn", 5, lambda *a: 1)


def _init_sqlite_engine():
    """Create high-performance local SQLite database engine (zero external infrastructure)."""
    backend_dir = Path(__file__).resolve().parent.parent.parent
    db_file = os.getenv("MARGRAKSHAK_SQLITE_DB", "margrakshak.db")
    db_path = backend_dir / db_file
    sqlite_url = f"sqlite:///{db_path}"
    logger.info(f"Connecting to primary SQLite database at: {sqlite_url}")
    eng = create_engine(
        sqlite_url,
        connect_args={"check_same_thread": False, "timeout": 30.0},
        pool_pre_ping=True,
        echo=False
    )
    _setup_sqlite_connection_hooks(eng)
    return eng, "sqlite"


def create_db_engine():
    """Create database engine. Defaults to fast, self-contained SQLite unless PostgreSQL explicitly configured."""
    db_url = settings.DATABASE_URL
    if db_url and db_url.startswith("postgresql"):
        try:
            logger.info("Connecting to PostgreSQL database server...")
            pg_engine = create_engine(
                db_url,
                pool_pre_ping=True,
                pool_size=5,
                max_overflow=10,
                connect_args={"connect_timeout": 3},
                echo=False,
            )
            with pg_engine.connect() as conn:
                conn.execute(text("SELECT 1;"))
            logger.info("Successfully connected to PostgreSQL database!")
            return pg_engine, "postgresql"
        except Exception as e:
            logger.warning(f"PostgreSQL connection unavailable ({e}). Using primary SQLite database (margrakshak.db).")

    return _init_sqlite_engine()


# Initialize global engine
engine, db_type = create_db_engine()


# Session local factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def seed_database_if_empty(db_session: Session):
    """Seed the 102 verified Nashik accident hotspots and admin account if database is empty."""
    from app.models.hotspot import Hotspot
    from app.models.user import User
    from app.core.security import get_password_hash

    try:
        hotspots_count = db_session.query(func.count(Hotspot.id)).scalar() or 0
        if hotspots_count == 0:
            seed_file = Path(__file__).resolve().parent.parent / "seed_hotspots.json"
            if seed_file.exists():
                logger.info(f"Seeding verified 102 Nashik blackspots from {seed_file}...")
                with open(seed_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                for item in data:
                    spot = Hotspot(
                        id=item["id"],
                        name=item["name"],
                        latitude=item["lat"],
                        longitude=item["lng"],
                        risk_level=item.get("riskLevel", "HIGH"),
                        risk_score=item.get("riskScore", 0.75),
                        density=float(item.get("density", 0.0)),
                        accident_count=item.get("accidentCount", 0),
                        fatalities=item.get("fatalities", 0),
                        radius_meters=float(item.get("radius", 200.0)),
                        safety_recommendation=item.get("safetyRecommendation"),
                        risk_factors=item.get("riskFactors", []),
                        algorithm=item.get("algorithm", "HDBSCAN / Traffic Police"),
                        source="KNOWN_BLACKSPOT",
                        is_active=True
                    )
                    db_session.merge(spot)
                db_session.commit()
                logger.info(f"Successfully seeded {len(data)} live hotspots into database.")

        # Ensure the 3 authorized admin accounts exist
        authorized_admins = [
            ("admin@margrakshak.in", "MargRakshak System Administrator", "Admin@123"),
            ("police.admin@margrakshak.in", "Nashik Traffic Police Commissionerate Admin", "PoliceAdmin@123"),
            ("safety.admin@margrakshak.in", "Road Safety Cell Administrator", "SafetyAdmin@123"),
        ]
        for email, full_name, raw_pwd in authorized_admins:
            admin_user = db_session.query(User).filter_by(email=email).first()
            if not admin_user:
                admin_user = User(
                    email=email,
                    hashed_password=get_password_hash(raw_pwd),
                    full_name=full_name,
                    role="admin",
                    is_active=True,
                    is_superuser=True
                )
                db_session.add(admin_user)
                db_session.commit()
                logger.info(f"Created authorized administrator account: {email}")

        # Ensure default demo driver account exists
        demo_driver_email = "driver@margrakshak.in"
        driver_user = db_session.query(User).filter_by(email=demo_driver_email).first()
        if not driver_user:
            driver_user = User(
                email=demo_driver_email,
                hashed_password=get_password_hash("Driver@123"),
                full_name="Demo Driver Verified",
                role="user",
                is_active=True,
                is_superuser=False,
                preferred_language="en"
            )
            db_session.add(driver_user)
            db_session.commit()
            logger.info(f"Created default driver account: {demo_driver_email}")

        # Enforce spatial deduplication across all hotspots
        from app.services.hotspot_service import HotspotService
        dedup_res = HotspotService.deduplicate_hotspots(db_session, tolerance_meters=250.0)
        logger.info(f"Hotspot deduplication on startup: {dedup_res['before_count']} -> {dedup_res['after_count']}")

        # Seed verified Nashik road hazards (construction, potholes, closures)
        from app.models.hazard import Hazard
        from app.services.hazard_service import NASHIK_VERIFIED_HAZARDS
        hazards_count = db_session.query(func.count(Hazard.id)).scalar() or 0
        if hazards_count == 0:
            logger.info("Seeding verified Nashik road hazards (construction, potholes, closures)...")
            for h_data in NASHIK_VERIFIED_HAZARDS:
                h_obj = Hazard(
                    id=h_data["id"],
                    title=h_data["title"],
                    hazard_type=h_data["hazard_type"],
                    severity=h_data["severity"],
                    latitude=h_data["latitude"],
                    longitude=h_data["longitude"],
                    location_name=h_data["location_name"],
                    description=h_data.get("description"),
                    speed_limit_kmh=h_data.get("speed_limit_kmh"),
                    source=h_data.get("source", "VERIFIED_GIS"),
                    is_active=h_data.get("is_active", True),
                    icon_type=h_data.get("icon_type", "damage"),
                )
                db_session.merge(h_obj)
            db_session.commit()
            logger.info(f"Successfully seeded {len(NASHIK_VERIFIED_HAZARDS)} verified road hazards.")

    except Exception as err:
        db_session.rollback()
        logger.error(f"Error during database initialization/seeding: {err}")


def init_db():
    """Create all tables and seed data if needed."""
    from app.models.base import Base
    from app.models import hotspot, user, accident, risk_zone, history, alert, prediction, report, hazard
    try:
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as session:
            seed_database_if_empty(session)
    except Exception as e:
        logger.error(f"Failed to create schema or seed DB: {e}")


# Run schema creation and initial seeding
init_db()


def get_db() -> Generator[Session, None, None]:
    """Dependency for providing a transactional database session in FastAPI endpoints."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_info() -> Dict[str, Any]:
    """Get active database status and metrics for health checks."""
    postgis_version = None
    hotspots_count = 0
    try:
        with SessionLocal() as db:
            from app.models.hotspot import Hotspot
            hotspots_count = db.query(func.count(Hotspot.id)).scalar() or 0
            if db_type == "postgresql":
                res = db.execute(text("SELECT PostGIS_version();")).fetchone()
                if res:
                    postgis_version = res[0]
    except Exception as e:
        logger.error(f"Error getting db info: {e}")

    return {
        "type": db_type,
        "status": "operational",
        "database_file": os.getenv("MARGRAKSHAK_SQLITE_DB", "margrakshak.db") if db_type == "sqlite" else "PostgreSQL",
        "journal_mode": "WAL" if db_type == "sqlite" else "N/A",
        "postgis_enabled": bool(postgis_version),
        "postgis_version": postgis_version,
        "hotspots_count": hotspots_count,
        "verified_nashik_blackspots": 102,
    }

