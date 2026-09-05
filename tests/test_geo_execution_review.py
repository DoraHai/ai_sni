"""Behavioral regressions for exact retests, live publication and network boundaries."""
import asyncio
import gzip
from copy import deepcopy
from datetime import date, datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from fastapi import HTTPException, BackgroundTasks
from app.geo.retest import plan_from_baseline, validate_plan_prompts, engines_for_prompt, validate_run_result, prepare_retest
from app.geo.publication_evidence import match_publication, visible_text, verify_publication
from app.geo.content.connectors.safe_http import public_request
from app.geo.integration import completion_evidence, update_task, TaskUpdate, start_retest
from test_geo_integration import task, state


def baseline_task():
    row = task()
    row.baseline_snapshot['questions'] = [[1, 'question one'], [2, 'question two']]
    row.baseline_snapshot['sample_counts'] = [[1, 'deepseek', 2], [1, 'kimi', 1], [2, 'deepseek', 3]]
    row.baseline_snapshot['model_counts'] = [[pid, engine, 'test-provider', 'test-model', n] for pid, engine, n in row.baseline_snapshot['sample_counts']]
    return row


def test_sparse_plan_preserves_each_cell_count():
    plan = plan_from_baseline(baseline_task())
    assert plan['total_samples'] == 6
    assert engines_for_prompt(plan, 1) == ['deepseek', 'deepseek', 'kimi']
    assert engines_for_prompt(plan, 2) == ['deepseek'] * 3
    assert engines_for_prompt(plan, 3) == []
    items = [dict(prompt_id=c['prompt_id'], engine=c['engine'], ok=True, sample_mode='openai_compat', simulated=False, analysis_status='completed', snapshot_id=i+1)
             for c in plan['cells'] for i in range(c['count'])]
    assert validate_run_result(plan, items)['comparable']
    items[-1]['analysis_status'] = 'needs_review'
    assert not validate_run_result(plan, items)['comparable']
    assert validate_run_result(plan, items)['missing'] == [dict(prompt_id=2, engine='deepseek', count=1)]


@pytest.mark.parametrize('mutation', ['missing_question', 'duplicate_question', 'duplicate_cell', 'zero_count', 'bool_count', 'over_limit', 'no_value', 'terminal'])
def test_invalid_baseline_cannot_trigger_paid_sampling(mutation):
    row=baseline_task()
    if mutation=='missing_question': row.baseline_snapshot['questions']=[]
    if mutation=='duplicate_question': row.baseline_snapshot['questions'].append([1, 'changed'])
    if mutation=='duplicate_cell': row.baseline_snapshot['sample_counts'].append([1, 'deepseek', 1])
    if mutation=='zero_count': row.baseline_snapshot['sample_counts'][0][2]=0
    if mutation=='bool_count': row.baseline_snapshot['sample_counts'][0][2]=True
    if mutation=='over_limit': row.baseline_snapshot['sample_counts'][0][2]=201
    if mutation=='no_value':
        for m in row.baseline_snapshot['metrics']: m['value']=None
    if mutation=='terminal': row.status='done'
    with pytest.raises(HTTPException): plan_from_baseline(row)


@pytest.mark.parametrize('field,value', [('question','changed'), ('status','paused'), ('is_brand_probe',True), ('id',999)])
def test_changed_or_unavailable_prompt_rejected(field,value):
    plan=plan_from_baseline(baseline_task())
    prompts=[NS(id=1,question='question one',status='active',is_brand_probe=False),NS(id=2,question='question two',status='active',is_brand_probe=False)]
    setattr(prompts[0],field,value)
    with pytest.raises(HTTPException): validate_plan_prompts(plan,prompts)


def test_retest_refuses_unverified_publication_and_existing_week_samples():
    async def run():
        row=baseline_task()
        prompts=[NS(id=i,question=q,status='active',is_brand_probe=False) for i,q in row.baseline_snapshot['questions']]
        session=NS(scalars=AsyncMock(return_value=prompts),scalar=AsyncMock(side_effect=[None,88,None]))
        with patch('app.geo.retest.closed_week_end', return_value=date(2026,9,7)):
            row.progress_first['params']['content_task_id']=12
            with pytest.raises(HTTPException) as exc: await prepare_retest(session,row)
            assert exc.value.status_code==409
            session.scalar.assert_not_awaited()
            row.progress={'publication_evidence':{'first_verified_at':'2026-09-05T10:00:00Z'}}
            with pytest.raises(HTTPException) as exc: await prepare_retest(session,row)
            assert exc.value.status_code==409
    asyncio.run(run())


