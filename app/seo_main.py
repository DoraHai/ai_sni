"""Independent SEO API process.

This application mounts only SEO routes and owns only the SEO scheduler.
Deploying or restarting it does not restart the shared SEM backend or GEO.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text, BigInteger, Integer, SmallInteger
from sqlalchemy.dialects.postgresql import JSONB

from app.api.customer_modules import seo_sites_router
from app.api.seo import router as seo_router
from app.config import get_settings
from app.database import engine
from app.http_errors import register_infra_handlers
from app.security.prod_guard import enforce_production_secrets
from app.seo_scheduler import shutdown_seo_scheduler, start_seo_scheduler

settings = get_settings()
enforce_production_secrets(settings, hard_fail=True)
SEO_REQUIRED_SCHEMA_REVISION = "0095_adopt_geo_ticket"
# Runtime compatibility supports code-first rollout; it never authorizes the
# separately reviewed migration operation.
SEO_COMPATIBLE_SCHEMA_REVISIONS = frozenset({"0094_seo_qa_batches", SEO_REQUIRED_SCHEMA_REVISION})
SEO_GEO_TICKET_SHAPE = {
    "owner_name": ("character varying(100)", False, None, "", "", "b", None, True),
    "due_date": ("date", False, None, "", "", "b", None, True),
}


def _required_schema_columns():
    from app.models.seo import SeoContentAsset, SeoAiOperation, SeoMetricSnapshot, SeoImageAltReview
    from app.models.seo_cockpit import SeoTask, SeoImageVerification
    from app.models.seo_qa import SeoQuestion, SeoQaFact, SeoQaAnswer, SeoQaPlacement, SeoQaBatch
    from app.models.module_workspace import SeoSite
    models = (SeoSite, SeoContentAsset, SeoAiOperation, SeoMetricSnapshot, SeoImageAltReview,
              SeoTask, SeoImageVerification, SeoQuestion, SeoQaFact, SeoQaAnswer, SeoQaPlacement, SeoQaBatch)
    required = {}
    for model in models:
        for column in model.__table__.columns:
            kind = ('int8' if isinstance(column.type, BigInteger) else 'int2' if isinstance(column.type, SmallInteger)
                    else 'int4' if isinstance(column.type, Integer)
                    else 'jsonb' if isinstance(column.type, JSONB) else None)
            required[(model.__tablename__, column.name)] = kind
    return required


SEO_REQUIRED_COLUMNS = _required_schema_columns()
SEO_SCHEMA_COLUMNS_SQL = text("""
    SELECT requested.name, a.attname, t.typname
    FROM unnest(CAST(:tables AS text[])) AS requested(name)
    JOIN pg_catalog.pg_class c ON c.oid = to_regclass(requested.name)
    JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
    JOIN pg_catalog.pg_type t ON t.oid = a.atttypid
    WHERE c.relkind IN ('r', 'p') AND a.attnum > 0 AND NOT a.attisdropped
""")

SEO_GEO_TICKET_SHAPE_SQL = text("""
    SELECT
        a.attname,
        c.relkind,
        pg_catalog.format_type(a.atttypid, a.atttypmod),
        a.attnotnull,
        pg_catalog.pg_get_expr(ad.adbin, ad.adrelid),
        a.attidentity,
        a.attgenerated,
        t.typtype,
        CASE WHEN t.typbasetype = 0 THEN NULL ELSE bt.typname END,
        a.attcollation = t.typcollation,
        EXISTS (
            SELECT 1
            FROM pg_catalog.pg_depend dep
            JOIN pg_catalog.pg_class index_class
              ON dep.classid = 'pg_catalog.pg_class'::pg_catalog.regclass
             AND index_class.oid = dep.objid
            JOIN pg_catalog.pg_index i
              ON i.indexrelid = index_class.oid AND i.indrelid = c.oid
            WHERE dep.refclassid = 'pg_catalog.pg_class'::pg_catalog.regclass
              AND dep.refobjid = c.oid AND dep.refobjsubid = a.attnum
        ),
        EXISTS (
            SELECT 1
            FROM pg_catalog.pg_depend dep
            JOIN pg_catalog.pg_constraint con
              ON dep.classid = 'pg_catalog.pg_constraint'::pg_catalog.regclass
             AND con.oid = dep.objid
            WHERE dep.refclassid = 'pg_catalog.pg_class'::pg_catalog.regclass
              AND dep.refobjid = c.oid AND dep.refobjsubid = a.attnum
        )
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
    JOIN pg_catalog.pg_type t ON t.oid = a.atttypid
    LEFT JOIN pg_catalog.pg_type bt ON bt.oid = t.typbasetype
    LEFT JOIN pg_catalog.pg_attrdef ad ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
    WHERE n.nspname = 'public'
      AND c.relname = 'geo_action_tickets'
      AND a.attname IN ('owner_name', 'due_date')
      AND a.attnum > 0 AND NOT a.attisdropped
    ORDER BY a.attname
""")


async def _check_seo_structure(conn):
    rows = await conn.execute(SEO_SCHEMA_COLUMNS_SQL,
                              {'tables': sorted({table for table, _ in SEO_REQUIRED_COLUMNS})})
    actual = {(table, column): kind for table, column, kind in rows}
    incompatible = [f'{table}.{column}' for (table, column), kind in SEO_REQUIRED_COLUMNS.items()
                    if (table, column) not in actual or (kind and actual[(table, column)] != kind)]
    if incompatible:
        raise RuntimeError('SEO required columns missing or incompatible: ' + ', '.join(sorted(incompatible)))


async def _check_geo_ticket_adoption(conn):
    rows = await conn.execute(SEO_GEO_TICKET_SHAPE_SQL)
    actual = {}
    for row in rows:
        name, relkind, *shape = row
        actual[name] = (relkind, tuple(shape))
    expected = {name: ("r", shape + (False, False)) for name, shape in SEO_GEO_TICKET_SHAPE.items()}
    if actual != expected:
        raise RuntimeError(
            "0095 GEO ticket assignment columns missing or incompatible: "
            f"found {sorted(actual)}"
        )



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
            if len(revisions) != 1 or revisions[0] not in SEO_COMPATIBLE_SCHEMA_REVISIONS:
                schema_status = "error"
                raise RuntimeError(
                    "SEO database schema mismatch: "
                    f"expected {SEO_REQUIRED_SCHEMA_REVISION} or an explicitly reviewed compatible revision, "
                    f"found {schema_revision or 'none'}"
                )
            schema_status = "error"
            await _check_seo_structure(conn)
            if revisions[0] == "0095_adopt_geo_ticket":
                await _check_geo_ticket_adoption(conn)
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
        "compatible_schema_revisions": sorted(SEO_COMPATIBLE_SCHEMA_REVISIONS),
    }
