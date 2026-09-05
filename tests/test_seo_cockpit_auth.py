import asyncio
import json
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from starlette.requests import Request
from app.security.auth import AuthContext, require_scoped_auth

@pytest.mark.parametrize('value,status',[(5.0,403),(4.0,None),(5,403),('5',403),(True,422),(5.2,422),(None,422)])
def test_body_tenant_is_checked_before_pydantic_coercion(value,status):
    async def receive():
        return {'type':'http.request','body':json.dumps({'tenant_id':value}).encode()}
    request=Request({'type':'http','method':'POST','path':'/api/v1/seo/content-assets','query_string':b'','headers':[]},receive)
    ctx=AuthContext(7,'test','test',4,{'seo.content':'edit'})
    if status:
        with pytest.raises(HTTPException) as error:asyncio.run(require_scoped_auth(request,ctx))
        assert error.value.status_code==status
    else:assert asyncio.run(require_scoped_auth(request,ctx)) is ctx

def test_rule_upsert_reopens_alerts_with_new_priority():
    from app.rules.engine import run_rules_for_tenant
    draft=SimpleNamespace(rule_code='test',priority='P1',title='new',message='new',report_date='2026-09-05',keyword_id=1,keyword='test',campaign_id=2,campaign_name='test',metrics={})
    session=SimpleNamespace(execute=AsyncMock(),commit=AsyncMock())
    with patch('app.rules.engine.ALL_RULES',[SimpleNamespace(evaluate=AsyncMock(return_value=[draft]))]),patch('app.rules.engine.merge_duplicate_alerts',new=AsyncMock(return_value=0)):
        asyncio.run(run_rules_for_tenant(session,SimpleNamespace(id=4),'2026-09-05'))
    sql=str(session.execute.call_args.args[0])
    assert 'status = excluded.status' in sql and 'priority = excluded.priority' in sql

def test_manual_metric_api_cannot_forge_cockpit_history():
    from app.api.seo import MetricSnapshotCreate,create_metric_snapshot
    ctx=AuthContext(7,'test','test',4,{'seo.dashboard':'edit'})
    session=AsyncMock()
    with pytest.raises(HTTPException) as error:
        asyncio.run(create_metric_snapshot(MetricSnapshotCreate(tenant_id=4,site_id=1,metric_type='seo.images.verified_repair_count',source='cockpit_observation',numeric_value=100),session,ctx))
    assert error.value.status_code==422
    session.commit.assert_not_called()
