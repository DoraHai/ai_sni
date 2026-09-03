"""Historical wire-response replay, not another live model evaluation."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from tests.test_sem_expansion_acceptance import FIXTURE, deny_network
from tests.test_sem_expansion_business_profile import tenant, basis
from app.ai import expansion_eval as ev


RECORD = json.loads((Path(__file__).parent / "fixtures/sem_expansion_basis_observed_20260903.json")
                    .read_text(encoding="utf-8"))


def test_observation_is_unchanged_raw_model_text_not_expected_answers():
    assert RECORD["source_commit"] == "894e51ee0a8cbf66840874284850f0b707ff4656"
    assert RECORD["model"] == "qwen-plus"
    assert RECORD["system_sha256"] == "6c268938e240be9479ab0dd09b4bc881e701e24b44ef69a6e9778d5169ab673c"
    items = json.loads(RECORD["model_output"])["items"]
    cases = {c["word"]: c for c in FIXTURE["cases"]}
    assert len(items) == len({i["word"] for i in items}) == 20
    assert {i["word"] for i in items} == set(cases)
    scored = [i for i in items if cases[i["word"]]["allowed_pairs"] is not None]
    assert len(scored) == 17
    assert all([i["relevance"], i["recommend"]] in cases[i["word"]]["allowed_pairs"] for i in scored)
    assert all(i["basis"]["field"] in ("业务描述", "行业", None) for i in items)
    # English input keys intentionally change the wire hash, not the profile data.
    prompt = ev._build_user_prompt(tenant(**FIXTURE["profile"]), [{"word": c["word"]} for c in FIXTURE["cases"]])
    assert hashlib.sha256(prompt.encode()).hexdigest() != RECORD["user_sha256"]


def test_real_chinese_fields_work_without_certifying_scope_exclusions(deny_network):
    runner, guard = deny_network
    response = json.loads(RECORD["model_output"])
    original = deepcopy(response)
    mock = AsyncMock(return_value=response)
    guard.setattr(ev, "chat_json", mock)
    words = [{"word": c["word"]} for c in FIXTURE["cases"]]
    result = runner.run(ev._evaluate_batch(tenant(**FIXTURE["profile"]), words))
    mock.assert_awaited_once()
    assert response == original and len(result) == 20
    accepted, review = [], []
    for item, case in zip(response["items"], FIXTURE["cases"]):
        assert item["word"] == case["word"]
        processed = result[item["word"]]
        assert processed["suggested_bid"] is None and processed["bid_reason"] is None
        if case["group"] in ("competitor", "information", "unrelated", "boundary", "noise"):
            assert processed["relevance"] == "generic" and processed["recommend"] == "watch"
            assert "待人工确认" in processed["reason"]
            review.append(case["id"])
        else:
            assert (processed["relevance"], processed["recommend"]) == (item["relevance"], item["recommend"])
            accepted.append(case["id"])
    # Historical peers have no subject/product_scope; do not retrofit evidence.
    # Generic/drop is no longer an alternate path around scope review.
    assert len(accepted) == 4 and len(review) == 16
    # Do not change the gold draft to hide lost automatic negative discrimination.
    assert sum([result[c["word"]]["relevance"], result[c["word"]]["recommend"]] in c["allowed_pairs"]
               for c in FIXTURE["cases"] if c["allowed_pairs"] is not None) == 7


@pytest.mark.parametrize("field,quote", [
    ("industry", "涂料"), ("行业", "涂料"),
    ("business_desc", "汽车修补漆"), ("业务描述", "汽车修补漆"),
])
def test_only_explicit_aliases_map_to_same_customer_field(field, quote):
    item = dict(relevance="relevant", recommend="watch", basis=basis(field=field, quote=quote))
    before = deepcopy(item)
    assert ev._basis_consistent(tenant(), item)
    assert item == before
    other = tenant(id=4, industry="水泵", business_desc="只经营水泵")
    assert not ev._basis_consistent(other, item)


@pytest.mark.parametrize("field", ["business", "profile_summary", "name", "客户", "行业 ",
                                   "Industry", "__dict__", [], {}, None])
def test_alias_compatibility_does_not_widen_field_access(field):
    assert not ev._basis_consistent(tenant(), dict(relevance="relevant", recommend="watch",
                                                   basis=basis(field=field)))


@pytest.mark.parametrize("field", ["industry", "行业", "business_desc", "业务描述"])
@pytest.mark.parametrize("quote", ["涂料", "汽车修补漆", "不经营家装涂料"])
def test_scope_exclusion_is_review_even_with_real_or_explicit_negative_text(field, quote):
    # No NLP phrase matching: quoted exclusion text is still a model-selected
    # assertion, not a reviewed mapping between this keyword and that exclusion.
    item = dict(relevance="irrelevant", recommend="drop", basis=basis("out_of_scope", field=field, quote=quote))
    assert not ev._basis_consistent(tenant(), item)


@pytest.mark.parametrize("quote", ["另一客户的涂料", "（未填写，不推断）", "候选词专用文本"])
def test_chinese_alias_still_requires_real_quote_not_placeholder_or_candidate(quote):
    item = dict(relevance="relevant", recommend="watch", basis=basis(field="业务描述", quote=quote))
    assert not ev._basis_consistent(tenant(), item)


def test_positive_quote_still_is_not_semantic_truth():
    # Remaining limitation: a model may invent an in_scope relation while quoting
    # real text; aliases and the negative-scope gate cannot prove semantic truth.
    item = dict(word="猫粮", relevance="relevant", recommend="adopt", basis=basis())
    assert ev._basis_consistent(tenant(), item)
