"""Real PostgreSQL FKs/triggers, synthetic rows in a disposable random schema only."""
import asyncio
import importlib.util
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from unittest.mock import AsyncMock, patch
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text, func, delete
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.exc import DBAPIError
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "test-secret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.database import Base
import app.models
from app.api import customer_modules as api
from app.security.auth import AuthContext

ROOT=Path(__file__).resolve().parents[1]
def migration(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/"migrations/versions"/name)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
M106=migration("20261008_0106_seo_content_messages.py")
M107=migration("20261011_0107_seo_site_delete.py")


def test_purge_inventory_covers_every_site_scoped_seo_table():
    tables={t.name for t in Base.metadata.tables.values() if t.name.startswith("seo_") and "site_id" in t.c}
    assert set(M107.SITE_TABLES)|{"seo_content_conversations"}==tables


@asynccontextmanager
async def database():
    raw=os.getenv("SEO_DELETE_TEST_DATABASE_URL")
    if not raw:pytest.skip("requires dedicated local PostgreSQL")
    url=make_url(raw)
    assert url.drivername=="postgresql+asyncpg" and url.host=="127.0.0.1" and not url.query
    assert url.database in {"seo_delete_test","test"}
    assert url.port in {55439,5432}
    schema="seo_delete_test_"+uuid4().hex
    engine=create_async_engine(url,connect_args={"server_settings":{"search_path":schema,"statement_timeout":"15000"}})
    try:
        async with engine.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            def prepare(sync):
                tables=[t for t in Base.metadata.sorted_tables if t.name not in {
                  "seo_content_conversations","seo_conversation_participants","seo_content_messages"}]
                Base.metadata.create_all(sync,tables=tables)
                with Operations.context(MigrationContext.configure(sync)):M106.upgrade()
            await conn.run_sync(prepare)
        sessions=async_sessionmaker(engine,expire_on_commit=False)
        async with sessions() as session:
            async def insert(table_name,**values):
                await session.execute(Base.metadata.tables[table_name].insert().values(**values))
            await insert("tenants",id=1,name="Synthetic customer")
            await insert("roles",id=1,name="synthetic",permissions={})
            await insert("users",id=1,username="synthetic",password_hash="not-a-password",role_id=1)
            await insert("tenant_modules",id=1,tenant_id=1,module_code="seo")
            await insert("tenants",id=2,name="Other customer")
            await insert("tenant_modules",id=2,tenant_id=2,module_code="seo")
            for ident in (10,20,30):
                tenant=2 if ident==30 else 1
                await insert("seo_sites",id=ident,tenant_id=tenant,tenant_module_id=tenant,name="synthetic",domain=f"test{ident}.invalid",canonical_domain=f"test{ident}.invalid",status="archived" if ident==20 else "active")
                await insert("seo_keyword_assets",id=ident,tenant_id=tenant,site_id=ident,keyword="synthetic")
                await insert("seo_site_pages",id=ident,tenant_id=tenant,site_id=ident,url=f"https://test{ident}.invalid/",target_keyword_id=ident)
                await insert("seo_content_assets",id=ident,tenant_id=tenant,site_id=ident,title="synthetic",keyword_id=ident,keyword_ids=[ident])
                await insert("seo_crawl_runs",id=ident,tenant_id=tenant,site_id=ident,status="completed",seed_url=f"https://test{ident}.invalid/")
                await insert("seo_page_snapshots",id=ident,tenant_id=tenant,site_id=ident,crawl_run_id=ident,url=f"https://test{ident}.invalid/")
                await insert("seo_metric_snapshots",id=ident,tenant_id=tenant,site_id=ident,metric_type="synthetic",source="test",observed_at=datetime(2026,10,11))
                await insert("seo_content_conversations",id=ident,tenant_id=tenant,site_id=ident,content_asset_id=ident)
                await insert("seo_conversation_participants",conversation_id=ident,user_id=1)
                await insert("seo_content_messages",id=ident,conversation_id=ident,sender_user_id=1,sender_name="synthetic",sender_kind="advisor",request_id=uuid4(),body="synthetic message")
            await session.commit()
        async with engine.begin() as conn:
            def upgrade(sync):
                with Operations.context(MigrationContext.configure(sync)):M107.upgrade()
            await conn.run_sync(upgrade)
        role=schema+"_app"
        async with engine.begin() as conn:
            await conn.execute(text(f'CREATE ROLE "{role}" NOLOGIN'))
            await conn.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"'))
            await conn.execute(text(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO "{role}"'))
            await conn.execute(text(f'GRANT DELETE, UPDATE ON "{schema}".seo_sites TO "{role}"'))
        sessions.test_role=role
        yield sessions
    finally:
        async with engine.begin() as conn:await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP ROLE IF EXISTS "{schema}_app"'))
        await engine.dispose()


def test_populated_site_delete_cleans_children_preserves_other_site_and_can_rollback():
    async def run():
        async with database() as sessions:
            async with sessions() as s:
                assert await s.scalar(text("SELECT status FROM seo_sites WHERE id=20"))=="paused"
                await s.execute(text("DELETE FROM seo_sites WHERE id=10"))
                assert await s.scalar(text("SELECT count(*) FROM seo_content_messages WHERE id=10"))==0
                await s.rollback()
                assert await s.scalar(text("SELECT count(*) FROM seo_content_messages WHERE id=10"))==1
                await s.execute(text(f'SET LOCAL ROLE "{sessions.test_role}"'))
                assert not await s.scalar(text("SELECT has_table_privilege(current_user,'seo_content_messages','DELETE')"))
                ctx=AuthContext(1,"synthetic","test",1,{"seo.assets":"edit"})
                with patch.object(api,"ensure_module_access",new=AsyncMock()):
                    assert (await api.delete_seo_site(10,1,"test10.invalid",ctx,s))["deleted"]
                for name in ("seo_sites","seo_keyword_assets","seo_site_pages","seo_content_assets","seo_crawl_runs","seo_page_snapshots","seo_metric_snapshots","seo_content_conversations","seo_content_messages"):
                    assert await s.scalar(text(f'SELECT count(*) FROM {name} WHERE id=10'))==0,name
                    assert await s.scalar(text(f'SELECT count(*) FROM {name} WHERE id=20'))==1,name
                    assert await s.scalar(text(f'SELECT count(*) FROM {name} WHERE id=30'))==1,name
                assert await s.scalar(text("SELECT count(*) FROM tenants"))==2
                assert await s.scalar(text("SELECT count(*) FROM users"))==1
    asyncio.run(run())


@pytest.mark.parametrize("sql",["DELETE FROM seo_content_messages WHERE id=10","UPDATE seo_content_messages SET body='changed' WHERE id=10","TRUNCATE seo_content_messages"])
def test_regular_message_mutation_remains_forbidden_even_with_forged_scope(sql):
    async def run():
        async with database() as sessions:
            async with sessions() as s:
                await s.execute(text("SELECT set_config('seo.purge_site_id','10',true), set_config('seo.purge_tenant_id','1',true)"))
                with pytest.raises(DBAPIError):await s.execute(text(sql))
                await s.rollback()
                assert await s.scalar(text("SELECT count(*) FROM seo_content_messages"))==3
    asyncio.run(run())


def test_failure_halfway_through_purge_rolls_back_messages_and_website():
    async def run():
        async with database() as sessions:
            async with sessions() as s:
                await s.execute(text("""CREATE FUNCTION fail_test_purge() RETURNS trigger LANGUAGE plpgsql AS $$
                  BEGIN RAISE EXCEPTION 'test injected failure' USING ERRCODE='23514'; END; $$"""))
                await s.execute(text("CREATE TRIGGER fail_test_purge BEFORE DELETE ON seo_keyword_assets FOR EACH ROW EXECUTE FUNCTION fail_test_purge()"))
                await s.commit()
                ctx=AuthContext(1,"synthetic","test",1,{"seo.assets":"edit"})
                from fastapi import HTTPException
                with patch.object(api,"ensure_module_access",new=AsyncMock()):
                    with pytest.raises(HTTPException) as error:await api.delete_seo_site(10,1,"test10.invalid",ctx,s)
                assert error.value.status_code==409
                assert await s.scalar(text("SELECT count(*) FROM seo_content_messages"))==3
                assert await s.scalar(text("SELECT count(*) FROM seo_sites"))==3
    asyncio.run(run())


def test_concurrent_foreign_key_insert_cannot_leave_orphan_after_delete():
    async def run():
        async with database() as sessions:
            async with sessions() as deleting, sessions() as inserting:
                await deleting.execute(text("DELETE FROM seo_sites WHERE id=10"))
                # The FK check waits for the locked parent. It must fail after deletion commits.
                pending=asyncio.create_task(inserting.execute(text(
                  "INSERT INTO seo_metric_snapshots(tenant_id,site_id,metric_type,dimension,source,data_quality,status,observed_at) VALUES (1,10,'concurrent','total','test','estimated','available',now())")))
                await asyncio.sleep(0.05)
                assert not pending.done()
                await deleting.commit()
                with pytest.raises(DBAPIError):await pending
                await inserting.rollback()
                assert await inserting.scalar(text("SELECT count(*) FROM seo_metric_snapshots WHERE site_id=10"))==0
    asyncio.run(run())
