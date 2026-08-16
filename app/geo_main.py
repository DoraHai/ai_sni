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
from app.http_errors import register_infra_handlers
from app.geo.content.oauth_public import router as geo_oauth_public_router
from app.geo.routes import router as geo_router
from app.security.prod_guard import enforce_production_secrets

settings = get_settings()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # Productization must-do: refuse demo keys when APP_ENV=prod|production
    enforce_production_secrets(settings, hard_fail=True)
    try:
        from app.geo.content.async_jobs import recover_jobs_on_startup

        stats = await recover_jobs_on_startup(requeue_pending=True)
        if any(stats.values()):
            import logging

            logging.getLogger("geo-api").info("async job recover: %s", stats)
    except Exception:  # noqa: BLE001 — never block API boot
        import logging

        logging.getLogger("geo-api").exception("async job recover on startup failed")
    yield


app = FastAPI(title="Growth Sniper GEO API", version="0.1.0", lifespan=_lifespan)
register_infra_handlers(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(geo_router)
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
