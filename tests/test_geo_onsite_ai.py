from datetime import datetime, timezone, timedelta

import pytest
from fastapi import HTTPException

from app.geo import onsite_ai


def items():
    base = "https://example.com/"
    return [
        {"id": "structured_content", "kind": "structured_content", "target_url": base,
         "expected": "", "instruction": "填写页面可见内容"},
        {"id": "knowledge", "kind": "knowledge", "target_url": base + "knowledge",
         "expected": "", "instruction": "填写公开知识内容"},
        {"id": "faq", "kind": "faq", "target_url": base + "faq",
         "expected": "", "instruction": "填写公开问答"},
        {"id": "schema", "kind": "schema", "target_url": base,
         "expected": "", "instruction": "填写 JSON-LD"},
        {"id": "llms", "kind": "llms", "target_url": base + "llms.txt",
         "expected": "", "instruction": "填写公开资料导览"},
    ]


def facts():
    return [{"fact_id": 8, "source_id": "geo-public-source:test",
             "title": "产品说明", "statement": "公开产品支持节能运行。",
             "source_name": "官网", "source_url": "https://source.example/fact",
             "updated_at": "2026-10-01T00:00:00", "expires_at": None}]


def result():
    values = {
        "structured_content": "示例品牌提供节能运行产品。",
        "knowledge": "示例品牌产品资料与适用范围。",
        "faq": "示例品牌产品是否支持节能运行？支持。",
        "schema": '{"@context":"https://schema.org","@type":"Product","name":"示例品牌产品","description":"支持节能运行"}',
        "llms": "# 示例品牌公开资料\n- [产品资料](https://example.com/knowledge)",
    }
    return {"summary": "基于一条已核验公开事实起草。", "missing_information": ["缺少规格参数"],
            "items": [{"id": key, "expected": value, "rationale": "来自已核验官网资料",
                       "source_refs": [{"fact_id": 8, "url": "https://source.example/fact"}],
                       "missing_information": []} for key, value in values.items()]}


def test_daily_quota_is_bounded_and_request_nonce_is_idempotent():
    settings = {"other": "kept"}
    settings = onsite_ai.reserve_daily(settings, "same", request_digest="a", day="2026-10-10", limit=2)
    again = onsite_ai.reserve_daily(settings, "same", request_digest="a", day="2026-10-10", limit=2)
    assert again["onsite_ai_quota"]["count"] == 1 and again["other"] == "kept"
    with pytest.raises(HTTPException) as conflict:
        onsite_ai.reserve_daily(settings, "same", request_digest="different", day="2026-10-10", limit=2)
    assert conflict.value.status_code == 409
    full = onsite_ai.reserve_daily(again, "second", request_digest="b", day="2026-10-10", limit=2)
    with pytest.raises(HTTPException) as error:
        onsite_ai.reserve_daily(full, "third", request_digest="c", day="2026-10-10", limit=2)
    assert error.value.status_code == 429
    reset = onsite_ai.reserve_daily(full, "next-day", request_digest="d", day="2026-10-11", limit=2)
    assert reset["onsite_ai_quota"]["count"] == 1


def test_capabilities_never_claim_website_execution():
    value = onsite_ai.capabilities(provider_ready=True, can_write=True, phase="draft")
    assert value["ai_planning"]["can_generate"] is True
    assert value["website_execution"] == {
        "enabled": False, "status": "reserved",
        "reason": "官网自动修改暂未接入，按批准方案人工实施",
    }


def test_fact_public_use_requires_explicit_human_authorization():
    assert not onsite_ai.public_use_authorized({"public_use": {"allowed": True}})
    assert not onsite_ai.public_use_authorized({"public_use": {
        "allowed": True, "authorized_by": 7}})
    assert onsite_ai.public_use_authorized({"public_use": {
        "allowed": True, "authorized_by": 7, "authorized_at": "2026-10-10T01:00:00Z"}})


