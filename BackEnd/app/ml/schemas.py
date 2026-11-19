"""Pydantic schemas for MargRakshak AI Machine Learning Pipeline.
Includes schemas for Risk Prediction, Model Retraining, HDBSCAN Hotspot Clustering, and Route Safety Scoring.
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator, ConfigDict


class NearestHotspotInfo(BaseModel):
    """Information regarding the closest known blackspot or ML hotspot."""
    id: int
    name: str
    distance_meters: float
    risk_level: str
    risk_score: float
    source: str = "KNOWN_BLACKSPOT"


class RiskPredictionRequest(BaseModel):
    """Input payload for dynamic accident risk inference."""
    latitude: float = Field(..., ge=-90.0, le=90.0, description="WGS84 Latitude (-90 to 90)")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="WGS84 Longitude (-180 to 180)")
    road_class: Optional[str] = Field("Local Road", description="Road category: National Highway, State Highway, etc.")
    hour: Optional[int] = Field(None, ge=0, le=23, description="Hour of the day (0 to 23)")
    day_of_week: Optional[int] = Field(None, ge=0, le=6, description="Day of week (0=Mon, 6=Sun)")
    weather: Optional[str] = Field("CLEAR", description="CLEAR, RAIN, FOG, HAZE, STORM")
    road_condition: Optional[str] = Field("NORMAL", description="NORMAL, DRY, WET, POTHOLE, DAMAGED")
    lighting: Optional[str] = Field("DAYLIGHT", description="DAYLIGHT, DARK, NIGHT_LIT, POOR")
    vehicle_type: Optional[str] = Field("CAR", description="CAR, 2-WHEELER, 3-WHEELER, BUS, TRUCK, COMMERCIAL")
    current_speed: Optional[float] = Field(0.0, ge=0.0, description="Current vehicle speed in km/h")
    speed_limit: Optional[float] = Field(40.0, gt=0.0, description="Governing speed limit in km/h")
    rainfall_mm: Optional[float] = Field(0.0, ge=0.0, description="Precipitation in mm")
    visibility_meters: Optional[float] = Field(1000.0, ge=0.0, description="Atmospheric visibility in meters")

    @field_validator("latitude")
    @classmethod
    def validate_latitude(cls, v: float) -> float:
        if not (-90.0 <= v <= 90.0):
            raise ValueError("Latitude must be between -90.0 and 90.0")
        return round(v, 6)

    @field_validator("longitude")
    @classmethod
    def validate_longitude(cls, v: float) -> float:
        if not (-180.0 <= v <= 180.0):
            raise ValueError("Longitude must be between -180.0 and 180.0")
        return round(v, 6)


class RiskPredictionResponse(BaseModel):
    """Dynamic accident risk prediction output."""
    risk_score: float = Field(..., ge=0.0, le=1.0, description="Continuous risk probability 0.0 to 1.0")
    risk_level: str = Field(..., description="Classification: LOW, MEDIUM, HIGH, CRITICAL")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Model prediction confidence")
    model_version: str = Field(..., description="Active deployed ML model identifier")
    nearest_hotspot: Optional[NearestHotspotInfo] = Field(None, description="Nearest hotspot proximity context")
    alert_required: bool = Field(False, description="Whether alert threshold was triggered")
    contributing_factors: List[str] = Field(default_factory=list, description="Primary drivers of computed risk")
    inference_time_ms: float = Field(..., description="Execution latency in milliseconds")


class ModelTrainingRequest(BaseModel):
    """Request payload for model training/retraining pipeline."""
    algorithm: Optional[str] = Field("XGBoost", description="'XGBoost' (preferred) or 'Random Forest' fallback")
    n_estimators: Optional[int] = Field(50, ge=10, le=500, description="Number of boosting trees/estimators")
    test_size: Optional[float] = Field(0.2, gt=0.05, lt=0.5, description="Hold-out validation split ratio")
    calibrate_thresholds: Optional[bool] = Field(True, description="Whether to optimize risk category thresholds")
    save_as_active: Optional[bool] = Field(True, description="Set newly trained model as primary active model")
    notes: Optional[str] = Field(None, description="Optional training changelog/release notes")


class ModelMetrics(BaseModel):
    """Standardized statistical evaluation metrics."""
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    roc_auc: Optional[float] = None
    brier_score: Optional[float] = None
    spatial_cv_groups: Optional[int] = None


class ModelMetadata(BaseModel):
    """Full versioned model metadata and provenance record."""
    model_version: str
    training_timestamp: str
    training_records: int
    features_used: List[str]
    algorithm: str
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    roc_auc: Optional[float] = None
    brier_score: Optional[float] = None
    spatial_cv_groups: Optional[int] = None
    risk_thresholds: Dict[str, float]
    training_dataset_version: str
    is_active: bool = True
    discovered_clusters: Optional[int] = None
    noise_points: Optional[int] = None
    model_path: Optional[str] = None


class ModelTrainingResponse(BaseModel):
    """Response returned upon completion of model training."""
    success: bool
    message: str
    metrics: ModelMetrics
    metadata: ModelMetadata


class ClusterItem(BaseModel):
    """Individual accident hotspot cluster discovered by HDBSCAN."""
    cluster_id: int
    accident_count: int
    latitude: float
    longitude: float
    radius_meters: float
    fatalities: int
    injuries: int
    density: float
    severity: str
    risk_score: float
    risk_level: str
    safety_recommendation: Optional[str] = None
    db_hotspot_id: Optional[int] = None


class ClusteringRequest(BaseModel):
    """Configuration for running HDBSCAN spatial clustering."""
    min_cluster_size: Optional[int] = Field(3, ge=2, description="Minimum accidents to constitute a cluster")
    min_samples: Optional[int] = Field(2, ge=1, description="HDBSCAN min_samples noise regulation parameter")
    persist_to_db: Optional[bool] = Field(False, description="Persist discovered clusters as ML_DISCOVERED_HOTSPOT in DB")
    replace_existing_ml_hotspots: Optional[bool] = Field(True, description="Replace prior ML clusters without touching KNOWN_BLACKSPOT")


class ClusteringResponse(BaseModel):
    """Result of HDBSCAN hotspot clustering."""
    status: str
    algorithm: str = "HDBSCAN"
    total_records: int
    clusters_count: int
    noise_count: int
    clusters: List[ClusterItem]
    timestamp: str
    message: str
    data_source_limitation_note: Optional[str] = None


class RouteCoordinate(BaseModel):
    """Latitude/Longitude pair along a navigation corridor."""
    lat: float
    lng: float


class RouteInput(BaseModel):
    """Individual candidate route for safety scoring."""
    route_id: str
    label: Optional[str] = None
    distance_km: float
    duration_minutes: float
    path: List[List[float]] = Field(..., description="Array of [lat, lng] coordinates along the road corridor")


class RouteRiskRequest(BaseModel):
    """Multi-route safety evaluation request."""
    routes: List[RouteInput]
    vehicle_type: Optional[str] = "CAR"
    current_speed: Optional[float] = None
    weather: Optional[str] = "CLEAR"
    road_condition: Optional[str] = "NORMAL"
    lighting: Optional[str] = "DAYLIGHT"


class ScoredRoute(BaseModel):
    """Evaluation result for an individual route."""
    route_id: str
    label: str
    category: str = Field(..., description="'Fastest Route', 'Safest Route', or 'Balanced Route'")
    distance_km: float
    duration_minutes: float
    risk_score: float = Field(..., ge=0.0, le=1.0)
    safety_score: int = Field(..., ge=0, le=100, description="Safety index from 0 (unsafe) to 100 (safest)")
    risk_level: str = Field(..., description="LOW, MEDIUM, HIGH, CRITICAL")
    blackspots_count: int
    ml_hotspots_count: int
    existing_blackspots_count: int = 0
    predicted_hotspots_count: int = 0
    total_hotspots_count: int = 0
    existing_blackspots: List[Dict[str, Any]] = Field(default_factory=list, description="Verified 102 blackspots along route")
    predicted_hotspots: List[Dict[str, Any]] = Field(default_factory=list, description="Dynamically predicted elevated risk hotspots along route")
    contributing_factors: List[str]


class RouteRiskResponse(BaseModel):
    """Multi-route comparative safety evaluation response."""
    routes: List[ScoredRoute]
    recommended_route_id: str
    evaluation_timestamp: str
