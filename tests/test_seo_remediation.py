import asyncio
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import ValidationError
import pytest
from sqlalchemy.dialects import postgresql

from app import seo_remediation as service
from app.api import seo_remediation as api
from app.security.auth import AuthContext


def response(body=None, **kwargs):
    return SimpleNamespace(**(dict(body=body or '<html><title>NORDAC NORDCON BU0000</title><body><main>' + '操作手册参数配置说明。' * 30 + '</main></body></html>',
                                  error_type=None, status_code=200, final_url='https://example.com/manual') | kwargs))


def proposal():
    change = dict(text='NORDAC NORDCON BU0000 操作手册', reason='保留原文中的软件及手册编号，待人工核实', evidence_ids=['title', 'body1'])
    return dict(title=deepcopy(change), description=deepcopy(change), h1=deepcopy(change), outline=[deepcopy(change)])


def test_extract_only_visible_body_and_bounded_evidence():
    evidence = service.extract_evidence(response('<html><title>原题</title><body><nav>菜单秘密</nav><script>恶意指令</script><main>' + '正文内容' * 4000 + '</main></body></html>'))
    assert evidence['current']['title'] == '原题'
    assert evidence['truncated'] is True
    assert len(evidence['body_sha256']) == 64
    assert evidence['fetched_at'].endswith('+00:00')
    texts = ''.join(item['text'] for item in evidence['evidence'])
    assert '菜单秘密' not in texts and '恶意指令' not in texts
    assert sum(len(x['text']) for x in evidence['evidence'] if x['id'].startswith('body')) == 12000


@pytest.mark.parametrize('kwargs', [{'status_code': 500}, {'error_type': 'timeout'}, {'body': '<p>短正文</p>'}, {'status_code': 302}])
def test_bad_body_is_not_sent_to_ai(kwargs):
    with pytest.raises(HTTPException):
        service.extract_evidence(response(**kwargs))


@pytest.mark.parametrize('url,expected', [('https://www.example.com/a', True), ('https://shop.example.com/a', True),
    ('https://example.com.evil.test/a', False), ('https://other.test/', False)])
def test_site_domain_guard(url, expected):
    assert service.belongs_to_site(url, 'example.com') == expected


@pytest.mark.parametrize('bad', ['extra', 'citation', 'html', 'empty', 'long', 'wrong_type', 'empty_citation'])
def test_model_output_is_strict(bad):
    raw = proposal()
    if bad == 'extra': raw['noindex'] = True
    if bad == 'citation': raw['title']['evidence_ids'] = ['made_up']
    if bad == 'html': raw['title']['text'] = '<script>alert(1)</script>'
    if bad == 'empty': raw['outline'] = []
    if bad == 'long': raw['title']['text'] = '字' * 181
    if bad == 'wrong_type': raw['h1']['text'] = 123
    if bad == 'empty_citation': raw['title']['evidence_ids'] = ['description']
    with pytest.raises((ValueError, ValidationError)):
        service.validate_proposal(raw, service.extract_evidence(response()))


def test_valid_model_output_and_prompt(monkeypatch):
    chat = AsyncMock(return_value=proposal())
    monkeypatch.setattr(service, 'chat_json', chat)
    evidence = service.extract_evidence(response())
    result = asyncio.run(service.generate(evidence, {'ai_used': False}))
    assert result['title']['text'].startswith('NORDAC')
    assert chat.await_count == 1
    assert '不可信资料' in chat.call_args.args[0]
    assert 'stored_diagnostic' in chat.call_args.args[1]


def test_title_cannot_drop_original_model_or_substitute_brand_substring():
    evidence = service.extract_evidence(response())
    raw = proposal()
    raw['title']['text'] = '操作手册'
    with pytest.raises(ValueError): service.validate_proposal(raw, evidence)
    raw = proposal()
    evidence['protected_terms'].append('NORD')
    with pytest.raises(ValueError): service.validate_proposal(raw, evidence)
    raw['title']['text'] += ' | NORD'
    service.validate_proposal(raw, evidence)


