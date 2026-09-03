"""Offline fixture/adapter contracts, NOT a live model-quality evaluation."""
import asyncio
from collections import Counter
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import socket
from unittest.mock import AsyncMock

import pytest

# Reuse the existing offline settings bootstrap and non-persisted tenant factory.
from tests.test_sem_expansion_business_profile import tenant, basis
from app.ai import expansion_eval as ev
from app.api.expansion import _candidate_payload
from app.models import KeywordCandidate


FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "sem_expansion_acceptance_v1.json")
    .read_text(encoding="utf-8")
)
CASES = FIXTURE["cases"]
SCORED = [case for case in CASES if case["review"] == "scored_draft"]
OBSERVED = json.loads(
    (Path(__file__).parent / "fixtures" / "sem_expansion_qwen_observed_20260903.json")
    .read_text(encoding="utf-8")
)


@pytest.fixture(autouse=True)
def deny_network():
    def fail(*args, **kwargs):
        raise AssertionError("Offline acceptance must not access the network")

    # Windows creates a loopback socket pair for event-loop wakeups. Initialize
    # that infrastructure before blocking every connection made by test code.
    originals = (ev.chat_json, socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo)
    with asyncio.Runner() as runner:
        runner.get_loop()
        with pytest.MonkeyPatch.context() as guard:
            guard.setattr(socket.socket, "connect", fail)
            guard.setattr(socket.socket, "connect_ex", fail)
            guard.setattr(socket, "getaddrinfo", fail)
            guard.setattr(ev, "chat_json", AsyncMock(side_effect=fail))
            # All overrides must use this same scope. A second, outer fixture
            # could otherwise restore our blocker *after* this scope exits.
            yield runner, guard
        assert (ev.chat_json, socket.socket.connect, socket.socket.connect_ex,
                socket.getaddrinfo) == originals


def test_network_and_unmocked_model_calls_are_denied(deny_network):
    runner, _ = deny_network
    with socket.socket() as connection:
        with pytest.raises(AssertionError, match="Offline acceptance"):
            connection.connect(("127.0.0.1", 9))
    with pytest.raises(AssertionError, match="Offline acceptance"):
        runner.run(ev.chat_json("test", "test"))


def test_fixture_is_diverse_draft_not_production_data_or_observed_predictions():
    assert FIXTURE["schema_version"] == 1
    assert FIXTURE["review_status"] == "draft_requires_business_review"
    assert len(CASES) == len({c["id"] for c in CASES}) == len({c["word"] for c in CASES}) == 20
    assert Counter(c["group"] for c in CASES) == {
        "purchase": 4, "competitor": 4, "information": 3,
        "noise": 3, "unrelated": 3, "boundary": 3,
    }
    assert set(FIXTURE["profile"]) == {"name", "industry", "business_desc", "brand_terms"}
    for case in CASES:
        assert set(case) == {"id", "group", "word", "review", "allowed_pairs", "rationale"}
        assert case["word"] == case["word"].strip() and case["word"]
        assert case["rationale"]
        if case["group"] == "boundary":
            assert case["review"] == "business_confirmation_required"
            assert case["allowed_pairs"] is None
        else:
            assert case["review"] == "scored_draft"
            assert case["allowed_pairs"]
            for pair in case["allowed_pairs"]:
                assert len(pair) == 2 and ev._valid(*pair)
                if case["group"] != "purchase":
                    assert pair[1] != "adopt"


def test_all_related_baseline_cannot_satisfy_draft_expectations():
    # This checks discrimination in the reference set, not an actual model score.
    failures = [c["id"] for c in SCORED
                if all(pair[0] != "relevant" for pair in c["allowed_pairs"])]
    assert len(SCORED) == 17
    assert set(failures) == {c["id"] for c in CASES if c["group"] in {"noise", "unrelated"}}
    assert len(failures) == 6


