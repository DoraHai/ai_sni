"""Single additive head, frozen ORM parity, real 0109->0110 and existing-table refusal."""
import asyncio
import io
import os
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.environment import EnvironmentContext
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.schema import CreateTable, CreateIndex
from sqlalchemy.dialects.postgresql import dialect
import pytest

from app.models.distribution_inbox import DistributionInboxDevice as Device, DistributionInboxReceipt as Receipt
from test_distribution_inbox_postgres import revision

ROOT = Path(__file__).parents[1]
HEAD = '0110_distribution_inbox'


def test_unique_head_frozen_schema_and_no_existing_permissions_or_objects_modified():
    output = io.StringIO()
    config = Config(str(ROOT/'alembic.ini'), output_buffer=output)
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ['0111_geo_autopatrol']
    mod = revision()
    assert mod.down_revision == '0109_advisor_tenant_grants'
    tables = [Device.__table__,Receipt.__table__]
    ddl = [str(CreateTable(t).compile(dialect=dialect())).strip() for t in tables]
    ddl += [str(CreateIndex(i).compile(dialect=dialect())).strip() for t in tables for i in sorted(t.indexes,key=lambda i:i.name)]
    assert tuple(ddl) == mod.DDL
    command.upgrade(config, '0109_advisor_tenant_grants:'+HEAD, sql=True)
    sql = output.getvalue()
    assert sql.count('CREATE TABLE distribution_inbox_') == 2
    for forbidden in ('ALTER TABLE','DROP TABLE','GRANT ','REVOKE ','CREATE ROLE','ALTER ROLE','TRUNCATE','CREATE SEQUENCE'):
        assert forbidden not in sql
    assert 'COALESCE(scope_id, 0)' in sql and 'uq_inbox_device_event' in sql
    with pytest.raises(RuntimeError,match='cannot be downgraded'):
        mod.downgrade()


@pytest.mark.parametrize('existing', ['none','device','both'])
def test_native_alembic_0109_upgrade_and_existing_table_fail_closed(existing):
    raw = os.environ.get('SEO_MIGRATION_TEST_DATABASE_URL')
    if not raw:
        pytest.fail('Dedicated isolated loopback PostgreSQL is required')
    url = make_url(raw)
    if url.host not in {'localhost','127.0.0.1','::1'} or url.database != 'test' or url.query:
        raise ValueError('Only isolated loopback test database is permitted')
    async def scenario():
        schema = 'inbox_migration_'+uuid4().hex
        engine = create_async_engine(url,connect_args={'server_settings':{'search_path':schema}})
        try:
            async with engine.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
                await conn.execute(text('CREATE TABLE users(id bigint PRIMARY KEY)'))
                await conn.execute(text('CREATE TABLE existing_business(id bigint PRIMARY KEY, value text)'))
                await conn.execute(text("INSERT INTO existing_business VALUES (1,'unchanged')"))
                await conn.execute(text('CREATE TABLE alembic_version(version_num varchar(64) PRIMARY KEY)'))
                await conn.execute(text("INSERT INTO alembic_version VALUES ('0109_advisor_tenant_grants')"))
                if existing != 'none':
                    await conn.execute(text('CREATE TABLE distribution_inbox_devices(id text PRIMARY KEY)'))
                if existing == 'both':
                    await conn.execute(text('CREATE TABLE distribution_inbox_receipts(id text PRIMARY KEY)'))
            def upgrade(sync):
                config = Config(str(ROOT/'alembic.ini'))
                script = ScriptDirectory.from_config(config)
                with EnvironmentContext(config,script,fn=lambda rev,ctx:script._upgrade_revs(HEAD,rev)) as env:
                    env.configure(connection=sync)
                    with env.begin_transaction():
                        env.run_migrations()
            if existing != 'none':
                with pytest.raises(RuntimeError,match='already exist'):
                    async with engine.begin() as conn:
                        await conn.run_sync(upgrade)
            else:
                async with engine.begin() as conn:
                    await conn.run_sync(upgrade)
                # Re-running an applied upgrade is a true Alembic no-op.
                async with engine.begin() as conn:
                    await conn.run_sync(upgrade)
            async with engine.connect() as conn:
                current = await conn.scalar(text('SELECT version_num FROM alembic_version'))
                assert current == (HEAD if existing == 'none' else '0109_advisor_tenant_grants')
                assert await conn.scalar(text('SELECT value FROM existing_business')) == 'unchanged'
                if existing == 'none':
                    def verify(sync):
                        inspector = inspect(sync)
                        assert set(inspector.get_table_names()) == {'users','existing_business','alembic_version',Device.__tablename__,Receipt.__tablename__}
                        for table in (Device.__table__,Receipt.__table__):
                            assert {c['name'] for c in inspector.get_columns(table.name)} == set(table.columns.keys())
                        idx = {i['name']:i for i in inspector.get_indexes(Receipt.__tablename__)}
                        assert idx['uq_inbox_active_link']['unique']
                        assert 'label_state' in str(idx['uq_inbox_active_link']['dialect_options'])
                    await conn.run_sync(verify)
        finally:
            async with engine.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await engine.dispose()
    asyncio.run(scenario())
