from __future__ import annotations

import asyncio
import importlib.util
import json
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
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.schema import CreateTable

from app.models.demo_tenant_binding import DemoTenantBinding, DemoTenantBindingHistory


ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "migrations/versions/20260909_0097_demo_tenant_bindings.py"
CURRENT_CHECKS = {
    "ck_demo_tenant_bindings_demo_tenant_positive",
    "ck_demo_tenant_bindings_version_positive",
    "ck_demo_tenant_bindings_dataset_key_format",
    "ck_demo_tenant_bindings_dataset_version_format",
    "ck_demo_tenant_bindings_status",
    "ck_demo_tenant_bindings_disabled_state",
    "ck_demo_tenant_bindings_updated_time",
    "ck_demo_tenant_bindings_disabled_time",
    "ck_demo_tenant_bindings_disabled_updater",
}
HISTORY_CHECKS = {
    "ck_demo_tenant_binding_history_version_positive",
    "ck_demo_tenant_binding_history_operation",
    "ck_demo_tenant_binding_history_before",
    "ck_demo_tenant_binding_history_after",
    "ck_demo_tenant_binding_history_reason",
    "ck_demo_tenant_binding_history_links",
    "ck_demo_tenant_binding_history_transition",
}


def _config() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return config


def _load_migration():
    spec = importlib.util.spec_from_file_location("demo_binding_migration", MIGRATION)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_demo_binding_revision_is_the_single_linear_head() -> None:
    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == ["0097_demo_tenant_bindings"]
    assert script.get_revision("0097_demo_tenant_bindings").down_revision == "0096_sem_tasks"
    assert [step.revision.revision for step in script._upgrade_revs("0097_demo_tenant_bindings", "0096_sem_tasks")] == ["0097_demo_tenant_bindings"]


def test_demo_binding_orm_matches_control_plane_contract() -> None:
    current = DemoTenantBinding.__table__
    history = DemoTenantBindingHistory.__table__
    assert [column.name for column in current.columns] == [
        "tenant_id", "demo_tenant_id", "dataset_key", "dataset_version", "status",
        "bound_by_user_id", "bound_at", "updated_by_user_id", "updated_at",
        "disabled_at", "version", "notes",
    ]
    assert [column.name for column in history.columns] == [
        "id", "tenant_id", "binding_version", "operation", "before_snapshot",
        "after_snapshot", "actor_user_id", "reason", "created_at",
    ]
    assert current.c.tenant_id.primary_key
    assert not current.c.updated_by_user_id.nullable
    assert isinstance(history.c.id.type, sa.BigInteger) and history.c.id.primary_key
    assert current.primary_key.name == "pk_demo_tenant_bindings"
    assert history.primary_key.name == "pk_demo_tenant_binding_history"
    assert current.c.version.server_default.arg.text == "1"
    assert not current.c.bound_at.nullable and not current.c.updated_at.nullable
    assert history.c.before_snapshot.nullable and not history.c.after_snapshot.nullable
    assert isinstance(history.c.before_snapshot.type, postgresql.JSONB)
    assert isinstance(history.c.after_snapshot.type, postgresql.JSONB)
    assert {c.name for c in current.constraints if isinstance(c, sa.CheckConstraint)} == CURRENT_CHECKS
    assert {c.name for c in history.constraints if isinstance(c, sa.CheckConstraint)} == HISTORY_CHECKS
    assert {c.name for c in current.constraints if isinstance(c, sa.UniqueConstraint)} == {
        "uq_demo_tenant_bindings_demo_tenant", "uq_demo_tenant_bindings_dataset_key"
    }
    assert {c.name for c in history.constraints if isinstance(c, sa.UniqueConstraint)} == {
        "uq_demo_tenant_binding_history_tenant_version"
    }
    fks = {fk.name: fk for table in (current, history) for fk in table.foreign_key_constraints}
    assert set(fks) == {
        "fk_demo_tenant_bindings_tenant", "fk_demo_tenant_bindings_bound_by",
        "fk_demo_tenant_bindings_updated_by", "fk_demo_tenant_binding_history_tenant",
        "fk_demo_tenant_binding_history_actor",
    }
    assert all(fk.ondelete == "RESTRICT" for fk in fks.values())
    assert "BIGSERIAL NOT NULL" in str(CreateTable(history).compile(dialect=postgresql.dialect()))


