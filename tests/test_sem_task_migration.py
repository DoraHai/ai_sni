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
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.schema import CreateTable
from sqlalchemy.engine import make_url

from app.models.sem_task import SemTask


ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "migrations/versions/20260909_0096_sem_tasks.py"
CHECK_SQL = {
    "ck_sem_tasks_module": "module = 'sem'",
    "ck_sem_tasks_action": "action_type = 'metric_target'",
    "ck_sem_tasks_status": "status IN ('open','in_progress','done','cancelled')",
    "ck_sem_tasks_role": "assignee_role IN ('operator','admin')",
    "ck_sem_tasks_params": "jsonb_typeof(params) = 'object'",
    "ck_sem_tasks_baseline": "jsonb_typeof(baseline_snapshot) = 'object'",
    "ck_sem_tasks_evidence": (
        "completion_evidence IS NULL OR jsonb_typeof(completion_evidence) = 'object'"
    ),
    "ck_sem_tasks_done": (
        "(status = 'done' AND completion_evidence IS NOT NULL) "
        "OR (status <> 'done' AND completion_evidence IS NULL)"
    ),
}
CHECK_NAMES = set(CHECK_SQL)
INDEX_COLUMNS = {
    "ix_sem_tasks_action": ["tenant_id", "action_type", "id"],
    "ix_sem_tasks_queue": ["tenant_id", "status", "id"],
    "ix_sem_tasks_tenant_id_id": ["tenant_id", "id"],
}


def _config() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return config


def _load_migration():
    spec = importlib.util.spec_from_file_location("sem_tasks_migration", MIGRATION)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_sem_task_revision_is_the_single_linear_head() -> None:
    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == ["0098_demo_binding_no_truncate"]
    assert script.get_revision("0096_sem_tasks").down_revision == "0095_adopt_geo_ticket"
    assert [
        step.revision.revision
        for step in script._upgrade_revs("0096_sem_tasks", "0095_adopt_geo_ticket")
    ] == ["0096_sem_tasks"]


def test_sem_task_orm_matches_the_reviewed_contract() -> None:
    table = SemTask.__table__
    assert [column.name for column in table.columns] == [
        "id",
        "tenant_id",
        "module",
        "action_type",
        "title",
        "params",
        "status",
        "created_by",
        "assignee_role",
        "baseline_snapshot",
        "completion_evidence",
        "created_at",
        "updated_at",
    ]
    assert isinstance(table.c.id.type, sa.BigInteger)
    assert isinstance(table.c.tenant_id.type, sa.BigInteger)
    assert table.c.id.primary_key and not table.c.tenant_id.nullable

    foreign_key = next(iter(table.c.tenant_id.foreign_keys))
    assert foreign_key.target_fullname == "tenants.id"
    assert foreign_key.name == "fk_sem_tasks_tenant_id_tenants"
    assert foreign_key.ondelete == "RESTRICT"

    checks = {
        constraint.name: " ".join(str(constraint.sqltext).split())
        for constraint in table.constraints
        if isinstance(constraint, sa.CheckConstraint)
    }
    assert checks == CHECK_SQL
    assert {
        index.name: [column.name for column in index.columns] for index in table.indexes
    } == INDEX_COLUMNS

    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    assert "tenant_id BIGINT NOT NULL" in ddl
    assert "CONSTRAINT fk_sem_tasks_tenant_id_tenants" in ddl
    assert "ON DELETE RESTRICT" in ddl


def test_migration_renders_reviewed_postgresql_ddl_without_a_database() -> None:
    migration = _load_migration()
    output = __import__("io").StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    migration.op = Operations(context)
    migration.upgrade()
    ddl = output.getvalue()

    assert "CREATE TABLE sem_tasks" in ddl
    assert "BIGSERIAL NOT NULL" in ddl
    assert "CONSTRAINT fk_sem_tasks_tenant_id_tenants" in ddl
    assert "FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE RESTRICT" in ddl
    for name in CHECK_NAMES | set(INDEX_COLUMNS):
        assert name in ddl
    normalized_ddl = "".join(ddl.split())
    for expression in CHECK_SQL.values():
        assert "".join(expression.split()) in normalized_ddl
    assert "CREATE INDEX ix_sem_tasks_tenant_id_id ON sem_tasks (tenant_id, id)" in ddl


def test_sem_task_downgrade_fails_before_any_ddl() -> None:
    migration = _load_migration()
    with pytest.raises(RuntimeError, match="irreversible"):
        migration.downgrade()


async def _create_or_drop_database(source_url: str, database: str, *, create: bool) -> None:
    admin_url = make_url(source_url).set(database="postgres")
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            if create:
                await connection.execute(text(f'CREATE DATABASE "{database}" TEMPLATE template0'))
            else:
                await connection.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
    finally:
        await engine.dispose()


async def _require_local_postgres_16(source_url: str) -> None:
    parsed = make_url(source_url)
    if parsed.host not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("migration rehearsal requires a loopback PostgreSQL URL")
    engine = create_async_engine(source_url)
    try:
        async with engine.connect() as connection:
            version = int((await connection.execute(text("SHOW server_version_num"))).scalar_one())
        if not 160000 <= version < 170000:
            raise RuntimeError(f"migration rehearsal requires PostgreSQL 16, found {version}")
    finally:
        await engine.dispose()


def _isolated_database_url(source_url: str, database: str) -> str:
    return make_url(source_url).set(database=database).render_as_string(hide_password=False)