def test_retest_retry_returns_durable_reservation_without_new_work():
    async def run():
        row=baseline_task();row.progress={'retest_runs':{'2026-09-06T16:00:00':42}}
        session=NS(execute=AsyncMock(),commit=AsyncMock(),add=Mock())
        background=BackgroundTasks()
        with patch('app.geo.integration.ticket',AsyncMock(return_value=row)), patch('app.geo.integration_metrics.closed_week_end',return_value=date(2026,9,7)),patch('app.geo.retest.prepare_retest',AsyncMock()) as prepare:
            result=await start_retest(10,background,7,NS(ensure_tenant=lambda _:None),session)
            assert result=={'run_id':42,'already_started':True}
            prepare.assert_not_awaited();session.add.assert_not_called()
            assert background.tasks==[]
    asyncio.run(run())


def publication_body():
    return '\n\n'.join(f'Paragraph {i}: engineering selection requires checking load, speed, thermal limits, duty cycle and installation conditions for model {i}.' for i in range(10))


def test_live_publication_requires_visible_current_body():
    from app.geo.content.md_to_html import markdown_to_publish_html
    md=publication_body();html='<h1>Selection guide</h1>'+markdown_to_publish_html(md,wrap_article=False)
    assert match_publication('Selection guide',md,html)['matched_passages']>=3
    for bad in ['<h1>Selection guide</h1>', '<h1>Selection guide</h1><script>'+md+'</script>', '<h1>Selection guide</h1><div hidden>'+md+'</div>', '<h1>Selection guide</h1><div style="display:none">'+md+'</div>']:
        with pytest.raises(HTTPException): match_publication('Selection guide',md,bad)
    assert visible_text('<div hidden><span hidden>x</span></div><p>real</p>')=='real'


def test_publication_rejects_other_tenant_or_obsolete_version_without_fetch():
    async def run():
        for result in [None, (NS(status='published',published_url='https://example.com'),NS(article_version_id=1))]:
            session=NS(scalar=AsyncMock(side_effect=[NS(id=12),NS(id=2)]),execute=AsyncMock(return_value=NS(first=lambda:result)))
            with patch('app.geo.publication_evidence.safe_fetch',AsyncMock()) as fetch:
                with pytest.raises(HTTPException): await verify_publication(session,baseline_task(),99)
                fetch.assert_not_awaited()
            sql=str(session.execute.call_args.args[0])
            assert 'geo_content_tasks.tenant_id' in sql and 'FOR UPDATE' in sql
    asyncio.run(run())


def test_changed_baseline_cannot_complete_or_persist_evidence():
    async def run():
        row=task();fresh=deepcopy(row.baseline_snapshot);fresh['metrics']=[]
        session=NS(commit=AsyncMock())
        with patch('app.geo.integration.ticket',AsyncMock(return_value=row)),patch('app.geo.integration.snapshot',AsyncMock(side_effect=[state(),fresh])):
            with pytest.raises(HTTPException): await update_task(10,TaskUpdate(status='done'),7,NS(ensure_tenant=lambda _:None),session)
        assert row.status=='doing' and not row.progress
        session.commit.assert_not_awaited()
    asyncio.run(run())


def test_public_connection_uses_validated_ip_host_and_sni_and_decodes_once():
    async def run():
        requests=[]
        def handle(req):
            requests.append(req)
            return httpx.Response(200,headers={'Content-Encoding':'gzip'},content=gzip.compress(b'{"ok":true}'))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            with patch('app.geo.content.connectors.safe_http._ensure_public_host',AsyncMock(return_value=['93.184.216.34'])) as resolve:
                resp=await public_request(client,'POST','https://publish.example/api',headers={'Host':'evil'},json={'hello':1})
        assert resp.json()=={'ok':True}
        req=requests[0]
        assert req.url.host=='93.184.216.34' and req.headers['host']=='publish.example'
        assert req.extensions['sni_hostname']=='publish.example'
        resolve.assert_awaited_once_with('https://publish.example/api')
    asyncio.run(run())


@pytest.mark.parametrize('url',['http://127.0.0.1/a','https://user:secret@example.com/a','file:///etc/passwd','https://127.0.0.1/a','https://169.254.169.254/a'])
def test_unsafe_publish_destinations_never_connect(url):
    async def run():
        transport=Mock(side_effect=AssertionError('must not connect'))
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            with pytest.raises(httpx.HTTPError): await public_request(client,'POST',url)
        transport.assert_not_called()
    asyncio.run(run())


