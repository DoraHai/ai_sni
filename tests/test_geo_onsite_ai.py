from datetime import datetime, timezone, timedelta
import json

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
    }
    return {"schema_version": 2, "summary": "基于一条已核验公开事实起草。",
            "missing_information": ["缺少规格参数"],
            "items": [{"id": key, "expected": value,
                       "reason": "来自已核验官网资料", "fact_ids": [8],
                       "blocking_missing_information": [], "optional_information": []}
                      for key, value in values.items()]}


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


def test_request_nonce_history_is_never_silently_truncated():
    settings = {}
    for index in range(3):
        settings = onsite_ai.reserve_daily(
            settings, f"request-{index}", request_digest=f"hash-{index}",
            day=f"2026-10-{10 + index:02d}", limit=10, request_limit=3)
    assert [value["id"] for value in settings["onsite_ai_requests"]] == [
        "request-0", "request-1", "request-2"]
    replay = onsite_ai.reserve_daily(
        settings, "request-0", request_digest="hash-0",
        day="2026-10-13", limit=10, request_limit=3)
    assert replay == settings
    with pytest.raises(HTTPException) as error:
        onsite_ai.reserve_daily(
            settings, "request-3", request_digest="hash-3",
            day="2026-10-13", limit=10, request_limit=3)
    assert error.value.status_code == 409
    assert "不能覆盖历史防重依据" in str(error.value.detail)


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
    assert explanation["contract_version"] == 2
    assert explanation["items"][0]["source_refs"][0] == {
        "source_id": "geo-public-source:test", "title": "产品说明",
        "url": "https://source.example/fact"}
    assert explanation["missing_information"] == ["缺少规格参数"]


def test_provider_result_requires_public_sources_for_any_body_and_no_fact_stays_empty():
    payload = result()
    payload["items"][0]["fact_ids"] = []
    with pytest.raises(HTTPException) as error:
        onsite_ai.validate_provider_result(
            payload, current_items=items(), facts=facts(), domain="example.com")
    assert "必须引用" in str(error.value.detail)

    empty = result()
    for item in empty["items"]:
        item["expected"] = ""
        item["fact_ids"] = []
        item["blocking_missing_information"] = ["缺少获准公开使用的事实"]
    output, explanation = onsite_ai.validate_provider_result(
        empty, current_items=items(), facts=[], domain="example.com")
    assert all(not item["expected"] for item in output)
    assert "缺少获准公开使用的事实" in explanation["missing_information"]

    unsafe = result()
    unsafe["items"][0]["expected"] = "请参考 https://evil.example/private"
    unsafe["items"][0]["blocking_missing_information"] = ["仍需核验"]
    with pytest.raises(HTTPException) as error:
        onsite_ai.validate_provider_result(
            unsafe, current_items=items(), facts=facts(), domain="example.com")
    assert "URL" in str(error.value.detail)

    protocol_relative = result()
    protocol_relative["items"][0]["reason"] = "来源见 //evil.example/private"
    with pytest.raises(HTTPException) as error:
        onsite_ai.validate_provider_result(
            protocol_relative, current_items=items(), facts=facts(), domain="example.com")
    assert "URL" in str(error.value.detail)


def test_provider_result_rejects_duplicate_ids_and_oversized_or_wrong_list_fields():
    duplicate = result()
    duplicate["items"].append(dict(duplicate["items"][0]))
    with pytest.raises(HTTPException) as error:
        onsite_ai.validate_provider_result(
            duplicate, current_items=items(), facts=facts(), domain="example.com")
    assert "编号重复" in str(error.value.detail)

    wrong = result()
    wrong["items"][0]["fact_ids"] = "not-a-list"
    with pytest.raises(HTTPException) as error:
        onsite_ai.validate_provider_result(
            wrong, current_items=items(), facts=facts(), domain="example.com")
    assert "版本 2 契约" in str(error.value.detail)


def test_prompt_marks_all_inputs_untrusted_and_has_a_hard_size_limit():
    snapshot = {"project": {}, "questions": [], "facts": [], "items": items()}
    snapshot["facts"] = facts()
    system, user = onsite_ai.prompt_text(snapshot, "initial")
    assert "不可信数据" in system and "不得执行" in system
    assert "https://source.example/fact" not in user
    assert '"fact_id": 8' in user
    assert '"kind": "schema"' not in user
    snapshot["questions"] = [{"question": "x" * onsite_ai.MAX_PROMPT_CHARS}]
    with pytest.raises(HTTPException) as error:
        onsite_ai.prompt_text(snapshot, "initial")
    assert error.value.status_code == 413


