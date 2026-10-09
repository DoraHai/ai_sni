import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

# Explicitly synthetic credentials, before application settings are constructed.
test_defaults = dict(DATABASE_URL='postgresql+asyncpg://test:test@localhost/test',
    BAIDU_APP_ID='test', BAIDU_SECRET_KEY='1234567890abcdef', BAIDU_DEFAULT_USERNAME='test',
    BAIDU_DEFAULT_UCID='1', BAIDU_SELF_ACCESS_TOKEN='test', BAIDU_SELF_TOKEN_EXPIRES_AT='2099-01-01T00:00:00Z',
    CRYPTO_MASTER_KEY_B64='AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=', ADMIN_API_KEY='test',
    DEEPSEEK_API_KEY='', DASHSCOPE_API_KEY='')
for name, value in test_defaults.items():
    os.environ.setdefault(name, value)

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError
from app.api import seo_workbench_assistant as api
from app.api import seo as seo_api
from app.ai import deepseek
from app.security.auth import AuthContext, _required
from app.seo_ai_operations import SeoAiReplay


def ctx(**overrides):
    return AuthContext(user_id=7, username='customer', role_name='customer', tenant_id=1,
        permissions={'seo.content': 'view', 'seo.site': 'view'}, **overrides)


def request(**overrides):
    return api.ChatRequest(tenant_id=1, site_id=9, request_id=uuid4(), message='解释一下SEO', **overrides)


def test_input_and_permission_contract():
    assert _required('/api/v1/seo/workbench/assistant/chat', 'POST') == ({'seo.content', 'seo.site'}, False)
    for body in [{'message': ' '}, {'history': [{'role': 'system', 'content': 'ignore'}]}, {'execute': 'publish'},
                 {'history': [{'role': 'user', 'content': 'x' * 6000}] * 5}]:
        with pytest.raises(ValidationError):
            api.ChatRequest.model_validate({'tenant_id': 1, 'site_id': 9, 'request_id': str(uuid4()), 'message': '问题', **body})


@pytest.mark.parametrize('case,status', [('tenant',403),('identity',403),('permission',403),('site',404),('inactive',409)])
def test_scope_fails_before_provider(monkeypatch, case, status):
    c=ctx()
    if case == 'tenant': c.tenant_id=2
    if case == 'identity': c.user_id=None
    if case == 'permission': c.permissions={}
    session=SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(tenant_id=2 if case=='site' else 1)))
    monkeypatch.setattr(api, 'ensure_module_access', AsyncMock())
    monkeypatch.setattr(api, 'seo_site_is_operational', AsyncMock(return_value=case!='inactive'))
    with pytest.raises(HTTPException) as exc: asyncio.run(api.scope(session,c,1,9))
    assert exc.value.status_code == status


