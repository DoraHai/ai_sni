from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine


ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "migrations/versions/20260910_0099_demo_fixture_registry.py"


def _config() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return config


def _load_migration():
    spec = importlib.util.spec_from_file_location("demo_fixture_registry", MIGRATION)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_0099_is_the_single_linear_head() -> None:
    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == ["0099_demo_fixture_registry"]
    assert script.get_revision("0099_demo_fixture_registry").down_revision == "0098_demo_binding_no_truncate"


def test_static_registry_contract_is_shared_immutable_and_role_neutral() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE SCHEMA demo_control" in source
    assert '"fixture_registry"' in source
    assert '"module_code", "demo_tenant_id", "dataset_key", "dataset_version"' in source
    assert "module_code IN ('sem','seo','geo')" in source
    assert "demo_tenant_id > 0" in source
    assert "^[a-z0-9][a-z0-9_-]{0,63}$" in source
    assert "^[a-z0-9][a-z0-9._-]{0,39}$" in source
    assert "^[0-9a-f]{64}$" in source
    assert "schema_revision = '0099_demo_fixture_registry'" in source
    assert "is_nonnegative_integer_object(row_counts)" in source
    assert "jsonb_typeof(source_summary) = 'object'" in source
    assert "status = 'sealed'" in source
    assert source.count("CREATE TRIGGER trg_fixture_registry_no_") == 3
    assert "BEFORE UPDATE ON" in source
    assert "BEFORE DELETE ON" in source
    assert "BEFORE TRUNCATE ON" in source
    assert "GRANT" not in source.upper()
    assert "CREATE SEQUENCE" not in source.upper()
    assert "alicloud" not in source.lower()


def test_offline_and_downgrade_refuse_before_ddl() -> None:
    migration = _load_migration()

    class Context:
        as_sql = True

    class RefusingOp:
        def get_context(self):
            return Context()

        def __getattr__(self, _name):
            raise AssertionError("operation attempted DDL")

    migration.op = RefusingOp()
    with pytest.raises(RuntimeError, match="online PostgreSQL catalog check"):
        migration.upgrade()
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


async def _inspect(target_url: str) -> tuple[str, int]:
    from app import seo_main

    engine = create_async_engine(target_url)
    try:
        async with engine.connect() as connection:
            await seo_main._check_fixture_registry_structure(connection)
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            count = await connection.scalar(text("SELECT count(*) FROM demo_control.fixture_registry"))
            return revision, count
    finally:
        await engine.dispose()


@pytest.mark.parametrize("start", ["base", "0098_demo_binding_no_truncate"])
def test_postgres_fresh_and_0098_upgrade_to_0099(monkeypatch, start: str) -> None:
    source_url = _postgres_url()
    from app.config import get_settings

    database = "demo_registry_" + uuid4().hex
    target_url = make_url(source_url).set(database=database).render_as_string(hide_password=False)
    asyncio.run(_database(source_url, database, create=True))
    try:
        monkeypatch.setenv("DATABASE_URL", target_url)
        get_settings.cache_clear()
        if start != "base":
            command.upgrade(_config(), start)
        command.upgrade(_config(), "0099_demo_fixture_registry")
        command.upgrade(_config(), "0099_demo_fixture_registry")
        assert asyncio.run(_inspect(target_url)) == ("0099_demo_fixture_registry", 0)
    finally:
        get_settings.cache_clear()
        asyncio.run(_database(source_url, database, create=False))


@pytest.mark.parametrize("partial", ["schema", "table"])
def test_postgres_rejects_partial_or_drifted_preexisting_objects(monkeypatch, partial: str) -> None:
    source_url = _postgres_url()
    from app.config import get_settings

    database = "demo_registry_drift_" + uuid4().hex
    target_url = make_url(source_url).set(database=database).render_as_string(hide_password=False)
    asyncio.run(_database(source_url, database, create=True))
    try:
        monkeypatch.setenv("DATABASE_URL", target_url)
        get_settings.cache_clear()
        command.upgrade(_config(), "0098_demo_binding_no_truncate")

        async def inject() -> None:
            engine = create_async_engine(target_url)
            try:
                async with engine.begin() as connection:
                    await connection.execute(text("CREATE SCHEMA demo_control"))
                    if partial == "table":
                        await connection.execute(text("CREATE TABLE demo_control.fixture_registry (fake integer)"))
            finally:
                await engine.dispose()

        asyncio.run(inject())
        with pytest.raises(Exception, match="demo_control schema already exists"):
            command.upgrade(_config(), "0099_demo_fixture_registry")
        assert asyncio.run(_current_revision(target_url)) == "0098_demo_binding_no_truncate"
    finally:
        get_settings.cache_clear()
        asyncio.run(_database(source_url, database, create=False))