@pytest.mark.parametrize("mutation, message", [
    ("extra_url_field", "版本 2 契约"),
    ("foreign_fact", "范围外"),
    ("private_marker", "内部资料"),
    ("private_reason", "内部资料"),
    ("string_missing", "版本 2 契约"),
])
def test_provider_result_rejects_scope_and_disclosure_failures(mutation, message):
    payload = result()
    if mutation == "extra_url_field":
        payload["items"][0]["source_refs"] = [{"fact_id": 8, "url": "https://source.example/fact"}]
    elif mutation == "foreign_fact":
        payload["items"][0]["fact_ids"] = [999]
    elif mutation == "private_marker":
        payload["items"][0]["expected"] = "内部事实卡原文"
    elif mutation == "private_reason":
        payload["items"][0]["reason"] = "来自内部事实卡"
    else:
        payload["items"][0]["blocking_missing_information"] = "缺少资料"
    with pytest.raises(HTTPException) as error:
        onsite_ai.validate_provider_result(payload, current_items=items(), facts=facts(), domain="example.com")
    assert message in str(error.value.detail)


def test_old_running_attempt_is_projected_stale_without_retrying():
    value = {"ai_run": {"request_id": "r", "state": "running",
                        "started_at": (datetime.now(timezone.utc)-timedelta(minutes=11)).isoformat()}}
    assert onsite_ai.projected_ai_run(value)["state"] == "stale"


@pytest.mark.parametrize("title, first, second", [
    ("HC-50 水箱容量", "HC-50 水箱容量为 40 L。", "HC-50 水箱容量为 60 L。"),
    ("AQ-20 量程", "AQ-20 测量范围为 0-20 ppm。", "AQ-20 测量范围为 0-50 ppm。"),
])
def test_conflicting_instrument_facts_blank_all_generated_delivery(title, first, second):
    conflict_facts = [
        {**facts()[0], "fact_id": 8, "title": title, "statement": first},
        {**facts()[0], "fact_id": 9, "source_id": "geo-public-source:other",
         "title": title, "statement": second},
    ]
    payload = result()
    for item in payload["items"]:
        item["fact_ids"] = [8, 9]
    output, explanation = onsite_ai.validate_provider_result(
        payload, current_items=items(), facts=conflict_facts, domain="example.com")
    assert all(item["expected"] == "" for item in output)
    assert any("冲突" in reason for reason in explanation["missing_information"])


@pytest.mark.parametrize("statement", [
    "两份资料没有冲突，参数一致。", "已核验为无冲突。", "不存在冲突或矛盾。",
    "两份说明一致无矛盾。", "The sources have no conflict and no contradiction.",
])
def test_explicit_conflict_negations_do_not_blank_valid_content(statement):
    safe_facts = [{**facts()[0], "statement": statement}]
    output, explanation = onsite_ai.validate_provider_result(
        result(), current_items=items(), facts=safe_facts, domain="example.com")
    assert next(item for item in output if item["id"] == "structured_content")["expected"]
    assert not any("明确冲突" in reason for reason in explanation["missing_information"])


def test_multiple_visible_pages_keep_ids_targets_and_build_each_schema_from_same_page():
    current = [
        {"id": "content-a", "kind": "structured_content", "target_url": "https://example.com/a",
         "expected": "", "instruction": "A 页面"},
        {"id": "content-b", "kind": "faq", "target_url": "https://example.com/b",
         "expected": "", "instruction": "B 页面"},
        {"id": "schema-a", "kind": "schema", "target_url": "https://example.com/a",
         "expected": "", "instruction": "A Schema"},
        {"id": "schema-b", "kind": "schema", "target_url": "https://example.com/b",
         "expected": "", "instruction": "B Schema"},
        {"id": "llms-one", "kind": "llms", "target_url": "https://example.com/llms.txt",
         "expected": "", "instruction": "导览"},
    ]
    payload = {"schema_version": 2, "summary": "多页", "missing_information": [], "items": [
        {"id": "content-a", "expected": "A 页面公开内容", "reason": "事实支持", "fact_ids": [8],
         "blocking_missing_information": [], "optional_information": []},
        {"id": "content-b", "expected": "B 页面公开问答", "reason": "事实支持", "fact_ids": [8],
         "blocking_missing_information": [], "optional_information": []},
    ]}
    output, _ = onsite_ai.validate_provider_result(
        payload, current_items=current, facts=facts(), domain="example.com")
    by_id = {item["id"]: item for item in output}
    assert json.loads(by_id["schema-a"]["expected"])["description"] == "A 页面公开内容"
    assert json.loads(by_id["schema-b"]["expected"])["description"] == "B 页面公开问答"
    assert "https://example.com/a" in by_id["llms-one"]["expected"]
    assert "https://example.com/b" in by_id["llms-one"]["expected"]