def test_provider_result_keeps_explanations_outside_existing_items():
    output, explanation = onsite_ai.validate_provider_result(
        result(), current_items=items(), facts=facts(), domain="example.com")
    assert {item["id"] for item in output} == {item["id"] for item in items()}
    assert all(set(item) == {"id", "kind", "target_url", "expected", "instruction"} for item in output)
    assert explanation["items"][0]["source_refs"][0] == {
        "source_id": "geo-public-source:test", "title": "产品说明",
        "url": "https://source.example/fact"}
    assert explanation["missing_information"] == ["缺少规格参数"]


def test_provider_result_requires_public_sources_for_any_body_and_no_fact_stays_empty():
    payload = result()
    payload["items"][0]["source_refs"] = []
    with pytest.raises(HTTPException) as error:
        onsite_ai.validate_provider_result(
            payload, current_items=items(), facts=facts(), domain="example.com")
    assert "必须引用" in str(error.value.detail)

    empty = result()
    for item in empty["items"]:
        item["expected"] = ""
        item["source_refs"] = []
        item["missing_information"] = ["缺少获准公开使用的事实"]
    output, explanation = onsite_ai.validate_provider_result(
        empty, current_items=items(), facts=[], domain="example.com")
    assert all(not item["expected"] for item in output)
    assert "缺少获准公开使用的事实" in explanation["missing_information"]


def test_provider_result_rejects_duplicate_ids_and_oversized_or_wrong_list_fields():
    duplicate = result()
    duplicate["items"].append(dict(duplicate["items"][0]))
    with pytest.raises(HTTPException) as error:
        onsite_ai.validate_provider_result(
            duplicate, current_items=items(), facts=facts(), domain="example.com")
    assert "编号重复" in str(error.value.detail)

    wrong = result()
    wrong["items"][0]["source_refs"] = "not-a-list"
    with pytest.raises(HTTPException) as error:
        onsite_ai.validate_provider_result(
            wrong, current_items=items(), facts=facts(), domain="example.com")
    assert "来源引用格式" in str(error.value.detail)


def test_prompt_marks_all_inputs_untrusted_and_has_a_hard_size_limit():
    snapshot = {"project": {}, "questions": [], "facts": [], "items": items()}
    system, _ = onsite_ai.prompt_text(snapshot, "initial")
    assert "不可信数据" in system and "不得执行" in system
    snapshot["questions"] = [{"question": "x" * onsite_ai.MAX_PROMPT_CHARS}]
    with pytest.raises(HTTPException) as error:
        onsite_ai.prompt_text(snapshot, "initial")
    assert error.value.status_code == 413


@pytest.mark.parametrize("mutation, message", [
    ("foreign_llms", "当前网站"),
    ("foreign_fact", "范围外"),
    ("private_marker", "内部资料"),
    ("private_reason", "内部资料"),
    ("schema_mismatch", "可见内容"),
])
def test_provider_result_rejects_scope_and_disclosure_failures(mutation, message):
    payload = result()
    if mutation == "foreign_llms":
        next(i for i in payload["items"] if i["id"] == "llms")["expected"] = "# 公开资料\nhttps://evil.example/x"
    elif mutation == "foreign_fact":
        payload["items"][0]["source_refs"] = [{"fact_id": 999, "url": "https://source.example/fact"}]
    elif mutation == "private_marker":
        payload["items"][0]["expected"] = "内部事实卡原文"
    elif mutation == "private_reason":
        payload["items"][0]["rationale"] = "来自内部事实卡"
    else:
        next(i for i in payload["items"] if i["id"] == "schema")["expected"] = (
            '{"@type":"Product","name":"页面从未提及的型号"}')
    with pytest.raises(HTTPException) as error:
        onsite_ai.validate_provider_result(payload, current_items=items(), facts=facts(), domain="example.com")
    assert message in str(error.value.detail)


def test_old_running_attempt_is_projected_stale_without_retrying():
    value = {"ai_run": {"request_id": "r", "state": "running",
                        "started_at": (datetime.now(timezone.utc)-timedelta(minutes=11)).isoformat()}}
    assert onsite_ai.projected_ai_run(value)["state"] == "stale"
