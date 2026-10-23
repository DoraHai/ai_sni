"""Shared 0111 graph/DDL contract and real disposable PostgreSQL upgrade guards."""
import asyncio
import hashlib
import io
import os
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).parents[1]
HEAD = "0111_geo_autopatrol"
PREVIOUS = "0110_distribution_inbox"
# Frozen from reviewed GEO 0075, excluding 0111 preflight (no cross-repo dependency).
GEO_0075_DDL_SHA256 = "50595a32fbd6ac223c3b053d69ef7cfb64f80f5e22cbb9e49475e67b2743a650"


def scripts():
    config = Config()
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return config, ScriptDirectory.from_config(config)


def test_shared_chain_graph_and_exact_retired_geo_schema():
    _, script = scripts()
    assert script.get_heads() == [HEAD]
    assert script.get_base() == "0001_initial"
    assert len(list(script.walk_revisions())) > 100  # Resolves every parent.
    assert "0075_geo_autopatrol" not in {r.revision for r in script.walk_revisions()}
    revision = script.get_revision(HEAD)
    assert revision.down_revision == PREVIOUS
    assert [r.revision.revision for r in script._upgrade_revs(HEAD, PREVIOUS)] == [HEAD]
    output = io.StringIO()
    with Operations.context(MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})):
        revision.module.upgrade()
    sql = output.getvalue()
    schema_sql = sql[sql.index("ALTER TABLE"):]
    assert hashlib.sha256(schema_sql.encode()).hexdigest() == GEO_0075_DDL_SHA256
    assert "LOCK TABLE" in sql and "refuses existing or partial" in sql
    assert not any(word in sql.upper() for word in ("DROP ", "GRANT ", "REVOKE ", "UPDATE ", "ALTER COLUMN"))
    with pytest.raises(RuntimeError, match="irreversible"):
        revision.module.downgrade()


