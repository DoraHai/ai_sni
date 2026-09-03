"""Offline fixture/adapter contracts, NOT a live model-quality evaluation."""
import asyncio
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import socket
from unittest.mock import AsyncMock

import pytest

# Reuse the existing offline settings bootstrap and non-persisted tenant factory.
from tests.test_sem_expansion_business_profile import tenant
from app.ai import expansion_eval as ev


FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "sem_expansion_acceptance_v1.json")
    .read_text(encoding="utf-8")
)
CASES = FIXTURE["cases"]
SCORED = [case for case in CASES if case["review"] == "scored_draft"]


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
    assert profile["业务描述"] == FIXTURE["profile"]["business_desc"]
    assert profile["品牌词根"] == []
    assert "尚未确认" in profile["业务描述"]
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
        fake = AsyncMock(return_value={"items": [{
            "word": case["word"], "relevance": relevance, "recommend": recommend,
            "reason": "模拟模型返回，仅测试解析和出价保护",
            "suggested_bid": 3.0, "bid_reason": "模拟价格，不用于投放",
        }]})
        guard.setattr(ev, "chat_json", fake)
        result = runner.run(ev._evaluate_batch(customer, words))
        fake.assert_awaited_once()
        assert set(result) == {case["word"]}
        verdict = result[case["word"]]
        assert (verdict["relevance"], verdict["recommend"]) == (relevance, recommend)
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
