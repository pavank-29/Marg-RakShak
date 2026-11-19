"""Authentication router for registration, login, JWT token issuance, and user profile."""
import re
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, get_current_admin
from app.core.security import get_password_hash, verify_password, create_access_token
from app.core.config import settings
from app.models.user import User
from app.schemas.user import UserCreate, UserLogin, UserResponse, UserRole, UserUpdate
from app.schemas.token import Token

router = APIRouter()


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account"
)
def register(
    user_in: UserCreate,
    db: Session = Depends(get_db)
):
    """Register a new user account with optional email & mobile, uniqueness checks on non-empty values, and password hashing."""
    clean_email = user_in.email.strip().lower() if (user_in.email and isinstance(user_in.email, str) and user_in.email.strip()) else None
    clean_mobile = user_in.mobile.strip() if (user_in.mobile and isinstance(user_in.mobile, str) and user_in.mobile.strip()) else None

    # Check email uniqueness ONLY if email is provided
    if clean_email:
        existing_email_user = db.execute(
            select(User).where(func.lower(User.email) == clean_email)
        ).scalars().first()
        if existing_email_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A user with this email address already exists."
            )

    # Check mobile uniqueness ONLY if mobile is provided
    if clean_mobile:
        digits = re.sub(r"\D", "", clean_mobile)
        possible_mobiles = [clean_mobile]
        if digits:
            possible_mobiles.extend([digits, f"+{digits}"])
        existing_mobile_user = db.execute(
            select(User).where(User.mobile.in_(possible_mobiles))
        ).scalars().first()
        if existing_mobile_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A user with this mobile number already exists."
            )

    role_str = user_in.role.value if hasattr(user_in.role, "value") else str(user_in.role)
    authorized_admins = [e.strip().lower() for e in getattr(settings, "AUTHORIZED_ADMIN_EMAILS", [settings.ADMIN_EMAIL])]
    
    # Server-side security: Prevent arbitrary self-promotion to admin
    if role_str.lower() in ("admin", UserRole.ADMIN.value.lower()):
        if not clean_email or clean_email.lower() not in authorized_admins:
            role_str = "user"
            
    is_admin = role_str.lower() in ("admin", UserRole.ADMIN.value.lower())

    new_user = User(
        email=clean_email,
        hashed_password=get_password_hash(user_in.password),
        full_name=user_in.full_name,
        role=role_str,
        mobile=clean_mobile,
        preferred_language=user_in.preferred_language,
        voice_alerts=user_in.voice_alerts,
        sound_alerts=user_in.sound_alerts,
        vibration_alerts=user_in.vibration_alerts,
        is_active=True,
        is_superuser=is_admin,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@router.post(
    "/login",
    response_model=Token,
    summary="Login with JSON credentials"
)
def login_json(
    credentials: UserLogin,
    db: Session = Depends(get_db)
):
    """Authenticate user with Name + Phone Number, or Email, and return signed JWT access token."""
    user = None
    input_phone = credentials.phone.strip() if (credentials.phone and credentials.phone.strip()) else None
    input_name = credentials.name.strip() if (credentials.name and credentials.name.strip()) else None
    input_email = credentials.email.strip().lower() if (credentials.email and credentials.email.strip()) else None

    # Handle synthetic emails from frontend (e.g. 9876543210@margrakshak.in)
    if not input_phone and input_email and "@margrakshak.in" in input_email:
        prefix = input_email.replace("@margrakshak.in", "").strip()
        digits = re.sub(r"\D", "", prefix)
        if digits and len(digits) >= 7:
            input_phone = prefix

    # If input_name has an '@', user may have entered email into name input
    if not input_email and input_name and "@" in input_name:
        input_email = input_name.lower()

    # If input_phone has an '@', user entered an email address
    if not input_email and input_phone and "@" in input_phone:
        input_email = input_phone.lower()

    # 1. Lookup candidate user by phone number
    if input_phone and not ("@" in input_phone):
        digits = re.sub(r"\D", "", input_phone)
        possible_mobiles = [input_phone]
        if digits:
            possible_mobiles.extend([digits, f"+{digits}"])
        possible_emails = [f"{digits}@margrakshak.in"] if digits else []

        candidates = db.execute(
            select(User).where(
                User.mobile.in_(possible_mobiles) |
                User.email.in_(possible_emails)
            )
        ).scalars().all()

        if candidates:
            # If name is also provided, prefer the candidate matching both name & password
            if input_name:
                norm_name = input_name.lower()
                for cand in candidates:
                    if cand.full_name and cand.full_name.strip().lower() == norm_name:
                        if verify_password(credentials.password, cand.hashed_password):
                            user = cand
                            break
            # If not matched yet, check password on all phone candidates
            if not user:
                for cand in candidates:
                    if verify_password(credentials.password, cand.hashed_password):
                        user = cand
                        break
            if not user:
                user = candidates[0]

    # 2. Lookup by email if provided
    if not user and input_email:
        user = db.execute(
            select(User).where(func.lower(User.email) == input_email)
        ).scalars().first()

    # 3. Lookup by Name if not matched by phone/email
    if not user and input_name:
        norm_name = input_name.lower()
        candidates = db.execute(
            select(User).where(func.lower(User.full_name) == norm_name)
        ).scalars().all()
        if candidates:
            for cand in candidates:
                if verify_password(credentials.password, cand.hashed_password):
                    user = cand
                    break
            if not user:
                user = candidates[0]

    # 4. Fallback search across all fields if still not resolved
    if not user:
        search_term = input_email or input_phone or input_name
        if search_term:
            fallback_candidates = db.execute(
                select(User).where(
                    (func.lower(User.email) == search_term.lower()) |
                    (User.mobile == search_term) |
                    (func.lower(User.full_name) == search_term.lower())
                )
            ).scalars().all()
            for cand in fallback_candidates:
                if verify_password(credentials.password, cand.hashed_password):
                    user = cand
                    break
            if not user and fallback_candidates:
                user = fallback_candidates[0]

    if not user or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect name, phone number, or password.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user account."
        )

    # Restrict admin role login strictly to authorized administrator accounts
    user_role_str = str(user.role).strip().lower()
    if user_role_str == UserRole.ADMIN.value.lower() or user_role_str == "admin":
        authorized_admins = [e.strip().lower() for e in getattr(settings, "AUTHORIZED_ADMIN_EMAILS", [settings.ADMIN_EMAIL])]
        if not user.email or user.email.strip().lower() not in authorized_admins:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access is restricted to authorized administrator accounts."
            )

    # If user registered without a mobile number and now provided one on login, attach it
    if input_phone and not user.mobile and not ("@" in input_phone):
        user.mobile = input_phone
        try:
            db.commit()
            db.refresh(user)
        except Exception:
            db.rollback()

    access_token = create_access_token(
        subject=user.id,
        role=user.role,
        email=user.email or ""
    )

    return Token(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse.model_validate(user)
    )


