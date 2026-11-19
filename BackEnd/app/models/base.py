"""Declarative base, spatial geometry type, and common model mixins for SQLAlchemy."""
from datetime import datetime, timezone
from typing import Optional, Any
from sqlalchemy import DateTime, Text, func, TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column



class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""
    pass


class SpatialGeometry(TypeDecorator):
    """Platform-independent spatial geometry type storing WKT with SRID in SQLite/Text."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect) -> Optional[str]:
        if value is None:
            return None
        if hasattr(value, "data"):
            srid = getattr(value, "srid", 4326)
            data = value.data
            if isinstance(data, (bytes, memoryview)):
                try:
                    import shapely.wkb
                    data = shapely.wkb.loads(bytes(data)).wkt
                except Exception:
                    data = str(data)
            return f"SRID={srid};{data}" if srid else str(data)
        return str(value)

    def process_result_value(self, value: Optional[str], dialect) -> Optional[str]:
        return value



class TimestampMixin:
    """Reusable mixin providing timezone-aware created_at and updated_at fields."""
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
        server_onupdate=func.now(),
        nullable=False
    )