def test_migration_renders_fixed_public_schema_and_no_grants() -> None:
    migration = _load_migration()
    output = __import__("io").StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    migration.op = Operations(context)
    migration.upgrade()
    ddl = output.getvalue()
    assert "CREATE TABLE public.demo_tenant_bindings" in ddl
    assert "CREATE TABLE public.demo_tenant_binding_history" in ddl
    assert "REFERENCES public.tenants (id) ON DELETE RESTRICT" in ddl
    assert "REFERENCES public.users (id) ON DELETE RESTRICT" in ddl
    assert "BIGSERIAL NOT NULL" in ddl
    for name in CURRENT_CHECKS | HISTORY_CHECKS | {
        "pk_demo_tenant_bindings", "pk_demo_tenant_binding_history",
        "uq_demo_tenant_bindings_demo_tenant", "uq_demo_tenant_bindings_dataset_key",
        "uq_demo_tenant_binding_history_tenant_version",
        "trg_demo_tenant_binding_history_append_only",
        "reject_demo_tenant_binding_history_mutation",
    }:
        assert name in ddl
    assert "GRANT" not in ddl.upper()
    assert "DATABASE_URL" not in ddl


def test_demo_binding_downgrade_fails_before_any_ddl() -> None:
    migration = _load_migration()
    class RefusingOp:
        def __getattr__(self, _name):
            raise AssertionError("downgrade attempted DDL before refusal")
    migration.op = RefusingOp()
    with pytest.raises(RuntimeError, match="irreversible"):
        migration.downgrade()


