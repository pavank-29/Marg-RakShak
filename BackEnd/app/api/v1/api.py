"""API v1 router aggregator."""
from fastapi import APIRouter
from app.api.v1.endpoints import auth, accidents, hotspots, users, tracking, history, ml, route, hazards

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(accidents.router, prefix="/accidents", tags=["Accidents"])
api_router.include_router(hotspots.router, prefix="/hotspots", tags=["Hotspots"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(tracking.router, prefix="/tracking", tags=["Real-Time Tracking"])
api_router.include_router(history.router, prefix="/history", tags=["Navigation History"])
api_router.include_router(ml.router, prefix="/ml", tags=["Machine Learning Pipeline"])
api_router.include_router(route.router, prefix="/route", tags=["Road Routing & Traffic"])
api_router.include_router(hazards.router, prefix="/hazards", tags=["Road Hazards & Construction"])


