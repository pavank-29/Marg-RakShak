"""Unit and integration tests for real-time fleet & vehicle tracking endpoints."""
import time
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_get_fleet_empty_or_active():
    """Verify GET /api/v1/tracking/fleet returns active fleet dictionary."""
    response = client.get("/api/v1/tracking/fleet")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "fleet" in data
    assert isinstance(data["fleet"], list)


def test_push_location_update_rest():
    """Verify REST fallback location update pushes telemetry and returns risk evaluation."""
    payload = {
        "id": "vehicle-test-rest-1",
        "name": "Ambulance #108",
        "vehicleType": "emergency",
        "color": "#ef4444",
        "latitude": 19.9975,
        "longitude": 73.7898,
        "speed": 45.0,
        "heading": 180.0,
        "accuracy": 5.0,
    }
    response = client.post("/api/v1/tracking/update", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "tracker" in data
    tracker = data["tracker"]
    assert tracker["id"] == "vehicle-test-rest-1"
    assert tracker["name"] == "Ambulance #108"
    assert tracker["vehicleType"] == "emergency"
    assert tracker["speed"] == 45.0
    assert "riskScore" in tracker
    assert "riskLevel" in tracker

    # Verify tracker is now listed in /fleet
    fleet_resp = client.get("/api/v1/tracking/fleet")
    assert fleet_resp.status_code == 200
    fleet_ids = [v["id"] for v in fleet_resp.json()["fleet"]]
    assert "vehicle-test-rest-1" in fleet_ids


def test_push_location_invalid_coordinates():
    """Verify invalid geographic coordinates are rejected with HTTP 422."""
    payload = {
        "id": "vehicle-invalid",
        "latitude": 195.0,  # Invalid latitude > 90
        "longitude": 73.0,
    }
    response = client.post("/api/v1/tracking/update", json=payload)
    assert response.status_code == 422


def test_tracking_websocket_lifecycle():
    """Verify WebSocket connection, init-fleet snapshot, ping/pong, and location stream."""
    client_id = f"test_client_{int(time.time())}"

    with client.websocket_connect(f"/api/v1/tracking/ws/{client_id}") as ws:
        # 1. First message must be 'init-fleet'
        init_data = ws.receive_json()
        assert init_data["type"] == "init-fleet"
        assert "fleet" in init_data

        # 2. Ping-pong latency test
        ws.send_json({"type": "ping"})
        pong_data = ws.receive_json()
        assert pong_data["type"] == "pong"
        assert "timestamp" in pong_data

        # 3. Location update broadcast
        loc_payload = {
            "name": "Police Patrol #12",
            "vehicleType": "car",
            "color": "#3b82f6",
            "latitude": 19.9982,
            "longitude": 73.7844,
            "speed": 35.0,
            "heading": 90.0,
            "accuracy": 8.0,
        }
        ws.send_json(loc_payload)
        update_data = ws.receive_json()
        assert update_data["type"] == "location-update"
        assert update_data["data"]["id"] == client_id
        assert update_data["data"]["name"] == "Police Patrol #12"
        assert update_data["data"]["latitude"] == 19.9982
        assert update_data["data"]["longitude"] == 73.7844
        assert "riskScore" in update_data["data"]
        assert "riskLevel" in update_data["data"]
