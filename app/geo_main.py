"""Independent GEO API process.

This process intentionally mounts only GEO routes. Deploying or restarting it
does not restart the SEM scheduler or expose unrelated SEM endpoints.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import get_settings
from app.database import engine
from app.geo.content.oauth_public import router as geo_oauth_public_router
from app.geo.routes import router as geo_router
from app.api.customer_modules import geo_projects_router
from app.geo.scheduler import shutdown_geo_scheduler, start_geo_scheduler
from app.security.prod_guard import enforce_production_secrets

settings = get_settings()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # Productization must-do: refuse demo keys when APP_ENV=prod|production
    enforce_production_secrets(settings, hard_fail=True)
    start_geo_scheduler()
    try:
        yield
    finally:
        shutdown_geo_scheduler()


app = FastAPI(title="Growth Sniper GEO API", version="0.1.0", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list(),
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Accept", "Authorization", "Content-Type", "X-API-Key"],
)
app.include_router(geo_router)
app.include_router(geo_projects_router)
app.include_router(geo_oauth_public_router)


@app.get("/health/geo")
async def geo_health(response: Response) -> dict:
    """Fail-closed health: HTTP 503 when DB is unreachable (deploy smoke relies on this)."""
    db_status = "ok"
    db_error: str | None = None
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        db_status = "error"
        db_error = str(exc)
        response.status_code = 503
    return {
        "service": "geo-api",
        "env": settings.app_env,
        "db": db_status,
        "db_error": db_error,
    }
