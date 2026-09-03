"""Offline evidence contracts. Passing these does not prove model semantics."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.test_sem_expansion_business_profile import tenant, basis
from tests.test_sem_expansion_acceptance import deny_network  # reusable fail-closed fixture
from app.ai import expansion_eval as ev
from app.models import KeywordCandidate


def verdict(**changes):
    item = dict(word="同行资料", relevance="relevant", recommend="watch", reason="同行业务资料",
                suggested_bid=3, bid_reason="参考指导价", basis=basis("peer", "information"))
    item.update(changes)
    return item


def replay(deny_network, item, customer=None):
    runner, guard = deny_network
    original = deepcopy(item)
    chat = AsyncMock(return_value={"items": [item]})
    guard.setattr(ev, "chat_json", chat)
    result = runner.run(ev._evaluate_batch(customer or tenant(), [dict(word=item["word"], recommend_price_pc=4)]))
    chat.assert_awaited_once()
    assert item == original
    return result[item["word"]]


@pytest.mark.parametrize("evidence", [None, [], "text", True, {},
    basis(relation=[]), basis(intent={}), basis(field=[]), basis(quote=[]),
    basis(relation="unknown"), basis(relation="invented"), basis(intent="invented"),
    basis(field="profile_summary"), basis(field="name"), basis(quote="客户没写过这句话"),
    basis(quote=""), basis(quote=" "), basis(quote="汽"), basis(quote="x" * 501)])
def test_invalid_or_unknown_basis_cannot_adopt_drop_or_quote(deny_network, evidence):
    result = replay(deny_network, verdict(relevance="irrelevant", recommend="drop", basis=evidence))
    assert result == dict(relevance="generic", recommend="watch",
                          reason="业务依据不足或结论冲突，待人工确认", suggested_bid=None, bid_reason=None)


@pytest.mark.parametrize("changes", [
    dict(relevance="irrelevant", recommend="drop"),
    dict(recommend="adopt", basis=basis("peer", "comparison")),
    dict(recommend="adopt", basis=basis("in_scope", "information")),
    dict(recommend="watch", basis=basis("peer", "navigation")),
    dict(recommend="adopt", basis=basis("out_of_scope")),
    dict(relevance="generic", recommend="adopt", basis=basis("generic", field=None, quote=None)),
])
def test_contradictory_verdicts_go_to_review_not_auto_corrected_positive(deny_network, changes):
    result = replay(deny_network, verdict(**changes))
    assert (result["relevance"], result["recommend"], result["suggested_bid"]) == ("generic", "watch", None)


@pytest.mark.parametrize("relation,intent,rel,rec,price", [
    ("peer", "navigation", "relevant", "drop", None),
    ("peer", "information", "relevant", "watch", 3),
    ("peer", "comparison", "relevant", "watch", 3),
    ("in_scope", "purchase", "relevant", "adopt", 3),
    ("in_scope", "comparison", "relevant", "adopt", 3),
    ("generic", "unknown", "generic", "watch", None),
])
def test_consistent_structured_verdicts_remain_distinct(deny_network, relation, intent, rel, rec, price):
    evidence = basis(relation, intent)
    if relation == "generic":
        evidence.update(field=None, quote=None)
    result = replay(deny_network, verdict(relevance=rel, recommend=rec, basis=evidence))
    assert (result["relevance"], result["recommend"], result["suggested_bid"]) == (rel, rec, price)


def test_evidence_is_tenant_local_not_candidate_text_or_ai_summary(deny_network):
    customer = tenant(id=4, industry="泵阀", business_desc="只做泵阀", profile_summary="汽车修补漆")
    result = replay(deny_network, verdict(word="汽车修补漆", basis=basis()), customer)
    assert result["relevance"] == "generic" and result["suggested_bid"] is None


def test_real_quote_no_longer_certifies_a_negative_scope_assertion(deny_network):
    result = replay(deny_network, verdict(relevance="irrelevant", recommend="drop",
                                         basis=basis("out_of_scope")))
    assert result["relevance"] == "generic" and result["recommend"] == "watch"


def test_review_result_never_changes_candidate_status_or_manual_price(deny_network):
    runner, guard = deny_network
    guard.setattr(ev, "is_enabled", lambda: True)
    guard.setattr(ev, "chat_json", AsyncMock(return_value={"items": [verdict(basis=basis("unknown"))]}))
    row = KeywordCandidate(id=1, tenant_id=3, word="同行资料", source="planner", status="pending", preset_price=4)
    session = SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [row])), commit=AsyncMock())
    runner.run(ev.evaluate_candidates_for_tenant(session, tenant(), limit=20))
    assert row.status == "pending" and row.preset_price == 4
    assert row.ai_recommend == "watch" and row.ai_suggested_bid is None
    assert "待人工确认" in row.ai_reason


def test_new_contract_is_in_prompt_so_old_context_fingerprints_change():
    assert "basis.relation" in ev.SYSTEM_PROMPT
    assert "引用存在不等于支持结论" in ev.SYSTEM_PROMPT
    assert "unknown/generic 的 field、quote 为 null" in ev.SYSTEM_PROMPT
