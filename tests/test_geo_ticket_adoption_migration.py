from __future__ import annotations

import importlib.util
import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine


ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "migrations/versions/20260909_0095_adopt_geo_ticket.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("geo_ticket_adoption", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_adoption_is_the_only_head_and_follows_production_0094() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    script = ScriptDirectory.from_config(config)

    assert script.get_heads() == ["0095_adopt_geo_ticket"]
    assert script.get_revision("0095_adopt_geo_ticket").down_revision == "0094_seo_qa_batches"


def test_adoption_contract_is_fixed_schema_online_only_and_irreversible() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "LOCK TABLE public.geo_action_tickets IN ACCESS EXCLUSIVE MODE" in source
    assert "SET LOCAL lock_timeout = '5s'" in source
    assert "context.as_sql" in source
    assert 'bind.dialect.name != "postgresql"' in source
    assert 'schema=_SCHEMA' in source
    assert "partial geo_action_tickets adoption" in source
    assert "collation_is_type_default" in source
    assert "must not have indexes or constraints" in source
    assert source.count("pg_catalog.pg_depend") >= 2
    assert "ANY(i.indkey)" not in source

    migration = _load_migration()
    with pytest.raises(RuntimeError, match="irreversible"):
        migration.downgrade()


def test_reviewed_column_contract_matches_read_only_production_catalog() -> None:
    migration = _load_migration()

    assert migration._EXPECTED_COLUMNS == {
        "owner_name": {
            "formatted_type": "character varying(100)",
            "attnotnull": False,
            "default_expression": None,
            "attidentity": "",
            "attgenerated": "",
            "typtype": "b",
            "domain_base_type": None,
            "collation_is_type_default": True,
        },
        "due_date": {
            "formatted_type": "date",
            "attnotnull": False,
            "default_expression": None,
            "attidentity": "",
            "attgenerated": "",
            "typtype": "b",
            "domain_base_type": None,
            "collation_is_type_default": True,
        },
    }


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def mappings(self):
        return self


class _Bind:
    class _Dialect:
        name = "postgresql"

    dialect = _Dialect()

    def __init__(self, migration, columns):
        self.migration = migration
        self.columns = columns
        self.locked = False

    def execute(self, statement):
        sql = str(statement)
        if sql.startswith("SET LOCAL lock_timeout"):
            return _Result([])
        if sql.startswith("LOCK TABLE"):
            self.locked = True
            return _Result([])
        if "SELECT c.relkind" in sql:
            return _Result([("r",)])
        if "pg_catalog.pg_attribute AS a" in sql and "pg_attrdef" in sql:
            return _Result([
                {"attname": name, **values}
                for name, values in sorted(self.columns.items())
            ])
        if "pg_catalog.pg_index" in sql or "pg_catalog.pg_constraint" in sql:
            return _Result([])
        raise AssertionError(f"unexpected SQL: {sql}")


class _Operations:
    class _Context:
        as_sql = False

    def __init__(self, migration, columns):
        self.bind = _Bind(migration, columns)
        self.added = []

    def get_context(self):
        return self._Context()

    def get_bind(self):
        return self.bind

    def add_column(self, table, column, schema):
        assert self.bind.locked
        assert table == "geo_action_tickets"
        assert schema == "public"
        self.added.append(column.name)
        self.bind.columns[column.name] = dict(
            self.bind.migration._EXPECTED_COLUMNS[column.name]
        )


def test_exact_production_shape_is_adopted_without_ddl() -> None:
    migration = _load_migration()
    operations = _Operations(
        migration,
        {name: dict(values) for name, values in migration._EXPECTED_COLUMNS.items()},
    )
    migration.op = operations

    migration.upgrade()

    assert operations.bind.locked
    assert operations.added == []


def test_empty_canonical_shape_adds_both_columns_then_revalidates() -> None:
    migration = _load_migration()
    operations = _Operations(migration, {})
    migration.op = operations

    migration.upgrade()

    assert operations.added == ["owner_name", "due_date"]


