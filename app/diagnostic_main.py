"""Standalone diagnostic API: no GEO routers, schedulers or recovery jobs."""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Response
from sqlalchemy import text
from app.config import get_settings
from app.database import engine
from app.http_errors import register_infra_handlers
from app.security.prod_guard import enforce_production_secrets
from app.diagnostic.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    enforce_production_secrets(get_settings(), hard_fail=True)
    yield
    await engine.dispose()


app = FastAPI(title="Growth Sniper Diagnostic API", lifespan=lifespan)
register_infra_handlers(app)
app.include_router(router)


@app.get("/health/diagnostic")
async def health(response: Response):
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        response.status_code = 503
        return {"service": "diagnostic-api", "db": "error"}
    return {"service": "diagnostic-api", "db": "ok"}