async def _create_or_drop_database(source_url: str, database: str, *, create: bool) -> None:
    engine = create_async_engine(make_url(source_url).set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            if create:
                await connection.execute(text(f'CREATE DATABASE "{database}" TEMPLATE template0'))
            else:
                await connection.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
    finally:
        await engine.dispose()


def _postgres_url() -> str:
    url = os.getenv("SEO_MIGRATION_TEST_DATABASE_URL")
    if not url:
        pytest.skip("SEO_MIGRATION_TEST_DATABASE_URL is not configured")
    parsed = make_url(url)
    if parsed.host not in {"127.0.0.1", "localhost", "::1"}:
        pytest.skip("migration tests require a disposable loopback PostgreSQL")
    return url


async def _require_local_postgres_16(source_url: str) -> None:
    engine = create_async_engine(source_url)
    try:
        async with engine.connect() as connection:
            version = int(await connection.scalar(text("SHOW server_version_num")))
        if not 160000 <= version < 170000:
            raise RuntimeError(f"migration rehearsal requires PostgreSQL 16, found {version}")
    finally:
        await engine.dispose()


def _isolated_database_url(source_url: str, database: str) -> str:
    return make_url(source_url).set(database=database).render_as_string(hide_password=False)


def test_isolated_database_url_preserves_ci_credentials() -> None:
    url = _isolated_database_url(
        "postgresql+asyncpg://fixture-user:fixture-password@127.0.0.1:5432/test",
        "isolated",
    )
    assert "fixture-user:fixture-password@" in url
    assert "***" not in url
    assert url.endswith("/isolated")


async def _catalog_and_negative_contract(target_url: str) -> dict[str, object]:
    engine = create_async_engine(target_url)
    try:
        async with engine.begin() as connection:
            from app import seo_main

            await seo_main._check_demo_binding_structure(connection)
            version = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            columns = (await connection.execute(text("""
                SELECT table_name, column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema='public' AND table_name IN ('demo_tenant_bindings','demo_tenant_binding_history')
                ORDER BY table_name, ordinal_position
            """))).all()
            constraints = set((await connection.execute(text("""
                SELECT conname FROM pg_catalog.pg_constraint
                WHERE conrelid IN ('public.demo_tenant_bindings'::regclass, 'public.demo_tenant_binding_history'::regclass)
            """))).scalars())
            sequence = await connection.scalar(text("SELECT pg_get_serial_sequence('public.demo_tenant_binding_history','id')"))
            trigger_rows = (await connection.execute(text("""
                SELECT c.relname, t.tgname, pg_catalog.pg_get_triggerdef(t.oid, true)
                FROM pg_catalog.pg_trigger t
                JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid
                JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='public'
                  AND c.relname IN ('demo_tenant_bindings','demo_tenant_binding_history')
                  AND NOT t.tgisinternal
            """))).all()
            triggers = {(table, name): " ".join(definition.lower().split()) for table, name, definition in trigger_rows}
            await connection.execute(text("INSERT INTO tenants (id,name) VALUES (900000001,'fixture')"))
            await connection.execute(text("INSERT INTO tenants (id,name) VALUES (900000002,'other fixture')"))
            await connection.execute(text("INSERT INTO roles (id,name,permissions) VALUES (900000001,'fixture','{}'::jsonb)"))
            await connection.execute(text("INSERT INTO users (id,username,password_hash,role_id,is_active) VALUES (900000001,'fixture-user','x',900000001,true)"))
            await connection.execute(text("INSERT INTO users (id,username,password_hash,role_id,is_active) VALUES (900000002,'other-fixture-user','x',900000001,true)"))
            valid = """INSERT INTO public.demo_tenant_bindings
              (tenant_id,demo_tenant_id,dataset_key,dataset_version,status,bound_by_user_id,updated_by_user_id)
              VALUES (900000001,900000001,'gsnipers_demo','demo-20260909-v1','active',900000001,900000001)"""
            await connection.execute(text(valid))
            after = {
                "tenant_id": 900000001, "demo_tenant_id": 900000001,
                "dataset_key": "gsnipers_demo", "dataset_version": "demo-20260909-v1",
                "status": "active", "bound_by_user_id": 900000001,
                "bound_at": "2026-09-09T20:00:00+08:00", "updated_by_user_id": 900000001,
                "updated_at": "2026-09-09T20:00:00+08:00", "disabled_at": None,
                "version": 1, "notes": None,
            }
            await connection.execute(text("""INSERT INTO public.demo_tenant_binding_history
              (tenant_id,binding_version,operation,before_snapshot,after_snapshot,actor_user_id,reason)
              VALUES (900000001,1,'create',NULL,CAST(:after AS jsonb),900000001,'initial fixture')"""), {"after": json.dumps(after)})
            replaced = {**after, "dataset_version": "demo-20260909-v2", "version": 2,
                        "updated_at": "2026-09-09T20:10:00+08:00"}
            disabled = {**replaced, "status": "disabled", "version": 3,
                        "updated_at": "2026-09-09T20:20:00+08:00",
                        "disabled_at": "2026-09-09T20:20:00+08:00"}
            history_sql = text("""INSERT INTO public.demo_tenant_binding_history
              (tenant_id,binding_version,operation,before_snapshot,after_snapshot,actor_user_id,reason)
              VALUES (900000001,:version,:operation,CAST(:before AS jsonb),CAST(:after AS jsonb),900000001,:reason)""")
            await connection.execute(history_sql, {"version": 2, "operation": "replace", "before": json.dumps(after), "after": json.dumps(replaced), "reason": "replace fixture"})
            await connection.execute(history_sql, {"version": 3, "operation": "disable", "before": json.dumps(replaced), "after": json.dumps(disabled), "reason": "disable fixture"})
            invalid_history = (
                "UPDATE public.demo_tenant_bindings SET demo_tenant_id=0 WHERE tenant_id=900000001",
                "UPDATE public.demo_tenant_bindings SET dataset_key='BAD KEY' WHERE tenant_id=900000001",
                "UPDATE public.demo_tenant_bindings SET status='disabled' WHERE tenant_id=900000001",
                "INSERT INTO public.demo_tenant_binding_history (tenant_id,binding_version,operation,before_snapshot,after_snapshot,actor_user_id,reason) VALUES (900000001,2,'replace',NULL,'{}'::jsonb,900000001,'x')",
                "INSERT INTO public.demo_tenant_binding_history (tenant_id,binding_version,operation,before_snapshot,after_snapshot,actor_user_id,reason) VALUES (900000001,2,'disable','{}'::jsonb,'{}'::jsonb,900000001,'   ')",
                "INSERT INTO public.demo_tenant_binding_history (tenant_id,binding_version,operation,before_snapshot,after_snapshot,actor_user_id,reason) SELECT tenant_id,1,'create',NULL,after_snapshot,actor_user_id,'duplicate version' FROM public.demo_tenant_binding_history WHERE id=1",
                "UPDATE public.demo_tenant_binding_history SET reason='tamper' WHERE id=1",
                "DELETE FROM public.demo_tenant_binding_history WHERE id=1",
                "TRUNCATE public.demo_tenant_binding_history",
                "DELETE FROM public.demo_tenant_bindings WHERE tenant_id=900000001",
            )
            for statement in invalid_history:
                nested = await connection.begin_nested()
                with pytest.raises(Exception):
                    await connection.execute(text(statement))
                await nested.rollback()
            replacement = {**disabled, "status": "active", "version": 4,
                           "updated_at": "2026-09-09T20:30:00+08:00", "disabled_at": None}
            for bad_before, bad_after, bad_actor, bad_operation in (
                (disabled, {**replacement, "password": "secret"}, 900000001, "replace"),
                (disabled, {key: value for key, value in replacement.items() if key != "dataset_key"}, 900000001, "replace"),
                (disabled, {**replacement, "tenant_id": "900000001"}, 900000001, "replace"),
                (disabled, {**replacement, "dataset_key": "BAD KEY"}, 900000001, "replace"),
                (disabled, {**replacement, "version": 5}, 900000001, "replace"),
                (disabled, {**replacement, "tenant_id": 900000002}, 900000001, "replace"),
                (disabled, replacement, 900000002, "replace"),
                (disabled, {**replacement, "status": "disabled", "disabled_at": "2026-09-09T20:30:00+08:00"}, 900000001, "replace"),
                ({**disabled, "status": "disabled"}, disabled, 900000001, "disable"),
            ):
                nested = await connection.begin_nested()
                with pytest.raises(Exception):
                    await connection.execute(text("""INSERT INTO public.demo_tenant_binding_history
                      (tenant_id,binding_version,operation,before_snapshot,after_snapshot,actor_user_id,reason)
                      VALUES (900000001,4,:operation,CAST(:before AS jsonb),CAST(:after AS jsonb),:actor,'negative')"""),
                      {"before": json.dumps(bad_before), "after": json.dumps(bad_after), "actor": bad_actor, "operation": bad_operation})
                await nested.rollback()
            counts = (
                await connection.scalar(text("SELECT count(*) FROM public.demo_tenant_bindings")),
                await connection.scalar(text("SELECT count(*) FROM public.demo_tenant_binding_history")),
            )
        return {"version": version, "columns": columns, "constraints": constraints, "sequence": sequence, "triggers": triggers, "counts": counts}
    finally:
        await engine.dispose()


@pytest.mark.parametrize("start", ["base", "0096_sem_tasks"])
def test_postgres_fresh_and_0096_upgrade_contract(monkeypatch, start: str) -> None:
    source_url = _postgres_url()
    from app.config import get_settings

    asyncio.run(_require_local_postgres_16(source_url))
    database = "demo_bindings_" + uuid4().hex
    target_url = _isolated_database_url(source_url, database)
    asyncio.run(_create_or_drop_database(source_url, database, create=True))
    try:
        monkeypatch.setenv("DATABASE_URL", target_url)
        get_settings.cache_clear()
        if start != "base":
            command.upgrade(_config(), start)
        command.upgrade(_config(), "0097_demo_tenant_bindings")
        result = asyncio.run(_catalog_and_negative_contract(target_url))
        assert result["version"] == "0097_demo_tenant_bindings"
        assert result["sequence"].endswith("demo_tenant_binding_history_id_seq")
        assert set(result["triggers"]) == {
            ("demo_tenant_binding_history", "trg_demo_tenant_binding_history_append_only"),
            ("demo_tenant_binding_history", "trg_demo_tenant_binding_history_no_truncate"),
            ("demo_tenant_bindings", "trg_demo_tenant_bindings_no_delete"),
        }
        assert all(fragment in result["triggers"][("demo_tenant_binding_history", "trg_demo_tenant_binding_history_no_truncate")]
                   for fragment in ("before truncate", "for each statement", "reject_demo_tenant_binding_history_mutation"))
        assert all(fragment in result["triggers"][("demo_tenant_bindings", "trg_demo_tenant_bindings_no_delete")]
                   for fragment in ("before delete", "for each row", "reject_demo_tenant_binding_delete"))
        assert result["counts"] == (1, 3)
        assert CURRENT_CHECKS | HISTORY_CHECKS <= result["constraints"]
        by_column = {(table, column): (kind, nullable, default) for table, column, kind, nullable, default in result["columns"]}
        assert by_column[("demo_tenant_bindings", "updated_by_user_id")][1] == "NO"
        assert by_column[("demo_tenant_bindings", "version")] == ("integer", "NO", "1")
        assert by_column[("demo_tenant_binding_history", "before_snapshot")][0] == "jsonb"
        assert by_column[("demo_tenant_binding_history", "after_snapshot")][1] == "NO"
    finally:
        get_settings.cache_clear()
        asyncio.run(_create_or_drop_database(source_url, database, create=False))
