"""Pydantic schemas for User entity, registration, login, and profile management."""
from datetime import datetime
from enum import Enum
from typing import Optional
import re
from pydantic import BaseModel, Field, ConfigDict, field_validator

EMAIL_REGEX = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PHONE_REGEX = re.compile(r"^\+?\d{7,15}$")
NAME_REGEX = re.compile(r"^[A-Za-z\u0900-\u097F\s.'-]+$")


class UserRole(str, Enum):
    """Supported application roles."""
    USER = "user"          # Standard driver
    ADMIN = "admin"        # System administrator
    AUTHORITY = "authority" # Traffic Police / NHAI Official


class UserBase(BaseModel):
    """Base user schema with common attributes."""
    email: Optional[str] = None
    full_name: str = Field(..., min_length=1, max_length=150)
    mobile: Optional[str] = Field(None, max_length=30)
    preferred_language: str = Field(default="en", max_length=10)

    @field_validator("email", mode="before")
    @classmethod
    def clean_optional_email(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            v_clean = v.strip()
            return v_clean.lower() if v_clean else None
        return v

    @field_validator("full_name", mode="before")
    @classmethod
    def clean_full_name(cls, v):
        if isinstance(v, str):
            v_clean = v.strip()
            return v_clean if v_clean else "User"
        return v

    @field_validator("mobile", mode="before")
    @classmethod
    def clean_optional_mobile(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            v_clean = v.strip()
            return v_clean if v_clean else None
        return v


class UserCreate(UserBase):
    """Registration schema with password and role options."""
    password: str = Field(..., min_length=6, max_length=100)
    role: UserRole = UserRole.USER
    voice_alerts: bool = True
    sound_alerts: bool = True
    vibration_alerts: bool = True

    @field_validator("email", mode="before")
    @classmethod
    def validate_create_email(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            v_clean = v.strip()
            if not v_clean:
                return None
            if not EMAIL_REGEX.match(v_clean):
                raise ValueError("Invalid email format")
            return v_clean.lower()
        return v

    @field_validator("full_name", mode="before")
    @classmethod
    def validate_create_name(cls, v):
        if isinstance(v, str):
            v_clean = v.strip()
            if not v_clean or len(v_clean) < 2:
                raise ValueError("Full name must be at least 2 characters.")
            if "@" in v_clean:
                raise ValueError("Name cannot be an email address.")
            return v_clean
        return v

    @field_validator("mobile", mode="before")
    @classmethod
    def validate_create_mobile(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            v_clean = v.strip()
            if not v_clean:
                return None
            clean_digits = re.sub(r"[\s\-().]", "", v_clean)
            if not PHONE_REGEX.match(clean_digits):
                raise ValueError("Mobile number must be 7 to 15 digits (optional leading +).")
            return clean_digits
        return v


class UserLogin(BaseModel):
    """Login request payload supporting Name, Phone Number, Email, and Password."""
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    password: str = Field(..., min_length=1)

    @field_validator("name", "phone", "email", mode="before")
    @classmethod
    def clean_string_fields(cls, v):
        if isinstance(v, str):
            v_clean = v.strip()
            return v_clean if v_clean else None
        return v


class UserStatusUpdate(BaseModel):
    """Payload for updating user active status."""
    is_active: bool


class UserRoleUpdate(BaseModel):
    """Payload for updating user role."""
    role: str = Field(..., min_length=2, max_length=50)


class UserUpdate(BaseModel):
    """Profile update schema."""
    full_name: Optional[str] = Field(None, min_length=2, max_length=150)
    email: Optional[str] = None
    mobile: Optional[str] = Field(None, max_length=30)
    preferred_language: Optional[str] = Field(None, max_length=10)
    avatar_url: Optional[str] = Field(None, max_length=500)
    voice_alerts: Optional[bool] = None
    sound_alerts: Optional[bool] = None
    vibration_alerts: Optional[bool] = None


class UserResponse(UserBase):
    """Public user response schema without sensitive password hashes."""
    id: int
    role: str
    avatar_url: Optional[str] = None
    voice_alerts: bool = True
    sound_alerts: bool = True
    vibration_alerts: bool = True
    is_active: bool = True
    is_superuser: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginatedUserResponse(BaseModel):
    """Paginated user accounts list response."""
    total: int
    page: int
    limit: int
    total_pages: int
    items: list[UserResponse]


class UserStatsResponse(BaseModel):
    """Aggregate statistics for registered user accounts and roles."""
    total_accounts: int
    users_registered: int
    citizen_drivers: int
    administrators: int
    authorities: int
    active_users: int
    inactive_users: int


