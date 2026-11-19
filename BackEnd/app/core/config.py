"""Core application settings and configuration."""
import os
from typing import List, Union, Optional
from pydantic import AnyHttpUrl, field_validator

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
    class AppBaseSettings(BaseSettings):
        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            case_sensitive=True,
            extra="ignore"
        )
except ImportError:
    from pydantic import BaseSettings
    class AppBaseSettings(BaseSettings):
        class Config:
            env_file = ".env"
            case_sensitive = True
            extra = "ignore"


class Settings(AppBaseSettings):
    APP_NAME: str = "MargRakshak AI - Accident Hotspot Detection"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # CORS origins allowed to access the API
    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000"
    ]

    # Database Settings (Default: Fast, Serverless SQLite for zero-config portability and high reliability)
    DATABASE_URL: str = "sqlite:///./margrakshak.db"
    POSTGRES_SERVER: Optional[str] = None
    POSTGRES_PORT: Optional[int] = None
    POSTGRES_USER: Optional[str] = None
    POSTGRES_PASSWORD: Optional[str] = None
    POSTGRES_DB: Optional[str] = None


    # Security & Admin Restriction
    JWT_SECRET_KEY: str = "margrakshak_dev_secret_key_change_in_prod_2026"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    ADMIN_EMAIL: str = "admin@margrakshak.in"
    AUTHORIZED_ADMIN_EMAILS: List[str] = [
        "admin@margrakshak.in",
        "police.admin@margrakshak.in",
        "safety.admin@margrakshak.in"
    ]

    # Uploads
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE_MB: int = 15

    # ML Pipeline & Model Storage (Phase 6-10)
    MODEL_DIR: str = os.getenv(
        "MODEL_DIR",
        str(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "models")))
    )
    # Configurable Risk Thresholds (calibrated from validation data)
    RISK_THRESHOLD_LOW: float = 0.25
    RISK_THRESHOLD_MEDIUM: float = 0.50
    RISK_THRESHOLD_HIGH: float = 0.75

    # HDBSCAN Clustering parameters
    HDBSCAN_MIN_CLUSTER_SIZE: int = 3
    HDBSCAN_MIN_SAMPLES: int = 2

    # Live Traffic & Routing Provider Configuration
    GOOGLE_MAPS_API_KEY: Optional[str] = None
    GOOGLE_ROUTES_API_KEY: Optional[str] = None
    TOMTOM_API_KEY: Optional[str] = None
    MAPBOX_ACCESS_TOKEN: Optional[str] = None
    TRAFFIC_PROVIDER: str = "auto"  # 'auto', 'google', 'tomtom', 'hybrid'


settings = Settings()
