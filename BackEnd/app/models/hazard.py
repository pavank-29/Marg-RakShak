"""Hazard database model for road construction, potholes, road closures, and road damage."""
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Float, Boolean, Integer, DateTime, func, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Hazard(Base):
    """Road hazard tracking model for Nashik City."""
    __tablename__ = "hazards"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # Types: 'CONSTRUCTION', 'POTHOLE', 'ROAD_CLOSURE', 'ROAD_DAMAGE', 'ACCIDENT'
    hazard_type: Mapped[str] = mapped_column(String(50), nullable=False, default="ROAD_DAMAGE")
    # Severity: 'CRITICAL', 'HIGH', 'MODERATE', 'LOW'
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="MODERATE")
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    location_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    speed_limit_kmh: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Sources: 'VERIFIED_GIS', 'USER_REPORTED', 'ADMIN_VERIFIED', 'TOMTOM_LIVE'
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="VERIFIED_GIS")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    icon_type: Mapped[str] = mapped_column(String(30), default="damage", nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "hazard_type": self.hazard_type,
            "severity": self.severity,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "location_name": self.location_name,
            "description": self.description,
            "speed_limit_kmh": self.speed_limit_kmh,
            "source": self.source,
            "is_active": self.is_active,
            "icon_type": self.icon_type,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
