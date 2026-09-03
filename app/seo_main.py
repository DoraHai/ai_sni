"""Independent SEO API process.

This application mounts only SEO routes and owns only the SEO scheduler.
Deploying or restarting it does not restart the shared SEM backend or GEO.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.customer_modules import seo_sites_router
from app.api.seo import router as seo_router
from app.config import get_settings
from app.database import engine
from app.http_errors import register_infra_handlers
from app.security.prod_guard import enforce_production_secrets
from app.seo_scheduler import shutdown_seo_scheduler, start_seo_scheduler

settings = get_settings()
enforce_production_secrets(settings, hard_fail=True)
SEO_REQUIRED_SCHEMA_REVISION = "0088_seo_image_alt_reviews"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    start_seo_scheduler()
    try:
        yield
    finally:
        shutdown_seo_scheduler()


app = FastAPI(title="Growth Sniper SEO API", version="0.1.0", lifespan=lifespan)
register_infra_handlers(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(seo_router)
app.include_router(seo_sites_router)


@app.get("/health/seo")
async def seo_health(response: Response) -> dict:
    """Fail closed when the database is unreachable or its schema is incompatible."""
    db_status = "ok"
    db_error: str | None = None
    schema_status = "unknown"
    schema_revision: str | None = None
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            revisions = list(
                (
                    await conn.execute(
                        text("SELECT version_num FROM alembic_version ORDER BY version_num")
                    )
                ).scalars()
            )
            schema_revision = ",".join(revisions) or None
            if revisions != [SEO_REQUIRED_SCHEMA_REVISION]:
                schema_status = "error"
                raise RuntimeError(
                    "SEO database schema mismatch: "
                    f"expected {SEO_REQUIRED_SCHEMA_REVISION}, "
                    f"found {schema_revision or 'none'}"
                )
            schema_status = "ok"
    except Exception as exc:  # noqa: BLE001 - health must report infra failure
        db_status = "error"
        db_error = str(exc)
        response.status_code = 503
    return {
        "service": "seo-api",
        "env": settings.app_env,
        "db": db_status,
        "db_error": db_error,
        "schema": schema_status,
        "schema_revision": schema_revision,
        "required_schema_revision": SEO_REQUIRED_SCHEMA_REVISION,
    }