def test_redirect_not_followed_and_body_size_bounded():
    async def run():
        for status,body in [(302,b''),(200,b'x'*100)]:
            calls=[]
            def handle(req):
                calls.append(req);return httpx.Response(status,headers={'Location':'https://127.0.0.1/'},content=body)
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
                if status==302:
                    assert (await public_request(client,'GET','https://example.com',addresses=['93.184.216.34'])).status_code==302
                else:
                    with pytest.raises(httpx.HTTPError): await public_request(client,'GET','https://example.com',addresses=['93.184.216.34'],max_bytes=20)
            assert len(calls)==1
    asyncio.run(run())


def test_production_cannot_mint_mock_publication_tokens():
    from app.geo.content.connectors.wechat_mp import wechat_mp_mock_enabled
    from app.geo.content.connectors.oauth2 import exchange_code_for_tokens, refresh_access_token, OAuth2Error
    with patch('app.geo.content.connectors.safe_http.development_mode',return_value=False):
        assert not wechat_mp_mock_enabled('mock_test')
        creds=dict(token_url='https://mock.example/token',client_id='mock_client',client_secret='test',refresh_token='test')
        with pytest.raises(OAuth2Error): asyncio.run(exchange_code_for_tokens(creds,code='test'))
        with pytest.raises(OAuth2Error): asyncio.run(refresh_access_token(creds))


def test_weekly_trend_rejects_different_sampling_weights_and_question_text():
    from test_geo_integration import samples
    from app.geo.integration_metrics import build_weekly_snapshot
    before=samples(20);after=samples(27,mention=True,start_id=20)
    after.append(NS(**vars(after[0])))
    result=build_weekly_snapshot(before+after,['brand.example'],date(2026,8,31))
    assert all(m['trend_7d'] is None for m in result['metrics'])
    after.pop();after[0]._source_question='changed question'
    result=build_weekly_snapshot(before+after,['brand.example'],date(2026,8,31))
    assert all(m['trend_7d'] is None for m in result['metrics'])


def test_duplicate_worker_cannot_repeat_ai_calls():
    from app.geo.content.patrol import execute_patrol_run
    async def run():
        row=NS(status='running')
        session=NS(get=AsyncMock(return_value=row),refresh=AsyncMock(),commit=AsyncMock())
        with patch('app.geo.content.patrol.run_probe_draft',AsyncMock()) as probe:
            assert await execute_patrol_run(session,42) is row
            probe.assert_not_awaited()
        session.refresh.assert_awaited_once_with(row,with_for_update=True)
    asyncio.run(run())


def test_executor_calls_only_exact_sparse_matrix():
    from app.geo.content.patrol import execute_patrol_run
    async def run():
        plan=plan_from_baseline(baseline_task());plan['window_end']='2099-01-01T00:00:00'
        row=NS(id=42,tenant_id=7,status='pending',summary={'contract_plan':plan},auto_persist=False,prefer_real=True,engine_keys=['deepseek','kimi'],prompt_limit=2)
        tenant=NS(id=7,name='Acme',brand_terms=['Acme'])
        prompts=[NS(id=i,question=q,status='active',is_brand_probe=False) for i,q in [[1,'question one'],[2,'question two']]]
        engines=[NS(engine_key=e,enabled=True) for e in ['deepseek','kimi']]
        session=NS(get=AsyncMock(side_effect=[row,tenant]),refresh=AsyncMock(),commit=AsyncMock(),scalars=AsyncMock(side_effect=[engines,prompts]),scalar=AsyncMock(return_value=None))
        draft=dict(raw_text='real answer',sample_mode='openai_compat',simulated=False,suggested_mentions_brand=False,analysis_status='completed')
        with patch('app.geo.content.ai_settings.resolve_llm_credentials',AsyncMock(return_value={'api_key':'test'})),patch('app.geo.content.patrol.resolve_engine_llm',return_value=({'api_key':'test','model':'test-model','provider':'test-provider'},'openai_compat',None)),patch('app.geo.content.patrol.run_probe_draft',AsyncMock(return_value=draft)) as probe:
            result=await execute_patrol_run(session,42)
        assert result.status=='completed', result.error
        assert [(c.kwargs['question'],c.kwargs['engine']) for c in probe.await_args_list]==[('question one','deepseek'),('question one','deepseek'),('question one','kimi')]+[('question two','deepseek')]*3
        assert not result.summary['retest_result']['comparable']  # No persisted snapshot IDs means no evidence.
    asyncio.run(run())


