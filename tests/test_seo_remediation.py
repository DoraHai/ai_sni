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
    asyncio.run(service.settle(session, 1, reservation, success=False))
    assert module.module_settings[service.USAGE_KEY]['used'] == 0
    newer = asyncio.run(service.reserve(session, 1))
    asyncio.run(service.settle(session, 1, reservation, success=False))
    assert module.module_settings[service.USAGE_KEY]['used'] == 1
    today = datetime(2026, 9, 4, 0, 1, tzinfo=ZoneInfo('Asia/Shanghai'))
    newest = asyncio.run(service.reserve(session, 1))
    asyncio.run(service.settle(session, 1, newer, success=False))
    assert module.module_settings[service.USAGE_KEY]['used'] == 1
    asyncio.run(service.settle(session, 1, newest, success=True))
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
