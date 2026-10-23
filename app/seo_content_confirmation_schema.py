"""Read-only capability gate shared by HTTP requests and content workers."""
from functools import lru_cache
from pathlib import Path

from alembic.script import ScriptDirectory
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError

from app.models.seo import SeoContentConfirmation, SeoSiteAdvisorAssignment


@lru_cache(maxsize=1)
def _legacy_revisions():
    scripts = ScriptDirectory(str(Path(__file__).resolve().parents[1] / "migrations"))
    return frozenset(r.revision for r in scripts.walk_revisions(
        base="base", head="0104_seo_page_ai_tdk",
    ))


def _unavailable():
    return HTTPException(503, {"code": "content_confirmation_schema_unavailable"})


async def content_confirmation_schema_ready(session) -> bool:
    """Only an intact legacy schema may skip confirmation; damage fails closed.

    No process/session cache: a migration can make a previous False obsolete.
    Public catalogs and privileges are checked without touching business rows.
    """
    try:
        revisions = list((await session.execute(
            text("SELECT version_num FROM public.alembic_version")
        )).scalars())
        rows = list((await session.execute(text("""
            SELECT c.relname, a.attname,
                   pg_catalog.format_type(a.atttypid, a.atttypmod) AS column_type,
                   (c.relkind IN ('r', 'p') AND has_table_privilege(c.oid, 'SELECT')) AS readable
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
              AND a.attnum > 0 AND NOT a.attisdropped
            WHERE n.nspname = 'public'
              AND c.relname IN ('seo_content_confirmations', 'seo_site_advisor_assignments')
        """))).all())
    except SQLAlchemyError:
        raise _unavailable() from None
    if len(revisions) != 1:
        raise _unavailable()
    if revisions[0] in _legacy_revisions():
        if not rows:
            return False
        raise _unavailable()
    columns = {(r[0], r[1]): (r[2], r[3]) for r in rows}
    for model in (SeoContentConfirmation, SeoSiteAdvisorAssignment):
        for column in model.__table__.columns:
            expected = column.type.compile(dialect=postgresql.dialect()).lower()
            expected = expected.replace("varchar", "character varying")
            if expected == "timestamp":
                expected = "timestamp without time zone"
            actual, readable = columns.get((model.__tablename__, column.name), (None, False))
            if actual != expected or not readable:
                raise _unavailable()
    return True
