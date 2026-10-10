"""Proposal boundary and safe-state tests; no supplier or database calls."""
import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app import seo_onsite_ai as ai
from app.api import seo_onsite_ai as api
from app.api_controls import ControlDenied


def facts():
    return {"domain": "example.com", "allowed_urls": ["https://example.com/p"],
        "source_refs": ["fact:1:v1"], "facts": [{"ref":"fact:1:v1","statement":"公开资料标题","source_url":"https://example.com/p"}], "items": [{"id": "title-1", "kind": "title",
        "target_url": "https://example.com/p", "expected": "", "instruction": "人工填写"}]}


def result():
    return {"items": [{**facts()["items"][0], "expected": "公开资料标题", "reason": "依据资料",
        "source_refs": ["fact:1:v1"], "missing_information": []}]}


@pytest.mark.parametrize("change", [
    {"id": "new-item"}, {"kind": "description"}, {"target_url": "https://example.com/unbound"},
    {"source_refs": ["fact:999:v1"]}, {"source_refs": []},
    {"unknown": "unexpected"},
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


OBSERVED = json.loads((Path(__file__).parent / "fixtures/seo_onsite_ai_observed.json").read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", OBSERVED, ids=lambda c: c["run"].split("20261010-")[-1] + ":" + c["name"])
def test_recorded_real_outputs_replay_offline_without_relaxing_scope(case):
    original = deepcopy(case["output"])
    items, reasons = ai.validate_result(original, case["input"])
    assert original == case["output"]  # preserve the original supplier evidence
    bound = {i["id"]: i for i in case["input"]["items"]}
    for item, reason in zip(items, reasons):
        assert (item["kind"], item["target_url"]) == (bound[item["id"]]["kind"], bound[item["id"]]["target_url"])
        if reason["missing_information"]:
            assert item["expected"] == ""
        if not item["expected"]:
            assert reason["missing_information"]
        if item["kind"] in {"internal_link", "canonical"} and item["expected"]:
            assert item["expected"] in case["input"]["allowed_urls"]
            if item["kind"] == "internal_link": assert item["expected"] != item["target_url"]
    if case["name"] in {"normal_a", "normal_b", "heldout_normal_a"}:
        assert all(i["expected"] for i in items if i["kind"] in {"title", "description"})
    if case["name"] == "heldout_conflict":
        for item, reason in zip(items,reasons):
            if item["kind"] in {"title", "description"}:
                assert item["expected"] == ""
                assert any("0 至 50 ppm" in m and "0 至 20 ppm" in m and "fact:4:v1" in m
                           for m in reason["missing_information"])


@pytest.mark.parametrize("suffix", ["，且该页已绑定。", "。请人工核对", "；正文需另核对", "（来源页面）", ")。", ".", "!", "，再比较（https://example.com/p）。"])
def test_chinese_and_markdown_url_prose_does_not_mutate_destination(suffix):
    raw = result()
    raw["items"][0]["reason"] = "依据 https://example.com/p" + suffix
    items,_=ai.validate_result(raw,facts())
    assert items[0]["expected"] == "公开资料标题"


@pytest.mark.parametrize("url", ["https://evil.example/p", "https://example.com/p/extra",
    "https://example.com/p?next=evil", "https://example.com/p#changed", "https://example.com/p%2fextra",
    "https://example.com.evil/p", "https://example.com@evil.example/p", "https://example.com/p恶意路径",
    "//evil.example/p", "HTTPS://EVIL.EXAMPLE/p"])
def test_external_and_modified_prose_urls_still_fail_even_with_missing_information(url):
    raw=result()
    raw["items"][0].update(reason="请参照 "+url+"，再处理",missing_information=["参数缺失"])
    with pytest.raises(ValueError,match="unbound URL"):
        ai.validate_result(raw,facts())


def link_fixture():
    f=facts()
    f.update(pages=[{"id":21,"url":"https://example.com/p","ref":"page:21"},
                    {"id":22,"url":"https://example.com/guide","ref":"page:22"}],
             allowed_urls=["https://example.com/p","https://example.com/guide"],
             source_refs=["page:21","page:22","fact:1:v1"])
    f["items"][0]["kind"]="internal_link"
    r=result()
    r["items"][0].update(kind="internal_link",expected="https://example.com/guide",source_refs=["page:21","page:22"])
    return f,r


@pytest.mark.parametrize("expected", ['<a href="https://example.com/guide">选型指南</a>',
    "[选型指南](https://example.com/guide)",
    "从 https://example.com/guide 指向 https://example.com/p 的链接", "链接到选型指南"])
def test_html_explanation_or_reversed_link_does_not_become_a_guessed_url(expected):
    f,r=link_fixture()
    r["items"][0]["expected"]=expected
    items,reasons=ai.validate_result(r,f)
    assert items[0]["expected"]=="" and reasons[0]["missing_information"]
    assert "不得反向修改目标页" in items[0]["instruction"]


def test_server_assembles_fixed_fields_and_destination_from_exact_bound_id():
    f,r=link_fixture()
    r["items"][0].pop("kind"); r["items"][0].pop("target_url")
    r["items"][0].update(expected="",destination_page_id=22,source_refs=[])
    items,reasons=ai.validate_result(r,f)
    assert items[0]["target_url"]=="https://example.com/p"
    assert items[0]["expected"]=="https://example.com/guide"
    assert reasons[0]["source_refs"]==["page:22"]
    assert ai.planning_input(f)["bound_pages"]==f["pages"]


@pytest.mark.parametrize("changes", [{"destination_page_id":99}, {"destination_page_id":22,"expected":"https://example.com/p"},
    {"destination_page_id":22,"expected":"https://evil.example/"}, {"source_refs":["guessed-source"]}])
def test_ids_do_not_hide_changed_urls_or_guess_sources(changes):
    f,r=link_fixture(); r["items"][0].update(changes)
    with pytest.raises(ValueError): ai.validate_result(r,f)


def test_blocking_missing_information_always_wins_and_is_never_removed():
    r=result(); r["items"][0]["missing_information"]=["型号参数待确认", "适用范围待确认"]
    items,reasons=ai.validate_result(r,facts())
    assert items[0]["expected"]==""
    assert reasons[0]["missing_information"]==["型号参数待确认", "适用范围待确认"]
    assert r["items"][0]["expected"]=="公开资料标题"


def test_empty_expected_with_no_explanation_reports_actual_missing_output():
    r=result(); r["items"][0]["expected"]=""
    items,reasons=ai.validate_result(r,facts())
    assert not items[0]["expected"]
    assert "尚未给出可核验的预期内容" in reasons[0]["missing_information"][0]


def test_no_material_cannot_promote_old_draft_to_a_fact():
    f,r=link_fixture(); f["facts"]=[]
    f["items"][0]["kind"]="description"
    r["items"][0].update(kind="description",expected="精度 0.01 ppm，获得认证",source_refs=["page:21"])
    items,reasons=ai.validate_result(r,f)
    assert items[0]["expected"]==""
    assert any("没有有效产品事实" in m for m in reasons[0]["missing_information"])
