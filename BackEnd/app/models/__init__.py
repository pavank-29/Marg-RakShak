"""Database models package initialization."""
from app.models.base import Base, TimestampMixin, SpatialGeometry
from app.models.user import User
from app.models.accident import Accident
from app.models.hotspot import Hotspot
from app.models.risk_zone import RiskZone
from app.models.prediction import Prediction
from app.models.alert import SafetyAlert
from app.models.report import Report
from app.models.history import NavigationHistory
from app.models.hazard import Hazard

__all__ = [
    "Base",
    "TimestampMixin",
    "SpatialGeometry",

    "User",
    "Accident",
    "Hotspot",
    "RiskZone",
    "Prediction",
    "SafetyAlert",
    "Report",
    "NavigationHistory",
    "Hazard",
]
