"""Existing assist, quota and durable operation exercised with a fake provider."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from test_seo_content_workflow import Store, trigger
from app import seo_content_drafting as drafts, seo_content_workflow as flow, seo_ai_operations as ops
from app.api import seo as api
from app.models.module_workspace import TenantModule, SeoSite
from app.models.tenant import Tenant
from app.models.user import User
from app.models.role import Role
from app.models.seo import SeoAiOperation, SeoKeywordAsset, SeoSiteAdvisorAssignment, SeoContentAsset, SeoContentConfirmation, SeoContentPublication
from app.models.seo_cockpit import SeoTask
from app.models.seo_qa import SeoQaFact
from app.security.auth import AuthContext

ADVISOR = AuthContext(7, "advisor", "advisor", None,
    {"seo.content": "edit", "seo.site": "edit", "seo.keywords": "edit"})
RESULT = {"title": "选型依据", "outline": "已提供的选型资料", "content": "选型以官网资料为依据。[F30]"}


@pytest.fixture
def store(tmp_path, monkeypatch):
    store = Store(tmp_path / "drafts.sqlite")
    with store.engine.begin() as conn:
        for model in (Tenant, User, Role, SeoKeywordAsset, SeoQaFact, SeoAiOperation):
            conn.execute(CreateTable(model.__table__, include_foreign_key_constraints=[]))
    with Session(store.engine) as db:
        db.add(Tenant(id=4, name="isolated"))
        db.add(Role(id=5, name="advisor", permissions=ADVISOR.permissions))
        db.add(User(id=7, username="advisor", password_hash="unused", role_id=5, is_active=True))
        db.add(SeoKeywordAsset(id=20, tenant_id=4, site_id=2, keyword="选型", status="active"))
        db.add(SeoQaFact(id=30, tenant_id=4, site_id=2, title="选型资料", statement="选型以官网资料为依据。",
            source_name="人工核对的官网资料", source_url="https://example.com/facts", status="active", version=1))
        db.commit()
    for module in (drafts, flow, ops):
        monkeypatch.setattr(module, "async_session_factory", store.session)
    monkeypatch.setattr(api, "is_enabled", lambda: True)
    store.settings = SimpleNamespace(seo_ai_max_requests_per_tenant_per_day=5,
        deepseek_api_key="isolated-deepseek", deepseek_base_url="https://api.deepseek.com",
        deepseek_model="deepseek-chat", dashscope_api_key="isolated-dashscope", dashscope_model="qwen-test")
    monkeypatch.setattr(api, "get_settings", lambda: store.settings)
    store.provider = AsyncMock(return_value=RESULT)
    monkeypatch.setattr(api, "chat_json", store.provider)
    yield store
    store.engine.dispose()


def enable(store):
    store.edit_plan(content_ai_enabled=True, content_ai_authorized_by=7,
        content_ai_fact_ids=[30], content_ai_keyword_ids=[20])


def run(store):
    asyncio.run(drafts.execute_content_draft(store.task().id))


def edit(store, model, ident, **fields):
    with Session(store.engine) as db:
        row = db.get(model, ident)
        for key, value in fields.items():
            setattr(row, key, value)
        db.commit()


def content(store):
    with Session(store.engine) as db:
        return db.get(SeoContentAsset, store.task().params["content_id"])


def test_default_off_and_existing_manual_body_never_call_provider(store):
    trigger(store)
    run(store)
    assert not store.task().params.get("ai_draft")
    enable(store)
    edit(store, SeoContentAsset, content(store).id, draft="顾问已编写的正文")
    run(store)
    store.provider.assert_not_awaited()
    assert content(store).draft == "顾问已编写的正文"


def test_actual_assist_operation_quota_and_scheduler_save_only_one_draft(store):
    enable(store)
    store.edit_plan(content_cycle_enabled=True)
    asyncio.run(flow.process_site(2))
    for _ in range(3):
        asyncio.run(flow.process_site(2))
    row, task = content(store), store.task()
    assert row.status == "drafting" and row.version_count == 2
    assert row.draft == RESULT["content"] and row.keyword_ids == [20]
    assert row.reviewed_at is None and row.review_submitted_at is None
    assert task.status == "in_progress" and task.params["phase"] == "awaiting_internal_review"
    assert task.params["ai_draft"]["generated_by"] == "system"
    assert task.params["ai_draft"]["authorized_by"] == 7
    store.provider.assert_awaited_once()
    with Session(store.engine) as db:
        operation = db.scalar(select(SeoAiOperation))
        assert operation.status == "succeeded" and operation.actor == "7"
        assert db.get(TenantModule, 1).module_settings["seo_daily_usage"]["ai_requests"] == 1
        assert db.scalar(select(func.count()).select_from(SeoContentConfirmation)) == 0
        assert db.scalar(select(func.count()).select_from(SeoContentPublication)) == 0
    prompt = store.provider.call_args.args
    assert "[F编号]" in prompt[1] and "人工核对的官网资料" in prompt[1]


@pytest.mark.parametrize("model,ident,fields,reason", [
    (SeoQaFact, 30, {"status": "inactive"}, "ai_draft_material_missing_or_expired"),
    (SeoQaFact, 30, {"site_id": 99}, "ai_draft_material_missing_or_expired"),
    (SeoQaFact, 30, {"tenant_id": 9}, "ai_draft_material_missing_or_expired"),
    (SeoQaFact, 30, {"expires_at": datetime.now(timezone.utc) - timedelta(days=1)}, "ai_draft_material_missing_or_expired"),
    (SeoQaFact, 30, {"source_name": " "}, "ai_draft_material_provenance_required"),
    (SeoKeywordAsset, 20, {"site_id": None}, "ai_draft_keywords_missing_or_inactive"),
    (SeoKeywordAsset, 20, {"status": "inactive"}, "ai_draft_keywords_missing_or_inactive"),
    (SeoSiteAdvisorAssignment, 3, {"active": False}, "ai_draft_authorization_revoked"),
    (User, 7, {"is_active": False}, "ai_draft_authorization_revoked"),
    (User, 7, {"tenant_id": 9}, "ai_draft_authorization_revoked"),
    (Role, 5, {"permissions": {"seo.content": "view", "seo.site": "edit", "seo.keywords": "view"}}, "ai_draft_authorization_revoked"),
])
def test_invalid_sources_or_authorization_handoff_before_ai(store, model, ident, fields, reason):
    enable(store)
    trigger(store)
    edit(store, model, ident, **fields)
    run(store)
    assert store.task().params["ai_draft"]["reason"] == reason
    assert not content(store).draft
    run(store)
    store.provider.assert_not_awaited()


@pytest.mark.parametrize("change,reason", [
    ("plan", "ai_draft_plan_changed"), ("disabled", "ai_draft_disabled"),
    ("fact", "ai_draft_material_changed"), ("keyword", "ai_draft_material_changed"),
    ("content", "ai_draft_content_changed"), ("revoked", "ai_draft_authorization_revoked"),
    ("paused", "service_plan_paused"), ("module", "site_or_module_not_operational"),
    ("role", "ai_draft_authorization_revoked"),
])
def test_changes_while_supplier_running_do_not_overwrite_or_confirm(store, change, reason):
    enable(store)
    trigger(store)
    async def provider(*args, **kwargs):
        if change == "plan": store.edit_plan(revision=2)
        elif change == "disabled": store.edit_plan(content_ai_enabled=False)
        elif change == "fact": edit(store, SeoQaFact, 30, statement="更新后的资料", version=2)
        elif change == "keyword": edit(store, SeoKeywordAsset, 20, keyword="安装")
        elif change == "content": edit(store, SeoContentAsset, content(store).id, title="人工改题", version_count=2)
        elif change == "revoked": edit(store, SeoSiteAdvisorAssignment, 3, active=False)
        elif change == "paused": store.edit_plan(status="paused")
        elif change == "module": edit(store, TenantModule, 1, status="paused")
        elif change == "role": edit(store, Role, 5, permissions={})
        return RESULT
    store.provider.side_effect = provider
    run(store)
    assert store.task().params["ai_draft"]["reason"] == reason
    assert not content(store).draft
    store.provider.assert_awaited_once()


@pytest.mark.parametrize("body", ["选型缺少出处", "选型未知资料[F99]", "选型参数待补充[F30]"])
def test_insufficient_or_unknown_citation_stays_with_advisor(store, body):
    enable(store)
    trigger(store)
    store.provider.return_value = {**RESULT, "content": body}
    run(store)
    assert store.task().params["ai_draft"]["reason"] == "ai_draft_quality_review_required"
    assert store.task().params["ai_draft"]["quality_checks"]
    assert not content(store).draft
    run(store)
    store.provider.assert_awaited_once()


def test_provider_failure_refunds_and_never_automatically_retries(store):
    enable(store)
    trigger(store)
    store.provider.side_effect = RuntimeError("isolated error")
    run(store)
    run(store)
    store.provider.assert_awaited_once()
    assert store.task().params["ai_draft"]["reason"] == "ai_draft_generation_failed"
    with Session(store.engine) as db:
        assert db.scalar(select(SeoAiOperation)).status == "refunded"
        assert db.get(TenantModule, 1).module_settings["seo_daily_usage"]["ai_requests"] == 0


def test_quota_does_not_call_supplier(store, monkeypatch):
    enable(store)
    trigger(store)
    from app.seo_usage_limits import charge_seo_usage
    async def consume():
        async with store.session() as session:
            await charge_seo_usage(session, 4, "ai_requests", 1, 1)
    asyncio.run(consume())
    store.settings.seo_ai_max_requests_per_tenant_per_day = 1
    run(store)
    assert store.task().params["ai_draft"]["reason"] == "ai_draft_quota_exceeded"
    store.provider.assert_not_awaited()


def test_missing_provider_does_not_charge(store, monkeypatch):
    enable(store)
    trigger(store)
    store.settings.deepseek_api_key = ""
    run(store)
    assert store.task().params["ai_draft"]["reason"] == "ai_draft_deepseek_not_configured"
    store.provider.assert_not_awaited()
    with Session(store.engine) as db:
        assert db.scalar(select(func.count()).select_from(SeoAiOperation)) == 0


def test_restart_replays_committed_operation_without_second_provider_call(store, monkeypatch):
    enable(store)
    trigger(store)
    persist = drafts.persist_result
    monkeypatch.setattr(drafts, "persist_result", AsyncMock(side_effect=RuntimeError("simulated crash after settlement")))
    with pytest.raises(RuntimeError): run(store)
    assert store.task().params["ai_draft"]["status"] == "claimed" and not content(store).draft
    monkeypatch.setattr(drafts, "persist_result", persist)
    run(store)
    assert content(store).status == "drafting"
    store.provider.assert_awaited_once()


def test_restart_before_operation_claim_stops_after_timeout(store, monkeypatch):
    enable(store)
    trigger(store)
    monkeypatch.setattr(api, "_assist_seo_content", AsyncMock(side_effect=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError): run(store)
    task = store.task()
    ai = {**task.params["ai_draft"], "claimed_at": (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()}
    edit(store, SeoTask, task.id, params={**task.params, "ai_draft": ai})
    run(store)
    assert store.task().params["ai_draft"]["reason"] == "ai_draft_outcome_unknown"
    store.provider.assert_not_awaited()


def test_second_worker_running_and_cancellation_never_attach_stale_result(store):
    enable(store)
    trigger(store)
    async def provider(*args, **kwargs):
        await drafts.execute_content_draft(store.task().id)
        edit(store, SeoTask, store.task().id, status="cancelled")
        return RESULT
    store.provider.side_effect = provider
    run(store)
    assert store.task().status == "cancelled" and not content(store).draft
    store.provider.assert_awaited_once()


def update_plan(store, actor=ADVISOR, **values):
    async def update():
        async with store.session() as session:
            return await api.update_seo_service_plan(api.SeoServicePlanUpdate(
                tenant_id=4, site_id=2, expected_revision=values.pop("expected_revision", 1),
                optimization_directions=["资料优先"], content_topics=["选型"], **values), session, actor)
    return asyncio.run(update())


def test_plan_opt_in_sources_and_old_client_preservation(store):
    result = update_plan(store, content_ai_enabled=True, content_ai_fact_ids=[30], content_ai_keyword_ids=[20])
    assert result["content_ai_authorized_by"] == 7 and result["content_ai_authorized_at"]
    updated = update_plan(store, expected_revision=2)
    assert updated["content_ai_enabled"] and updated["content_ai_fact_ids"] == [30]
    assert updated["content_ai_authorized_at"] == result["content_ai_authorized_at"]
    with pytest.raises(HTTPException) as exc:
        update_plan(store, expected_revision=3, content_ai_fact_ids=[])
    assert exc.value.detail["code"] == "ai_draft_explicit_enable_required"
    update_plan(store, expected_revision=3, content_ai_enabled=False)


@pytest.mark.parametrize("fields,reason", [
    ({"content_ai_enabled": True}, "ai_draft_material_and_keywords_required"),
    ({"content_ai_enabled": True, "content_ai_fact_ids": [99], "content_ai_keyword_ids": [20]}, "ai_draft_material_missing_or_expired"),
])
def test_plan_rejects_unusable_material_without_changes(store, fields, reason):
    with pytest.raises(HTTPException) as exc:
        update_plan(store, **fields)
    assert exc.value.detail["code"] == reason
    with Session(store.engine) as db:
        assert db.get(SeoSite, 2).site_settings["seo_service_plan"]["revision"] == 1


def test_trigger_capabilities_independent_of_plan_edit_read_only(store):
    async def read(actor=ADVISOR):
        async with store.session() as session:
            return await api.get_seo_service_plan(4, 2, session, actor)
    first = asyncio.run(read())
    assert first["trigger_actions"]["content"]["allowed"]
    assert first["trigger_actions"]["monitoring"]["allowed"]
    assert first["content_ai_enabled"] is False
    trigger(store)
    later = asyncio.run(read())
    assert later["allowed_actions"]["update_service_plan"] is True
    assert later["trigger_actions"]["content"]["reason"] == "content_workflow_already_active"
    assert later["trigger_actions"]["website"]["allowed"] is True
    no_keywords = AuthContext(7, "advisor", "advisor", None, {"seo.content": "edit", "seo.site": "edit"})
    assert asyncio.run(read(no_keywords))["trigger_actions"]["monitoring"]["reason"] == "keyword_edit_permission_required"
    edit(store, SeoSiteAdvisorAssignment, 3, active=False)
    assert asyncio.run(read())["trigger_actions"]["website"]["reason"] == "active_site_advisor_assignment_required"
    store.provider.assert_not_awaited()
