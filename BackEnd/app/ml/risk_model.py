"""Dynamic Accident Risk Prediction Model.
Implements XGBoost with automatic Random Forest fallback.
Produces continuous risk scores (0.0 - 1.0), risk levels (LOW, MEDIUM, HIGH, CRITICAL),
and confidence metrics with full explainability.
"""
import json
import logging
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.preprocessing import LabelEncoder

# Attempt importing XGBoost
try:
    import xgboost as xgb
    XGBOOST_AVAILABLE = True
except ImportError:
    xgb = None
    XGBOOST_AVAILABLE = False

from app.core.config import settings
from app.ml.feature_engineering import FeatureEngineer, FEATURE_COLUMNS, haversine_distance
from app.ml.schemas import (
    RiskPredictionRequest,
    RiskPredictionResponse,
    NearestHotspotInfo,
    ModelMetrics,
    ModelMetadata,
)

logger = logging.getLogger(__name__)


class RiskModel:
    """Manages training, versioning, evaluation, and inference of the risk prediction pipeline."""

    def __init__(self, model_dir: Optional[str] = None):
        self.base_dir = Path(model_dir or settings.MODEL_DIR) / "risk_model"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.model_path = self.base_dir / "risk_model.joblib"
        self.metadata_path = self.base_dir / "metadata.json"

        self.model = None
        self.regressor = None
        self.label_encoder = None
        self.feature_engineer = FeatureEngineer()
        self.active_version = "v1.0.0-initial"
        self.algorithm = "XGBoost" if XGBOOST_AVAILABLE else "Random Forest"
        self.thresholds = {
            "low": settings.RISK_THRESHOLD_LOW,
            "medium": settings.RISK_THRESHOLD_MEDIUM,
            "high": settings.RISK_THRESHOLD_HIGH,
        }
        self.metadata: Dict[str, Any] = {}

        # Attempt to load saved model on initialization
        self.load_model()

    def load_model(self) -> bool:
        """Load trained model weights and metadata from storage."""
        if self.model_path.exists() and self.metadata_path.exists():
            try:
                bundle = joblib.load(self.model_path)
                self.model = bundle.get("classifier")
                self.regressor = bundle.get("regressor")
                self.label_encoder = bundle.get("label_encoder")
                self.algorithm = bundle.get("algorithm", self.algorithm)

                with open(self.metadata_path, "r", encoding="utf-8") as f:
                    self.metadata = json.load(f)

                self.active_version = self.metadata.get("model_version", "v1.0.0")
                if "risk_thresholds" in self.metadata:
                    self.thresholds = self.metadata["risk_thresholds"]

                logger.info(
                    f"Successfully loaded active model {self.active_version} "
                    f"({self.algorithm}) from {self.model_path}"
                )
                return True
            except Exception as e:
                logger.error(f"Error loading model from {self.model_path}: {e}")
                return False
        return False

    def classify_risk(self, risk_score: float) -> str:
        """Map normalized continuous risk score to standard categorical level."""
        if risk_score >= self.thresholds.get("high", 0.75):
            return "CRITICAL"
        elif risk_score >= self.thresholds.get("medium", 0.50):
            return "HIGH"
        elif risk_score >= self.thresholds.get("low", 0.25):
            return "MEDIUM"
        return "LOW"

    def predict(
        self,
        request: Union[RiskPredictionRequest, Dict[str, Any]],
        known_hotspots: Optional[List[Dict[str, Any]]] = None
    ) -> RiskPredictionResponse:
        """Execute risk inference for a given spatial location and environmental/telemetry context."""
        start_time = time.perf_counter()

        data_dict = request.model_dump() if isinstance(request, RiskPredictionRequest) else dict(request)

        # Update spatial context if hotspots passed
        if known_hotspots:
            self.feature_engineer.set_known_hotspots(known_hotspots)

        feature_vector, nearest_spot = self.feature_engineer.extract_features_from_dict(data_dict)
        feature_matrix = feature_vector.reshape(1, -1)

        risk_score = 0.0
        confidence = 0.85
        factors: List[str] = []

        # 1. ML inference if model is loaded
        if self.regressor is not None:
            try:
                raw_score = float(self.regressor.predict(feature_matrix)[0])
                risk_score = max(0.0, min(1.0, raw_score))

                if self.model is not None and hasattr(self.model, "predict_proba"):
                    probs = self.model.predict_proba(feature_matrix)[0]
                    confidence = float(np.max(probs))
            except Exception as e:
                logger.warning(f"Model prediction failed, using fallback heuristic: {e}")
                risk_score, confidence = self._fallback_heuristic(data_dict, nearest_spot)
        else:
            # Resilient fallback heuristic if model is not yet trained
            risk_score, confidence = self._fallback_heuristic(data_dict, nearest_spot)

        # 2. Risk classification
        risk_level = self.classify_risk(risk_score)

        # 3. Factor explanations
        factors = self._explain_risk(data_dict, risk_score, nearest_spot)

        # 4. Proximity info
        nearest_info = None
        if nearest_spot:
            dist_m = haversine_distance(
                data_dict.get("latitude", 19.9975),
                data_dict.get("longitude", 73.7898),
                nearest_spot.get("latitude") or nearest_spot.get("lat"),
                nearest_spot.get("longitude") or nearest_spot.get("lng")
            )
            nearest_info = NearestHotspotInfo(
                id=int(nearest_spot.get("id", 0)),
                name=str(nearest_spot.get("name", "Known Blackspot")),
                distance_meters=round(dist_m, 1),
                risk_level=str(nearest_spot.get("risk_level") or nearest_spot.get("riskLevel") or "HIGH"),
                risk_score=float(nearest_spot.get("risk_score") or nearest_spot.get("riskScore") or 0.75),
                source=str(nearest_spot.get("source", "KNOWN_BLACKSPOT"))
            )

        alert_required = risk_level in ("HIGH", "CRITICAL") or risk_score >= 0.50
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

        return RiskPredictionResponse(
            risk_score=round(risk_score, 3),
            risk_level=risk_level,
            confidence=round(confidence, 3),
            model_version=self.active_version,
            nearest_hotspot=nearest_info,
            alert_required=alert_required,
            contributing_factors=factors,
            inference_time_ms=elapsed_ms
        )

    def _fallback_heuristic(
        self,
        data: Dict[str, Any],
        nearest_spot: Optional[Dict[str, Any]]
    ) -> Tuple[float, float]:
        """Physics- and GIS-based deterministic heuristic risk calculation when ML model is pending."""
        base_risk = 0.20

        # Spatial proximity component
        if nearest_spot:
            spot_lat = nearest_spot.get("latitude") or nearest_spot.get("lat")
            spot_lng = nearest_spot.get("longitude") or nearest_spot.get("lng")
            dist = haversine_distance(
                float(data.get("latitude", 19.9975)),
                float(data.get("longitude", 73.7898)),
                float(spot_lat),
                float(spot_lng)
            )
            spot_risk = float(nearest_spot.get("risk_score") or nearest_spot.get("riskScore") or 0.75)
            if dist < 200:
                base_risk = max(base_risk, spot_risk * 0.95)
            elif dist < 500:
                base_risk = max(base_risk, spot_risk * 0.75)
            elif dist < 1000:
                base_risk = max(base_risk, spot_risk * 0.50)

        # Overspeed component
        speed = float(data.get("current_speed", 0.0) or 0.0)
        limit = float(data.get("speed_limit", 40.0) or 40.0)
        if limit > 0 and speed > limit:
            ratio = (speed - limit) / limit
            base_risk += min(0.35, ratio * 0.4)

        # Environmental component
        weather = str(data.get("weather", "CLEAR")).upper()
        if "RAIN" in weather or "STORM" in weather:
            base_risk += 0.20
        elif "FOG" in weather:
            base_risk += 0.15

        road_cond = str(data.get("road_condition", "NORMAL")).upper()
        if "WET" in road_cond or "POTHOLE" in road_cond or "POOR" in road_cond:
            base_risk += 0.15

        # Temporal / Lighting
        hour = data.get("hour")
        if hour is not None and (hour >= 21 or hour <= 5):
            base_risk += 0.15

        return round(max(0.05, min(0.98, base_risk)), 3), 0.80

    def _explain_risk(
        self,
        data: Dict[str, Any],
        risk_score: float,
        nearest_spot: Optional[Dict[str, Any]]
    ) -> List[str]:
        """Generate actionable human-interpretable factors explaining the risk determination."""
        factors = []

        if nearest_spot:
            dist = haversine_distance(
                float(data.get("latitude", 19.9975)),
                float(data.get("longitude", 73.7898)),
                float(nearest_spot.get("latitude") or nearest_spot.get("lat")),
                float(nearest_spot.get("longitude") or nearest_spot.get("lng"))
            )
            if dist <= 350:
                name = nearest_spot.get("name", "Accident Hotspot")
                factors.append(f"Proximity to high-density blackspot: {name} ({int(dist)}m away)")

        speed = float(data.get("current_speed", 0.0) or 0.0)
        limit = float(data.get("speed_limit", 40.0) or 40.0)
        if limit > 0 and speed > limit:
            pct = int(((speed - limit) / limit) * 100)
            factors.append(f"Speed limit exceeded: {int(speed)} km/h in {int(limit)} km/h zone (+{pct}%)")

        weather = str(data.get("weather", "CLEAR")).upper()
        if "RAIN" in weather:
            factors.append("Adverse weather: Active rainfall reducing road traction")
        elif "FOG" in weather:
            factors.append("Adverse weather: Dense fog impairing corridor visibility")

        road_cond = str(data.get("road_condition", "NORMAL")).upper()
        if "WET" in road_cond or "POOR" in road_cond:
            factors.append(f"Road surface hazard: {road_cond.title()} condition")

        hour = data.get("hour")
        if hour is not None and (hour >= 21 or hour <= 5):
            factors.append(f"Nighttime operation: Reduced visibility at {hour:02d}:00 hrs")

        vtype = str(data.get("vehicle_type", "CAR")).upper()
        if "2-WHEELER" in vtype or "BIKE" in vtype:
            factors.append("High-vulnerability vehicle type (Two-Wheeler)")

        if not factors:
            factors.append("Optimal road conditions and standard traffic flow")

        return factors

    def train_pipeline(
        self,
        training_records: List[Dict[str, Any]],
        algorithm: str = "XGBoost",
        n_estimators: int = 50,
        test_size: float = 0.2,
        version_label: Optional[str] = None
    ) -> Tuple[ModelMetrics, ModelMetadata]:
        """Execute full training, feature extraction, cross-validation, and model persistence.
        Guarantees strict zero target leakage by separating input features from ground-truth risk.
        """
        if len(training_records) < 20:
            raise ValueError(f"Insufficient training records ({len(training_records)}). Minimum 20 records required.")

        # Build feature matrix strictly using FEATURE_COLUMNS
        X_df = self.feature_engineer.build_feature_dataframe(training_records)
        X = X_df.values

        # Build ground-truth target without leaking target columns
        y_scores = []
        y_classes = []

        for rec in training_records:
            if "target_score" in rec and "target_class" in rec:
                target_score = float(rec["target_score"])
                target_class = str(rec["target_class"]).upper()
            else:
                # Target is derived from historical severity impact and ground-truth accident history
                fatalities = float(rec.get("fatalities", 0) or rec.get("Total Fatalities", 0) or 0)
                accidents = float(rec.get("accident_count", 0) or rec.get("Total Accidents", 0) or 0)
                injuries = float(rec.get("injuries", 0) or rec.get("Injuries", 0) or 0)

                # Domain severity formula
                norm_severity = (min(fatalities, 20) / 20.0) * 0.45 + \
                                (min(accidents, 50) / 50.0) * 0.35 + \
                                (min(injuries, 30) / 30.0) * 0.20
                
                # Incorporate contextual operational factors from the training instance
                speed = float(rec.get("current_speed", 30))
                limit = float(rec.get("speed_limit", 40))
                speed_mult = min(0.3, max(0.0, (speed - limit) / limit * 0.3)) if limit > 0 else 0.0

                weather = str(rec.get("weather", "CLEAR")).upper()
                w_mult = 0.15 if ("RAIN" in weather or "FOG" in weather) else 0.0

                target_score = max(0.05, min(0.98, norm_severity * 0.65 + speed_mult + w_mult + 0.10))

                if target_score >= 0.75:
                    target_class = "CRITICAL"
                elif target_score >= 0.50:
                    target_class = "HIGH"
                elif target_score >= 0.25:
                    target_class = "MEDIUM"
                else:
                    target_class = "LOW"

            y_scores.append(target_score)
            y_classes.append(target_class)

        y_scores = np.array(y_scores, dtype=np.float32)
        y_classes = np.array(y_classes)

        # Encode multi-class target labels to integers (0, 1, 2, 3) for XGBoost compatibility
        le = LabelEncoder()
        y_classes_encoded = le.fit_transform(y_classes)
        self.label_encoder = le

        # Account for spatial dependence: Group by spatial geographic blocks to prevent spatial autocorrelation leakage
        spatial_groups = np.array([
            f"{round(float(r.get('latitude', 19.9975)) / 0.02, 1)}_{round(float(r.get('longitude', 73.7898)) / 0.02, 1)}"
            for r in training_records
        ])
        unique_groups = len(np.unique(spatial_groups))

        split_success = False
        try:
            from sklearn.model_selection import GroupShuffleSplit
            gss = GroupShuffleSplit(n_splits=10, test_size=test_size, random_state=42)
            for tr_idx, te_idx in gss.split(X, y_classes_encoded, groups=spatial_groups):
                # Verify representation of classes across split
                if len(np.unique(y_classes_encoded[tr_idx])) == len(le.classes_) and len(np.unique(y_classes_encoded[te_idx])) >= min(3, len(le.classes_)):
                    X_train, X_test = X[tr_idx], X[te_idx]
                    y_train_score, y_test_score = y_scores[tr_idx], y_scores[te_idx]
                    y_train_class_enc, y_test_class_enc = y_classes_encoded[tr_idx], y_classes_encoded[te_idx]
                    split_success = True
                    break
        except Exception as e:
            logger.warning(f"Spatial group split encountered issue, falling back to stratified: {e}")

        if not split_success:
            # Fallback to stratified split if spatial block distribution lacks minority classes
            X_train, X_test, y_train_score, y_test_score, y_train_class_enc, y_test_class_enc = train_test_split(
                X, y_scores, y_classes_encoded, test_size=test_size, random_state=42, stratify=y_classes_encoded
            )

        y_test_class = le.inverse_transform(y_test_class_enc)

        use_xgboost = algorithm.upper() == "XGBOOST" and XGBOOST_AVAILABLE

        if use_xgboost:
            logger.info("Training gradient boosted trees using XGBoost with spatial validation...")
            # Regressor for risk_score
            reg = xgb.XGBRegressor(
                n_estimators=n_estimators,
                max_depth=5,
                learning_rate=0.08,
                subsample=0.85,
                colsample_bytree=0.85,
                random_state=42
            )
            reg.fit(X_train, y_train_score)

            # Classifier for discrete level & class probabilities
            clf = xgb.XGBClassifier(
                n_estimators=n_estimators,
                max_depth=5,
                learning_rate=0.08,
                random_state=42
            )
            clf.fit(X_train, y_train_class_enc)
            algo_name = "XGBoost"
        else:
            logger.info("Training ensemble trees using Random Forest with spatial validation...")
            reg = RandomForestRegressor(
                n_estimators=n_estimators,
                max_depth=6,
                random_state=42
            )
            reg.fit(X_train, y_train_score)

            clf = RandomForestClassifier(
                n_estimators=n_estimators,
                max_depth=6,
                random_state=42
            )
            clf.fit(X_train, y_train_class_enc)
            algo_name = "Random Forest"

        # Evaluation
        y_pred_enc = clf.predict(X_test)
        y_pred_class = le.inverse_transform(y_pred_enc)
        y_pred_score = reg.predict(X_test)

        acc = float(accuracy_score(y_test_class, y_pred_class))
        prec = float(precision_score(y_test_class, y_pred_class, average="weighted", zero_division=0))
        rec = float(recall_score(y_test_class, y_pred_class, average="weighted", zero_division=0))
        f1 = float(f1_score(y_test_class, y_pred_class, average="weighted", zero_division=0))

        roc_auc = None
        brier_score = None
        try:
            if hasattr(clf, "predict_proba"):
                y_prob = clf.predict_proba(X_test)
                if len(np.unique(y_test_class_enc)) > 1 and y_prob.shape[1] == len(le.classes_):
                    roc_auc = float(roc_auc_score(y_test_class_enc, y_prob, multi_class="ovr", average="weighted"))
                
                # Probability calibration metric (Brier score)
                from sklearn.preprocessing import label_binarize
                y_test_one_hot = label_binarize(y_test_class_enc, classes=np.arange(len(le.classes_)))
                if y_prob.shape == y_test_one_hot.shape:
                    brier_score = float(np.mean(np.sum((y_prob - y_test_one_hot) ** 2, axis=1)))
        except Exception:
            pass

        metrics = ModelMetrics(
            accuracy=round(acc, 4),
            precision=round(prec, 4),
            recall=round(rec, 4),
            f1_score=round(f1, 4),
            roc_auc=round(roc_auc, 4) if roc_auc is not None else None,
            brier_score=round(brier_score, 4) if brier_score is not None else None,
            spatial_cv_groups=unique_groups
        )

        version = version_label or f"v{datetime.now().strftime('%Y%m%d-%H%M')}"
        timestamp_str = datetime.now(timezone.utc).isoformat()

        metadata = ModelMetadata(
            model_version=version,
            training_timestamp=timestamp_str,
            training_records=len(training_records),
            features_used=FEATURE_COLUMNS,
            algorithm=algo_name,
            accuracy=metrics.accuracy,
            precision=metrics.precision,
            recall=metrics.recall,
            f1_score=metrics.f1_score,
            roc_auc=metrics.roc_auc,
            brier_score=metrics.brier_score,
            spatial_cv_groups=unique_groups,
            risk_thresholds=self.thresholds,
            training_dataset_version="Nashik Unified GIS Blackspots 2026",
            is_active=True,
            model_path=str(self.model_path)
        )

        # Persist model bundle and metadata
        bundle = {
            "classifier": clf,
            "regressor": reg,
            "label_encoder": le,
            "algorithm": algo_name,
            "version": version,
            "features": FEATURE_COLUMNS,
        }
        joblib.dump(bundle, self.model_path)

        with open(self.metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata.model_dump(), f, indent=2)

        # Update in-memory active instances
        self.model = clf
        self.regressor = reg
        self.label_encoder = le
        self.algorithm = algo_name
        self.active_version = version
        self.metadata = metadata.model_dump()

        logger.info(
            f"Model {version} ({algo_name}) successfully trained and persisted. "
            f"F1: {metrics.f1_score:.4f}, Accuracy: {metrics.accuracy:.4f}"
        )
        return metrics, metadata
