"""Machine Learning API Endpoints for MargRakshak AI.
Provides:
- Dynamic Accident Risk Prediction (/api/v1/ml/predict-risk)
- Automated Model Training and Evaluation (/api/v1/ml/retrain)
- Multi-Route Safety Risk Scoring (/api/v1/ml/route-risk)
- HDBSCAN Spatial Hotspot Clustering (/api/v1/ml/cluster-hotspots)
- Active Model Status and Provenance (/api/v1/ml/status)
"""
import logging
import time
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, get_current_admin, get_optional_current_user
from app.models.user import User
from app.models.prediction import Prediction
from app.ml.model_manager import ml_manager
from app.ml.schemas import (
    RiskPredictionRequest,
    RiskPredictionResponse,
    ModelTrainingRequest,
    ModelTrainingResponse,
    RouteRiskRequest,
    RouteRiskResponse,
    ClusteringRequest,
    ClusteringResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/predict-risk",
    response_model=RiskPredictionResponse,
    status_code=status.HTTP_200_OK,
    summary="Predict dynamic accident risk for location and environmental telemetry",
    description="Calculates continuous risk score (0.0 to 1.0) and assigns classification (LOW, MEDIUM, HIGH, CRITICAL) using active XGBoost/Random Forest model.",
)
def predict_risk(
    payload: RiskPredictionRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user),
):
    """Predict dynamic accident risk at given spatial coordinates and conditions."""
    try:
        response = ml_manager.predict_risk(payload, db=db)

        # Audit inference into predictions table asynchronously or best-effort
        try:
            pred_record = Prediction(
                model_name=response.model_version,
                algorithm=ml_manager.risk_model.algorithm,
                latitude=payload.latitude,
                longitude=payload.longitude,
                predicted_risk_level=response.risk_level,
                predicted_risk_score=response.risk_score,
                confidence_score=response.confidence,
                input_features=payload.model_dump(),
                model_metrics={"inference_time_ms": response.inference_time_ms}
            )
            db.add(pred_record)
            db.commit()
        except Exception as audit_err:
            db.rollback()
            logger.warning(f"Could not record prediction audit log: {audit_err}")

        return response
    except Exception as e:
        logger.error(f"Prediction failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Risk prediction engine encountered an error: {str(e)}"
        )


@router.post(
    "/retrain",
    response_model=ModelTrainingResponse,
    status_code=status.HTTP_200_OK,
    summary="Trigger model training / retraining pipeline (Admin / Authorized)",
    description="Trains XGBoost / Random Forest on verified ground-truth blackspots and logged incidents. Computes Accuracy, Precision, Recall, F1, and saves versioned model artifacts.",
)
def retrain_model(
    payload: Optional[ModelTrainingRequest] = None,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user),
):
    """Train or retrain the accident risk prediction pipeline."""
    if payload is None:
        payload = ModelTrainingRequest()

    try:
        logger.info(f"Retrain triggered with algorithm={payload.algorithm}")
        res = ml_manager.retrain_model(payload, db=db)
        return res
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )
    except Exception as e:
        logger.error(f"Retraining failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Model retraining pipeline failed: {str(e)}"
        )


@router.post(
    "/route-risk",
    response_model=RouteRiskResponse,
    status_code=status.HTTP_200_OK,
    summary="Calculate safety score and risk profile for alternative navigation corridors",
    description="Samples coordinates along candidate routes, checks proximity to known blackspots and ML clusters, and classifies routes as 'Fastest Route', 'Safest Route', or 'Balanced Route'.",
)
def evaluate_route_risk(
    payload: RouteRiskRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user),
):
    """Evaluate multi-route corridor risk and safety score."""
    try:
        return ml_manager.evaluate_routes(payload, db=db)
    except Exception as e:
        logger.error(f"Route risk evaluation error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Route safety calculation failed: {str(e)}"
        )


@router.post(
    "/cluster-hotspots",
    response_model=ClusteringResponse,
    status_code=status.HTTP_200_OK,
    summary="Run HDBSCAN spatial clustering on accident incidents",
    description="Discovers density-based accident hotspots using spherical Haversine metric and persists them as ML_DISCOVERED_HOTSPOT in the database.",
)
def cluster_hotspots(
    payload: Optional[ClusteringRequest] = None,
    db: Session = Depends(get_db),
    current_admin: Optional[User] = Depends(get_optional_current_user),
):
    """Run HDBSCAN clustering on accident records."""
    if payload is None:
        payload = ClusteringRequest()

    try:
        return ml_manager.run_hdbscan_clustering(payload, db=db)
    except Exception as e:
        logger.error(f"HDBSCAN clustering failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"HDBSCAN clustering failed: {str(e)}"
        )


@router.get(
    "/status",
    summary="Get active ML model status, version, and performance metrics",
    description="Returns current active model metadata, algorithm, accuracy, precision, recall, F1, and risk thresholds.",
)
def get_ml_status():
    """Retrieve operational status and metrics for the ML pipeline."""
    return ml_manager.get_model_status()