async def _inspect_sem_tasks(target_url: str) -> dict[str, object]:
    engine = create_async_engine(target_url)
    try:
        async with engine.connect() as connection:
            columns = (await connection.execute(text("""
                SELECT attname, pg_catalog.format_type(atttypid, atttypmod), attnotnull
                FROM pg_catalog.pg_attribute
                WHERE attrelid = 'public.sem_tasks'::pg_catalog.regclass
                  AND attnum > 0 AND NOT attisdropped
                ORDER BY attnum
            """))).all()
            constraints = (await connection.execute(text("""
                SELECT conname, contype::text, pg_catalog.pg_get_constraintdef(oid)
                FROM pg_catalog.pg_constraint
                WHERE conrelid = 'public.sem_tasks'::pg_catalog.regclass
                ORDER BY conname
            """))).all()
            indexes = (await connection.execute(text("""
                SELECT indexname, indexdef
                FROM pg_catalog.pg_indexes
                WHERE schemaname = 'public' AND tablename = 'sem_tasks'
                ORDER BY indexname
            """))).all()
            return {
                "columns": columns,
                "constraints": constraints,
                "indexes": indexes,
                "sequence": await connection.scalar(
                    text("SELECT to_regclass('public.sem_tasks_id_seq')::text")
                ),
                "rows": await connection.scalar(text("SELECT count(*) FROM public.sem_tasks")),
                "version": await connection.scalar(text("SELECT version_num FROM alembic_version")),
            }
    finally:
        await engine.dispose()


def _assert_postgres_shape(shape: dict[str, object]) -> None:
    assert shape["version"] == "0096_sem_tasks"
    assert shape["sequence"] == "sem_tasks_id_seq"
    assert shape["rows"] == 0
    assert len(shape["columns"]) == 13
    assert shape["columns"][0] == ("id", "bigint", True)
    assert shape["columns"][1] == ("tenant_id", "bigint", True)
    assert dict((name, definition) for name, _kind, definition in shape["constraints"])[
        "fk_sem_tasks_tenant_id_tenants"
    ] == "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT"
    assert {name for name, kind, _definition in shape["constraints"] if kind == "c"} == CHECK_NAMES
    assert {name for name, _definition in shape["indexes"]} == {
        "sem_tasks_pkey",
        *INDEX_COLUMNS,
    }


@pytest.mark.skipif(
    not os.getenv("SEO_MIGRATION_TEST_DATABASE_URL"),
    reason="requires isolated PostgreSQL 16 with CREATE DATABASE",
)
def test_postgres_fresh_chain_creates_empty_sem_tasks(monkeypatch) -> None:
    source_url = os.environ["SEO_MIGRATION_TEST_DATABASE_URL"]
    from app.config import get_settings

    asyncio.run(_require_local_postgres_16(source_url))
    database = "sem_tasks_fresh_" + uuid4().hex
    asyncio.run(_create_or_drop_database(source_url, database, create=True))
    target_url = _isolated_database_url(source_url, database)
    try:
        monkeypatch.setenv("DATABASE_URL", target_url)
        get_settings.cache_clear()
        command.upgrade(_config(), "0096_sem_tasks")
        _assert_postgres_shape(asyncio.run(_inspect_sem_tasks(target_url)))
    finally:
        get_settings.cache_clear()
        asyncio.run(_create_or_drop_database(source_url, database, create=False))


@pytest.mark.skipif(
    not os.getenv("SEO_MIGRATION_TEST_DATABASE_URL"),
    reason="requires isolated PostgreSQL 16 with CREATE DATABASE",
)
def test_postgres_0095_upgrades_only_by_adding_empty_sem_tasks(monkeypatch) -> None:
    source_url = os.environ["SEO_MIGRATION_TEST_DATABASE_URL"]
    from app.config import get_settings

    asyncio.run(_require_local_postgres_16(source_url))
    database = "sem_tasks_from_0095_" + uuid4().hex
    asyncio.run(_create_or_drop_database(source_url, database, create=True))
    target_url = _isolated_database_url(source_url, database)
    try:
        monkeypatch.setenv("DATABASE_URL", target_url)
        get_settings.cache_clear()
        command.upgrade(_config(), "0095_adopt_geo_ticket")

        async def seed_and_snapshot() -> tuple[int, object]:
            engine = create_async_engine(target_url)
            try:
                async with engine.begin() as connection:
                    assert await connection.scalar(text("SELECT to_regclass('public.sem_tasks')")) is None
                    await connection.execute(
                        text("INSERT INTO public.tenants (id, name) VALUES (900000001, 'preserve')")
                    )
                    return (
                        await connection.scalar(text("SELECT count(*) FROM public.tenants")),
                        await connection.scalar(text("SELECT max(id) FROM public.tenants")),
                    )
            finally:
                await engine.dispose()

        before = asyncio.run(seed_and_snapshot())
        command.upgrade(_config(), "0096_sem_tasks")
        shape = asyncio.run(_inspect_sem_tasks(target_url))
        _assert_postgres_shape(shape)

        async def tenant_snapshot() -> tuple[int, object]:
            engine = create_async_engine(target_url)
            try:
                async with engine.connect() as connection:
                    return (
                        await connection.scalar(text("SELECT count(*) FROM public.tenants")),
                        await connection.scalar(text("SELECT max(id) FROM public.tenants")),
                    )
            finally:
                await engine.dispose()

        assert asyncio.run(tenant_snapshot()) == before
    finally:
        get_settings.cache_clear()
        asyncio.run(_create_or_drop_database(source_url, database, create=False))
