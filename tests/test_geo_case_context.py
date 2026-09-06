import pytest

from app.geo.content.claim_guard import case_claims, format_ungrounded, ungrounded_claims
from app.geo.content.evidence_cite import build_sentence_citations


@pytest.mark.parametrize('sentence', [
    '暂无可核验的成功案例。', '目前尚未提供成功案例资料。', '请提供可核验的成功案例资料。',
    '请补充客户案例原文以供核验。', '建议核验成功案例资料。',
    '暂无成功案例，请提供成功案例资料。',
    '- 暂无可核验的成功案例。', '1. 请提供成功案例资料。',
])
def test_evidence_requests_do_not_assert_a_case(sentence):
    assert not case_claims(sentence, [])
    assert not any(row['needs_fact'] for row in build_sentence_citations(sentence, []))


@pytest.mark.parametrize('sentence', [
    '该产品已有成功案例。', '暂无资料，但已有某客户成功案例。',
    '请提供成功案例资料，该产品已有成功案例。', '请提供成功案例证明该产品拥有头部客户。',
    '请提供成功案例但我们已有成功案例。', '如果需要资料，我们已有成功案例。',
    '我们不缺成功案例。', '并非没有成功案例。', '成功案例证明该产品的效果。',
    '暂无失败记录，成功案例遍布全国。',
])
def test_real_and_mixed_assertions_remain_blocked(sentence):
    hits = case_claims(sentence, [])
    assert hits
    assert all(hit['excerpt'] == sentence for hit in hits)
    assert sentence in format_ungrounded(hits)


def test_keyword_in_fact_title_or_other_subject_does_not_prove_case():
    body = '乙产品已有成功案例。'
    assert case_claims(body, [{'title': '成功案例', 'statement': '甲产品支持冷却。'}])
    assert case_claims(body, [{'statement': '甲产品已有成功案例。'}])
    assert not case_claims(body, [{'statement': body}])


@pytest.mark.parametrize('source', ['该产品没有成功案例。', '如果完成验证，该产品才会成为成功案例。'])
def test_source_negation_and_condition_cannot_be_dropped(source):
    assert case_claims('该产品已有成功案例。', [{'statement': source}])
    assert not case_claims(source, [{'statement': source}])


def test_repeated_keyword_keeps_each_offending_sentence():
    body = '请提供成功案例。甲产品已有成功案例。乙产品已有成功案例。'
    hits = case_claims(body, [])
    assert [hit['excerpt'] for hit in hits] == ['甲产品已有成功案例。', '乙产品已有成功案例。']


def test_case_request_does_not_disable_number_guard():
    hits = ungrounded_claims('请提供成功案例资料，识别率达到99%。', [])
    assert any(hit['kind'] == 'number' for hit in hits)


def test_lint_preserves_long_sentence_instead_of_keyword_only():
    from app.geo.content.draft_lint import lint_draft
    sentence = '该产品' + '介绍文字' * 30 + '已有成功案例。'
    issue = next(row for row in lint_draft(sentence, facts=[]) if row['code'] == 'unverified_case')
    assert issue['excerpt'] == sentence
    assert sentence in format_ungrounded(case_claims(sentence, []))


@pytest.mark.parametrize('sentence,blocked', [('暂无可核验的成功案例。', False), ('该产品已有某客户成功案例。', True)])
def test_generation_pipeline_with_mock_model_preserves_gate_and_full_error(sentence, blocked):
    import asyncio
    from unittest.mock import AsyncMock, patch
    from app.geo.content.generate_article import generate_master_article
    from app.geo.content.variants import GeoContentError
    from tests.test_geo_h1_evidence import FACTS, payload
    async def generate():
        return await generate_master_article(
            tenant_name='示例品牌', question='产品有什么特点？', facts=FACTS,
            brief={'industry': '工业传动', 'audience': '采购', 'intent': 'scenario', 'content_type': 'thought_leadership', 'cta': '咨询选型'},
            llm={'api_key': 'dummy', 'base_url': 'http://invalid', 'model': 'test'})
    with patch('app.geo.content.generate_article.chat_json', new=AsyncMock(return_value=payload(sentence))) as model:
        if blocked:
            with pytest.raises(GeoContentError) as error:
                asyncio.run(generate())
            assert sentence in str(error.value)
            assert model.await_count == 2
        else:
            assert asyncio.run(generate())
            assert model.await_count == 1
