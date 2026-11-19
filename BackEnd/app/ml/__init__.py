"""MargRakshak AI Machine Learning Package.
Provides HDBSCAN spatial clustering, XGBoost/Random Forest dynamic risk prediction,
and multi-route safety scoring.
"""
from app.ml.model_manager import ml_manager, ModelManager
from app.ml.risk_model import RiskModel
from app.ml.clustering import HotspotClusterer
from app.ml.route_risk import RouteSafetyEngine
from app.ml.feature_engineering import FeatureEngineer, FEATURE_COLUMNS

__all__ = [
    "ml_manager",
    "ModelManager",
    "RiskModel",
    "HotspotClusterer",
    "RouteSafetyEngine",
    "FeatureEngineer",
    "FEATURE_COLUMNS",
]