def test_prompt_contains_only_profile_and_words_not_reference_answers():
    customer = tenant(**FIXTURE["profile"])
    prompt = ev._build_user_prompt(customer, [{"word": c["word"]} for c in CASES])
    profile = json.loads(prompt.splitlines()[1])
    assert profile["business_desc"] == FIXTURE["profile"]["business_desc"]
    assert profile["品牌词根"] == []
    assert "尚未确认" in profile["business_desc"]
    for case in CASES:
        assert f"- {case['word']}" in prompt.splitlines()
        assert case["rationale"] not in prompt
    assert "allowed_pairs" not in prompt and "scored_draft" not in prompt
    assert "business_confirmation_required" not in prompt


@pytest.mark.parametrize("guide", [None, 4.0], ids=["no-provider-guide", "synthetic-guide"])
@pytest.mark.parametrize("case", SCORED, ids=lambda c: c["id"])
def test_reference_verdicts_exercise_real_adapter_bid_safety(deny_network, case, guide):
    # Deliberately mock the model; do not claim it independently chose these labels.
    runner, guard = deny_network
    customer = tenant(**FIXTURE["profile"])
    before_profile = ev._business_profile(customer)
    words = [{"word": case["word"], "recommend_price_pc": guide}]
    before_words = deepcopy(words)
    # Exercise every allowed pair, including relevant/drop and generic/watch.
    for relevance, recommend in case["allowed_pairs"]:
        # Synthetic evidence tests structural consistency, not entailment. An
        # actual industry quote alone cannot prove out_of_scope for a given word.
        relation = {"relevant": "in_scope", "generic": "generic", "irrelevant": "out_of_scope"}[relevance]
        evidence = basis(relation=relation, quote=customer.industry, field="industry")
        if relation == "generic":
            evidence.update(field=None, quote=None)
        fake = AsyncMock(return_value={"items": [{
            "word": case["word"], "relevance": relevance, "recommend": recommend,
            "basis": evidence,
            "reason": "模拟模型返回，仅测试解析和出价保护",
            "suggested_bid": 3.0, "bid_reason": "模拟价格，不用于投放",
        }]})
        guard.setattr(ev, "chat_json", fake)
        result = runner.run(ev._evaluate_batch(customer, words))
        fake.assert_awaited_once()
        assert set(result) == {case["word"]}
        verdict = result[case["word"]]
        expected = ("generic", "watch") if relation == "out_of_scope" else (relevance, recommend)
        assert (verdict["relevance"], verdict["recommend"]) == expected
        allow_bid = guide is not None and relevance == "relevant" and recommend in {"adopt", "watch"}
        assert verdict["suggested_bid"] == (3.0 if allow_bid else None)
        assert (verdict["bid_reason"] is not None) == allow_bid
    assert words == before_words
    assert ev._business_profile(customer) == before_profile


def test_boundary_cases_remain_unscored_and_have_no_reference_prices():
    boundary = [c for c in CASES if c["group"] == "boundary"]
    assert {c["word"] for c in boundary} == {"艾仕得水性漆", "汽车修补漆", "家装乳胶漆"}
    assert all(c["allowed_pairs"] is None for c in boundary)
    assert all("suggested_bid" not in c for c in CASES)


def test_historical_observation_is_complete_and_separate_from_reference_labels():
    assert OBSERVED["kind"] == "historical_observation_not_expected_answers"
    observed = {item["word"]: item for item in OBSERVED["items"]}
    assert len(observed) == len(OBSERVED["items"]) == 20
    assert set(observed) == {c["word"] for c in CASES}
    deviations = []
    for case in SCORED:
        item = observed[case["word"]]
        if [item["relevance"], item["recommend"]] not in case["allowed_pairs"]:
            deviations.append(case["id"])
    # Historical 13/17 against a DRAFT, not a quality pass for this new prompt.
    assert deviations == ["competitor-03", "information-01", "information-02", "information-03"]
    assert sum(item["suggested_bid"] is not None for item in observed.values()) == 4
    assert all(c["allowed_pairs"] is None for c in CASES if c["group"] == "boundary")