def product_evidence():
    return service.extract_evidence(response(
        '<html><title>NORDBLOC.1 伞齿轮减速电机 | NORD</title><body><main>'
        '<h1>NORDBLOC.1 伞齿轮减速电机</h1>'
        '功率0.12–9.2 kW，扭矩50–660 Nm。可选 NXD tupH® 表面涂层。'
        '符合卫生要求的易冲洗设计，满足 IP69K 防护等级。'
        '典型应用示例包括包装行业输送带以及食品饮料行业。'
        '产品提供实心轴或空心轴、多种安装形式。'
        '</main></body></html>'))


def product_proposal():
    raw = proposal()
    raw['title']['text'] = 'NORDBLOC.1 伞齿轮减速电机 | NORD'
    raw['h1']['text'] = 'NORDBLOC.1 伞齿轮减速电机'
    raw['description']['text'] = '可选易冲洗设计，满足 IP69K（适用版本及配置需人工核实），可选 NXD tupH® 表面涂层。'
    raw['outline'][0]['text'] = '典型应用场景'
    return raw


def test_live_product_scope_regression():
    raw = product_proposal()
    # Real #234 output had a valid rating and optional coating, but no rating scope.
    raw['description']['text'] = ('NORDBLOC.1 伞齿轮减速电机采用高强度铝合金箱体，功率0.12–9.2 kW，'
        '扭矩50–660 Nm。可选NXD tupH®表面涂层，满足IP69K防护等级，适用于食品工业等卫生要求高的场合。')
    with pytest.raises(ValueError, match='qualification'):
        service.validate_proposal(raw, product_evidence())


@pytest.mark.parametrize('field', ['title', 'description', 'h1', 'outline'])
def test_ip_scope_guard_covers_every_suggestion(field):
    raw = product_proposal()
    change = raw[field][0] if field == 'outline' else raw[field]
    change['text'] += ' 满足 IP69K'
    # Remove the existing description's qualifier so it cannot mask the test claim.
    change['text'] = change['text'].replace('（适用版本及配置需人工核实）', '')
    with pytest.raises(ValueError, match='qualification'):
        service.validate_proposal(raw, product_evidence())


@pytest.mark.parametrize('text', [
    '满足 IP69K。适用版本及配置需人工核实',
    '满足 IP69K；适用版本及配置需人工核实',
    '全系满足 IP69K（适用版本及配置需人工核实）',
    '所有型号标配 IP69K（适用版本及配置需人工核实）',
])
def test_scope_note_must_qualify_same_claim_without_universal_statement(text):
    raw = product_proposal()
    raw['description']['text'] = text
    raw['description']['reason'] = '适用版本及配置需人工核实'
    with pytest.raises(ValueError, match='qualification'):
        service.validate_proposal(raw, product_evidence())


@pytest.mark.parametrize('qualification', [
    '不代表全系标配', '并非全系标配', '不是所有型号的标配',
    '不意味着全系列标配', '不能视为标配', '并不代表所有版本',
])
def test_explicit_negative_configuration_qualification_is_allowed(qualification):
    raw = product_proposal()
    raw['description']['text'] = f'易冲洗版本满足 IP69K（适用版本及配置需人工核实），{qualification}。'
    service.validate_proposal(raw, product_evidence())


@pytest.mark.parametrize('description', [
    '不代表全系标配，但所有型号满足 IP69K（适用版本及配置需人工核实）',
    '全系满足 IP69K（适用版本及配置需人工核实），并非全系标配',
    '并非不是全系标配，满足 IP69K（适用版本及配置需人工核实）',
    '不是 并非全系标配，满足 IP69K（适用版本及配置需人工核实）',
    '不代表全系标配不支持 IP69K（适用版本及配置需人工核实）',
])
def test_negation_does_not_mask_affirmative_or_double_negative_claim(description):
    raw = product_proposal()
    raw['description']['text'] = description
    with pytest.raises(ValueError, match='qualification'):
        service.validate_proposal(raw, product_evidence())


