"""User Management API endpoints.
Provides paginated list of registered users for administrators.
"""
import math
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_admin
from app.models.user import User
from app.schemas.user import UserResponse, PaginatedUserResponse, UserStatusUpdate, UserRoleUpdate, UserStatsResponse

router = APIRouter()


@router.get(
    "/stats",
    response_model=UserStatsResponse,
    summary="Get user account and role statistics (Admin only)",
    description="Retrieve live counts of registered accounts, citizen drivers, administrators, and active status directly from database.",
)
def get_user_stats(
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """Compute real-time user statistics from database records."""
    total_accounts = db.query(func.count(User.id)).scalar() or 0
    citizen_drivers = db.query(func.count(User.id)).filter(
        func.lower(User.role).in_(["user", "driver"])
    ).scalar() or 0
    administrators = db.query(func.count(User.id)).filter(
        func.lower(User.role) == "admin"
    ).scalar() or 0
    authorities = db.query(func.count(User.id)).filter(
        func.lower(User.role) == "authority"
    ).scalar() or 0
    active_users = db.query(func.count(User.id)).filter(
        User.is_active == True
    ).scalar() or 0
    inactive_users = total_accounts - active_users

    return UserStatsResponse(
        total_accounts=total_accounts,
        users_registered=total_accounts,
        citizen_drivers=citizen_drivers,
        administrators=administrators,
        authorities=authorities,
        active_users=active_users,
        inactive_users=inactive_users,
    )


@router.get(
    "",
    response_model=PaginatedUserResponse,
    summary="Get paginated list of users (Admin only)",
    description="Retrieve registered users with optional role filtering and search by name/email/mobile. Requires administrator privileges.",
)
def get_users(
    role: Optional[str] = Query(None, description="Filter by role (e.g. admin, user, authority)"),
    search: Optional[str] = Query(None, description="Search term matching full_name, email, or mobile"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(50, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """List registered users with pagination and filtering for administrative oversight."""
    query = select(User)

    if role and role.strip().upper() != "ALL":
        query = query.where(func.lower(User.role) == role.strip().lower())

    if search and search.strip():
        search_pattern = f"%{search.strip()}%"
        query = query.where(
            or_(
                User.full_name.ilike(search_pattern),
                User.email.ilike(search_pattern),
                User.mobile.ilike(search_pattern),
            )
        )

    # Calculate total count
    total_query = select(func.count()).select_from(query.subquery())
    total = db.scalar(total_query) or 0

    # Paginate and order by newest first
    query = query.order_by(User.created_at.desc()).offset((page - 1) * limit).limit(limit)
    items = db.scalars(query).all()

    total_pages = math.ceil(total / limit) if total > 0 else 1

    return PaginatedUserResponse(
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
        items=[UserResponse.model_validate(item) for item in items],
    )


@router.patch(
    "/{user_id}/status",
    response_model=UserResponse,
    summary="Update user active/inactive status (Admin only)",
)
def update_user_status(
    user_id: int,
    status_in: UserStatusUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """Activate or deactivate user account access."""
    target_user = db.get(User, user_id)
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Prevent deactivating authorized administrators
    authorized_admins = [e.strip().lower() for e in getattr(settings, "AUTHORIZED_ADMIN_EMAILS", [settings.ADMIN_EMAIL])]
    if target_user.email and target_user.email.strip().lower() in authorized_admins:
        if not status_in.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Authorized administrator accounts cannot be deactivated."
            )

    target_user.is_active = status_in.is_active
    db.commit()
    db.refresh(target_user)
    return target_user


@router.patch(
    "/{user_id}/role",
    response_model=UserResponse,
    summary="Update user role (Admin only)",
)
def update_user_role(
    user_id: int,
    role_in: UserRoleUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """Change a user's assigned role ('user', 'admin', 'authority')."""
    target_user = db.get(User, user_id)
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    authorized_admins = [e.strip().lower() for e in getattr(settings, "AUTHORIZED_ADMIN_EMAILS", [settings.ADMIN_EMAIL])]

    # Protect authorized admin accounts from demotion
    if target_user.email and target_user.email.strip().lower() in authorized_admins:
        if role_in.role.strip().lower() != "admin":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Authorized administrator accounts cannot have their role modified."
            )

    clean_role = role_in.role.strip().lower()
    if clean_role not in ("admin", "user", "authority"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid role. Must be one of: 'user', 'admin', 'authority'."
        )

    # Enforce that only authorized admin emails can hold the admin role
    if clean_role == "admin":
        if not target_user.email or target_user.email.strip().lower() not in authorized_admins:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Administrator role can only be assigned to authorized administrator email addresses."
            )

    target_user.role = clean_role
    target_user.is_superuser = (clean_role == "admin")
    db.commit()
    db.refresh(target_user)
    return target_user