def test_input_fields_are_canonical_but_historical_profile_values_are_unchanged():
    prompt = ev._build_user_prompt(tenant(**FIXTURE["profile"]), [{"word": c["word"]} for c in CASES])
    lines = prompt.splitlines()
    canonical = json.loads(lines[1])
    assert "industry" in canonical and "business_desc" in canonical
    assert "行业" not in canonical and "业务描述" not in canonical
    aliases = {"industry": "行业", "business_desc": "业务描述"}
    # Reconstruct only the OLD wire keys for provenance, never for a model call.
    lines[1] = json.dumps({aliases.get(k, k): v for k, v in canonical.items()}, ensure_ascii=False)
    assert hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest() == OBSERVED["user_prompt_sha256"]
    assert hashlib.sha256(prompt.encode("utf-8")).hexdigest() != OBSERVED["user_prompt_sha256"]
    assert hashlib.sha256(ev.SYSTEM_PROMPT.encode("utf-8")).hexdigest() != OBSERVED["system_prompt_sha256"]
    for item in OBSERVED["items"]:
        assert item["reason"] not in prompt
        if item["bid_reason"]:
            assert item["bid_reason"] not in prompt


def test_legacy_response_without_evidence_is_review_not_a_quality_pass(deny_network):
    runner, guard = deny_network
    customer = tenant(**FIXTURE["profile"])
    words = [{"word": c["word"]} for c in CASES]
    original = deepcopy(OBSERVED)
    fake = AsyncMock(return_value={"items": deepcopy(OBSERVED["items"])})
    guard.setattr(ev, "chat_json", fake)
    verdicts = runner.run(ev._evaluate_batch(customer, words))
    fake.assert_awaited_once_with(ev.SYSTEM_PROMPT, ev._build_user_prompt(customer, words),
                                  timeout=ev.MODEL_TIMEOUT_SECONDS)
    assert len(verdicts) == 20
    for raw in OBSERVED["items"]:
        verdict = verdicts[raw["word"]]
        assert verdict["suggested_bid"] is None and verdict["bid_reason"] is None
        # Old response schema is NOT accepted silently, for positives or negatives.
        # All-review is safety fallback, not semantic accuracy improvement.
        assert (verdict["relevance"], verdict["recommend"]) == ("generic", "watch")
        assert "待人工确认" in verdict["reason"]
    assert OBSERVED == original


def test_cached_observed_quotes_are_hidden_by_api_without_changing_manual_presets():
    fingerprint = ev.context_fingerprint(tenant(**FIXTURE["profile"]))
    for raw in OBSERVED["items"]:
        row = KeywordCandidate(
            id=1, tenant_id=3, word=raw["word"], source="planner", status="pending",
            preset_price=2, ai_relevance=raw["relevance"], ai_recommend=raw["recommend"],
            ai_reason=raw["reason"], ai_suggested_bid=raw["suggested_bid"],
            ai_bid_reason=raw["bid_reason"], ai_evaluated_at=datetime(2026, 9, 3),
            raw={ev.EVALUATION_META_KEY: {"context_hash": fingerprint}},
        )
        payload = _candidate_payload(row, fingerprint)
        assert payload["ai_freshness"] == "current"  # not merely stale-price suppression
        assert payload["ai_suggested_bid"] is None and payload["ai_bid_reason"] is None
        assert payload["preset_price"] == 2
        assert row.ai_suggested_bid == raw["suggested_bid"] and row.status == "pending"


@pytest.mark.parametrize("rule", [
    "主营不等于唯一经营范围，未提及不等于明确排除",
    "相邻产品是否经营尚未确认时用 generic/watch",
    "不能因投放策略未知抹去已确认的业务相关性",
    "已知同行的官网导航用 relevant/drop",
    "不得仅因出现“替代”就给 adopt",
    "缺指导价时 suggested_bid=null 且 bid_reason=null",
    "未提供的搜索量、竞争度、指导价和转化表现均为未知",
    "adopt 只是运营建议，不是投放许可",
])
def test_prompt_preserves_reviewed_decision_policy(rule):
    # Text-policy contract only; cannot assert that a real model obeys it.
    assert rule in ev.SYSTEM_PROMPT
    assert "艾仕得" not in ev.SYSTEM_PROMPT and "阿克苏诺贝尔" not in ev.SYSTEM_PROMPT
    assert "suggested_bid\": null" in ev.SYSTEM_PROMPT