@router.post(
    "/login/access-token",
    response_model=Token,
    summary="OAuth2 compatible token login (for Swagger UI /docs)"
)
def login_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """OAuth2 compatible token login for FastAPI Swagger documentation Authorize button."""
    clean_username = form_data.username.strip()
    user = db.execute(
        select(User).where(
            (func.lower(User.email) == clean_username.lower()) |
            (User.mobile == clean_username) |
            (func.lower(User.full_name) == clean_username.lower())
        )
    ).scalars().first()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user account."
        )

    # Restrict admin role login strictly to authorized administrator accounts
    user_role_str = str(user.role).strip().lower()
    if user_role_str == UserRole.ADMIN.value.lower() or user_role_str == "admin":
        authorized_admins = [e.strip().lower() for e in getattr(settings, "AUTHORIZED_ADMIN_EMAILS", [settings.ADMIN_EMAIL])]
        if not user.email or user.email.strip().lower() not in authorized_admins:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access is restricted to authorized administrator accounts."
            )

    access_token = create_access_token(
        subject=user.id,
        role=user.role,
        email=user.email or ""
    )

    return Token(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse.model_validate(user)
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current authenticated user profile"
)
def get_me(
    current_user: User = Depends(get_current_user)
):
    """Return the profile of the currently authenticated user identified by the Bearer token."""
    return current_user


@router.put(
    "/me",
    response_model=UserResponse,
    summary="Update current authenticated user profile"
)
@router.patch(
    "/me",
    response_model=UserResponse,
    summary="Update current authenticated user profile"
)
def update_me(
    user_in: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update profile details and safety preferences for the currently authenticated user."""
    if user_in.full_name is not None and user_in.full_name.strip():
        current_user.full_name = user_in.full_name.strip()

    if user_in.email is not None:
        clean_email = user_in.email.strip().lower() if user_in.email.strip() else None
        if clean_email and clean_email != (current_user.email or "").lower():
            existing = db.execute(
                select(User).where(func.lower(User.email) == clean_email, User.id != current_user.id)
            ).scalars().first()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already in use by another account."
                )
            current_user.email = clean_email

    if user_in.mobile is not None:
        clean_mobile = user_in.mobile.strip() if user_in.mobile.strip() else None
        if clean_mobile and clean_mobile != current_user.mobile:
            existing = db.execute(
                select(User).where(User.mobile == clean_mobile, User.id != current_user.id)
            ).scalars().first()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Mobile number already in use by another account."
                )
            current_user.mobile = clean_mobile

    if user_in.preferred_language is not None and user_in.preferred_language.strip():
        current_user.preferred_language = user_in.preferred_language.strip()

    if user_in.avatar_url is not None:
        current_user.avatar_url = user_in.avatar_url

    if user_in.voice_alerts is not None:
        current_user.voice_alerts = user_in.voice_alerts

    if user_in.sound_alerts is not None:
        current_user.sound_alerts = user_in.sound_alerts

    if user_in.vibration_alerts is not None:
        current_user.vibration_alerts = user_in.vibration_alerts

    db.commit()
    db.refresh(current_user)
    return current_user


@router.get(
    "/admin/test",
    summary="Verify ADMIN role access"
)
def admin_only_test(
    current_admin: User = Depends(get_current_admin)
):
    """Protected endpoint accessible exclusively to administrators."""
    return {
        "status": "authorized",
        "message": f"Welcome Admin {current_admin.full_name}",
        "admin_id": current_admin.id,
        "role": current_admin.role
    }
