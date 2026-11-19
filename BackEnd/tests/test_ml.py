"""Unit and integration test suite for MargRakshak AI Machine Learning Pipeline."""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.ml.feature_engineering import FeatureEngineer, haversine_distance
from app.ml.risk_model import RiskModel

client = TestClient(app)


def test_ml_status_endpoint():
    """Verify that /api/v1/ml/status returns model operational state."""
    response = client.get("/api/v1/ml/status")
    assert response.status_code == 200
    data = response.json()
    assert "model_version" in data
    assert "algorithm" in data
    assert "thresholds" in data
    assert "features_used" in data
    assert len(data["features_used"]) > 0


def test_predict_risk_valid():
    """Verify dynamic accident risk prediction with full contextual telemetry."""
    payload = {
        "latitude": 19.9975,
        "longitude": 73.7898,
        "road_class": "National Highway",
        "hour": 21,
        "day_of_week": 5,
        "weather": "RAIN",
        "road_condition": "WET",
        "lighting": "DARK",
        "vehicle_type": "2-WHEELER",
        "current_speed": 55.0,
        "speed_limit": 40.0
    }
    response = client.post("/api/v1/ml/predict-risk", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "risk_score" in data
    assert 0.0 <= data["risk_score"] <= 1.0
    assert data["risk_level"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert "confidence" in data
    assert "model_version" in data
    assert "alert_required" in data
    assert isinstance(data["contributing_factors"], list)
    assert len(data["contributing_factors"]) > 0
    assert data["inference_time_ms"] >= 0


def test_predict_risk_missing_optional_fields():
    """Verify prediction works reliably with only latitude and longitude."""
    payload = {
        "latitude": 20.005,
        "longitude": 73.790
    }
    response = client.post("/api/v1/ml/predict-risk", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert 0.0 <= data["risk_score"] <= 1.0
    assert data["risk_level"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")


def test_predict_risk_invalid_coordinates():
    """Verify that out-of-bounds coordinates are rejected with 422 Unprocessable Entity."""
    # Latitude > 90
    bad_lat = {"latitude": 95.0, "longitude": 73.8}
    res_lat = client.post("/api/v1/ml/predict-risk", json=bad_lat)
    assert res_lat.status_code == 422

    # Longitude < -180
    bad_lng = {"latitude": 20.0, "longitude": -195.0}
    res_lng = client.post("/api/v1/ml/predict-risk", json=bad_lng)
    assert res_lng.status_code == 422


def test_model_retrain_endpoint():
    """Verify model retraining pipeline executes and returns valid metrics."""
    retrain_payload = {
        "algorithm": "XGBoost",
        "n_estimators": 50,
        "test_size": 0.2
    }
    response = client.post("/api/v1/ml/retrain", json=retrain_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "metrics" in data
    metrics = data["metrics"]
    assert 0.0 <= metrics["accuracy"] <= 1.0
    assert 0.0 <= metrics["f1_score"] <= 1.0
    assert 0.0 <= metrics["precision"] <= 1.0
    assert 0.0 <= metrics["recall"] <= 1.0

    metadata = data["metadata"]
    assert metadata["training_records"] >= 100
    assert "model_version" in metadata
    assert "features_used" in metadata


def test_route_risk_scoring():
    """Verify alternative route risk scoring evaluates and classifies routes."""
    routes_payload = {
        "routes": [
            {
                "route_id": "route_1",
                "label": "Route 1",
                "distance_km": 8.5,
                "duration_minutes": 18.0,
                "path": [
                    [19.9870, 73.7841],
                    [19.9920, 73.7890],
                    [20.0050, 73.7950],
                    [20.0150, 73.8050]
                ]
            },
            {
                "route_id": "route_2",
                "label": "Route 2",
                "distance_km": 11.2,
                "duration_minutes": 22.0,
                "path": [
                    [19.9870, 73.7841],
                    [19.9750, 73.7600],
                    [19.9900, 73.7400],
                    [20.0150, 73.8050]
                ]
            }
        ],
        "vehicle_type": "CAR",
        "weather": "CLEAR"
    }

    response = client.post("/api/v1/ml/route-risk", json=routes_payload)
    assert response.status_code == 200
    data = response.json()
    assert "routes" in data
    assert len(data["routes"]) == 2
    assert "recommended_route_id" in data

    for r in data["routes"]:
        assert "route_id" in r
        assert "safety_score" in r
        assert 0 <= r["safety_score"] <= 100
        assert r["risk_level"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
        assert "category" in r
        assert "blackspots_count" in r
        assert "ml_hotspots_count" in r
        assert "predicted_hotspots" in r
        assert "existing_blackspots" in r
        assert isinstance(r["contributing_factors"], list)


def test_dynamic_predicted_hotspots_along_route():
    """Verify ML hotspot prediction generates distinct predicted hotspots with uncertainty labeling."""
    routes_payload = {
        "routes": [
            {
                "route_id": "test_corridor",
                "label": "Nashik Pune Highway Corridor",
                "distance_km": 14.5,
                "duration_minutes": 25.0,
                "path": [
                    [19.9538, 73.8376],  # Near Bitco Chowk (known blackspot)
                    [19.9450, 73.8450],
                    [19.9350, 73.8550],
                    [19.9250, 73.8750],  # Palase gaon corridor
                    [19.9100, 73.9050],
                ]
            }
        ],
        "vehicle_type": "CAR",
        "weather": "RAIN",
        "road_condition": "WET",
        "lighting": "DARK"
    }

    response = client.post("/api/v1/ml/route-risk", json=routes_payload)
    assert response.status_code == 200
    data = response.json()
    r = data["routes"][0]

    # Verify existing blackspots and predicted hotspots are separated
    assert isinstance(r["existing_blackspots"], list)
    assert isinstance(r["predicted_hotspots"], list)
    assert r["existing_blackspots_count"] == len(r["existing_blackspots"])
    assert r["predicted_hotspots_count"] == len(r["predicted_hotspots"])
    assert r["total_hotspots_count"] == r["existing_blackspots_count"] + r["predicted_hotspots_count"]

    # Verify existing blackspot source
    for eb in r["existing_blackspots"]:
        assert eb["source"] == "KNOWN_BLACKSPOT"
        assert eb["is_predicted"] is False

    # Verify predicted hotspot properties and uncertainty communication
    for ph in r["predicted_hotspots"]:
        assert ph["source"] == "ML_PREDICTED"
        assert ph["is_predicted"] is True
        assert 0.0 <= ph["risk_score"] <= 1.0
        assert ph["risk_level"] in ("MEDIUM", "HIGH", "CRITICAL")
        assert "uncertainty_note" in ph
        assert len(ph["uncertainty_note"]) > 0
        assert "confidence" in ph
        assert 0.0 <= ph["confidence"] <= 1.0


def test_hdbscan_cluster_hotspots_endpoint():
    """Verify HDBSCAN clustering endpoint handles database state gracefully."""
    response = client.post("/api/v1/ml/cluster-hotspots", json={"min_cluster_size": 3})
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "algorithm" in data
    assert data["algorithm"] == "HDBSCAN"
    assert "clusters_count" in data
    assert "noise_count" in data


def test_haversine_distance():
    """Test geospatial haversine distance calculation."""
    # Nashik Bitco Chowk to Mumbai Agra Road
    lat1, lon1 = 19.953882, 73.837678
    lat2, lon2 = 19.969002, 73.818446
    dist = haversine_distance(lat1, lon1, lat2, lon2)
    assert 2000 < dist < 4000  # Approx 2.6 km
