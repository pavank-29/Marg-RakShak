"""Pydantic schemas for NavigationHistory."""
from datetime import datetime
from typing import Optional, List, Any
import re
from pydantic import BaseModel, ConfigDict, Field, model_validator


class NavigationHistoryBase(BaseModel):
    """Core attributes of a navigation history log."""
    source_name: str = Field(..., description="Starting location name or address")
    source_lat: Optional[float] = Field(None, ge=-90.0, le=90.0)
    source_lng: Optional[float] = Field(None, ge=-180.0, le=180.0)
    destination_name: str = Field(..., description="Destination location name or address")
    destination_lat: Optional[float] = Field(None, ge=-90.0, le=90.0)
    destination_lng: Optional[float] = Field(None, ge=-180.0, le=180.0)
    selected_route: str = Field(default="Route 1", description="Identifier of the chosen route option")
    distance_km: float = Field(default=0.0, ge=0.0, description="Trip distance in kilometers")
    duration_min: float = Field(default=0.0, ge=0.0, description="Estimated or actual trip duration in minutes")
    hotspots_count: int = Field(default=0, ge=0, description="Count of accident hotspots along this route")
    hotspots_en_route: Optional[str] = Field(None, description="Serialized summary of hotspots encountered")
    risk_level: str = Field(default="LOW", description="Overall risk level: LOW, MODERATE, HIGH, CRITICAL")
    status: str = Field(default="COMPLETED", description="Navigation status: COMPLETED, ACTIVE, CANCELLED")


class NavigationHistoryCreate(NavigationHistoryBase):
    """Schema for saving a new navigation history record with flexible input parsing."""

    @model_validator(mode="before")
    @classmethod
    def normalize_inputs(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Map source / source_name
            if "source" in data and not data.get("source_name"):
                data["source_name"] = str(data["source"])
            # Map destination / destination_name
            if "destination" in data and not data.get("destination_name"):
                data["destination_name"] = str(data["destination"])
            # Map route_name / selected_route
            if "route_name" in data and not data.get("selected_route"):
                data["selected_route"] = str(data["route_name"])
            # Parse distance string like '12.8 km' into float distance_km
            if "distance" in data and not data.get("distance_km"):
                val = str(data["distance"])
                match = re.search(r"(\d+(\.\d+)?)", val)
                if match:
                    data["distance_km"] = float(match.group(1))
            # Parse duration string like '24 mins' into float duration_min
            if "duration" in data and not data.get("duration_min"):
                val = str(data["duration"])
                match = re.search(r"(\d+(\.\d+)?)", val)
                if match:
                    data["duration_min"] = float(match.group(1))
        return data


class NavigationHistoryResponse(NavigationHistoryBase):
    """Public navigation history output schema."""
    id: int
    user_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginatedHistoryResponse(BaseModel):
    """Paginated user navigation history list."""
    total: int
    page: int
    limit: int
    total_pages: int
    items: List[NavigationHistoryResponse]
