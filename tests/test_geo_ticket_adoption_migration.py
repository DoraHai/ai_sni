from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory


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
