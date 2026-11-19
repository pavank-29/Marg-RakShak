"""Feature Engineering and Preprocessing Pipeline for Accident Risk Prediction.
Ensures zero target leakage: features strictly include observable spatial, temporal,
environmental, and vehicle telemetry inputs.
"""
import math
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional
import numpy as np
import pandas as pd


# Documented list of features fed into the risk models
FEATURE_COLUMNS = [
    "latitude",
    "longitude",
    "road_class_encoded",
    "distance_to_nearest_hotspot",
    "hotspot_density",
    "road_segment_risk",
    "hour",
    "day_of_week",
    "is_weekend",
    "is_rush_hour",
    "is_night",
    "weather_encoded",
    "road_condition_encoded",
    "lighting_encoded",
    "vehicle_type_encoded",
    "current_speed",
    "speed_limit",
    "overspeed_ratio",
    "rainfall_mm",
    "visibility_factor"
]

ROAD_CLASS_MAPPING = {
    "national highway": 1.0,
    "national highway (nh-60)": 1.0,
    "national highway (nh-03)": 1.0,
    "state highway": 0.8,
    "major district road": 0.65,
    "other district road": 0.5,
    "collector road": 0.45,
    "local road": 0.35,
    "village road": 0.25,
}

WEATHER_MAPPING = {
    "clear": 0.0,
    "normal": 0.0,
    "haze": 0.3,
    "fog": 0.7,
    "rain": 0.85,
    "heavy rain": 1.0,
    "storm": 1.0,
}

ROAD_CONDITION_MAPPING = {
    "normal": 0.0,
    "dry": 0.0,
    "good": 0.0,
    "wet": 0.6,
    "pothole": 0.8,
    "damaged": 0.9,
    "poor road surface": 0.85,
}

LIGHTING_MAPPING = {
    "daylight": 0.0,
    "day": 0.0,
    "night_lit": 0.35,
    "dusk": 0.4,
    "dawn": 0.4,
    "poor": 0.75,
    "dark": 0.9,
    "pitch dark": 1.0,
}