@pytest.mark.parametrize("existing", ["none", "column", "table", "index", "sequence", "complete"])
def test_native_0110_to_0111_and_fail_closed(existing):
    raw = os.environ.get("SEO_MIGRATION_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("requires isolated CI PostgreSQL")
    url = make_url(raw)
    if url.drivername != "postgresql+asyncpg" or url.host not in {"localhost", "127.0.0.1", "::1"} or url.database != "test" or url.username != "test" or url.query:
        raise ValueError("only dedicated loopback CI PostgreSQL test database/user allowed")

    async def scenario():
        schema = "autopatrol_0111_" + uuid4().hex
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
        def upgrade(sync):
            config, script = scripts()
            with EnvironmentContext(config, script, fn=lambda rev, ctx: script._upgrade_revs(HEAD, rev)) as env:
                env.configure(connection=sync)
                with env.begin_transaction(): env.run_migrations()
        try:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
                for sql in (
                    "CREATE TABLE tenants(id bigint PRIMARY KEY)",
                    "INSERT INTO tenants VALUES (123)",
                    "CREATE TABLE geo_visibility_patrol_settings(tenant_id bigint PRIMARY KEY REFERENCES tenants(id), enabled boolean NOT NULL)",
                    "INSERT INTO geo_visibility_patrol_settings VALUES (123, true)",
                    "CREATE TABLE geo_visibility_patrol_runs(id bigserial PRIMARY KEY, tenant_id bigint NOT NULL REFERENCES tenants(id), status varchar(24))",
                    "INSERT INTO geo_visibility_patrol_runs(tenant_id,status) VALUES (123,'completed')",
                    "CREATE TABLE alembic_version(version_num varchar(32) PRIMARY KEY)",
                    "INSERT INTO alembic_version VALUES ('0110_distribution_inbox')",
                ): await conn.execute(sa.text(sql))
                if existing == "column": await conn.execute(sa.text("ALTER TABLE geo_visibility_patrol_settings ADD COLUMN schedule_mode text"))
                if existing == "table": await conn.execute(sa.text("CREATE TABLE geo_visibility_patrol_daily_budget(budget_day text)"))
                if existing == "index": await conn.execute(sa.text("CREATE INDEX uq_geo_patrol_tenant_auto_day ON geo_visibility_patrol_runs(id)"))
                if existing == "sequence": await conn.execute(sa.text("CREATE SEQUENCE geo_visibility_patrol_setting_events_id_seq"))
                if existing == "complete":
                    await conn.run_sync(upgrade)
                    # Simulate reviewed shape but an unadvanced version. Adoption is refused.
                    await conn.execute(sa.text("UPDATE alembic_version SET version_num='0110_distribution_inbox'"))
            if existing != "none":
                with pytest.raises(Exception, match="refuses existing or partial"):
                    async with engine.begin() as conn: await conn.run_sync(upgrade)
            else:
                async with engine.begin() as conn: await conn.run_sync(upgrade)
                async with engine.begin() as conn: await conn.run_sync(upgrade)  # Native already-applied no-op.
            async with engine.begin() as conn:
                assert await conn.scalar(sa.text("SELECT version_num FROM alembic_version")) == (HEAD if existing == "none" else PREVIOUS)
                assert await conn.scalar(sa.text("SELECT enabled FROM geo_visibility_patrol_settings WHERE tenant_id=123")) is True
                assert await conn.scalar(sa.text("SELECT status FROM geo_visibility_patrol_runs WHERE id=1")) == "completed"
                if existing == "none":
                    row = (await conn.execute(sa.text("SELECT * FROM geo_visibility_patrol_settings"))).mappings().one()
                    assert (row["schedule_mode"], row["self_service_enabled"], row["manual_daily_limit"], row["revision"]) == ("legacy", False, 10, 0)
                    assert await conn.scalar(sa.text("SELECT auto_day FROM geo_visibility_patrol_runs WHERE id=1")) is None
                    assert await conn.scalar(sa.text("SELECT count(*) FROM geo_visibility_patrol_setting_events")) == 0
                    assert await conn.scalar(sa.text("SELECT count(*) FROM geo_visibility_patrol_daily_budget")) == 0
                    ident = await conn.scalar(sa.text("""INSERT INTO geo_visibility_patrol_setting_events(tenant_id,actor_role,action,"before","after",revision) VALUES (123,'advisor','enable','{}','{}',1) RETURNING id"""))
                    assert ident == 1
                    await conn.execute(sa.text("INSERT INTO geo_visibility_patrol_runs(tenant_id,auto_day) VALUES(123,'2026-10-23')"))
                    with pytest.raises(sa.exc.IntegrityError):
                        async with conn.begin_nested():
                            await conn.execute(sa.text("INSERT INTO geo_visibility_patrol_runs(tenant_id,auto_day) VALUES(123,'2026-10-23')"))
        finally:
            async with engine.begin() as conn: await conn.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
            await engine.dispose()
    asyncio.run(scenario())


def test_release_package_is_exact_offline_output_and_transactional():
    from alembic import command
    import re
    package = ROOT / "docs/migration-0111"
    output = io.StringIO()
    config = Config(str(ROOT / "alembic.ini"), output_buffer=output)
    command.upgrade(config, PREVIOUS + ":" + HEAD, sql=True)
    upgrade = (package / "upgrade-0111.sql").read_text(encoding="utf-8")
    assert upgrade == output.getvalue()
    body = upgrade[len("BEGIN;\n"):].rstrip()[:-len("COMMIT;")].strip()
    apply = (package / "apply-0111.psql").read_text(encoding="utf-8")
    embedded = apply.split("-- BEGIN exact Alembic-generated body (outer transaction removed only)\n")[1].split("\n-- END exact Alembic-generated body")[0]
    assert embedded == body
    assert apply.count("\nBEGIN;") == 1 and apply.count("\nCOMMIT;") == 1
    assert "SET LOCAL lock_timeout='5s'" in apply
    assert "SET LOCAL statement_timeout='300s'" in apply
    assert "LOCK TABLE public.alembic_version IN EXCLUSIVE MODE" in apply
    for filename in ("precheck.sql", "verify.sql"):
        sql = (package / filename).read_text(encoding="utf-8")
        unquoted = re.sub(r"'(?:''|[^'])*'", "''", sql)
        unquoted = re.sub(r"--[^\n]*", "", unquoted)
        assert "BEGIN READ ONLY" in sql
        assert not re.search(r"\b(CREATE|ALTER|DROP|INSERT|UPDATE|DELETE|TRUNCATE|GRANT|REVOKE|DO|CALL|COPY)\b", unquoted, re.I)
        assert "coalesce(ok,false)" in sql and "nextval(" not in sql
    for filename in ("upgrade-0111.sql", "apply-0111.psql"):
        assert not re.search(r"\b(GRANT|REVOKE|DROP|TRUNCATE)\b", (package / filename).read_text(encoding="utf-8"), re.I)
    for line in (package / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, filename = line.split("  ")
        assert hashlib.sha256((package / filename).read_bytes()).hexdigest() == digest