def test_partial_or_drifted_shape_fails_without_ddl() -> None:
    migration = _load_migration()
    partial = _Operations(
        migration,
        {"owner_name": dict(migration._EXPECTED_COLUMNS["owner_name"])},
    )
    migration.op = partial
    with pytest.raises(RuntimeError, match="refusing partial"):
        migration.upgrade()
    assert partial.added == []

    drifted_columns = {
        name: dict(values) for name, values in migration._EXPECTED_COLUMNS.items()
    }
    drifted_columns["owner_name"]["formatted_type"] = "character varying(200)"
    drifted = _Operations(migration, drifted_columns)
    migration.op = drifted
    with pytest.raises(RuntimeError, match="does not match"):
        migration.upgrade()
    assert drifted.added == []


def test_offline_mode_stops_before_catalog_or_ddl() -> None:
    migration = _load_migration()

    class OfflineOperations:
        class Context:
            as_sql = True

        def get_context(self):
            return self.Context()

    migration.op = OfflineOperations()
    with pytest.raises(RuntimeError, match="online PostgreSQL"):
        migration.upgrade()


def _config() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return config


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


def _isolated_database_url(source_url: str, database: str) -> str:
    return make_url(source_url).set(database=database).render_as_string(hide_password=False)


@pytest.mark.skipif(
    not os.getenv("SEO_MIGRATION_TEST_DATABASE_URL"),
    reason="requires isolated PostgreSQL 16 with CREATE DATABASE",
)
def test_postgres_fresh_chain_creates_reviewed_columns(monkeypatch) -> None:
    source_url = os.environ["SEO_MIGRATION_TEST_DATABASE_URL"]
    database = "geo_adopt_fresh_" + uuid4().hex
    asyncio.run(_create_or_drop_database(source_url, database, create=True))
    target_url = _isolated_database_url(source_url, database)
    try:
        monkeypatch.setenv("DATABASE_URL", target_url)
        from app.config import get_settings

        get_settings.cache_clear()
        command.upgrade(_config(), "head")

        async def inspect_shape():
            engine = create_async_engine(target_url)
            try:
                async with engine.connect() as connection:
                    version = (await connection.execute(text(
                        "SELECT version_num FROM alembic_version"
                    ))).scalar_one()
                    rows = (await connection.execute(text("""
                        SELECT attname, pg_catalog.format_type(atttypid, atttypmod), attnotnull
                        FROM pg_catalog.pg_attribute
                        WHERE attrelid = 'public.geo_action_tickets'::pg_catalog.regclass
                          AND attname IN ('owner_name', 'due_date')
                        ORDER BY attname
                    """))).all()
                    return version, rows
            finally:
                await engine.dispose()

        version, rows = asyncio.run(inspect_shape())
        assert version == "0095_adopt_geo_ticket"
        assert rows == [("due_date", "date", False), ("owner_name", "character varying(100)", False)]
    finally:
        get_settings.cache_clear()
        asyncio.run(_create_or_drop_database(source_url, database, create=False))


