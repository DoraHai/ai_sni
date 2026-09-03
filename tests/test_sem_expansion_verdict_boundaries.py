"""Real-output regressions and synthetic contracts; no model-quality claims."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.test_sem_expansion_acceptance import FIXTURE, deny_network
from tests.test_sem_expansion_business_profile import tenant, basis
from app.ai import expansion_eval as ev
from app.models import KeywordCandidate

RECORD = json.loads((Path(__file__).parent / 'fixtures/sem_expansion_boundaries_observed_20260903.json')
                    .read_text(encoding='utf-8'))


def observed():
    return json.loads(RECORD['model_output'])['items']


def replay(deny_network, rows, customer=None, guide=None):
    runner, guard = deny_network
    original = deepcopy(rows)
    mock = AsyncMock(return_value={'items': rows})
    guard.setattr(ev, 'chat_json', mock)
    result = runner.run(ev._evaluate_batch(customer or tenant(**FIXTURE['profile']),
        [dict(word=r['word'], recommend_price_pc=guide) for r in rows]))
    mock.assert_awaited_once()
    assert rows == original
    return result


def test_observation_provenance_and_original_labels_are_preserved():
    assert set(RECORD) == {'source_commit', 'model', 'observed_at', 'system_sha256', 'user_sha256', 'model_output'}
    assert RECORD['source_commit'] == '35b23179adb155249a5c1fb7a1442c9f215480d2'
    assert RECORD['model'] == 'qwen-plus'
    assert RECORD['observed_at'] == '2026-09-03T14:22:41.020452+00:00'
    assert RECORD['system_sha256'] == '5630901a509429ee891f5934e0b0e2915b9764cd53f6be51b6a90918533caee8'
    rows = observed()
    assert len(rows) == len({r['word'] for r in rows}) == 5
    assert rows[1]['basis']['product_scope']['relation'] == 'unknown'
    assert rows[1]['relevance'] == 'relevant'
    assert rows[3]['basis']['relation'] == rows[3]['relevance'] == 'generic'
    assert rows[3]['recommend'] == 'drop'
    assert rows[4]['basis']['product_scope']['relation'] == 'out_of_scope'
    cases = {c['word']: c for c in FIXTURE['cases'] if c['allowed_pairs'] is not None}
    assert sum([r['relevance'], r['recommend']] in cases[r['word']]['allowed_pairs']
               for r in rows if r['word'] in cases) == 3
    prompt = ev._build_user_prompt(tenant(**FIXTURE['profile']), [dict(word=r['word']) for r in rows])
    assert hashlib.sha256(prompt.encode()).hexdigest() == RECORD['user_sha256']
    assert hashlib.sha256(ev.SYSTEM_PROMPT.encode()).hexdigest() != RECORD['system_sha256']


def test_real_replay_blocks_generic_drop_without_inventing_positive_scope(deny_network):
    rows = observed()
    result = replay(deny_network, rows)
    assert len(result) == 5
    for index in (1, 3, 4):
        value = result[rows[index]['word']]
        assert (value['relevance'], value['recommend']) == ('generic', 'watch')
        assert '待人工确认' in value['reason']
    for index in (0, 2):
        value = result[rows[index]['word']]
        assert (value['relevance'], value['recommend']) == (rows[index]['relevance'], rows[index]['recommend'])
    assert all(v['suggested_bid'] is None and v['bid_reason'] is None for v in result.values())
    cases = {c['word']: c for c in FIXTURE['cases'] if c['allowed_pairs'] is not None}
    # No claim that changing the prompt retroactively improves the old output.
    assert sum([v['relevance'], v['recommend']] in cases[word]['allowed_pairs']
               for word, v in result.items() if word in cases) == 2


@pytest.mark.parametrize('word', ['设备', '宠物猫粮批发', '未知产品', '已知同行替代品'])
@pytest.mark.parametrize('relation', ['generic', 'unknown', 'out_of_scope'])
@pytest.mark.parametrize('recommend', ['drop', 'adopt'])
def test_unverified_negative_cannot_switch_relation_to_bypass_review(deny_network, word, relation, recommend):
    row = dict(word=word, basis=basis(relation, 'unknown', field=None, quote=None),
               relevance='generic', recommend=recommend, reason='模拟判定', suggested_bid=3, bid_reason='模拟报价')
    value = replay(deny_network, [row], guide=4)[word]
    assert value == dict(relevance='generic', recommend='watch', reason='业务依据不足或结论冲突，待人工确认',
                         suggested_bid=None, bid_reason=None)


@pytest.mark.parametrize('guide', [None, 4])
def test_synthetic_category_evidence_preserves_peer_watch_not_adoption(deny_network, guide):
    # Synthetic adapter case, NOT a corrected/recorded model answer.
    row = dict(word='模拟同行粉末涂料替代',
        basis=basis('peer', 'comparison', field='business_desc', quote='艾仕得、阿克苏诺贝尔是同行竞品，不是自有品牌。'),
        relevance='relevant', recommend='watch', reason='类别相关，适配与投放策略待确认',
        suggested_bid=3, bid_reason='模拟指导价')
    row['basis']['product_scope'] = dict(relation='in_scope', field='business_desc', quote='主要推广粉末涂料')
    value = replay(deny_network, [row], guide=guide)[row['word']]
    assert (value['relevance'], value['recommend']) == ('relevant', 'watch')
    assert value['suggested_bid'] == (3 if guide is not None else None)
    # Another customer's profile cannot borrow this evidence.
    other = tenant(id=4, industry='水泵', business_desc='仅经营水泵')
    value = replay(deny_network, [row], customer=other, guide=guide)[row['word']]
    assert (value['relevance'], value['recommend'], value['suggested_bid']) == ('generic', 'watch', None)


def test_real_generic_drop_downgrade_preserves_manual_data_and_customer(deny_network):
    runner, guard = deny_network
    customer = tenant(**FIXTURE['profile'])
    before = ev._business_profile(customer)
    row = observed()[3]
    candidate = KeywordCandidate(id=1, tenant_id=customer.id, word=row['word'], source='planner',
        status='pending', preset_price=2, recommend_price_pc=4, ai_suggested_bid=3, ai_bid_reason='旧理由')
    session = SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [candidate])), commit=AsyncMock())
    guard.setattr(ev, 'is_enabled', lambda: True)
    mock = AsyncMock(return_value={'items': [row]})
    guard.setattr(ev, 'chat_json', mock)
    result = runner.run(ev.evaluate_candidates_for_tenant(session, customer, limit=5))
    mock.assert_awaited_once()
    assert result['successful_words'] == 1
    assert candidate.ai_relevance == 'generic' and candidate.ai_recommend == 'watch'
    assert candidate.ai_suggested_bid is None and candidate.ai_bid_reason is None
    assert candidate.preset_price == 2 and candidate.status == 'pending'
    assert ev._business_profile(customer) == before


def test_prompt_distinguishes_category_from_suitability_without_brand_patches():
    for clause in ('product_scope 只判断前者', '不要求已证明具体型号可替代',
                   '不得据此把 product_scope 改成 unknown', '不能仅因同一品牌或行业大类就判 in_scope',
                   '有明确产品或', '不得为了通过应用校验将 out_of_scope 改报 generic',
                   'generic 结论仅允许 generic/watch'):
        assert clause in ev.SYSTEM_PROMPT
    for row in observed():
        assert row['word'] not in ev.SYSTEM_PROMPT


def test_positive_semantic_misclassification_remains_a_documented_limit():
    # A real citation still cannot certify the keyword/category relationship.
    row = dict(word='未知跨行业产品', relevance='relevant', recommend='adopt', basis=basis())
    assert ev._basis_consistent(tenant(), row)
