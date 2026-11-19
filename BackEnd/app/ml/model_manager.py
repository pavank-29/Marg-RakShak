"""ML Model Lifecycle and Orchestration Manager.
Coordinates training, hot-swapping models, HDBSCAN clustering, and route risk inference.
Provides unified access to active models with zero data leakage.
"""
import csv
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session

from app.core.config import settings
from app.ml.clustering import HotspotClusterer
from app.ml.feature_engineering import FeatureEngineer, FEATURE_COLUMNS
from app.ml.risk_model import RiskModel, XGBOOST_AVAILABLE
from app.ml.route_risk import RouteSafetyEngine
from app.ml.schemas import (
    RiskPredictionRequest,
    RiskPredictionResponse,
    ModelTrainingRequest,
    ModelTrainingResponse,
    ClusteringResponse,
    ClusteringRequest,
    RouteRiskRequest,
    RouteRiskResponse,
    ModelMetrics,
    ModelMetadata,
)

logger = logging.getLogger(__name__)


class ModelManager:
    """Singleton service orchestrating ML lifecycle across the FastAPI application."""

    def __init__(self):
        self.model_dir = Path(settings.MODEL_DIR)
        self.risk_model = RiskModel(model_dir=str(self.model_dir))
        self.clusterer = HotspotClusterer(model_dir=str(self.model_dir))
        self.route_engine = RouteSafetyEngine(risk_model=self.risk_model)
        self.feature_engineer = self.risk_model.feature_engineer
        self._cached_hotspots: Optional[List[Dict[str, Any]]] = None

    def invalidate_hotspots_cache(self):
        """Invalidate in-memory hotspots cache upon database updates."""
        self._cached_hotspots = None

    def get_known_hotspots(self, db: Optional[Session] = None) -> List[Dict[str, Any]]:
        """Fetch active known blackspots and ML hotspots from DB or seed file with high-speed in-memory caching."""
        if db is None and self._cached_hotspots is not None:
            return self._cached_hotspots

        hotspots = []
        if db:
            try:
                from app.models.hotspot import Hotspot
                spots = db.query(Hotspot).filter(Hotspot.is_active == True).all()
                if spots:
                    for s in spots:
                        hotspots.append({
                            "id": s.id,
                            "name": s.name,
                            "latitude": s.latitude,
                            "longitude": s.longitude,
                            "risk_level": s.risk_level,
                            "risk_score": s.risk_score,
                            "source": s.source or "KNOWN_BLACKSPOT",
                            "accident_count": s.accident_count,
                            "fatalities": s.fatalities
                        })
                    self._cached_hotspots = hotspots
                    return hotspots
            except Exception as e:
                logger.warning(f"Could not load hotspots from DB: {e}")

        # Fallback to Nashik_Unified_Blackspots.csv
        csv_path = Path(__file__).resolve().parent.parent.parent / "Nashik_Unified_Blackspots.csv"
        if csv_path.exists():
            try:
                with open(csv_path, mode="r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for idx, row in enumerate(reader):
                        hotspots.append({
                            "id": idx + 1,
                            "name": row.get("Name of Blackspot", "Blackspot"),
                            "latitude": float(row.get("Latitude", 0)),
                            "longitude": float(row.get("Longitude", 0)),
                            "risk_level": row.get("Risk Level", "HIGH"),
                            "risk_score": float(row.get("Risk Score", 0.75)),
                            "source": "KNOWN_BLACKSPOT",
                            "accident_count": int(row.get("Total Accidents", 0) or 0),
                            "fatalities": int(row.get("Total Fatalities", 0) or 0)
                        })
                self._cached_hotspots = hotspots
            except Exception as e:
                logger.error(f"Error reading {csv_path}: {e}")

        return hotspots

    def load_dataset_for_training(self, db: Optional[Session] = None) -> List[Dict[str, Any]]:
        """Load dataset for model training.
        Grounded on real 102 Nashik verified blackspots with multi-condition scenario variations.
        Strictly zero target leakage: input features exclude target risk level and target risk score.
        """
        records: List[Dict[str, Any]] = []

        # 1. Read base records from CSV
        csv_path = Path(__file__).resolve().parent.parent.parent / "Nashik_Unified_Blackspots.csv"
        raw_blackspots: List[Dict[str, Any]] = []

        if csv_path.exists():
            with open(csv_path, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    raw_blackspots.append(r)

        # 2. Add real accident records from DB if any exist
        if db:
            try:
                from app.models.accident import Accident
                db_accidents = db.query(Accident).all()
                for acc in db_accidents:
                    records.append({
                        "latitude": acc.latitude,
                        "longitude": acc.longitude,
                        "road_class": "Local Road",
                        "hour": acc.accident_date.hour if acc.accident_date else 18,
                        "day_of_week": acc.accident_date.weekday() if acc.accident_date else 4,
                        "weather": acc.weather_condition or "CLEAR",
                        "road_condition": acc.road_condition or "NORMAL",
                        "lighting": acc.lighting_condition or "DARK",
                        "vehicle_type": "CAR",
                        "current_speed": 40.0,
                        "speed_limit": 40.0,
                        "fatalities": acc.fatalities,
                        "accident_count": 1,
                        "injuries": acc.injuries,
                    })
            except Exception as e:
                logger.warning(f"Could not load accidents for training: {e}")

        # 3. Comprehensive grounded scenario matrix generation across 102 verified Nashik blackspots, approach corridors, and safe zones
        conditions = [
            # Normal daytime conditions
            (14, 2, "CLEAR", "DRY", "DAYLIGHT", "CAR", -5),
            (11, 1, "CLEAR", "NORMAL", "DAYLIGHT", "BUS", 0),
            # Rush hour
            (9, 1, "CLEAR", "NORMAL", "DAYLIGHT", "2-WHEELER", 5),
            (18, 4, "CLEAR", "NORMAL", "DUSK", "CAR", 10),
            (19, 4, "CLEAR", "NORMAL", "NIGHT_LIT", "2-WHEELER", 15),
            # Night conditions
            (22, 5, "CLEAR", "NORMAL", "DARK", "CAR", 5),
            (23, 6, "CLEAR", "NORMAL", "DARK", "2-WHEELER", 12),
            (2, 6, "CLEAR", "NORMAL", "DARK", "TRUCK", 8),
            # Adverse weather & road hazards
            (15, 3, "RAIN", "WET", "DAYLIGHT", "CAR", -5),
            (20, 5, "RAIN", "WET", "DARK", "2-WHEELER", 5),
            (6, 0, "FOG", "NORMAL", "POOR", "TRUCK", -10),
            (21, 2, "RAIN", "POTHOLE", "DARK", "CAR", 8),
        ]

        import math
        import random

        rng = random.Random(42)

        for b in raw_blackspots:
            try:
                lat = float(b.get("Latitude", 0))
                lng = float(b.get("Longitude", 0))
                road_class = b.get("Road Class / No.", "Local Road")
                b_risk = float(b.get("Risk Score", 0.5) or 0.5)
                s_limit = float(b.get("Speed Limit (km/h)", 40) or 40)
            except (ValueError, TypeError):
                continue

            # A. Centroid scenarios (d = 0)
            for cond in conditions:
                hour, day, weather, road_cond, lighting, vtype, spd_delta = cond
                spd = max(10.0, s_limit + spd_delta)

                spd_mod = min(0.25, max(0.0, (spd - s_limit) / s_limit * 0.35)) if s_limit > 0 else 0.0
                w_mod = 0.15 if weather == "RAIN" else (0.12 if weather == "FOG" else 0.0)
                rc_mod = 0.10 if road_cond in ("POTHOLE", "DAMAGED") else (0.06 if road_cond == "WET" else 0.0)
                l_mod = 0.10 if lighting in ("DARK", "POOR") else (0.04 if lighting in ("NIGHT_LIT", "DUSK") else 0.0)
                v_mod = 0.08 if vtype == "2-WHEELER" else (0.04 if vtype == "TRUCK" else 0.0)

                score = b_risk * 0.60 + (spd_mod + w_mod + rc_mod + l_mod + v_mod) * 0.40 + 0.05
                # Incorporate realistic stochastic human reaction and near-miss variance
                score = max(0.08, min(0.96, score + rng.gauss(0, 0.043)))

                if score >= 0.75:
                    c_label = "CRITICAL"
                elif score >= 0.50:
                    c_label = "HIGH"
                elif score >= 0.25:
                    c_label = "MEDIUM"
                else:
                    c_label = "LOW"

                records.append({
                    "latitude": lat,
                    "longitude": lng,
                    "road_class": road_class,
                    "hour": hour,
                    "day_of_week": day,
                    "weather": weather,
                    "road_condition": road_cond,
                    "lighting": lighting,
                    "vehicle_type": vtype,
                    "current_speed": spd,
                    "speed_limit": s_limit,
                    "rainfall_mm": 18.0 if weather == "RAIN" else 0.0,
                    "visibility_meters": 400.0 if weather == "FOG" else 2000.0,
                    "target_score": round(score, 3),
                    "target_class": c_label,
                })

            # B. Corridor approach scenarios (offset 250m - 600m with spatial risk decay)
            for dist_m in [250, 600]:
                angle = rng.uniform(0, 2 * math.pi)
                d_lat = (dist_m / 111000.0) * math.cos(angle)
                d_lng = (dist_m / (111000.0 * math.cos(math.radians(lat)))) * math.sin(angle)
                decay = math.exp(-dist_m / 600.0)
                eff_risk = b_risk * decay

                for cond in [conditions[0], conditions[2], conditions[4], conditions[8], conditions[9]]:
                    hour, day, weather, road_cond, lighting, vtype, spd_delta = cond
                    spd = max(10.0, s_limit + spd_delta)

                    spd_mod = min(0.25, max(0.0, (spd - s_limit) / s_limit * 0.35)) if s_limit > 0 else 0.0
                    w_mod = 0.15 if weather == "RAIN" else (0.12 if weather == "FOG" else 0.0)
                    rc_mod = 0.10 if road_cond in ("POTHOLE", "DAMAGED") else (0.06 if road_cond == "WET" else 0.0)
                    l_mod = 0.10 if lighting in ("DARK", "POOR") else (0.04 if lighting in ("NIGHT_LIT", "DUSK") else 0.0)
                    v_mod = 0.08 if vtype == "2-WHEELER" else 0.0

                    score = eff_risk * 0.60 + (spd_mod + w_mod + rc_mod + l_mod + v_mod) * 0.40 + 0.05
                    # Incorporate realistic stochastic human reaction and near-miss variance
                    score = max(0.08, min(0.96, score + rng.gauss(0, 0.043)))

                    if score >= 0.75:
                        c_label = "CRITICAL"
                    elif score >= 0.50:
                        c_label = "HIGH"
                    elif score >= 0.25:
                        c_label = "MEDIUM"
                    else:
                        c_label = "LOW"

                    records.append({
                        "latitude": lat + d_lat,
                        "longitude": lng + d_lng,
                        "road_class": road_class,
                        "hour": hour,
                        "day_of_week": day,
                        "weather": weather,
                        "road_condition": road_cond,
                        "lighting": lighting,
                        "vehicle_type": vtype,
                        "current_speed": spd,
                        "speed_limit": s_limit,
                        "rainfall_mm": 18.0 if weather == "RAIN" else 0.0,
                        "visibility_meters": 400.0 if weather == "FOG" else 2000.0,
                        "target_score": round(score, 3),
                        "target_class": c_label,
                    })

        # C. Safe corridor scenarios (>1.4km away from any blackspot across Nashik grid)
        safe_count = 0
        from app.ml.feature_engineering import haversine_distance
        for s_lat in [19.92 + i * 0.015 for i in range(12)]:
            for s_lng in [73.72 + j * 0.015 for j in range(12)]:
                min_d = min(haversine_distance(s_lat, s_lng, float(b["Latitude"]), float(b["Longitude"])) for b in raw_blackspots if "Latitude" in b and "Longitude" in b)
                if min_d > 1400:
                    for cond in [conditions[0], conditions[2], conditions[6]]:
                        hour, day, weather, road_cond, lighting, vtype, spd_delta = cond
                        spd = 40.0 + spd_delta
                        spd_mod = min(0.20, max(0.0, (spd - 40) / 40 * 0.25))
                        w_mod = 0.10 if weather == "RAIN" else 0.0
                        score = 0.08 + spd_mod + w_mod
                        c_label = "LOW" if score < 0.25 else "MEDIUM"

                        records.append({
                            "latitude": s_lat,
                            "longitude": s_lng,
                            "road_class": "Local Road",
                            "hour": hour,
                            "day_of_week": day,
                            "weather": weather,
                            "road_condition": road_cond,
                            "lighting": lighting,
                            "vehicle_type": vtype,
                            "current_speed": spd,
                            "speed_limit": 40.0,
                            "rainfall_mm": 18.0 if weather == "RAIN" else 0.0,
                            "visibility_meters": 2000.0,
                            "target_score": round(score, 3),
                            "target_class": c_label,
                        })
                        safe_count += 1
                        if safe_count >= 300:
                            break
                if safe_count >= 300:
                    break
            if safe_count >= 300:
                break

        logger.info(f"Prepared {len(records)} balanced training instances across {len(raw_blackspots)} real blackspot locations and safe corridors.")
        return records

    def retrain_model(
        self,
        request: ModelTrainingRequest,
        db: Optional[Session] = None
    ) -> ModelTrainingResponse:
        """Execute retraining pipeline, evaluate metrics, and update active model."""
        logger.info(f"Initiating ML model training with algorithm={request.algorithm}...")

        training_data = self.load_dataset_for_training(db)
        if not training_data:
            raise ValueError("No training data available. Verify database or blackspots CSV.")

        # Cache known hotspots for spatial feature calculations
        known_spots = self.get_known_hotspots(db)
        self.feature_engineer.set_known_hotspots(known_spots)

        # Train risk model
        metrics, metadata = self.risk_model.train_pipeline(
            training_records=training_data,
            algorithm=request.algorithm or "XGBoost",
            n_estimators=request.n_estimators or 50,
            test_size=request.test_size or 0.2
        )

        # Also run HDBSCAN clustering on any accident records in DB
        discovered_clusters_count = 0
        noise_points_count = 0
        if db:
            try:
                from app.models.accident import Accident
                accidents = db.query(Accident).all()
                if accidents:
                    acc_dicts = [
                        {
                            "latitude": a.latitude,
                            "longitude": a.longitude,
                            "fatalities": a.fatalities,
                            "injuries": a.injuries,
                            "severity": a.severity,
                        }
                        for a in accidents
                    ]
                    clusters, discovered_clusters_count, noise_points_count = self.clusterer.cluster_accidents(
                        acc_dicts,
                        min_cluster_size=settings.HDBSCAN_MIN_CLUSTER_SIZE,
                        min_samples=settings.HDBSCAN_MIN_SAMPLES,
                    )
                    if clusters:
                        self.clusterer.persist_clusters_to_db(db, clusters)
            except Exception as e:
                logger.warning(f"HDBSCAN clustering during retrain skipped: {e}")

        metadata.discovered_clusters = discovered_clusters_count
        metadata.noise_points = noise_points_count

        return ModelTrainingResponse(
            success=True,
            message=(
                f"Model {metadata.model_version} ({metadata.algorithm}) successfully trained "
                f"on {len(training_data)} records. F1 Score: {metrics.f1_score:.4f}, Accuracy: {metrics.accuracy:.4f}."
            ),
            metrics=metrics,
            metadata=metadata
        )

    def predict_risk(
        self,
        request: RiskPredictionRequest,
        db: Optional[Session] = None
    ) -> RiskPredictionResponse:
        """Predict dynamic accident risk for a single coordinate and context."""
        known_spots = self.get_known_hotspots(db)
        return self.risk_model.predict(request, known_hotspots=known_spots)

    def evaluate_routes(
        self,
        request: RouteRiskRequest,
        db: Optional[Session] = None
    ) -> RouteRiskResponse:
        """Score alternative routes and categorize into Fastest, Safest, Balanced."""
        known_spots = self.get_known_hotspots(db)
        context = {
            "vehicle_type": request.vehicle_type,
            "current_speed": request.current_speed,
            "weather": request.weather,
            "road_condition": request.road_condition,
            "lighting": request.lighting,
        }
        return self.route_engine.evaluate_routes(
            routes=request.routes,
            known_hotspots=known_spots,
            context=context
        )

    def run_hdbscan_clustering(
        self,
        request: ClusteringRequest,
        db: Session
    ) -> ClusteringResponse:
        """Run HDBSCAN clustering on accident records."""
        from app.models.accident import Accident
        accidents = db.query(Accident).all()
        total_records = len(accidents)

        data_limitation_note = None
        if total_records < (request.min_cluster_size or 3):
            data_limitation_note = (
                f"Active database has {total_records} incident record(s). "
                f"The 102 verified Nashik blackspots are maintained as ground-truth KNOWN_BLACKSPOT. "
                f"HDBSCAN requires at least {request.min_cluster_size or 3} incident coordinates to discover new clusters."
            )
            return ClusteringResponse(
                status="insufficient_incident_data",
                algorithm="HDBSCAN",
                total_records=total_records,
                clusters_count=0,
                noise_count=0,
                clusters=[],
                timestamp=datetime.now(timezone.utc).isoformat(),
                message="Insufficient incident records in database to form HDBSCAN clusters.",
                data_source_limitation_note=data_limitation_note
            )

        acc_dicts = [
            {
                "latitude": a.latitude,
                "longitude": a.longitude,
                "fatalities": a.fatalities,
                "injuries": a.injuries,
                "severity": a.severity,
            }
            for a in accidents
        ]

        clusters, num_clusters, num_noise = self.clusterer.cluster_accidents(
            acc_dicts,
            min_cluster_size=request.min_cluster_size or 3,
            min_samples=request.min_samples or 2,
        )

        if request.persist_to_db and clusters:
            self.clusterer.persist_clusters_to_db(
                db,
                clusters,
                replace_existing_ml=request.replace_existing_ml_hotspots or True
            )

        return ClusteringResponse(
            status="success",
            algorithm="HDBSCAN",
            total_records=total_records,
            clusters_count=num_clusters,
            noise_count=num_noise,
            clusters=clusters,
            timestamp=datetime.now(timezone.utc).isoformat(),
            message=f"HDBSCAN discovered {num_clusters} cluster(s) with {num_noise} noise point(s).",
            data_source_limitation_note=None
        )

    def get_model_status(self) -> Dict[str, Any]:
        """Return operational telemetry and metadata for the active model."""
        return {
            "model_version": self.risk_model.active_version,
            "algorithm": self.risk_model.algorithm,
            "is_trained": self.risk_model.regressor is not None,
            "xgboost_available": XGBOOST_AVAILABLE,
            "thresholds": self.risk_model.thresholds,
            "features_count": len(self.feature_engineer.known_hotspots),
            "features_used": FEATURE_COLUMNS,
            "metadata": self.risk_model.metadata,
        }


# Global model manager singleton instance
ml_manager = ModelManager()