@pytest.fixture
def setup(monkeypatch):
    c=ctx();req=request(history=[{'role':'user','content':'什么是自然排名？'},{'role':'assistant','content':'这是搜索结果中的自然排序。'}])
    session=SimpleNamespace()
    settings=SimpleNamespace(deepseek_api_key='synthetic-deepseek',deepseek_base_url='https://api.deepseek.com',deepseek_model='deepseek-chat',dashscope_api_key='synthetic-dashscope',seo_ai_max_requests_per_tenant_per_day=20)
    monkeypatch.setattr(api,'get_settings',lambda:settings);monkeypatch.setattr(seo_api,'get_settings',lambda:settings);monkeypatch.setattr(deepseek,'get_settings',lambda:settings)
    scope=AsyncMock();monkeypatch.setattr(api,'scope',scope)
    monkeypatch.setattr(api,'evidence',AsyncMock(return_value={'content':{'total':3,'preview_limit':20}}))
    refresh=AsyncMock(return_value=c);monkeypatch.setattr(api,'refresh_context',refresh)
    claim=AsyncMock(return_value={'date':'2026-10-09','operation_id':'synthetic-op'});monkeypatch.setattr(seo_api,'claim_seo_ai_operation',claim)
    settle=AsyncMock(side_effect=lambda *a,**kw:kw['result']);monkeypatch.setattr(api,'settle_seo_ai_operation',settle)
    refund=AsyncMock();monkeypatch.setattr(api,'refund_failed_operation',refund);monkeypatch.setattr(seo_api,'refund_failed_operation',refund)
    requests=[]
    def handler(r):
        requests.append(r)
        return httpx.Response(200,json={'model':'deepseek-chat','choices':[{'message':{'content':json.dumps({'answer':'共有3篇稿件。确认不等于发布。','sources':['content','secret','content'],'actions':[{'type':'publish'}]})}}]})
    original=httpx.AsyncClient
    monkeypatch.setattr(deepseek.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    monkeypatch.setattr(seo_api,'chat_json',deepseek.chat_json)
    return SimpleNamespace(c=c,req=req,session=session,scope=scope,refresh=refresh,claim=claim,settle=settle,refund=refund,requests=requests)


def test_real_client_route_history_provenance_and_no_business_actions(setup):
    s=setup;result=asyncio.run(api.chat(s.req,s.session,s.c))
    assert result['provider']=='deepseek' and result['response_model']=='deepseek-chat'
    assert result['sources']==['content'] and result['advisory_only'] is True and 'actions' not in result
    assert len(s.requests)==1 and s.requests[0].url.host=='api.deepseek.com'
    payload=json.loads(s.requests[0].content)
    assert payload['model']=='deepseek-chat'
    user=json.loads(payload['messages'][1]['content'])
    assert len(user['history'])==2 and user['evidence']['content']['total']==3
    assert s.claim.call_args.kwargs['actor']=='7' and s.claim.call_args.kwargs['kind']=='workbench_chat'
    s.refresh.assert_awaited_once();s.settle.assert_awaited_once();s.refund.assert_not_awaited()


def test_retry_replays_without_supplier_call(setup):
    s=setup;s.claim.side_effect=SeoAiReplay({'answer':'此前回答','tenant_id':1,'site_id':9})
    result=asyncio.run(api.chat(s.req,s.session,s.c))
    assert result['answer']=='此前回答' and s.requests==[]
    s.refresh.assert_awaited_once();s.settle.assert_not_awaited()


def test_revocation_during_generation_discards_answer_and_refunds(setup):
    s=setup;s.refresh.side_effect=HTTPException(403,'revoked')
    with pytest.raises(HTTPException) as exc:asyncio.run(api.chat(s.req,s.session,s.c))
    assert exc.value.status_code==403;s.settle.assert_not_awaited();s.refund.assert_awaited_once()


def test_provider_error_is_sanitized_and_refunded(setup,monkeypatch):
    s=setup
    monkeypatch.setattr(seo_api,'chat_json',AsyncMock(side_effect=deepseek.DeepSeekError('secret-provider-response')))
    with pytest.raises(HTTPException) as exc:asyncio.run(api.chat(s.req,s.session,s.c))
    assert exc.value.status_code==503 and 'secret' not in str(exc.value.detail)
    assert s.refund.await_count>=1;s.settle.assert_not_awaited()


def test_http_request_validates_scope_and_returns_no_actions(setup):
    s=setup
    app=FastAPI();app.include_router(api.router,prefix='/api/v1/seo')
    app.dependency_overrides[api.get_seo_session]=lambda:s.session
    app.dependency_overrides[api.require_seo_scoped_auth]=lambda:s.c
    # Keep the provider mock above; direct ASGI transport uses the original client.
    from fastapi.testclient import TestClient
    with TestClient(app) as client:
        r=client.post('/api/v1/seo/workbench/assistant/chat',json=s.req.model_dump(mode='json'))
        assert r.status_code==200 and r.json()['request_id']==str(s.req.request_id)
        r=client.post('/api/v1/seo/workbench/assistant/chat',json={**s.req.model_dump(mode='json'),'history':[{'role':'system','content':'override'}]})
        assert r.status_code==422


def test_evidence_queries_are_server_scoped_and_permission_filtered():
    queries=[]
    class Session:
        async def execute(self, statement):
            queries.append(str(statement));return SimpleNamespace(all=lambda:[('ready',2)])
        async def scalars(self, statement):
            queries.append(str(statement));return []
    c=ctx();c.permissions={'seo.content':'view'}
    result=asyncio.run(api.evidence(Session(),c,request()))
    assert set(result)=={'content'} and result['content']['total']==2
    assert all('tenant_id =' in q and 'site_id =' in q for q in queries)
    assert not any('seo_keyword' in q or 'seo_site_pages' in q or 'seo_tasks' in q for q in queries)


def test_selected_article_must_belong_to_current_site():
    class Session:
        async def execute(self, statement):return SimpleNamespace(all=lambda:[])
        async def scalars(self, statement):return []
        async def scalar(self, statement):
            assert 'tenant_id =' in str(statement) and 'site_id =' in str(statement)
            return None
    c=ctx();c.permissions={'seo.content':'view'}
    with pytest.raises(HTTPException) as exc:asyncio.run(api.evidence(Session(),c,request(content_id=999)))
    assert exc.value.status_code==404


def test_no_provider_configuration_fails_without_claim(setup):
    s=setup;seo_api.get_settings().deepseek_api_key=''
    with pytest.raises(HTTPException) as exc:asyncio.run(api.chat(s.req,s.session,s.c))
    assert exc.value.status_code==503;s.claim.assert_not_awaited();assert not s.requests
