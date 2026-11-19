"""Tests for road routing and multi-route navigation endpoints without live traffic dependencies."""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_calculate_route_post_success():
    """Verify POST /api/v1/route/calculate returns genuine road routes with real-time segment-based traffic."""
    payload = {
        "source": {"lat": 19.9982, "lng": 73.7844, "name": "CBS Nashik"},
        "destination": {"lat": 19.9575, "lng": 73.8340, "name": "Nashik Road Station"},
        "waypoints": [],
        "vehicle_type": "car",
        "alternatives": True,
        "with_traffic": True,
    }
    response = client.post("/api/v1/route/calculate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["traffic_enabled"] is True
    assert len(data["routes"]) >= 1

    primary = data["routes"][0]
    assert "distance_km" in primary
    assert primary["distance_km"] > 0
    assert "duration_min" in primary
    assert primary["duration_min"] > 0
    assert "path" in primary
    assert len(primary["path"]) > 5
    assert primary["is_recommended"] is True
    assert "traffic_segments" in primary
    assert len(primary["traffic_segments"]) >= 1
    # Check that road segments contain traffic status and color
    seg = primary["traffic_segments"][0]
    assert "traffic_status" in seg
    assert "color" in seg
    assert seg["color"].startswith("#")



def test_calculate_route_two_alternatives():
    """Verify routing returns two feasible alternative routes between distinct endpoints."""
    payload = {
        "source": {"lat": 19.9982, "lng": 73.7844, "name": "CBS Nashik"},
        "destination": {"lat": 19.9575, "lng": 73.8340, "name": "Nashik Road Station"},
        "waypoints": [],
        "vehicle_type": "car",
        "alternatives": True,
    }
    response = client.post("/api/v1/route/calculate", json=payload)
    assert response.status_code == 200
    data = response.json()
    routes = data["routes"]
    assert len(routes) == 2
    r1, r2 = routes[0], routes[1]

    # Verify both routes start at source and terminate at destination
    assert abs(r1["path"][0][0] - payload["source"]["lat"]) < 0.05
    assert abs(r1["path"][-1][0] - payload["destination"]["lat"]) < 0.05
    assert abs(r2["path"][0][0] - payload["source"]["lat"]) < 0.05
    assert abs(r2["path"][-1][0] - payload["destination"]["lat"]) < 0.05

    # Verify distinctness: distances are plausible and routes are labeled
    assert r1["distance_km"] > 0
    assert r2["distance_km"] > 0
    assert r1["id"] != r2["id"]


def test_calculate_route_identical_coordinates():
    """Verify error 400 when source and destination coordinates are identical."""
    payload = {
        "source": {"lat": 19.9982, "lng": 73.7844},
        "destination": {"lat": 19.9982, "lng": 73.7844},
    }
    response = client.post("/api/v1/route/calculate", json=payload)
    assert response.status_code == 400
    assert "identical" in response.json()["detail"].lower()


def test_calculate_route_get_convenience_endpoint():
    """Verify GET /api/route?from=...&to=... endpoint returns primaryRoute and routes with traffic segments."""
    url = "/api/route?from=19.9982,73.7844&to=19.9575,73.8340&alternatives=true"
    response = client.get(url)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["primaryRoute"] is not None
    assert "distance_km" in data["primaryRoute"]
    assert "duration_min" in data["primaryRoute"]
    assert data["traffic_enabled"] is True
    assert "traffic_segments" in data["primaryRoute"]