VEHICLE_TYPE_MAPPING = {
    "car": 0.3,
    "2-wheeler": 0.75,
    "motorcycle": 0.75,
    "scooter": 0.75,
    "bike": 0.75,
    "3-wheeler": 0.6,
    "auto": 0.6,
    "bus": 0.5,
    "truck": 0.65,
    "commercial": 0.55,
}


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two points in meters."""
    R = 6371000.0  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


class FeatureEngineer:
    """Extracts, encodes, and normalizes feature vectors for prediction and training."""

    def __init__(self, known_hotspots: Optional[List[Dict[str, Any]]] = None):
        """Initialize feature engineer with optional cached known hotspot locations."""
        self.known_hotspots = known_hotspots or []

    def set_known_hotspots(self, hotspots: List[Dict[str, Any]]) -> None:
        """Update active known hotspot reference points."""
        self.known_hotspots = hotspots

    def compute_spatial_context(self, lat: float, lng: float) -> Tuple[float, float, Optional[Dict[str, Any]]]:
        """Compute distance to nearest known hotspot and density of hotspots within 2km.
        
        Returns:
            (min_distance_meters, hotspot_density_count, nearest_hotspot_dict)
        """
        if not self.known_hotspots:
            return 5000.0, 0.0, None

        min_dist = float("inf")
        nearest_spot = None
        density_count = 0

        for spot in self.known_hotspots:
            s_lat = spot.get("latitude") or spot.get("lat")
            s_lng = spot.get("longitude") or spot.get("lng")
            if s_lat is None or s_lng is None:
                continue

            dist = haversine_distance(lat, lng, float(s_lat), float(s_lng))
            if dist < min_dist:
                min_dist = dist
                nearest_spot = spot

            if dist <= 2000.0:  # Within 2km corridor
                density_count += 1

        if min_dist == float("inf"):
            min_dist = 5000.0

        return min_dist, float(density_count), nearest_spot

    def extract_features_from_dict(self, data: Dict[str, Any]) -> Tuple[np.ndarray, Dict[str, Any]]:
        """Extract a single feature vector from raw dictionary inputs.
        Handles missing fields gracefully with sensible domain defaults.
        """
        lat = float(data.get("latitude", 19.9975))
        lng = float(data.get("longitude", 73.7898))

        # Spatial context
        min_dist, density, nearest_spot = self.compute_spatial_context(lat, lng)

        # Road class and spatial hazard decay
        raw_road = str(data.get("road_class", "Local Road")).lower().strip()
        road_class_encoded = ROAD_CLASS_MAPPING.get(raw_road, 0.4)
        nearest_spot_risk = float(nearest_spot.get("risk_score") or nearest_spot.get("riskScore") or 0.20) if nearest_spot else 0.15
        decay = math.exp(-min_dist / 600.0)
        road_segment_risk = (road_class_encoded * 0.35) + (nearest_spot_risk * decay * 0.65)

        # Temporal
        now = datetime.now()
        hour = int(data.get("hour", now.hour) if data.get("hour") is not None else now.hour)
        day_of_week = int(data.get("day_of_week", now.weekday()) if data.get("day_of_week") is not None else now.weekday())
        is_weekend = 1.0 if day_of_week in (5, 6) else 0.0
        is_rush_hour = 1.0 if (8 <= hour <= 11 or 17 <= hour <= 21) else 0.0
        is_night = 1.0 if (hour >= 20 or hour <= 5) else 0.0

        # Environmental
        raw_weather = str(data.get("weather", "CLEAR")).lower().strip()
        weather_encoded = WEATHER_MAPPING.get(raw_weather, 0.0)

        raw_condition = str(data.get("road_condition", "NORMAL")).lower().strip()
        road_condition_encoded = ROAD_CONDITION_MAPPING.get(raw_condition, 0.0)

        raw_lighting = str(data.get("lighting", "DAYLIGHT" if not is_night else "DARK")).lower().strip()
        lighting_encoded = LIGHTING_MAPPING.get(raw_lighting, 0.0 if not is_night else 0.8)

        rf_val = data.get("rainfall_mm")
        rainfall_mm = float(rf_val if rf_val is not None else (15.0 if "rain" in raw_weather else 0.0))

        vis_val = data.get("visibility_meters")
        vis_meters = float(vis_val if vis_val is not None else (500.0 if "fog" in raw_weather else 2000.0))
        visibility_factor = max(0.0, min(1.0, 1.0 - (vis_meters / 3000.0)))

        # Vehicle / Telemetry
        raw_vtype = str(data.get("vehicle_type", "CAR") or "CAR").lower().strip()
        vehicle_type_encoded = VEHICLE_TYPE_MAPPING.get(raw_vtype, 0.3)

        raw_limit = data.get("speed_limit")
        speed_limit = float(raw_limit if raw_limit is not None else 40.0)
        if speed_limit <= 0:
            speed_limit = 40.0

        raw_spd = data.get("current_speed")
        current_speed = float(raw_spd if raw_spd is not None else 0.0)
        overspeed_ratio = max(0.0, (current_speed - speed_limit) / speed_limit) if speed_limit > 0 else 0.0

        feature_map = {
            "latitude": lat,
            "longitude": lng,
            "road_class_encoded": road_class_encoded,
            "distance_to_nearest_hotspot": min_dist,
            "hotspot_density": density,
            "road_segment_risk": road_segment_risk,
            "hour": float(hour),
            "day_of_week": float(day_of_week),
            "is_weekend": is_weekend,
            "is_rush_hour": is_rush_hour,
            "is_night": is_night,
            "weather_encoded": weather_encoded,
            "road_condition_encoded": road_condition_encoded,
            "lighting_encoded": lighting_encoded,
            "vehicle_type_encoded": vehicle_type_encoded,
            "current_speed": current_speed,
            "speed_limit": speed_limit,
            "overspeed_ratio": overspeed_ratio,
            "rainfall_mm": rainfall_mm,
            "visibility_factor": visibility_factor
        }

        vector = np.array([feature_map[col] for col in FEATURE_COLUMNS], dtype=np.float32)
        return vector, nearest_spot

    def build_feature_dataframe(self, records: List[Dict[str, Any]]) -> pd.DataFrame:
        """Construct pandas DataFrame containing strictly the documented input feature set."""
        rows = []
        for rec in records:
            vec, _ = self.extract_features_from_dict(rec)
            rows.append(vec)
        df = pd.DataFrame(rows, columns=FEATURE_COLUMNS)
        return df