@pytest.mark.parametrize('field', ['_source_model', '_source_provider'])
def test_model_drift_preserves_values_but_blocks_trend_and_completion(field):
    from test_geo_integration import samples
    from app.geo.integration_metrics import build_weekly_snapshot, MENTIONS
    before=samples(20);after=samples(27,mention=True,start_id=20)
    setattr(after[0],field,'changed')
    current=build_weekly_snapshot(before+after,['brand.example'],date(2026,8,31))
    assert next(m for m in current['metrics'] if m['metric_key']==MENTIONS)['value']==12
    assert all(m['trend_7d'] is None for m in current['metrics'])
    with pytest.raises(HTTPException): completion_evidence(task(),current)


def test_missing_model_history_and_mixed_versions_cannot_be_guessed():
    row=baseline_task();row.baseline_snapshot.pop('model_counts')
    with pytest.raises(HTTPException): plan_from_baseline(row)
    row=baseline_task();row.baseline_snapshot['model_counts'].append([1,'deepseek','other','other',1])
    with pytest.raises(HTTPException): plan_from_baseline(row)


def test_model_preflight_refuses_changed_provider_before_request():
    from app.geo.retest import validate_plan_model
    plan=plan_from_baseline(baseline_task())
    validate_plan_model(plan,1,'deepseek',{'provider':'test-provider','model':'test-model'})
    with pytest.raises(ValueError): validate_plan_model(plan,1,'deepseek',{'provider':'other','model':'test-model'})


@pytest.mark.parametrize('window_blocked', [False, True])
def test_execution_readiness_checks_actual_window_without_writes(window_blocked):
    from app.geo.integration import execution_readiness
    async def run():
        row=task();session=NS(commit=AsyncMock(),flush=AsyncMock())
        effects=[{'total_samples':12},HTTPException(409,'waiting for publication week') if window_blocked else {'total_samples':12}]
        with patch('app.geo.integration.ticket',AsyncMock(return_value=row)),patch('app.geo.retest.prepare_retest',AsyncMock(side_effect=effects)) as prepare,patch('app.geo.content.multi_push.tenant_auto_push_matrix',AsyncMock(return_value={'ready_count':0})):
            result=await execution_readiness(10,7,NS(ensure_tenant=lambda _:None),session)
        assert result['baseline_valid'] and result['can_retest'] is (not window_blocked)
        assert prepare.await_args_list[0].kwargs['check_window'] is False
        assert prepare.await_args_list[1].kwargs['check_window'] is True
        session.commit.assert_not_awaited();session.flush.assert_not_awaited()
    asyncio.run(run())


def test_readiness_retest_record_is_tenant_scoped():
    from app.geo.integration import execution_readiness
    async def run():
        row=task();row.progress={'retest_runs':{'2026-09-06T16:00:00':88}}
        session=NS(scalar=AsyncMock(return_value=NS(id=88,status='failed',summary={'retest_result':{'comparable':False}},error='failed sample')))
        with patch('app.geo.integration.ticket',AsyncMock(return_value=row)),patch('app.geo.retest.prepare_retest',AsyncMock(side_effect=HTTPException(409,'blocked'))),patch('app.geo.content.multi_push.tenant_auto_push_matrix',AsyncMock(return_value={'ready_count':0})):
            result=await execution_readiness(10,7,NS(ensure_tenant=lambda _:None),session)
        assert 'tenant_id' in str(session.scalar.call_args.args[0])
        assert result['latest_retest']['status']=='failed' and not result['can_retest']
    asyncio.run(run())



def test_publication_choices_use_current_version_and_tenant():
    from app.geo.integration import execution_readiness
    async def run():
        row=task();row.progress_first['params']['content_task_id']=12
        session=NS(scalar=AsyncMock(return_value=15),execute=AsyncMock(return_value=NS(all=lambda:[(NS(id=99,published_url='https://example.com'), 'website')])) )
        with patch('app.geo.integration.ticket',AsyncMock(return_value=row)),patch('app.geo.retest.prepare_retest',AsyncMock(side_effect=HTTPException(409,'blocked'))),patch('app.geo.content.multi_push.tenant_auto_push_matrix',AsyncMock(return_value={'ready_count':0})):
            result=await execution_readiness(10,7,NS(ensure_tenant=lambda _:None),session)
        assert result['publication_candidates']==[{'id':99,'channel':'website','url':'https://example.com'}]
        sql=str(session.execute.call_args.args[0]); assert 'tenant_id' in sql and 'article_version_id' in sql
    asyncio.run(run())
