"""Owned PostgreSQL proves project isolation, revisions and duplicate-request locking."""
import asyncio
from uuid import uuid4
import os
import pytest
from fastapi import HTTPException
from sqlalchemy import select, func
from test_geo_project_scope_postgres import database
from app.geo import onsite_routes as api
from app.geo.project_workflows import save_plan
from app.models import GeoActionTicket
from app.security.auth import AuthContext
from types import SimpleNamespace

pytestmark = pytest.mark.skipif(not os.getenv("GEO_TEST_POSTGRES_URL"), reason="requires dedicated PostgreSQL")
ADVISOR = AuthContext(7, "advisor", "advisor", None, {"geo.assets":"edit", "geo.content":"edit"})
CUSTOMER = AuthContext(12, "customer", "customer", 1, {"geo.assets":"view", "geo.content":"view"})

async def configured(sessions):
    async with sessions() as db:
        await save_plan(db, 1, 10, dict(enabled=False, status="active", prompt_ids=[], interval_days=7, advisor_user_id=7), 0, 7)
        await db.commit()

def test_project_task_is_idempotent_and_scope_or_legacy_writes_cannot_complete_it():
    async def run():
        async with database() as sessions:
            await configured(sessions)
            req=api.Create(tenant_id=1, project_id=10, request_id=uuid4(), work_type="startup", owner_name="维护人员")
            async def create():
                async with sessions() as db:
                    return await api.create(req, db, ADVISOR)
            rows=await asyncio.gather(*(create() for _ in range(5)))
            assert len({r["id"] for r in rows})==1
            assert rows[0]["workflow"].get("content_task_id") is None
            async with sessions() as db:
                assert await db.scalar(select(func.count()).select_from(GeoActionTicket))==1
                with pytest.raises(HTTPException) as err:
                    await api.act(rows[0]["id"], api.Update(tenant_id=1, project_id=11, action="accept", expected_revision=1, note="越界"), db, ADVISOR)
                assert err.value.status_code in {403,404}
            async with sessions() as db:
                from app.geo.routes import patch_action_ticket, TicketUpdate
                with pytest.raises(HTTPException) as err:
                    await patch_action_ticket(rows[0]["id"], TicketUpdate(manual_pass=True, verification_note="绕过"), 1, ADVISOR, db)
                assert err.value.status_code==409
            async with sessions() as db:
                result=await api.list_tasks(1, 10, None, db, CUSTOMER)
                assert len(result["items"])==1 and result["items"][0]["allowed_actions"]==[]
            async with sessions() as db:
                result=await api.list_tasks(1, 11, None, db, CUSTOMER)
                assert result["items"]==[]
    asyncio.run(run())

def test_website_only_geo_delivery_has_no_article_or_ai_effect_gate_and_rejects_stale_writes(monkeypatch):
    async def fetch(url, **kwargs):
        assert kwargs["allowed_hosts"]==frozenset({"p10.example","www.p10.example"})
        return SimpleNamespace(final_url=url,html='# 官网知识\n真实问答\n<script type="application/ld+json">{"@type":"Organization","name":"真实客户"}</script>')
    monkeypatch.setattr(api,"safe_fetch",fetch)
    async def run():
        async with database() as sessions:
            await configured(sessions)
            async with sessions() as db:
                row=await api.create(api.Create(tenant_id=1,project_id=10,request_id=uuid4(),work_type="monthly",month="2026-10",owner_name="维护人员"),db,ADVISOR)
            items=[dict(i,expected='{"@type":"Organization","name":"真实客户"}' if i["kind"]=="schema" else '# 官网知识' if i["kind"]=="llms" else "真实问答") for i in row["workflow"]["items"]]
            async def act(row, action, **fields):
                async with sessions() as db:
                    return await api.act(row["id"],api.Update(tenant_id=1,project_id=10,action=action,
                        expected_revision=row["workflow"]["revision"],**fields),db,ADVISOR)
            old=row
            row=await act(row,"save_proposal",items=items)
            with pytest.raises(HTTPException) as err:
                await act(old,"save_proposal",items=items)
            assert err.value.status_code==409
            row=await act(row,"approve",note="事实、出处、适用条件已核对")
            row=await act(row,"implement",note="官网、知识库、FAQ、Schema 与文件已实施")
            row=await act(row,"recheck")
            assert row["workflow"]["phase"]=="acceptance"
            row=await act(row,"accept",note="人工核对页面事实与质量")
            assert row["workflow"]["phase"]=="done" and row["completion_evidence"]["recheck"]["passed"]
    asyncio.run(run())

