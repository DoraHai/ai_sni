"""0108 advisor account links: graph position, real PostgreSQL upgrade/downgrade and ORM parity."""
import asyncio
import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateTable

from test_seo_workflow_postgres import dedicated_url, requires_pg
from app.models.advisor_account import AdvisorAccountLink, AdvisorAccountSwitchAudit
from app.models.user import User

ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "migrations/versions/20261015_0108_advisor_account_links.py"


def _migration():
    spec = importlib.util.spec_from_file_location("advisor_links_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_0108_precedes_0109_and_is_directly_after_0107():
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["0111_geo_autopatrol"]
    assert script.get_revision("0108_advisor_account_links").down_revision == "0107_seo_site_delete"


def test_0108_only_creates_the_two_reviewed_tables_without_privilege_changes():
    source = MIGRATION.read_text(encoding="utf-8").upper()
    assert source.count("CREATE TABLE") == 2 and source.count("CREATE INDEX") == 2
    for forbidden in ("GRANT", "REVOKE", "ALTER DEFAULT", "ALTER TABLE", "INSERT", "UPDATE ", "DELETE FROM", "TRUNCATE"):
        assert forbidden not in source


@requires_pg
def test_0108_upgrade_matches_orm_and_downgrade_removes_only_its_tables():
    migration = _migration()

    async def scenario():
        url = dedicated_url(os.environ["SEO_WORKFLOW_TEST_DATABASE_URL"])
        schema = "seo_workflow_test_" + uuid4().hex
        engine = create_async_engine(url, connect_args={"server_settings": {
            "search_path": schema, "lock_timeout": "5000", "statement_timeout": "15000"}})
        created = False
        try:
            async with engine.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
                created = True
                await conn.execute(CreateTable(User.__table__, include_foreign_key_constraints=[]))
                await conn.run_sync(lambda sync: _run(sync, migration.upgrade))
            async with engine.connect() as conn:
                columns = {(row.table_name, row.column_name): (row.data_type, row.is_nullable, row.is_identity)
                           for row in await conn.execute(text(
                               "SELECT table_name, column_name, data_type, is_nullable, is_identity "
                               "FROM information_schema.columns WHERE table_schema = current_schema() "
                               "AND table_name LIKE 'advisor_account_%'"))}
                for model in (AdvisorAccountLink, AdvisorAccountSwitchAudit):
                    for column in model.__table__.columns:
                        data_type, nullable, _ = columns[(model.__tablename__, column.name)]
                        assert (nullable == "YES") == column.nullable, column
                assert len(columns) == len(AdvisorAccountLink.__table__.columns) + len(AdvisorAccountSwitchAudit.__table__.columns)
                assert columns[("advisor_account_switch_audit", "id")][2] == "YES"
                assert columns[("advisor_account_links", "created_at")][0] == "timestamp with time zone"
                fks = set(await conn.execute(text(
                    "SELECT conname, confdeltype::text FROM pg_constraint WHERE contype = 'f' "
                    "AND conrelid = 'advisor_account_links'::regclass")))
                assert sorted(kind for _, kind in fks) == ["c", "r"]
                indexes = set((await conn.execute(text(
                    "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema() "
                    "AND tablename LIKE 'advisor_account_%'"))).scalars())
                assert {"ix_advisor_account_links_group_id", "ix_advisor_account_switch_audit_from_user_id"} <= indexes
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions() as session:
                session.add_all([
                    User(id=1, username="admin", password_hash="unused", role_id=1, is_active=True),
                    User(id=2, username="advisor", password_hash="unused", role_id=2, tenant_id=4, is_active=True),
                ])
                await session.flush()
                group = uuid4()
                session.add(AdvisorAccountLink(user_id=2, group_id=group, tenant_id=4, created_by=1))
                session.add(AdvisorAccountSwitchAudit(from_user_id=2, to_user_id=2, action="link", actor_user_id=1,
                                                      group_id=group, status="success"))
                await session.commit()
                assert (await session.scalar(select(AdvisorAccountSwitchAudit.id))) is not None
                await session.scalar(select(AdvisorAccountLink).where(AdvisorAccountLink.user_id == 2).with_for_update(read=True))
                await session.rollback()
            for bad in ({"action": "promote", "status": "success"}, {"action": "switch", "status": "maybe"}):
                async with sessions() as session:
                    session.add(AdvisorAccountSwitchAudit(from_user_id=2, to_user_id=2, actor_user_id=1, **bad))
                    with pytest.raises(IntegrityError):
                        await session.commit()
            async with sessions() as session:
                with pytest.raises(IntegrityError):
                    async with session.begin():
                        await session.execute(text("DELETE FROM users WHERE id = 1"))
            async with engine.begin() as conn:
                await conn.execute(text("DELETE FROM users WHERE id = 2"))
                assert await conn.scalar(text("SELECT count(*) FROM advisor_account_links")) == 0
                await conn.run_sync(lambda sync: _run(sync, migration.downgrade))
                remaining = set((await conn.execute(text(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()"))).scalars())
                assert remaining == {"users"}
        finally:
            try:
                if created:
                    assert schema.startswith("seo_workflow_test_") and len(schema) == len("seo_workflow_test_") + 32
                    async with engine.begin() as conn:
                        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            finally:
                await engine.dispose()

    asyncio.run(scenario())


def _run(connection, step):
    with Operations.context(MigrationContext.configure(connection)):
        step()
