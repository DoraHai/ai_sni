"""Dedicated local PG tests; reuse the guarded per-test schema lifecycle."""
import asyncio
import importlib.util
from pathlib import Path
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, text, func
from sqlalchemy.exc import DBAPIError
from alembic.migration import MigrationContext
from alembic.operations import Operations
from test_seo_workflow_postgres import database, ADVISOR, requires_pg, trigger
from app.api import seo_messages as api
from app.models.user import User
from app.models.role import Role
from app.models.seo import SeoContentAsset, SeoSiteAdvisorAssignment
from app.models.seo_messages import SeoContentConversation as Conversation, SeoContentMessage as Message, SeoConversationParticipant as Participant
from app.security.auth import AuthContext

CUSTOMER = AuthContext(8, "customer", "customer", 4, {"seo.content": "view", "seo.site": "view"})


@asynccontextmanager
async def store():
    async with database() as sessions:
        await trigger(sessions, uuid4())
        async with sessions() as session:
            connection = await session.connection()
            def upgrade(conn):
                path = Path(__file__).parents[1] / "migrations/versions/20261008_0106_seo_content_messages.py"
                spec = importlib.util.spec_from_file_location("message_migration", path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                with Operations.context(MigrationContext.configure(conn)):
                    module.upgrade()
            await connection.run_sync(upgrade)
            await session.execute(text("UPDATE alembic_version SET version_num=:revision"), {"revision": api.SCHEMA})
            session.add(Role(id=6, name="customer", permissions=CUSTOMER.permissions))
            session.add(User(id=8, role_id=6, username="customer", display_name="Actual customer", password_hash="unused", tenant_id=4, is_active=True))
            await session.commit()
        yield sessions


async def send(sessions, actor, body, key=None, content_id=1):
    async with sessions() as session:
        return await api.send_message(content_id, api.Send(tenant_id=4, site_id=2, body=body, request_id=key or uuid4()), session, actor)


async def meta(sessions, actor=CUSTOMER):
    async with sessions() as session:
        return await api.get_conversation(1, 4, 2, session, actor)


async def messages(sessions, actor=CUSTOMER, before=None, limit=2, content_id=1):
    async with sessions() as session:
        return await api.list_messages(content_id, 4, 2, limit, before, session, actor)


async def read(sessions, ident, actor=CUSTOMER):
    async with sessions() as session:
        return await api.mark_read(1, api.Read(tenant_id=4, site_id=2, last_read_message_id=ident), session, actor)


@requires_pg
def test_two_roles_persist_messages_but_get_and_send_do_not_mark_read():
    async def run():
        async with store() as sessions:
            empty = await meta(sessions)
            assert empty["conversation_id"] is None and empty["read_state"]["unread_count"] == 0
            async with sessions() as session:
                assert await session.scalar(select(func.count()).select_from(Conversation)) == 0
                assert await session.scalar(select(func.count()).select_from(Participant)) == 0
            first = await send(sessions, CUSTOMER, "Customer question")
            second = await send(sessions, ADVISOR, "Advisor answer")
            assert first["message"]["sender"] == {"id":8,"name":"Actual customer","kind":"customer"}
            assert second["message"]["sender"]["kind"] == "advisor"
            assert second["message"]["created_at"].endswith("Z")
            assert (await meta(sessions))["read_state"] == {"last_read_message_id":0,"latest_message_id":second["message"]["id"],"unread_count":1}
            assert len((await messages(sessions))["items"]) == 2
            marked = await read(sessions, second["message"]["id"])
            assert marked["read_state"]["unread_count"] == 0
            assert (await read(sessions, first["message"]["id"]))["read_state"] == marked["read_state"]
            async with sessions() as session:
                content = await session.get(SeoContentAsset, 1)
                assert content.status == "planned" and content.version_count == 1
                assert content.published_at is None
    asyncio.run(run())


@requires_pg
def test_concurrent_idempotent_first_send_and_key_conflict():
    async def run():
        async with store() as sessions:
            key = uuid4()
            results = await asyncio.gather(*(send(sessions, CUSTOMER, "same", key) for _ in range(8)))
            assert len({x["message"]["id"] for x in results}) == 1
            assert sum(not x["replayed"] for x in results) == 1
            with pytest.raises(HTTPException) as exc:
                await send(sessions, CUSTOMER, "changed", key)
            assert exc.value.status_code == 409 and exc.value.detail["code"] == "message_request_conflict"
            other = await send(sessions, ADVISOR, "same UUID different sender", key)
            assert other["message"]["id"] != results[0]["message"]["id"]
            async with sessions() as session:
                assert await session.scalar(select(func.count()).select_from(Conversation)) == 1
                assert await session.scalar(select(func.count()).select_from(Message)) == 2
    asyncio.run(run())


@requires_pg
def test_cursor_pagination_and_cross_conversation_read_rejected():
    async def run():
        async with store() as sessions:
            ids = [(await send(sessions, ADVISOR, str(i)))["message"]["id"] for i in range(5)]
            first = await messages(sessions)
            second = await messages(sessions, before=first["next_before_id"])
            third = await messages(sessions, before=second["next_before_id"])
            assert [m["id"] for m in first["items"]] == ids[3:]
            assert [m["id"] for m in second["items"]] == ids[1:3]
            assert [m["id"] for m in third["items"]] == ids[:1] and not third["has_more"]
            async with sessions() as session:
                session.add(SeoContentAsset(id=2, tenant_id=4, site_id=2, title="Other article", status="drafting"))
                await session.commit()
            foreign = (await send(sessions, ADVISOR, "Other thread", content_id=2))["message"]["id"]
            for call in (read(sessions, foreign), messages(sessions, before=foreign), read(sessions, foreign + 100)):
                with pytest.raises(HTTPException) as exc: await call
                assert exc.value.status_code == 404
            assert (await meta(sessions))["read_state"]["last_read_message_id"] == 0
    asyncio.run(run())


@requires_pg
@pytest.mark.parametrize("change", ["assignment", "edit_to_view", "inactive_user", "tenant", "site", "content"])
def test_revoked_and_wrong_scope_cannot_read_or_write(change):
    async def run():
        async with store() as sessions:
            sent = await send(sessions, ADVISOR, "Before revocation")
            actor = ADVISOR
            tenant, site, content = 4, 2, 1
            if change in {"assignment", "inactive_user"}:
                async with sessions() as session:
                    row = await session.get(SeoSiteAdvisorAssignment if change == "assignment" else User, 3 if change == "assignment" else 7)
                    setattr(row, "active" if change == "assignment" else "is_active", False)
                    await session.commit()
            elif change == "edit_to_view":
                # A tenant-bound downgraded advisor must never fall through to customer.
                async with sessions() as session:
                    row = await session.get(User, 7); row.tenant_id = 4
                    await session.commit()
                actor = AuthContext(7,"advisor","downgraded",4,{"seo.content":"view"})
            elif change == "tenant": actor = CUSTOMER; tenant = 99
            elif change == "site": site = 99
            else: content = 99
            for operation in ("get", "send", "read"):
                async with sessions() as session:
                    with pytest.raises(HTTPException) as exc:
                        if operation == "get": await api.get_conversation(content, tenant, site, session, actor)
                        elif operation == "send": await api.send_message(content, api.Send(tenant_id=tenant,site_id=site,request_id=uuid4(),body="must reject"),session,actor)
                        else: await api.mark_read(content,api.Read(tenant_id=tenant,site_id=site,last_read_message_id=sent["message"]["id"]),session,actor)
                    assert exc.value.status_code == (404 if change in {"site", "content"} else 403)
            async with sessions() as session:
                assert await session.scalar(select(func.count()).select_from(Message)) == 1
    asyncio.run(run())


@requires_pg
def test_send_waits_for_concurrent_assignment_revocation_then_denies():
    async def run():
        async with store() as sessions:
            async with sessions() as revoker:
                assignment = await revoker.get(SeoSiteAdvisorAssignment, 3, with_for_update=True)
                assignment.active = False
                await revoker.flush()
                pending = asyncio.create_task(send(sessions, ADVISOR, "Must not win revocation"))
                await asyncio.sleep(0.1)
                assert not pending.done()
                await revoker.commit()
                with pytest.raises(HTTPException) as exc: await asyncio.wait_for(pending, timeout=10)
                assert exc.value.status_code == 403
            async with sessions() as session:
                assert await session.scalar(select(func.count()).select_from(Message)) == 0
    asyncio.run(run())


@requires_pg
def test_message_table_is_append_only_and_0106_keeps_old_workflows_ready():
    async def run():
        async with store() as sessions:
            await send(sessions, CUSTOMER, "Immutable")
            async with sessions() as session:
                from app.api.seo import _content_confirmation_schema_ready
                from app.seo_content_workflow import schema_ready
                assert await _content_confirmation_schema_ready(session) and await schema_ready(session)
                for sql in ("UPDATE seo_content_messages SET body='changed'", "DELETE FROM seo_content_messages", "TRUNCATE seo_content_messages"):
                    with pytest.raises(DBAPIError):
                        async with session.begin_nested(): await session.execute(text(sql))
                assert await session.scalar(select(Message.body)) == "Immutable"
    asyncio.run(run())


@requires_pg
def test_real_migration_structure_rejects_missing_columns_constraints_and_triggers():
    from app.seo_main import _check_content_message_structure
    async def run():
        async with store() as sessions:
            async with sessions() as session:
                conn = await session.connection()
                schema = await session.scalar(text("SELECT current_schema()"))
                await _check_content_message_structure(conn, schema)
                changes = [
                    "ALTER TABLE seo_content_messages DROP COLUMN sender_name",
                    "ALTER TABLE seo_content_messages DROP CONSTRAINT uq_seo_message_request",
                    "ALTER TABLE seo_content_messages DROP CONSTRAINT ck_seo_message_body",
                    "ALTER TABLE seo_content_messages DROP CONSTRAINT fk_seo_message_participant",
                    "ALTER TABLE seo_content_messages DISABLE TRIGGER trg_seo_messages_append_only",
                    "ALTER TABLE seo_content_messages DISABLE TRIGGER trg_seo_messages_no_truncate",
                ]
                for sql in changes:
                    savepoint = await session.begin_nested()
                    await session.execute(text(sql))
                    with pytest.raises(RuntimeError):
                        await _check_content_message_structure(conn, schema)
                    await savepoint.rollback()
                await _check_content_message_structure(conn, schema)
    asyncio.run(run())


@requires_pg
def test_inactive_site_allows_history_but_rejects_send_and_read_cursor():
    from app.models.module_workspace import SeoSite
    async def run():
        async with store() as sessions:
            first = await send(sessions, ADVISOR, "Before pause")
            async with sessions() as session:
                site = await session.get(SeoSite, 2)
                site.status = "inactive"
                await session.commit()
            assert (await meta(sessions))["allowed_actions"] == {"read":True,"send":False,"mark_read":False}
            assert len((await messages(sessions))["items"]) == 1
            for call in (send(sessions,CUSTOMER,"Paused"), read(sessions, first["message"]["id"])):
                with pytest.raises(HTTPException) as exc: await call
                assert exc.value.status_code == 409
    asyncio.run(run())


@pytest.mark.parametrize("body,extra", [(" ",{}),("x"*4001,{}),("\x00",{}),("valid",{"sender_user_id":99}),("valid",{"created_at":"2026-01-01"})])
def test_send_rejects_blank_oversized_or_forged_fields(body,extra):
    with pytest.raises(ValidationError): api.Send(tenant_id=4,site_id=2,request_id=uuid4(),body=body,**extra)
