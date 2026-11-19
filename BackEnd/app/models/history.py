"""NavigationHistory database model storing user trips and navigation sessions."""
from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Integer, Float, DateTime, Text, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class NavigationHistory(Base):
    """Stores completed or active navigation sessions for drivers."""
    __tablename__ = "navigation_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source_lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    destination_name: Mapped[str] = mapped_column(String(255), nullable=False)
    destination_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    destination_lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    selected_route: Mapped[str] = mapped_column(String(100), default="Route 1", nullable=False)
    distance_km: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    duration_min: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    hotspots_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hotspots_en_route: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    risk_level: Mapped[str] = mapped_column(String(50), default="LOW", nullable=False)

    # Status: 'COMPLETED', 'ACTIVE', 'CANCELLED'
    status: Mapped[str] = mapped_column(String(50), default="COMPLETED", nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True
    )

    user: Mapped["User"] = relationship("User", back_populates="navigation_histories")

    def __repr__(self) -> str:
        return f"<NavigationHistory id={self.id} user_id={self.user_id} {self.source_name}->{self.destination_name}>"
