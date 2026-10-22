"""DDL/graph checks plus real migrations in disposable CI PostgreSQL schemas."""
import asyncio
from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from uuid import uuid4
import os

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

ROOT = Path(__file__).parents[1]
HEAD = "0075_geo_autopatrol"
PREVIOUS = "0074_geo_ticket_assignment"


def scripts():
    config = Config()
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return ScriptDirectory.from_config(config)


def test_migration_graph_and_additive_postgresql_ddl():
    script = scripts()
    assert script.get_heads() == [HEAD]
    migration = script.get_revision(HEAD)
    assert migration.down_revision == PREVIOUS
    output = StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        migration.module.upgrade()
    sql = output.getvalue()
    assert "WHERE auto_day IS NOT NULL" in sql
    assert "DEFAULT 'legacy'" in sql and "DEFAULT '10'" in sql
    assert not any(word in sql.upper() for word in ("DROP ", "GRANT ", "UPDATE ", "ALTER COLUMN"))


@pytest.mark.skipif(not os.getenv("GEO_TEST_POSTGRES_URL"), reason="requires dedicated loopback CI PostgreSQL")
@pytest.mark.parametrize("incremental", [False, True], ids=["empty-upgrade", "existing-data-upgrade"])
def test_upgrade_on_owned_postgresql_schema(incremental):
    from ops.run_geo_checks import validate_ci_database
    from sqlalchemy.ext.asyncio import create_async_engine

    url = os.environ["GEO_TEST_POSTGRES_URL"]
    validate_ci_database(url)

    def upgrade(connection, target, since=None):
        script = scripts()
        revisions = list(script.iterate_revisions(target, since))
        with Operations.context(MigrationContext.configure(connection)):
            for rev in reversed(revisions):
                rev.module.upgrade()

    async def run():
        schema = "geo_autopatrol_migration_" + uuid4().hex
        engine = create_async_engine(url)
        try:
            async with engine.begin() as connection:
                await connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
                await connection.execute(sa.text(f'SET LOCAL search_path TO "{schema}"'))
                if incremental:
                    await connection.run_sync(lambda c: upgrade(c, PREVIOUS))
                    await connection.execute(sa.text("INSERT INTO tenants(id, name) VALUES (123, 'synthetic')"))
                    await connection.execute(sa.text("INSERT INTO geo_visibility_patrol_settings(tenant_id, enabled) VALUES (123, true)"))
                    await connection.execute(sa.text("INSERT INTO geo_visibility_patrol_runs(id, tenant_id, status) VALUES (456, 123, 'completed')"))
                    await connection.run_sync(lambda c: upgrade(c, HEAD, PREVIOUS))
                    row = (await connection.execute(sa.text("SELECT * FROM geo_visibility_patrol_settings WHERE tenant_id=123"))).mappings().one()
                    assert row["enabled"] is True
                    assert row["schedule_mode"] == "legacy" and row["self_service_enabled"] is False
                    assert row["manual_daily_limit"] == 10 and row["revision"] == 0
                    assert await connection.scalar(sa.text("SELECT auto_day FROM geo_visibility_patrol_runs WHERE id=456")) is None
                else:
                    await connection.run_sync(lambda c: upgrade(c, HEAD))
                columns = await connection.run_sync(lambda c: sa.inspect(c).get_columns("geo_visibility_patrol_settings"))
                assert {c["name"] for c in columns} >= {"owner_scope", "manual_daily_limit", "manual_limit_revision"}
                index = await connection.scalar(sa.text("SELECT indexdef FROM pg_indexes WHERE schemaname=:schema AND indexname='uq_geo_patrol_tenant_auto_day'"), {"schema": schema})
                assert "UNIQUE INDEX" in index and "auto_day IS NOT NULL" in index
                assert await connection.scalar(sa.text("SELECT count(*) FROM geo_visibility_patrol_setting_events")) == 0
        finally:
            # Only the randomly named schema created above is ever removed.
            async with engine.begin() as connection:
                await connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await engine.dispose()

    asyncio.run(run())