async def _current_revision(target_url: str) -> str:
    engine = create_async_engine(target_url)
    try:
        async with engine.connect() as connection:
            return await connection.scalar(text("SELECT version_num FROM alembic_version"))
    finally:
        await engine.dispose()


INSERT_SQL = text("""
INSERT INTO demo_control.fixture_registry (
    module_code, demo_tenant_id, dataset_key, dataset_version,
    fixture_namespace, manifest_sha256, schema_revision, loader_name,
    loader_version, row_counts, source_summary, sealed_at, status
) VALUES (
    :module_code, :demo_tenant_id, :dataset_key, :dataset_version,
    :fixture_namespace, :manifest_sha256, :schema_revision, :loader_name,
    :loader_version, CAST(:row_counts AS jsonb), CAST(:source_summary AS jsonb), now(), :status
)
""")


def _valid_values() -> dict[str, object]:
    return {
        "module_code": "seo",
        "demo_tenant_id": 4,
        "dataset_key": "tiger_demo",
        "dataset_version": "2026.09-v1",
        "fixture_namespace": "seo.tiger.public-baseline",
        "manifest_sha256": "a" * 64,
        "schema_revision": "0099_demo_fixture_registry",
        "loader_name": "seo-demo-fixture-loader",
        "loader_version": "1.0.0",
        "row_counts": '{"seo_sites":1}',
        "source_summary": '{"kind":"public-crawl"}',
        "status": "sealed",
    }


def test_postgres_constraints_reject_invalid_receipts(monkeypatch) -> None:
    source_url = _postgres_url()
    from app.config import get_settings

    database = "demo_registry_constraints_" + uuid4().hex
    target_url = make_url(source_url).set(database=database).render_as_string(hide_password=False)
    asyncio.run(_database(source_url, database, create=True))
    try:
        monkeypatch.setenv("DATABASE_URL", target_url)
        get_settings.cache_clear()
        command.upgrade(_config(), "0099_demo_fixture_registry")

        async def reject() -> None:
            engine = create_async_engine(target_url)
            try:
                invalid = [
                    ("module_code", "ads"), ("demo_tenant_id", 0), ("dataset_key", "Bad Key"),
                    ("dataset_version", "Bad Version"), ("fixture_namespace", "   "),
                    ("manifest_sha256", "A" * 64), ("schema_revision", "0098_demo_binding_no_truncate"),
                    ("loader_name", ""), ("loader_version", " "), ("row_counts", "{}"),
                    ("row_counts", '{"x":-1}'), ("row_counts", '{"x":1.5}'),
                    ("row_counts", '{"x":"1"}'), ("source_summary", "[]"), ("status", "pending"),
                ]
                for field, value in invalid:
                    values = _valid_values()
                    values[field] = value
                    with pytest.raises(Exception):
                        async with engine.begin() as connection:
                            await connection.execute(INSERT_SQL, values)
            finally:
                await engine.dispose()

        asyncio.run(reject())
    finally:
        get_settings.cache_clear()
        asyncio.run(_database(source_url, database, create=False))


def test_postgres_update_delete_and_truncate_each_preserve_receipt(monkeypatch) -> None:
    source_url = _postgres_url()
    from app.config import get_settings

    database = "demo_registry_immutable_" + uuid4().hex
    target_url = make_url(source_url).set(database=database).render_as_string(hide_password=False)
    asyncio.run(_database(source_url, database, create=True))
    try:
        monkeypatch.setenv("DATABASE_URL", target_url)
        get_settings.cache_clear()
        command.upgrade(_config(), "0099_demo_fixture_registry")

        async def exercise() -> None:
            engine = create_async_engine(target_url)
            try:
                async with engine.begin() as connection:
                    await connection.execute(INSERT_SQL, _valid_values())
                for statement in (
                    "UPDATE demo_control.fixture_registry SET loader_version='2.0.0'",
                    "DELETE FROM demo_control.fixture_registry",
                    "TRUNCATE demo_control.fixture_registry",
                ):
                    with pytest.raises(Exception, match="fixture_registry is immutable"):
                        async with engine.begin() as connection:
                            await connection.execute(text(statement))
                async with engine.connect() as connection:
                    assert await connection.scalar(text("SELECT count(*) FROM demo_control.fixture_registry")) == 1
            finally:
                await engine.dispose()

        asyncio.run(exercise())
    finally:
        get_settings.cache_clear()
        asyncio.run(_database(source_url, database, create=False))
