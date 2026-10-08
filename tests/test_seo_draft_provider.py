"""Explicit SEO draft routing over an in-memory HTTP transport, never the network."""
import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from test_seo_content_drafting import store, enable, run, content, update_plan, RESULT, ADVISOR
from test_seo_content_workflow import trigger
from app.api import seo as api
from app.ai import deepseek
from app import seo_content_drafting as drafts
from app.models.seo import SeoAiOperation
from app.models.module_workspace import TenantModule


def transport(store, monkeypatch, *, failure=False, repair=False, response_model="default"):
    requests = []
    store.settings.dashscope_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    original = httpx.AsyncClient
    def respond(request):
        requests.append(request)
        if failure: return httpx.Response(502, json={"error": "isolated failure"})
        body = {"content": "invalid initial result"} if repair and len(requests) == 1 else RESULT
        model = f"deepseek-response-version-{len(requests)}" if response_model == "default" else response_model
        return httpx.Response(200, json={"model": model,
            "choices": [{"message": {"content": json.dumps(body, ensure_ascii=False)}}]})
    mocked_transport = httpx.MockTransport(respond)
    monkeypatch.setattr(deepseek.httpx, "AsyncClient", lambda **kwargs: original(transport=mocked_transport, **kwargs))
    monkeypatch.setattr(deepseek, "get_settings", lambda: store.settings)
    monkeypatch.setattr(api, "chat_json", deepseek.chat_json)
    return requests


@pytest.mark.parametrize("repair", [False, True])
def test_explicit_deepseek_wins_over_dashscope_and_records_actual_response_model(store, monkeypatch, repair):
    enable(store)
    store.edit_plan(content_ai_provider="deepseek", content_ai_model="deepseek-reasoner")
    trigger(store)
    requests = transport(store, monkeypatch, repair=repair)
    run(store)
    assert len(requests) == (2 if repair else 1)
    for request in requests:
        assert request.url.host == "api.deepseek.com"
        assert request.headers["Authorization"] == "Bearer isolated-deepseek"
        assert json.loads(request.content)["model"] == "deepseek-reasoner"
    state = store.task().params["ai_draft"]
    assert state["status"] == "succeeded" and state["provider"] == "deepseek"
    assert state["model"] == "deepseek-reasoner"
    assert state["response_model"] == f"deepseek-response-version-{len(requests)}"
    assert content(store).status == "drafting"
    with Session(store.engine) as db:
        op = db.scalar(select(SeoAiOperation))
        assert op.result["response_model"] == state["response_model"]
        assert db.get(TenantModule, 1).module_settings["seo_daily_usage"]["ai_requests"] == 1
    run(store)
    assert len(requests) == (2 if repair else 1)


def test_supplier_failure_never_falls_back_to_dashscope_and_refunds(store, monkeypatch):
    enable(store)
    trigger(store)
    requests = transport(store, monkeypatch, failure=True)
    run(store)
    run(store)
    assert len(requests) == 1 and requests[0].url.host == "api.deepseek.com"
    assert store.task().params["ai_draft"]["status"] == "needs_attention"
    with Session(store.engine) as db:
        assert db.scalar(select(SeoAiOperation)).status == "refunded"
        assert db.get(TenantModule, 1).module_settings["seo_daily_usage"]["ai_requests"] == 0


@pytest.mark.parametrize("model", ["qwen-unexpected", None])
def test_actual_model_mismatch_is_rejected_and_missing_model_stays_unknown(store, monkeypatch, model):
    enable(store)
    trigger(store)
    requests = transport(store, monkeypatch, response_model=model)
    run(store)
    run(store)
    assert len(requests) == 1
    state = store.task().params["ai_draft"]
    if model:
        assert state["reason"] == "ai_draft_provider_model_mismatch"
        assert not content(store).draft
    else:
        assert state["status"] == "succeeded"
        assert state["response_model"] is None
        assert state["model"] == "deepseek-chat"


@pytest.mark.parametrize("base", ["https://dashscope.aliyuncs.com/compatible-mode/v1", "http://api.deepseek.com", "https://user:secret@api.deepseek.com", "https://[invalid"])
def test_non_deepseek_endpoint_is_not_mislabeled_or_called(store, base):
    enable(store)
    trigger(store)
    store.settings.deepseek_base_url = base
    run(store)
    assert store.task().params["ai_draft"]["reason"] == "ai_draft_deepseek_route_invalid"
    store.provider.assert_not_awaited()


def test_legacy_public_assist_keeps_global_routing_and_request_fingerprint(store, monkeypatch):
    requests = transport(store, monkeypatch)
    req = api.SeoContentAssistRequest(tenant_id=4, site_id=2, request_id="legacy-assist-test-key", action="generate", keyword_ids=[20])
    assert api._seo_assist_request_payload(req) == req.model_dump(mode="json", exclude={"request_id"})
    async def invoke():
        async with store.session() as session: return await api.assist_seo_content(req, session, ADVISOR)
    asyncio.run(invoke())
    assert len(requests) == 1 and requests[0].url.host == "dashscope.aliyuncs.com"
    assert json.loads(requests[0].content)["model"] == "qwen-test"


def test_unattributed_cached_result_is_not_adopted_or_regenerated(store, monkeypatch):
    enable(store)
    trigger(store)
    original = drafts.persist_result
    monkeypatch.setattr(drafts, "persist_result", AsyncMock(side_effect=RuntimeError("interrupted")))
    with pytest.raises(RuntimeError): run(store)
    with Session(store.engine) as db:
        op = db.scalar(select(SeoAiOperation))
        op.result = {k: v for k, v in op.result.items() if k not in {"provider", "generation_route"}}
        db.commit()
    monkeypatch.setattr(drafts, "persist_result", original)
    run(store)
    assert store.task().params["ai_draft"]["reason"] == "ai_draft_provider_evidence_missing"
    assert not content(store).draft
    store.provider.assert_awaited_once()


def test_model_change_requires_explicit_opt_in_and_old_client_preserves_model(store):
    from fastapi import HTTPException
    update_plan(store, content_ai_enabled=True, content_ai_fact_ids=[30], content_ai_keyword_ids=[20])
    with pytest.raises(HTTPException) as exc:
        update_plan(store, expected_revision=2, content_ai_model="deepseek-reasoner")
    assert exc.value.detail["code"] == "ai_draft_explicit_enable_required"
    changed = update_plan(store, expected_revision=2, content_ai_enabled=True, content_ai_model="deepseek-reasoner")
    assert changed["content_ai_model"] == "deepseek-reasoner"
    preserved = update_plan(store, expected_revision=3)
    assert preserved["content_ai_model"] == "deepseek-reasoner"
    store.provider.assert_not_awaited()
