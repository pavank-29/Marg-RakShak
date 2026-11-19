"""User Navigation & Trip History API Endpoints.
Provides user-specific trip logging, persistence, and retrieval.
"""
import math
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.history import NavigationHistory
from app.schemas.history import (
    NavigationHistoryCreate,
    NavigationHistoryResponse,
    PaginatedHistoryResponse,
)

router = APIRouter()


@router.get(
    "",
    response_model=PaginatedHistoryResponse,
    summary="Get current user's navigation and trip history",
    description="Retrieve all completed and past navigation journeys for the authenticated user.",
)
def get_user_history(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve user-specific navigation logs."""
    query = select(NavigationHistory).where(NavigationHistory.user_id == current_user.id)

    total_query = select(func.count()).select_from(query.subquery())
    total = db.scalar(total_query) or 0

    query = query.order_by(NavigationHistory.created_at.desc()).offset((page - 1) * limit).limit(limit)
    items = list(db.scalars(query).all())

    total_pages = math.ceil(total / limit) if total > 0 else 1

    return PaginatedHistoryResponse(
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
        items=[NavigationHistoryResponse.model_validate(item) for item in items],
    )


@router.post(
    "",
    response_model=NavigationHistoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a navigation trip session",
    description="Save source, destination, route selected, distance, duration, and safety alerts for the current user.",
)
def record_trip(
    history_in: NavigationHistoryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Save a navigation record associated with the authenticated user."""
    trip = NavigationHistory(
        user_id=current_user.id,
        source_name=history_in.source_name,
        source_lat=history_in.source_lat,
        source_lng=history_in.source_lng,
        destination_name=history_in.destination_name,
        destination_lat=history_in.destination_lat,
        destination_lng=history_in.destination_lng,
        selected_route=history_in.selected_route,
        distance_km=history_in.distance_km,
        duration_min=history_in.duration_min,
        hotspots_count=history_in.hotspots_count,
        hotspots_en_route=history_in.hotspots_en_route,
        risk_level=history_in.risk_level,
        status=history_in.status,
    )
    db.add(trip)
    db.commit()
    db.refresh(trip)
    return trip


@router.get(
    "/{history_id}",
    response_model=NavigationHistoryResponse,
    summary="Get single trip history item by ID",
)
def get_trip_detail(
    history_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve details for a specific user trip."""
    trip = db.get(NavigationHistory, history_id)
    if not trip or trip.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trip history record not found."
        )
    return trip


@router.delete(
    "/{history_id}",
    summary="Delete a single trip history item",
)
def delete_trip_record(
    history_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a specific trip record belonging to the authenticated user."""
    trip = db.get(NavigationHistory, history_id)
    if not trip or trip.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trip history record not found."
        )
    db.delete(trip)
    db.commit()
    return {"detail": f"Trip record {history_id} deleted successfully.", "id": history_id}


@router.delete(
    "",
    summary="Clear all trip history for the current user",
)
def clear_all_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete all trip records belonging to the authenticated user."""
    stmt = select(NavigationHistory).where(NavigationHistory.user_id == current_user.id)
    records = list(db.scalars(stmt).all())
    count = len(records)
    for r in records:
        db.delete(r)
    db.commit()
    return {"detail": f"Cleared {count} trip history records.", "deleted_count": count}