@pytest.mark.parametrize('description', [
    'Meets IP69K. 适用版本及配置需人工核实',
    'Meets IP69K.适用版本及配置需人工核实',
    'Meets IP69K.Next: 适用版本及配置需人工核实',
    '适用版本及配置需人工核实. Meets IP69K',
    'NORDBLOC.1 meets IP69K. 适用版本及配置需人工核实',
    '0.12–9.2 kW, meets IP69K. 适用版本及配置需人工核实',
])
def test_english_period_cannot_join_rating_with_detached_note(description):
    raw = product_proposal()
    raw['description']['text'] = description
    with pytest.raises(ValueError, match='qualification'):
        service.validate_proposal(raw, product_evidence())


@pytest.mark.parametrize('description', [
    '适用版本及配置需人工核实，NORDBLOC.1 易冲洗版本满足 IP69K。',
    '适用版本及配置需人工核实，nordbloc.1 易冲洗版本满足 IP69K。',
    '适用版本及配置需人工核实，功率0.12–9.2 kW 的易冲洗版本满足 IP69K。',
])
def test_dotted_models_and_decimals_do_not_detach_scope_note(description):
    raw = product_proposal()
    raw['description']['text'] = description
    service.validate_proposal(raw, product_evidence())


def test_sentence_splitter_preserves_source_model_but_not_unseen_dotted_words():
    sentences = list(service.claim_sentences(
        'AB.CD 0.12 kW. IP69K.Next sentence.', {'title':'AB.CD motor'}))
    assert sentences == ['AB.CD 0.12 kW', ' IP69K', 'Next sentence', '']


@pytest.mark.parametrize('description,status', [
    ('易冲洗版本满足 IP69K（适用版本及配置需人工核实），不代表全系标配。', 200),
    ('Meets IP69K. 适用版本及配置需人工核实', 502),
])
def test_review_repro_cases_through_generation(monkeypatch, description, status):
    raw = product_proposal()
    raw['description']['text'] = description
    chat = AsyncMock(return_value=raw)
    monkeypatch.setattr(service, 'chat_json', chat)
    if status == 200:
        assert asyncio.run(service.generate(product_evidence(), {})) == raw
    else:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(service.generate(product_evidence(), {}))
        assert exc.value.status_code == status and '不扣' in exc.value.detail
    assert chat.await_count == 1


@pytest.mark.parametrize('rating,citations', [('IP68', ['body1']), ('IP69K', ['title'])])
def test_rating_must_exist_in_this_changes_cited_evidence(rating, citations):
    raw = product_proposal()
    raw['description'].update(text=f'{rating}（适用版本及配置需人工核实）', evidence_ids=citations)
    with pytest.raises(ValueError, match='absent'):
        service.validate_proposal(raw, product_evidence())


@pytest.mark.parametrize('claim', ['应用案例', '客户案例与效果', '成功案例', '客户实绩', 'Case studies', 'Customer story', 'Success stories'])
def test_application_scenarios_cannot_be_promoted_to_cases(claim):
    raw = product_proposal()
    raw['outline'][0]['text'] = claim
    with pytest.raises(ValueError, match='customer cases'):
        service.validate_proposal(raw, product_evidence())


def test_scoped_product_copy_and_unchanged_good_fields_are_allowed():
    raw = product_proposal()
    raw['description']['text'] += '功率0.12–9.2 kW，扭矩50–660 Nm。'
    raw['title']['reason'] = '原题已明确品牌型号，无需改动。'
    result = service.validate_proposal(raw, product_evidence())
    assert result == raw
    raw['description']['text'] = '高强度铝合金箱体，可选表面涂层；适用配置由产品负责人核实。'
    service.validate_proposal(raw, product_evidence())  # Omitting uncertain ratings is safe.


def test_bad_claim_single_model_call_and_safe_failure(monkeypatch):
    raw = product_proposal()
    raw['outline'][0]['text'] = '应用案例'
    chat = AsyncMock(return_value=raw)
    monkeypatch.setattr(service, 'chat_json', chat)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(service.generate(product_evidence(), {}))
    assert exc.value.status_code == 502 and '不扣' in exc.value.detail
    assert chat.await_count == 1
    prompt = chat.call_args.args[0]
    assert '适用版本及配置需人工核实' in prompt and '典型应用场景' in prompt and '无需改动' in prompt


