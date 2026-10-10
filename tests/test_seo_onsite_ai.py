"""Proposal boundary and safe-state tests; no supplier or database calls."""
import json

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app import seo_onsite_ai as ai
from app.api import seo_onsite_ai as api
from app.api_controls import ControlDenied


def facts():
    return {"domain": "example.com", "allowed_urls": ["https://example.com/p"],
        "source_refs": ["fact:1:v1"], "items": [{"id": "title-1", "kind": "title",
        "target_url": "https://example.com/p", "expected": "", "instruction": "人工填写"}]}


def result():
    return {"items": [{**facts()["items"][0], "expected": "公开资料标题", "reason": "依据资料",
        "source_refs": ["fact:1:v1"], "missing_information": []}]}


@pytest.mark.parametrize("change", [
    {"id": "new-item"}, {"kind": "description"}, {"target_url": "https://example.com/unbound"},
    {"source_refs": ["fact:999:v1"]}, {"source_refs": []},
    {"missing_information": ["参数待补"]}, {"expected": ""}, {"unknown": "unexpected"},
    {"expected": "访问 https://evil.example/"}, {"instruction": "API_KEY=sk-abcdefghijklmnop"},
    {"missing_information": ["x" * 501]},
])
def test_untrusted_result_cannot_expand_scope_or_invent_provenance(change):
    raw = result()
    raw["items"][0].update(change)
    with pytest.raises((ValueError, HTTPException)):
        ai.validate_result(raw, facts())


def test_missing_facts_remain_explicit_and_item_contract_is_unchanged():
    raw = result()
    raw["items"][0].update(expected="", source_refs=[], missing_information=["型号适用范围待补"])
    items, reasons = ai.validate_result(raw, facts())
    assert set(items[0]) == {"id", "kind", "target_url", "expected", "instruction"}
    assert reasons[0]["missing_information"] == ["型号适用范围待补"]


def test_canonical_cannot_choose_even_same_host_unbound_page():
    f, raw = facts(), result()
    f["items"][0]["kind"] = raw["items"][0]["kind"] = "canonical"
    raw["items"][0]["expected"] = "https://example.com/unknown"
    with pytest.raises(ValueError): ai.validate_result(raw, f)


def test_provider_admission_rejects_unapproved_route_without_call(monkeypatch):
    monkeypatch.setattr(ai.deepseek, "_resolve_creds", lambda: ("dummy", "https://evil.example/v1", "model"))
    with pytest.raises(HTTPException) as exc: ai.provider_route()
    assert exc.value.status_code == 503


def test_capabilities_daily_limit_and_safe_error_classification(monkeypatch):
    monkeypatch.setattr(ai.deepseek, "_resolve_creds", lambda: ("dummy", "https://api.deepseek.com", "deepseek-chat"))
    w = {"phase": "draft", "history": []}
    assert ai.capabilities(w, True)["ai_planning"]["can_generate"]
    assert not ai.capabilities(w, False)["ai_planning"]["can_generate"]
    assert ai.capabilities(w, True)["website_execution"]["enabled"] is False
    settings = {}
    for _ in range(5): settings = ai.reserve(settings)
    with pytest.raises(HTTPException) as exc: ai.reserve(settings)
    assert exc.value.status_code == 429
    assert not ai.capabilities(w, True, settings)["ai_planning"]["can_generate"]
    state, error = api.failed_state(TimeoutError("secret raw provider body"))
    assert state == "unknown" and "secret" not in json.dumps(error)
    assert api.failed_state(ControlDenied("secret"))[0] == "failed"
    response = httpx.Response(503, request=httpx.Request("POST", "https://api.deepseek.com"))
    assert api.failed_state(httpx.HTTPStatusError("private", request=response.request, response=response))[0] == "failed"


def test_advisor_pagination_filters_live_authorization_in_sql():
    query = api.advisor_query(7).order_by(api.SeoTask.id.desc()).limit(21)
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    for fragment in ("seo_site_advisor_assignments.active IS true", "users.is_active IS true",
        "users.tenant_id IS NULL", "tenant_modules.expires_at", "seo_sites.status = 'active'",
        "roles.permissions", "onsite_optimization", "LIMIT 21"):
        assert fragment in sql
    assert sql.index("WHERE") < sql.index("LIMIT 21")
