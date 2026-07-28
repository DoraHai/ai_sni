"""Independent GEO API process.

This process intentionally mounts only GEO routes. Deploying or restarting it
does not restart the SEM scheduler or expose unrelated SEM endpoints.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import get_settings
from app.database import engine
from app.geo.routes import router as geo_router

settings = get_settings()

app = FastAPI(title="Growth Sniper GEO API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(geo_router)


@app.get("/health/geo")
async def geo_health() -> dict:
    db_status = "ok"
    db_error: str | None = None
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        db_status = "error"
        db_error = str(exc)
    return {
        "service": "geo-api",
        "env": settings.app_env,
        "db": db_status,
        "db_error": db_error,
    }
