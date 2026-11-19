"""Tests for Nashik road hazards and live traffic corridor endpoints."""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_get_hazards():
    """Verify GET /api/v1/hazards returns verified road hazards for Nashik City."""
    response = client.get("/api/v1/hazards")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["count"] > 0
    assert len(data["hazards"]) > 0

    first = data["hazards"][0]
    assert "hazard_type" in first
    assert "severity" in first
    assert "latitude" in first
    assert "longitude" in first
    assert "title" in first
    # Verify coordinates are in Nashik City bounding range
    assert 19.8 <= first["latitude"] <= 20.2
    assert 73.6 <= first["longitude"] <= 74.0


def test_get_hazards_near_route():
    """Verify POST /api/v1/hazards/near-route detects hazards along a road path."""
    # Polyline near Dwarka Circle (19.9912, 73.8015)
    sample_path = [
        [19.9900, 73.8010],
        [19.9915, 73.8015],
        [19.9930, 73.8020],
    ]
    response = client.post("/api/v1/hazards/near-route", json={"path": sample_path, "buffer_meters": 500.0})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert len(data["hazards"]) >= 1
    assert any(h["hazard_type"] == "CONSTRUCTION" for h in data["hazards"])


def test_get_traffic_corridors():
    """Verify GET /api/v1/route/corridors returns live traffic statuses for Nashik."""
    response = client.get("/api/v1/route/corridors")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["traffic_enabled"] is True
    assert data["count"] >= 8
    assert len(data["corridors"]) >= 8

    # Check key bottleneck presence
    names = [c["name"] for c in data["corridors"]]
    assert any("Dwarka" in n for n in names)
    assert any("CBS" in n for n in names)
    assert any("Mumbai Naka" in n for n in names)


def test_get_hazards_summary():
    """Verify GET /api/v1/hazards/summary returns counts of potholes and construction."""
    response = client.get("/api/v1/hazards/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "total" in data
    assert "potholes_count" in data
    assert "construction_count" in data
    assert "provider" in data
    assert data["total"] > 0


def test_calculate_route_without_realtime_traffic():
    """Verify route calculation operates without live traffic when with_traffic is False."""
    payload = {
        "source": {"lat": 19.9982, "lng": 73.7844, "name": "CBS Nashik"},
        "destination": {"lat": 19.9575, "lng": 73.8340, "name": "Nashik Road Station"},
        "waypoints": [],
        "vehicle_type": "car",
        "alternatives": True,
        "with_traffic": False,
    }
    response = client.post("/api/v1/route/calculate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["traffic_enabled"] is False
    route = data["routes"][0]
    assert "distance_km" in route
    assert "duration_min" in route
    assert route["distance_km"] > 0
    assert route["duration_min"] > 0

