"""Independent SEO API process.

This application mounts only SEO routes. Deploying or restarting it does not
restart the shared SEM backend or the GEO service. The existing daily SEO rank
collector remains owned by the shared scheduler until a separately reviewed
scheduler extraction is approved.
"""

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.seo import router as seo_router
from app.config import get_settings
from app.database import engine
from app.http_errors import register_infra_handlers
from app.security.prod_guard import enforce_production_secrets

settings = get_settings()
enforce_production_secrets(settings, hard_fail=True)

app = FastAPI(title="Growth Sniper SEO API", version="0.1.0")
register_infra_handlers(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(seo_router)


@app.get("/health/seo")
async def seo_health(response: Response) -> dict:
    """Return HTTP 503 when the shared database is unreachable."""
    db_status = "ok"
    db_error: str | None = None
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - health must report infra failure
        db_status = "error"
        db_error = str(exc)
        response.status_code = 503
    return {
        "service": "seo-api",
        "env": settings.app_env,
        "db": db_status,
        "db_error": db_error,
    }
