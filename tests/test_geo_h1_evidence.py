"""H1 regressions: synthetic inputs only, no customer rows or model calls."""
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock, patch

import pytest

from app.geo.content.claim_guard import ungrounded_claims
from app.geo.content.draft_lint import lint_draft
from app.geo.content.evidence_cite import build_sentence_citations
from app.geo.content.generate_article import normalize_article_payload, generate_master_article
from app.geo.content.rules import check_sentence_evidence
from app.geo.content.variants import GeoContentError
from tests.test_geo_content_rules import _base

FACTS = [{'id': i, 'title': '产品介绍', 'statement': '示例品牌产品专为连续运行设计，采用散热壳体。',
          'source_name': '已核验资料', 'trust_level': 'verified', 'status': 'active'} for i in range(1, 4)]


@pytest.mark.parametrize('claim', [
    '该产品适用于矿业、水泥、港口等严苛工况。',
    '重载设备如带式输送机、破碎机、搅拌机等需要连续运行。',
    '该结构防止温度过高导致密封失效或润滑劣化。',
    '齿轮材质直接影响使用寿命。',
    '扭矩范围决定了设备承载能力。',
    '该产品适用于航空设备。',
])
def test_qualitative_claim_requires_statement(claim):
    assert any(row['kind'] == 'qualitative' for row in ungrounded_claims(claim, FACTS))
    assert any(row['code'] == 'unverified_qualitative' and row['level'] == '高'
               for row in lint_draft(claim, facts=FACTS))
    supported = [{**FACTS[0], 'statement': claim}]
    assert not ungrounded_claims(claim, supported)


def test_title_is_not_evidence_and_similarity_cannot_override_blocker():
    claim = '示例品牌产品专为连续运行设计，适用于矿业和港口。'
    facts = [{**FACTS[0], 'title': claim}]
    rows = build_sentence_citations(claim, facts)
    assert rows[0]['needs_fact'] and not rows[0]['cited']
    assert rows[0]['fact_id'] is None
    assert 0 <= rows[0]['score'] <= 1


def test_evidence_checks_heading_bold_and_beyond_40_sentences():
    body = '资料整理后请核对来源。\n' * 41 + '# 适用于矿业和港口\n**防止密封失效和润滑劣化。**'
    rows = build_sentence_citations(body, FACTS)
    assert len(rows) > 40
    assert sum(row['needs_fact'] for row in rows) >= 2


def test_stale_citations_do_not_bypass_current_rule():
    data = _base(body_markdown='产品适用于矿业和港口。', facts=FACTS,
                 outline={'sentence_citations': [{'cited': True, 'needs_fact': False}]})
    assert not check_sentence_evidence(data).passed


def payload(body):
    return {'title': '产品资料说明', 'direct_answer': '示例品牌产品专为连续运行设计。',
            'sections': [{'type': 'definition', 'body': body},
                         {'type': 'conclusion', 'body': '示例品牌产品采用散热壳体。'}],
            'used_fact_ids': [], 'updated_at': '1999-01-01'}


def test_model_cannot_invent_update_date_or_used_fact_ids():
    result = normalize_article_payload(payload('资料说明'), FACTS)
    assert result['updated_at'] == datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    assert result['used_fact_ids'] == []


@pytest.mark.parametrize('source', ['产品不适用于矿业。', '产品仅在室内适用于矿业。', '产品适用于矿业，但必须另配冷却系统。'])
def test_source_negation_and_conditions_cannot_be_dropped(source):
    assert ungrounded_claims('产品适用于矿业。', [{**FACTS[0], 'statement': source}])


def test_publish_gate_blocks_qualitative_claim_with_stale_metadata():
    from app.geo.content.gate import assert_can_publish, PublishGateError
    data = _base()
    data.body_markdown += '\n产品适用于矿业和港口。'
    data.outline['sentence_citations'] = [{'cited': True, 'needs_fact': False}]
    with pytest.raises(PublishGateError, match='fabrication_lint|sentence_evidence'):
        assert_can_publish(data)


def test_generation_rejects_unsupported_rewrite():
    bad = payload('产品适用于矿业和港口。')
    with patch('app.geo.content.generate_article.chat_json', new=AsyncMock(return_value=bad)) as model:
        with pytest.raises(GeoContentError, match='已拦截'):
            asyncio.run(generate_master_article(tenant_name='示例品牌', question='产品有什么特点？', facts=FACTS, brief={'industry':'工业传动','audience':'采购','intent':'scenario','content_type':'thought_leadership','cta':'咨询选型'},
                                         llm={'api_key': 'dummy', 'base_url': 'http://invalid', 'model': 'test'}))
        assert model.await_count == 2


def test_generation_accepts_grounded_rewrite():
    with patch('app.geo.content.generate_article.chat_json', new=AsyncMock(side_effect=[
        payload('产品适用于矿业和港口。'), payload('示例品牌产品采用散热壳体。')])):
        result = asyncio.run(generate_master_article(tenant_name='示例品牌', question='产品有什么特点？', facts=FACTS, brief={'industry':'工业传动','audience':'采购','intent':'scenario','content_type':'thought_leadership','cta':'咨询选型'},
                                             llm={'api_key': 'dummy', 'base_url': 'http://invalid', 'model': 'test'}))
        assert '港口' not in str(result)


@pytest.mark.parametrize('text', [
    '如果您正在为具体设备进行选型，建议预约诊断或咨询专业选型服务，以获取针对性的方案。',
    '如需了解设备选型，请联系专业团队。',
    '如有设备选型问题，请向专业团队咨询。',
    '如何为具体设备进行选型？建议咨询专业团队。',
])
def test_conditional_consultation_is_not_an_equipment_example(text):
    assert not ungrounded_claims(text, FACTS)
    assert not any(row.get('level') == '高' for row in lint_draft(text, facts=FACTS))
    assert not any(row['needs_fact'] for row in build_sentence_citations(text, FACTS))


@pytest.mark.parametrize('text', [
    '如长期高负荷运转的工业机械）对驱动系统的核心部件——工业齿轮箱提出了严苛要求。',
    '如果您正在选型，该产品适用于矿业和港口。',
    '如需了解设备，该结构可有效降低润滑劣化风险。',
    '例如破碎机和搅拌机需要连续运行。',
])
def test_conditional_word_does_not_exempt_real_claims(text):
    assert any(row['kind'] == 'qualitative' for row in ungrounded_claims(text, FACTS))