def test_api_rejected_claim_refunds_without_record_changes(monkeypatch):
    actual_generate = service.generate
    session, row = setup_api(monkeypatch)
    before = dict(vars(row))
    monkeypatch.setattr(service, 'generate', actual_generate)
    monkeypatch.setattr(service, 'read_evidence', AsyncMock(return_value=product_evidence()))
    raw = product_proposal()
    raw['outline'][0]['text'] = '应用案例'
    monkeypatch.setattr(service, 'chat_json', AsyncMock(return_value=raw))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.preview_remediation(api.RemediationRequest(tenant_id=1,site_id=1,page_id=231),ctx(),session))
    assert exc.value.status_code == 502
    assert service.settle.call_args.kwargs == {'success': False}
    assert service.chat_json.await_count == 1 and dict(vars(row)) == before


def test_provider_secret_is_not_returned(monkeypatch):
    monkeypatch.setattr(service, 'chat_json', AsyncMock(side_effect=service.DeepSeekError('secret-key-XYZ https://api.invalid')))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(service.generate(service.extract_evidence(response()), {}))
    assert exc.value.status_code == 502
    assert 'secret' not in exc.value.detail and 'https' not in exc.value.detail


@pytest.mark.parametrize('robots', [response('User-agent: *\nDisallow: /'), response(status_code=503), response(error_type='timeout')])
def test_robots_blocks_before_page_fetch(monkeypatch, robots):
    fetch = AsyncMock(return_value=robots)
    monkeypatch.setattr(service, 'fetch_url', fetch)
    with pytest.raises(HTTPException):
        asyncio.run(service.read_evidence('https://example.com/manual', 'example.com'))
    assert fetch.await_count == 1


def test_robots_404_allows_single_page(monkeypatch):
    fetch = AsyncMock(side_effect=[response(status_code=404, error_type='http_4xx'), response()])
    monkeypatch.setattr(service, 'fetch_url', fetch)
    evidence = asyncio.run(service.read_evidence('https://example.com/manual', 'example.com'))
    assert fetch.await_count == 2 and evidence['current']['title'] == 'NORDAC NORDCON BU0000'


def test_external_redirect_not_sent_to_ai(monkeypatch):
    monkeypatch.setattr(service, 'fetch_url', AsyncMock(side_effect=[response('User-agent: *\nAllow: /'), response(final_url='https://other.test/')]))
    with pytest.raises(HTTPException):
        asyncio.run(service.read_evidence('https://example.com/manual', 'example.com'))


def session_for(module):
    return SimpleNamespace(scalar=AsyncMock(return_value=module), commit=AsyncMock())


