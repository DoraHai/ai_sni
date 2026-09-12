from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine


ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "migrations/versions/20260909_0098_demo_binding_no_truncate.py"


def _config() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return config


def _load_migration():
    spec = importlib.util.spec_from_file_location("demo_binding_no_truncate", MIGRATION)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_0098_is_the_single_linear_head() -> None:
    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == ["0099_demo_fixture_registry"]
    assert script.get_revision("0098_demo_binding_no_truncate").down_revision == "0097_demo_tenant_bindings"
    assert [step.revision.revision for step in script._upgrade_revs("0098_demo_binding_no_truncate", "0097_demo_tenant_bindings")] == ["0098_demo_binding_no_truncate"]


def test_0098_renders_only_the_current_binding_truncate_guard() -> None:
    migration = _load_migration()
    output = __import__("io").StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    migration.op = Operations(context)
    migration.upgrade()
    ddl = output.getvalue()
    assert "CREATE TRIGGER trg_demo_tenant_bindings_no_truncate" in ddl
    assert "BEFORE TRUNCATE ON public.demo_tenant_bindings" in ddl
    assert "FOR EACH STATEMENT" in ddl
    assert "reject_demo_tenant_binding_delete()" in ddl
    assert "CREATE TABLE" not in ddl
    assert "ALTER TABLE" not in ddl
    assert "GRANT" not in ddl


def test_0098_downgrade_refuses_before_ddl() -> None:
    migration = _load_migration()
    class RefusingOp:
        def __getattr__(self, _name):
            raise AssertionError("downgrade attempted DDL")
    migration.op = RefusingOp()
    with pytest.raises(RuntimeError, match="irreversible"):
        migration.downgrade()


def _postgres_url() -> str:
    url = os.getenv("SEO_MIGRATION_TEST_DATABASE_URL")
    if not url:
        pytest.skip("SEO_MIGRATION_TEST_DATABASE_URL is not configured")
    if make_url(url).host not in {"127.0.0.1", "localhost", "::1"}:
        pytest.skip("migration tests require a disposable loopback PostgreSQL")
    return url


async def _database(source_url: str, name: str, *, create: bool) -> None:
    engine = create_async_engine(make_url(source_url).set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            version = int(await connection.scalar(text("SHOW server_version_num")))
            if not 160000 <= version < 170000:
                raise RuntimeError(f"requires PostgreSQL 16, found {version}")
            if create:
                await connection.execute(text(f'CREATE DATABASE "{name}" TEMPLATE template0'))
            else:
                await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        await engine.dispose()


async def _inspect_and_reject_truncate(target_url: str) -> tuple[str, str, int]:
    from app import seo_main
    engine = create_async_engine(target_url)
    try:
        async with engine.connect() as connection:
            await seo_main._check_demo_binding_structure(connection, require_current_truncate=True)
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            definition = await connection.scalar(text("""
                SELECT pg_catalog.pg_get_triggerdef(t.oid, true)
                FROM pg_catalog.pg_trigger t
                WHERE t.tgrelid='public.demo_tenant_bindings'::regclass
                  AND t.tgname='trg_demo_tenant_bindings_no_truncate'
                  AND NOT t.tgisinternal
            """))
            count = await connection.scalar(text("SELECT count(*) FROM public.demo_tenant_bindings"))
            transaction = await connection.begin_nested()
            with pytest.raises(Exception, match="cannot be physically deleted"):
                await connection.execute(text("TRUNCATE public.demo_tenant_bindings"))
            await transaction.rollback()
            return revision, definition, count
    finally:
        await engine.dispose()


@pytest.mark.parametrize("start", ["base", "0097_demo_tenant_bindings"])
def test_postgres_fresh_and_0097_upgrade_add_only_truncate_guard(monkeypatch, start: str) -> None:
    source_url = _postgres_url()
    from app.config import get_settings
    database = "demo_no_truncate_" + uuid4().hex
    target_url = make_url(source_url).set(database=database).render_as_string(hide_password=False)
    asyncio.run(_database(source_url, database, create=True))
    try:
        monkeypatch.setenv("DATABASE_URL", target_url)
        get_settings.cache_clear()
        if start != "base":
            command.upgrade(_config(), start)
        command.upgrade(_config(), "0098_demo_binding_no_truncate")
        revision, definition, count = asyncio.run(_inspect_and_reject_truncate(target_url))
        normalized = " ".join(definition.lower().split())
        assert revision == "0098_demo_binding_no_truncate"
        assert count == 0
        assert all(fragment in normalized for fragment in (
            "before truncate", "for each statement", "reject_demo_tenant_binding_delete"
        ))
    finally:
        get_settings.cache_clear()
        asyncio.run(_database(source_url, database, create=False))