@pytest.mark.skipif(
    not os.getenv("SEO_MIGRATION_TEST_DATABASE_URL"),
    reason="requires isolated PostgreSQL 16 with CREATE DATABASE",
)
def test_postgres_reviewed_0094_shape_is_adopted_without_rewrite(monkeypatch) -> None:
    source_url = os.environ["SEO_MIGRATION_TEST_DATABASE_URL"]
    database = "geo_adopt_existing_" + uuid4().hex
    asyncio.run(_create_or_drop_database(source_url, database, create=True))
    target_url = _isolated_database_url(source_url, database)
    try:
        monkeypatch.setenv("DATABASE_URL", target_url)
        from app.config import get_settings

        get_settings.cache_clear()
        command.upgrade(_config(), "0094_seo_qa_batches")

        async def prepare_and_snapshot():
            engine = create_async_engine(target_url)
            try:
                async with engine.begin() as connection:
                    await connection.execute(text("""
                        ALTER TABLE public.geo_action_tickets
                        ADD COLUMN owner_name character varying(100) NULL,
                        ADD COLUMN due_date date NULL
                    """))
                    await connection.execute(text("INSERT INTO public.tenants (id, name) VALUES (900000001, 'fixture')"))
                    await connection.execute(text("""
                        INSERT INTO public.geo_action_tickets
                            (id, tenant_id, title, owner_name, due_date)
                        VALUES (900000001, 900000001, 'preserve', 'Alice', DATE '2026-09-30')
                    """))
                    return (await connection.execute(text("""
                        SELECT c.relfilenode, a.attname, a.attnum
                        FROM pg_catalog.pg_class c
                        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                        JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
                        WHERE n.nspname = 'public' AND c.relname = 'geo_action_tickets'
                          AND a.attname IN ('owner_name', 'due_date')
                        ORDER BY a.attname
                    """))).all()
            finally:
                await engine.dispose()

        before = asyncio.run(prepare_and_snapshot())
        command.upgrade(_config(), "head")

        async def inspect_after():
            engine = create_async_engine(target_url)
            try:
                async with engine.connect() as connection:
                    catalog = (await connection.execute(text("""
                        SELECT c.relfilenode, a.attname, a.attnum
                        FROM pg_catalog.pg_class c
                        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                        JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
                        WHERE n.nspname = 'public' AND c.relname = 'geo_action_tickets'
                          AND a.attname IN ('owner_name', 'due_date')
                        ORDER BY a.attname
                    """))).all()
                    values = (await connection.execute(text("""
                        SELECT owner_name, due_date::text
                        FROM public.geo_action_tickets WHERE id = 900000001
                    """))).one()
                    version = (await connection.execute(text(
                        "SELECT version_num FROM alembic_version"
                    ))).scalar_one()
                    return catalog, values, version
            finally:
                await engine.dispose()

        after, values, version = asyncio.run(inspect_after())
        assert after == before
        assert values == ("Alice", "2026-09-30")
        assert version == "0095_adopt_geo_ticket"
    finally:
        get_settings.cache_clear()
        asyncio.run(_create_or_drop_database(source_url, database, create=False))


@pytest.mark.skipif(
    not os.getenv("SEO_MIGRATION_TEST_DATABASE_URL"),
    reason="requires isolated PostgreSQL 16 with CREATE DATABASE",
)
def test_postgres_expression_and_predicate_indexes_fail_closed(monkeypatch) -> None:
    source_url = os.environ["SEO_MIGRATION_TEST_DATABASE_URL"]
    database = "geo_adopt_index_" + uuid4().hex
    asyncio.run(_create_or_drop_database(source_url, database, create=True))
    target_url = _isolated_database_url(source_url, database)
    try:
        monkeypatch.setenv("DATABASE_URL", target_url)
        from app.config import get_settings

        get_settings.cache_clear()
        command.upgrade(_config(), "0094_seo_qa_batches")

        async def prepare():
            engine = create_async_engine(target_url)
            try:
                async with engine.begin() as connection:
                    await connection.execute(text("""
                        ALTER TABLE public.geo_action_tickets
                        ADD COLUMN owner_name character varying(100) NULL,
                        ADD COLUMN due_date date NULL
                    """))
                    await connection.execute(text("""
                        CREATE INDEX ix_geo_ticket_owner_expression
                        ON public.geo_action_tickets (lower(owner_name))
                    """))
                    await connection.execute(text("""
                        CREATE INDEX ix_geo_ticket_due_predicate
                        ON public.geo_action_tickets (id) WHERE due_date IS NOT NULL
                    """))
            finally:
                await engine.dispose()

        asyncio.run(prepare())
        with pytest.raises(Exception, match="must not have indexes or constraints"):
            command.upgrade(_config(), "head")

        async def current_version():
            engine = create_async_engine(target_url)
            try:
                async with engine.connect() as connection:
                    return (await connection.execute(text(
                        "SELECT version_num FROM alembic_version"
                    ))).scalar_one()
            finally:
                await engine.dispose()

        assert asyncio.run(current_version()) == "0094_seo_qa_batches"
    finally:
        get_settings.cache_clear()
        asyncio.run(_create_or_drop_database(source_url, database, create=False))
