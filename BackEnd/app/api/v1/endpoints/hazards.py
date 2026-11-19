"""Nashik Road Hazards API Endpoints.
Provides endpoints for road construction, road closures, potholes, and hazards.
"""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.services.hazard_service import HazardService

router = APIRouter()


class CoordinatePair(BaseModel):
    lat: float
    lng: float


class RouteHazardsQueryRequest(BaseModel):
    path: List[List[float]] = Field(..., description="Route polyline as list of [lat, lng] pairs")
    buffer_meters: Optional[float] = Field(120.0, ge=30.0, le=2000.0, description="Proximity buffer in meters")


class HazardReportRequest(BaseModel):
    hazard_type: str = Field(..., description="CONSTRUCTION, POTHOLE, ROAD_CLOSURE, ROAD_DAMAGE, or ACCIDENT")
    latitude: float = Field(..., ge=-90.0, le=90.0, description="Latitude in decimal degrees")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="Longitude in decimal degrees")
    title: Optional[str] = Field(None, description="Short title describing the hazard")
    location_name: Optional[str] = Field(None, description="Readable location or street name in Nashik")
    description: Optional[str] = Field(None, description="Detailed hazard notes")
    severity: Optional[str] = Field("MODERATE", description="CRITICAL, HIGH, MODERATE, or LOW")
    speed_limit_kmh: Optional[int] = Field(None, ge=10, le=120, description="Recommended advisory speed limit")


@router.get(
    "",
    summary="List verified road hazards for Nashik City",
    description="Returns verified road construction, potholes, road closures, and traffic restrictions in Nashik."
)
def get_hazards(
    hazard_type: Optional[str] = Query(None, description="Filter by CONSTRUCTION, POTHOLE, ROAD_CLOSURE, ROAD_DAMAGE"),
    severity: Optional[str] = Query(None, description="Filter by CRITICAL, HIGH, MODERATE, LOW"),
    is_active: Optional[bool] = Query(True, description="Filter active hazards only"),
    refresh: bool = Query(False, description="Force fresh fetch from data providers"),
):
    """Returns active road hazards matching filter parameters."""
    hazards = HazardService.get_all_hazards(
        hazard_type=hazard_type,
        severity=severity,
        is_active=is_active,
        refresh=refresh
    )
    return {
        "success": True,
        "count": len(hazards),
        "hazards": hazards,
    }


@router.get(
    "/summary",
    summary="Get dynamic summary metrics of potholes, construction, and road hazards",
    description="Returns aggregate counts of active potholes, road construction, closures, and the active data provider."
)
def get_hazards_summary():
    """Returns high-level summary metrics of current road hazards."""
    summary_data = HazardService.get_hazards_summary()
    return {
        "success": True,
        **summary_data
    }



@router.post(
    "/report",
    status_code=status.HTTP_201_CREATED,
    summary="Submit a real-time road hazard report (Construction, Pothole, Closure, Hazard)",
    description="Allows verified drivers and users to report current road conditions in Nashik with geographic validation."
)
def report_hazard(payload: HazardReportRequest):
    """Submits a new user road hazard report."""
    try:
        hazard = HazardService.report_hazard(
            hazard_type=payload.hazard_type,
            latitude=payload.latitude,
            longitude=payload.longitude,
            title=payload.title or f"{payload.hazard_type.replace('_', ' ').title()}",
            location_name=payload.location_name or "Nashik City",
            description=payload.description,
            severity=payload.severity or "MODERATE",
            speed_limit_kmh=payload.speed_limit_kmh,
        )
        return {
            "success": True,
            "message": "Road hazard report successfully recorded and active for route warnings.",
            "hazard": hazard,
        }
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(ve)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to record hazard: {str(e)}"
        )


@router.post(
    "/near-route",
    summary="Find road hazards strictly along an active route polyline",
    description="Evaluates a road route polyline against verified Nashik hazards within a spatial corridor buffer (default 120m)."
)
def get_hazards_near_route(payload: RouteHazardsQueryRequest):
    """Finds all road hazards strictly in the corridor of the supplied route."""
    if not payload.path or len(payload.path) < 2:
        return {"success": True, "count": 0, "hazards": []}

    hazards = HazardService.get_hazards_near_route(
        path=payload.path,
        buffer_meters=payload.buffer_meters or 120.0
    )
    return {
        "success": True,
        "count": len(hazards),
        "buffer_meters": payload.buffer_meters or 120.0,
        "hazards": hazards,
    }
