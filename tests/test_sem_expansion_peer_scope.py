"""Separate peer identity from product scope; offline contracts, not model truth."""
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

RECORD = json.loads((Path(__file__).parent / 'fixtures/sem_expansion_peer_observed_20260903.json')
                    .read_text(encoding='utf-8'))


def item(subject='offering', scope=None, intent='information', **kwargs):
    evidence = basis('peer', intent)
    evidence.update(subject=subject, product_scope=scope)
    result = dict(word='测试产品', basis=evidence, relevance='relevant', recommend='watch',
                  reason='模拟依据', suggested_bid=3, bid_reason='模拟指导价')
    result.update(kwargs)
    return result


def product_scope(**kwargs):
    result = dict(relation='in_scope', field='business_desc', quote='汽车修补漆')
    result.update(kwargs)
    return result


def replay(deny_network, raw, customer=None):
    runner, guard = deny_network
    original = deepcopy(raw)
    chat = AsyncMock(return_value={'items': [raw]})
    guard.setattr(ev, 'chat_json', chat)
    verdict = runner.run(ev._evaluate_batch(customer or tenant(), [dict(word=raw['word'], recommend_price_pc=4)]))
    chat.assert_awaited_once()
    assert raw == original
    return verdict[raw['word']]


def test_exact_five_word_observation_is_not_rewritten():
    assert RECORD['source_commit'] == '2bcdda409060f6533664ae42e477f0fe9cd1ca93'
    assert RECORD['model'] == 'qwen-plus'
    assert RECORD['system_sha256'] == 'cf869ad78171d770a17c15862b4d10295f657b5740d07de61e5567f55da3906d'
    cases = {c['word']: c for c in FIXTURE['cases']}
    raw = json.loads(RECORD['model_output'])['items']
    assert len(raw) == len({r['word'] for r in raw}) == 5
    assert raw[-1]['word'] == '艾仕得水性漆'
    assert raw[-1]['relevance'] == 'relevant'
    assert raw[-1]['reason'] == '水性漆是否属同业务待确认'
    assert all('subject' not in r['basis'] and 'product_scope' not in r['basis'] for r in raw)
    assert sum([r['relevance'], r['recommend']] in cases[r['word']]['allowed_pairs']
               for r in raw if cases[r['word']]['allowed_pairs'] is not None) == 4
    customer = tenant(**FIXTURE['profile'])
    prompt = ev._build_user_prompt(customer, [{'word': r['word']} for r in raw])
    assert hashlib.sha256(prompt.encode()).hexdigest() == RECORD['user_sha256']
    assert hashlib.sha256(ev.SYSTEM_PROMPT.encode()).hexdigest() != RECORD['system_sha256']


def test_historical_replay_fails_closed_without_filling_in_peer_scope(deny_network):
    runner, guard = deny_network
    raw = json.loads(RECORD['model_output'])
    original = deepcopy(raw)
    chat = AsyncMock(return_value=raw)
    guard.setattr(ev, 'chat_json', chat)
    result = runner.run(ev._evaluate_batch(tenant(**FIXTURE['profile']),
                        [{'word': r['word']} for r in raw['items']]))
    chat.assert_awaited_once()
    assert raw == original and len(result) == 5
    assert result[raw['items'][0]['word']]['relevance'] == 'relevant'
    for row in raw['items'][1:]:
        verdict = result[row['word']]
        assert (verdict['relevance'], verdict['recommend']) == ('generic', 'watch')
        assert '待人工确认' in verdict['reason']
        assert verdict['suggested_bid'] is None and verdict['bid_reason'] is None


@pytest.mark.parametrize('scope', [None, {}, [], True, 'in_scope',
    product_scope(relation='unknown'), product_scope(relation='out_of_scope'),
    product_scope(relation=[]), product_scope(field='name'), product_scope(field=[]),
    product_scope(quote='未提供的业务'), product_scope(quote=''), product_scope(quote='汽')])
@pytest.mark.parametrize('recommend', ['watch', 'drop', 'adopt'])
def test_product_peer_requires_independent_scope_fields_and_real_quote(deny_network, scope, recommend):
    verdict = replay(deny_network, item(scope=scope, recommend=recommend))
    assert (verdict['relevance'], verdict['recommend']) == ('generic', 'watch')
    assert verdict['suggested_bid'] is None and verdict['bid_reason'] is None


@pytest.mark.parametrize('field,quote', [('business_desc', '汽车修补漆'), ('业务描述', '汽车修补漆'),
                                        ('industry', '涂料'), ('行业', '涂料')])
def test_valid_product_scope_preserves_watch_without_adopting(deny_network, field, quote):
    verdict = replay(deny_network, item(scope=product_scope(field=field, quote=quote), intent='comparison'))
    assert (verdict['relevance'], verdict['recommend']) == ('relevant', 'watch')
    assert verdict['suggested_bid'] == 3


@pytest.mark.parametrize('intent,recommend', [('information', 'watch'), ('information', 'drop'), ('navigation', 'drop')])
def test_entity_query_can_remain_related_without_inventing_product_scope(deny_network, intent, recommend):
    verdict = replay(deny_network, item(subject='entity', intent=intent, recommend=recommend))
    assert (verdict['relevance'], verdict['recommend']) == ('relevant', recommend)


@pytest.mark.parametrize('raw', [item(subject='entity', intent='purchase'),
    item(subject='entity', intent='comparison'), item(subject='entity', intent='unknown'),
    item(subject='entity', scope=product_scope(relation='unknown')),
    item(subject='entity', scope=product_scope()), item(subject=[]), item(subject=None),
    item(subject='invented'), item(scope=product_scope(), recommend='adopt')])
def test_subject_conflicts_and_peer_adoption_are_rejected(deny_network, raw):
    verdict = replay(deny_network, raw)
    assert (verdict['relevance'], verdict['recommend']) == ('generic', 'watch')
    assert verdict['suggested_bid'] is None


def test_unknown_scope_does_not_change_customer_or_manual_candidate_data(deny_network):
    runner, guard = deny_network
    guard.setattr(ev, 'is_enabled', lambda: True)
    raw = item(scope=product_scope(relation='unknown'))
    guard.setattr(ev, 'chat_json', AsyncMock(return_value={'items': [raw]}))
    customer = tenant()
    before = ev._business_profile(customer)
    row = KeywordCandidate(id=1, tenant_id=3, word=raw['word'], source='planner', status='pending',
                           recommend_price_pc=4, preset_price=2)
    session = SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [row])), commit=AsyncMock())
    runner.run(ev.evaluate_candidates_for_tenant(session, customer, limit=5))
    assert row.ai_relevance == 'generic' and row.ai_recommend == 'watch'
    assert row.ai_suggested_bid is None and row.preset_price == 2 and row.status == 'pending'
    assert ev._business_profile(customer) == before


def test_schema_cannot_prove_model_subject_or_citation_semantics():
    # Remaining counterexamples are explicit: no semantic-certification claim.
    assert ev._basis_consistent(tenant(), item(word='边界产品', subject='entity'))
    assert ev._basis_consistent(tenant(), item(word='边界产品', scope=product_scope()))
    assert not ev._basis_consistent(tenant(), item(scope=product_scope(relation='unknown')))