def test_quota_reserve_singleflight_refund_and_date(monkeypatch):
    today = datetime(2026, 9, 3, 23, 59, tzinfo=ZoneInfo('Asia/Shanghai'))
    monkeypatch.setattr(service, 'now_cst', lambda: today)
    module = SimpleNamespace(module_settings={'other_module_setting': 'preserve'})
    session = session_for(module)
    reservation = asyncio.run(service.reserve(session, 1))
    sql = str(session.scalar.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert 'FOR UPDATE' in sql and 'tenant_id' in sql
    assert session.scalar.call_args.args[0].get_execution_options()['populate_existing'] is True
    assert module.module_settings[service.USAGE_KEY]['used'] == 1
    with pytest.raises(HTTPException) as exc: asyncio.run(service.reserve(session, 1))
    assert exc.value.status_code == 429
    assert asyncio.run(service.settle(session, 1, reservation, success=False)) is True
    assert module.module_settings[service.USAGE_KEY]['used'] == 0
    newer = asyncio.run(service.reserve(session, 1))
    assert asyncio.run(service.settle(session, 1, reservation, success=False)) is False
    assert module.module_settings[service.USAGE_KEY]['used'] == 1
    today = datetime(2026, 9, 4, 0, 1, tzinfo=ZoneInfo('Asia/Shanghai'))
    newest = asyncio.run(service.reserve(session, 1))
    assert asyncio.run(service.settle(session, 1, newer, success=False)) is False
    assert module.module_settings[service.USAGE_KEY]['used'] == 1
    assert asyncio.run(service.settle(session, 1, newest, success=True)) is True
    assert module.module_settings[service.USAGE_KEY]['used'] == 1
    assert module.module_settings['other_module_setting'] == 'preserve'


@pytest.mark.parametrize('state', [{'used':20}, {'used':0, 'attempts':100}])
def test_daily_limits(monkeypatch, state):
    monkeypatch.setattr(service, 'now_cst', lambda: datetime(2026, 9, 3, tzinfo=ZoneInfo('Asia/Shanghai')))
    module = SimpleNamespace(module_settings={service.USAGE_KEY: {'date':'2026-09-03', **state}})
    with pytest.raises(HTTPException) as exc: asyncio.run(service.reserve(session_for(module), 1))
    assert exc.value.status_code == 429


def ctx(**kw):
    return AuthContext(**(dict(user_id=7, username='operator', role_name='editor', tenant_id=1,
        permissions={'seo.site':'edit', 'seo.content':'edit'}) | kw))


def setup_api(monkeypatch):
    row = SimpleNamespace(id=231, tenant_id=1, site_id=1, url='https://example.com/manual', last_checked_at=None,
                          title_suggestion='人工确认的建议')
    session = SimpleNamespace(scalar=AsyncMock(side_effect=[1, row, SimpleNamespace(canonical_domain='example.com')]))
    monkeypatch.setattr(api, 'is_enabled', lambda: True)
    monkeypatch.setattr(service, 'reserve', AsyncMock(return_value=('2026-09-03','token')))
    monkeypatch.setattr(service, 'settle', AsyncMock())
    monkeypatch.setattr(service, 'read_evidence', AsyncMock(return_value=service.extract_evidence(response())))
    monkeypatch.setattr(service, 'generate', AsyncMock(return_value=proposal()))
    return session, row


def test_api_success_preserves_page_and_scopes_queries(monkeypatch):
    session, row = setup_api(monkeypatch)
    before = dict(vars(row))
    result = asyncio.run(api.preview_remediation(api.RemediationRequest(tenant_id=1,site_id=1,page_id=231),ctx(),session))
    assert result['saved'] is False and result['source'] == 'ai'
    assert dict(vars(row)) == before
    assert service.settle.call_args.kwargs == {'success':True}
    query = str(session.scalar.call_args_list[1].args[0].compile(dialect=postgresql.dialect()))
    assert 'seo_site_pages.tenant_id' in query and 'seo_site_pages.site_id' in query and 'seo_site_pages.id' in query


@pytest.mark.parametrize('context', [ctx(tenant_id=2), ctx(user_id=None), ctx(permissions={'seo.site':'edit'}), ctx(permissions={'seo.content':'edit'})])
def test_api_rejects_wrong_scope_actor_permission_before_provider(monkeypatch, context):
    session, _ = setup_api(monkeypatch)
    with pytest.raises(HTTPException):
        asyncio.run(api.preview_remediation(api.RemediationRequest(tenant_id=1,site_id=1,page_id=231),context,session))
    assert service.reserve.await_count == 0 and service.generate.await_count == 0


@pytest.mark.parametrize('error', [HTTPException(424,'body unavailable'), TimeoutError()])
def test_api_failure_refunds_and_preserves_page(monkeypatch, error):
    session, row = setup_api(monkeypatch)
    monkeypatch.setattr(service, 'read_evidence', AsyncMock(side_effect=error))
    with pytest.raises(HTTPException):
        asyncio.run(api.preview_remediation(api.RemediationRequest(tenant_id=1,site_id=1,page_id=231),ctx(),session))
    assert service.settle.call_args.kwargs == {'success':False}
    assert service.generate.await_count == 0 and row.title_suggestion == '人工确认的建议'
