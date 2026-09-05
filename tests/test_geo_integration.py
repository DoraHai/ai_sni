import asyncio
from copy import deepcopy
from datetime import date, datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch, Mock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from app.geo.integration_metrics import build_weekly_snapshot, closed_week_end, competitor_key, MENTIONS, SCORE, metric_dictionary
from app.geo.integration import TaskCreate, TaskUpdate, completion_evidence, task_payload, create_task, update_task, metrics_snapshot
from app.models import GeoActionTicket


def samples(day, *, mention=False, start_id=1):
    return [NS(id=start_id+i, prompt_id=i%3+1, engine=['a','b'][i%2], captured_at=datetime(2026,8,day),
               mentions_brand=mention, cited_urls=['https://brand.example/page'] if mention else [],
               competitors=['Rival','RIVAL'] if mention else [], sample_mode='openai_compat', simulated=False,
               note='method=unprimed_json_v2 analysis=completed', citation_accuracy='unknown',
               _source_provider='test-provider', _source_model='test-model') for i in range(12)]


def state():
    return build_weekly_snapshot(samples(20)+samples(27,mention=True,start_id=20), ['brand.example'], date(2026,8,31))


def metric_map(value):
    return {m['metric_key']:m for m in value['metrics']}


def task():
    return GeoActionTicket(id=10,tenant_id=7,title='改进品牌回答',advice_code='cockpit:v1:task',status='doing',
        created_at=datetime(2026,8,23,15),updated_at=datetime(2026,8,23,15),
        progress_first={'action_type':'improve_content','params':{'metric_key':MENTIONS},'created_by':'cockpit','assignee_role':'geo_operator'},
        baseline_snapshot=build_weekly_snapshot(samples(20), ['brand.example'], date(2026,8,24)),progress={})


def test_week_boundaries_and_exact_five_field_contract():
    assert closed_week_end(date(2026,9,5)) == date(2026,8,31)
    result=state(); values=metric_map(result)
    for m in result['metrics']:
        assert set(m)=={'metric_key','value','unit','as_of','trend_7d'}
        assert m['as_of']=='2026-08-31T00:00:00+08:00'
    assert values[MENTIONS]['value']==12 and values[MENTIONS]['trend_7d']=={'direction':'up','change_pct':None,'change_abs':12}
    assert values[SCORE]['value']==100 and values[SCORE]['trend_7d']=={'direction':'up','change_pct':None,'change_abs':100}
    assert values[competitor_key('rival')]['value']==12
    assert set(values) <= set(metric_dictionary(result['competitor_names']))


def test_utc_boundary_excludes_next_week_and_includes_start():
    rows=samples(27)
    rows[0].captured_at=datetime(2026,8,23,16)
    rows[1].captured_at=datetime(2026,8,30,16)
    result=build_weekly_snapshot(rows,['brand.example'],date(2026,8,31))
    assert rows[0].id in result['sample_ids']
    assert rows[1].id not in result['sample_ids']


@pytest.mark.parametrize('field,value',[('simulated',True),('sample_mode','manual'),('note','method=unprimed_json_v2 analysis=needs_review'),('citation_accuracy','inaccurate'),('is_brand_probe',True)])
def test_unqualified_samples_never_enter_metrics(field,value):
    rows=samples(27,mention=True)
    for row in rows: setattr(row,field,value)
    result=build_weekly_snapshot(rows,['brand.example'],date(2026,8,31))
    assert result['sample_ids']==[]
    assert all(m['value'] is None for m in result['metrics'])


def test_missing_domains_and_changed_cohort_do_not_invent_trends():
    rows=samples(20)+samples(27,mention=True,start_id=20)
    rows[-1].engine='new_engine'
    values=metric_map(build_weekly_snapshot(rows,[],date(2026,8,31)))
    assert values[SCORE]['value'] is None
    assert values[MENTIONS]['trend_7d'] is None


def test_competitors_are_not_truncated_before_weekly_counts():
    rows=samples(27,mention=True)
    for row in rows: row.competitors=[f'Rival{i}' for i in range(20)]
    result=build_weekly_snapshot(rows,['brand.example'],date(2026,8,31))
    assert len(result['competitor_names'])==20


def test_completion_contains_actual_changes_and_traceable_samples():
    evidence=completion_evidence(task(),state())
    assert evidence['delta']==12
    assert evidence['before_sample_counts'] == evidence['after_sample_counts']
    assert len(evidence['before_snapshot_ids'])==12
    assert len(evidence['after_snapshot_ids'])==12
    row=task();row.progress={'completion_evidence':evidence};row.status='done'
    assert set(task_payload(row))=={'id','module','action_type','title','params','status','created_by','assignee_role','completion_evidence','created_at','updated_at'}


@pytest.mark.parametrize('reason',['same_week','null','no_change','domains','cohort','before_creation'])
def test_completion_rejects_unverifiable_claims(reason):
    row=task();current=state()
    if reason=='same_week': row.baseline_snapshot=current
    if reason=='null': metric_map(current)[MENTIONS]['value']=None
    if reason=='no_change': metric_map(current)[MENTIONS]['value']=0
    if reason=='domains': current['own_domains']=[]
    if reason=='cohort': current['cohort']=[]
    if reason=='before_creation': row.created_at=datetime(2026,8,25)
    with pytest.raises(HTTPException): completion_evidence(row,current)


def test_input_cannot_forge_completion_or_invalid_target():
    with pytest.raises(ValidationError): TaskUpdate(status='done',completion_evidence={'delta':100})
    for value in [True,float('nan'),float('inf'),-1]:
        with pytest.raises(ValidationError): TaskCreate(action_type='improve',title='test',assignee_role='operator',params={'min_delta':value})


def test_create_stores_adapter_in_existing_ticket_without_spoofing_creator():
    session=NS(add=Mock(),commit=AsyncMock(),refresh=AsyncMock())
    req=TaskCreate(action_type='improve',title='test',assignee_role='operator',created_by=999)
    async def run():
        with patch('app.geo.integration.snapshot',AsyncMock(return_value=state())):
            return await create_task(req,7,NS(user_id=3,ensure_tenant=lambda t:None),session)
    with pytest.raises(HTTPException) as exc: asyncio.run(run())
    assert exc.value.status_code==403
    session.commit.assert_not_awaited()


def test_failed_completion_never_commits_or_changes_status():
    row=task();bad=state();metric_map(bad)[MENTIONS]['value']=0
    session=NS(commit=AsyncMock(),refresh=AsyncMock())
    async def run():
        with patch('app.geo.integration.ticket',AsyncMock(return_value=row)),patch('app.geo.integration.snapshot',AsyncMock(return_value=bad)):
            await update_task(10,TaskUpdate(status='done'),7,NS(ensure_tenant=lambda t:None),session)
    with pytest.raises(HTTPException): asyncio.run(run())
    assert row.status=='doing' and not row.progress
    session.commit.assert_not_awaited()


def test_metric_read_does_not_commit_and_checks_tenant_first():
    session=NS(commit=AsyncMock())
    async def run():
        with patch('app.geo.integration.snapshot',AsyncMock(return_value=state())) as load:
            result=await metrics_snapshot(7,None,NS(ensure_tenant=lambda t:None),session)
            assert result==state()['metrics']
            load.assert_awaited_once()
    asyncio.run(run());session.commit.assert_not_awaited()
    def deny(t): raise HTTPException(403,'tenant')
    with pytest.raises(HTTPException): asyncio.run(metrics_snapshot(8,None,NS(ensure_tenant=deny),session))


@pytest.mark.parametrize('value,previous,expected',[(12,10,{'direction':'up','change_pct':20.0,'change_abs':2}),
    (5,10,{'direction':'down','change_pct':-50.0,'change_abs':-5}),
    (10,10,{'direction':'flat','change_pct':0.0,'change_abs':0}),
    (0,0,{'direction':'flat','change_pct':None,'change_abs':0}), (10,None,None)])
def test_shared_trend_contract(value,previous,expected):
    from app.geo.integration_metrics import metric_trend
    assert metric_trend(value,previous)==expected


@pytest.mark.parametrize('tamper',[None,'raw','mention','urls','competitors','time','run','mode'])
def test_metric_source_requires_matching_server_patrol(tamper):
    from app.geo.integration_metrics import verified_patrol_rows
    row=NS(id=1,patrol_run_id=2,prompt_id=3,engine='a',captured_at=datetime(2026,8,27,12),
           raw_text='Original answer',mentions_brand=True,cited_urls=[],competitors=['Rival'])
    cell=dict(snapshot_id=1,prompt_id=3,engine='a',ok=True,sample_mode='openai_compat',simulated=False,
              sampling_method='unprimed_json_v2',analysis_status='completed',raw_text='Original answer',
              suggested_mentions_brand=True,competitors=['Rival'])
    run=NS(id=2,status='completed',started_at=datetime(2026,8,27,11),finished_at=datetime(2026,8,27,13),items=[cell])
    if tamper=='raw': row.raw_text='Manually replaced'
    if tamper=='mention': row.mentions_brand=False
    if tamper=='urls': row.cited_urls=['https://injected.example']
    if tamper=='competitors': row.competitors=['Other']
    if tamper=='time': row.captured_at=datetime(2026,8,20)
    if tamper=='run': row.patrol_run_id=None
    if tamper=='mode': cell['sample_mode']='mock_persona'
    assert bool(verified_patrol_rows([row],[run])) == (tamper is None)


def test_http_task_and_snapshot_contract_and_permissions():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.geo.integration import router
    from app.database import get_session
    from app.security.auth import require_scoped_auth, _required
    app=FastAPI();app.include_router(router,prefix='/api/v1/geo')
    ctx=NS(user_id=3,ensure_tenant=lambda value: None)
    def scoped(value):
        if value!=7: raise HTTPException(403,'tenant')
    ctx.ensure_tenant=scoped
    rows=[]
    session=NS(commit=AsyncMock(),refresh=AsyncMock())
    def add(row): row.id=10;rows.append(row)
    async def scalar(query):
        params=query.compile().params
        return rows[0] if rows and params.get('id_1')==10 and params.get('tenant_id_1')==7 else None
    session.add=add;session.scalar=scalar;session.get=AsyncMock(return_value=NS(id=7))
    app.dependency_overrides[require_scoped_auth]=lambda:ctx
    app.dependency_overrides[get_session]=lambda:session
    with patch('app.geo.integration.snapshot',AsyncMock(return_value=state())),TestClient(app) as client:
        response=client.post('/api/v1/geo/integration/tasks?tenant_id=7',json={'action_type':'improve','title':'修复内容','assignee_role':'editor','params':{'metric_key':MENTIONS}})
        assert response.status_code==201,response.text
        body=response.json();assert body['module']=='geo' and body['created_by']==3 and body['status']=='open'
        assert body['completion_evidence'] is None
        response=client.get('/api/v1/geo/integration/tasks/10?tenant_id=7')
        assert response.status_code==200
        assert client.get('/api/v1/geo/integration/tasks/10?tenant_id=8').status_code==403
        assert client.patch('/api/v1/geo/integration/tasks/10?tenant_id=7',json={'status':'done','completion_evidence':{'value':100}}).status_code==422
        assert client.patch('/api/v1/geo/integration/tasks/10?tenant_id=7',json={'status':'done'}).status_code==409
        assert client.patch('/api/v1/geo/integration/tasks/10?tenant_id=7',json={'status':'in_progress'}).json()['status']=='in_progress'
        before=session.commit.await_count
        result=client.get('/api/v1/geo/integration/metrics/snapshot?tenant_id=7')
        assert result.status_code==200 and isinstance(result.json(),list)
        assert session.commit.await_count==before
        assert client.get('/api/v1/geo/integration/tasks/99?tenant_id=7').status_code==404
    assert _required('/api/v1/geo/integration/tasks','POST')==({'geo.content'},True)
    assert _required('/api/v1/geo/integration/metrics/snapshot','GET')==({'geo.content'},False)


def test_tracked_competitor_remains_a_zero_metric_without_recent_mentions():
    result=build_weekly_snapshot(samples(27),['brand.example'],date(2026,8,31),tracked_names=['rival'])
    assert metric_map(result)[competitor_key('rival')]['value']==0


def test_verified_task_completion_persists_actual_evidence():
    row=task();session=NS(commit=AsyncMock(),refresh=AsyncMock())
    async def run():
        with patch('app.geo.integration.ticket',AsyncMock(return_value=row)) as lookup,patch('app.geo.integration.snapshot',AsyncMock(side_effect=[state(), row.baseline_snapshot])):
            result=await update_task(10,TaskUpdate(status='done'),7,NS(ensure_tenant=lambda value:None),session)
            lookup.assert_awaited_once_with(session,7,10,lock=True)
            return result
    result=asyncio.run(run())
    assert result['status']=='done' and result['completion_evidence']['delta']==12
    assert 'tenant_id=7' in result['completion_evidence']['source']
    session.commit.assert_awaited_once()


def test_openapi_documents_shared_shapes():
    from fastapi import FastAPI
    from app.geo.integration import router
    app=FastAPI();app.include_router(router,prefix='/api/v1/geo')
    schemas=app.openapi()['components']['schemas']
    assert set(schemas['MetricTrend']['properties'])=={'direction','change_pct','change_abs'}
    assert set(schemas['MetricSnapshot']['properties'])=={'metric_key','value','unit','as_of','trend_7d'}
    assert len(schemas['TaskContract']['properties'])==11


def test_database_loader_filters_server_source_and_scopes_every_query():
    from app.geo.integration_metrics import load_weekly_snapshot
    rows=samples(27,mention=True)
    for row in rows:
        row.raw_text='Original';row.cited_urls=[];row.patrol_run_id=2
    cells=[dict(snapshot_id=row.id,prompt_id=row.prompt_id,engine=row.engine,ok=True,sample_mode='openai_compat',
        simulated=False,sampling_method='unprimed_json_v2',analysis_status='completed',raw_text='Original',
        suggested_mentions_brand=True,competitors=row.competitors) for row in rows]
    run=NS(id=2,status='completed',started_at=datetime(2026,8,26),finished_at=datetime(2026,8,28),items=cells)
    session=NS(scalars=AsyncMock(side_effect=[rows,[run],[NS(base_url='https://brand.example')],[{competitor_key('tracked'):'tracked'}]]),commit=AsyncMock())
    result=asyncio.run(load_weekly_snapshot(session,7,date(2026,8,31)))
    assert metric_map(result)[MENTIONS]['value']==12
    assert metric_map(result)[competitor_key('tracked')]['value']==0
    for call in session.scalars.await_args_list:
        params=call.args[0].compile().params
        assert params['tenant_id_1']==7
    session.commit.assert_not_awaited()


@pytest.mark.parametrize('direction', [[], {}, ['increase'], 1, None])
def test_invalid_direction_is_a_validation_error(direction):
    with pytest.raises(ValidationError):
        TaskCreate(action_type='improve', title='test', assignee_role='operator',
                   params={'direction': direction})


@pytest.mark.parametrize('week_end', [date(1, 1, 1), date(1, 1, 8), date(1, 1, 15)])
def test_early_week_rejected_before_database_read(week_end):
    from app.geo.integration import snapshot
    session = NS(scalars=AsyncMock())
    with pytest.raises(HTTPException) as exc:
        asyncio.run(snapshot(session, 7, week_end))
    assert exc.value.status_code == 400
    session.scalars.assert_not_awaited()


def test_more_sampling_cannot_complete_a_task_with_unchanged_mention_rate():
    row = task()
    row.baseline_snapshot = build_weekly_snapshot(samples(20, mention=True), ['brand.example'], date(2026, 8, 24))
    current = build_weekly_snapshot(samples(27, mention=True) + samples(27, mention=True, start_id=20),
                                    ['brand.example'], date(2026, 8, 31))
    assert row.baseline_snapshot['cohort'] == current['cohort']
    assert metric_map(current)[MENTIONS]['value'] == 24
    with pytest.raises(HTTPException) as exc:
        completion_evidence(row, current)
    assert exc.value.status_code == 409


def test_missing_sampling_distribution_cannot_complete_legacy_task():
    row = task()
    row.baseline_snapshot.pop('sample_counts')
    with pytest.raises(HTTPException) as exc:
        completion_evidence(row, state())
    assert exc.value.status_code == 409


def test_same_total_with_changed_sample_weights_cannot_complete_task():
    rows = samples(27, mention=True)
    rows[0].prompt_id = 3
    current = build_weekly_snapshot(rows, ['brand.example'], date(2026, 8, 31))
    row = task()
    assert row.baseline_snapshot['cohort'] == current['cohort']
    assert len(row.baseline_snapshot['sample_ids']) == len(current['sample_ids'])
    with pytest.raises(HTTPException) as exc:
        completion_evidence(row, current)
    assert exc.value.status_code == 409


@pytest.mark.parametrize('content_status', [None, 'archived'])
def test_create_rejects_missing_or_archived_link_before_reading_metrics(content_status):
    session = NS(get=AsyncMock(return_value=NS(id=7)), scalar=AsyncMock(
        return_value=None if content_status is None else NS(status=content_status)), commit=AsyncMock())
    req = TaskCreate(action_type='improve', title='test', assignee_role='operator', params={'content_task_id': 12})
    with patch('app.geo.integration.snapshot', AsyncMock()) as load:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(create_task(req, 7, NS(user_id=3, ensure_tenant=lambda t: None), session))
    assert exc.value.status_code == (404 if content_status is None else 409)
    load.assert_not_awaited()
    session.commit.assert_not_awaited()
    query = str(session.scalar.call_args.args[0])
    assert 'geo_content_tasks.tenant_id' in query and 'FOR UPDATE' in query


@pytest.mark.parametrize('same_request', [True, False])
def test_linked_create_reuses_identical_active_task_and_rejects_conflicting_goal(same_request):
    row = task()
    row.progress_first['params']['content_task_id'] = 12
    req = TaskCreate(action_type='improve_content', title=row.title,
        assignee_role='geo_operator', params=deepcopy(row.progress_first['params']))
    if not same_request:
        req.params['min_delta'] = 99
    session = NS(get=AsyncMock(return_value=NS(id=7)), scalar=AsyncMock(return_value=NS(status='ready')),
        scalars=AsyncMock(return_value=[row]), add=Mock(), commit=AsyncMock())
    async def run():
        return await create_task(req, 7, NS(user_id=None, ensure_tenant=lambda t: None), session)
    with patch('app.geo.integration.snapshot', AsyncMock()) as load:
        if same_request:
            assert asyncio.run(run())['id'] == row.id
        else:
            with pytest.raises(HTTPException) as exc:
                asyncio.run(run())
            assert exc.value.status_code == 409
    load.assert_not_awaited()
    session.add.assert_not_called()
    session.commit.assert_not_awaited()


def test_linked_create_saves_real_baseline_and_content_reference():
    session = NS(get=AsyncMock(return_value=NS(id=7)), scalar=AsyncMock(return_value=NS(status='ready')),
        scalars=AsyncMock(return_value=[]), add=Mock(), commit=AsyncMock(), refresh=AsyncMock())
    def assign_id(row): row.id = 21
    session.add.side_effect = assign_id
    req = TaskCreate(action_type='improve_content', title='验证文章', assignee_role='geo_operator',
        params={'content_task_id': 12, 'metric_key': MENTIONS, 'min_delta': 1})
    with patch('app.geo.integration.snapshot', AsyncMock(return_value=state())):
        result = asyncio.run(create_task(req, 7, NS(user_id=3, ensure_tenant=lambda t: None), session))
    assert result['params']['content_task_id'] == 12
    assert result['completion_evidence'] is None and result['created_by'] == 3
    assert result['status'] == 'open'
    session.commit.assert_awaited_once()


@pytest.mark.parametrize('metric_key', [SCORE, 'geo.visibility.ai_mention_rate_7d'])
def test_task_rejects_impossible_bounded_metric_delta(metric_key):
    for direction in ['increase', 'decrease']:
        with pytest.raises(ValidationError, match='不能超过 100'):
            TaskCreate(action_type='improve', title='test', assignee_role='operator',
                params={'metric_key': metric_key, 'direction': direction, 'min_delta': 100.01})
    TaskCreate(action_type='improve', title='test', assignee_role='operator',
        params={'metric_key': metric_key, 'min_delta': 100})
    TaskCreate(action_type='improve', title='test', assignee_role='operator',
        params={'metric_key': MENTIONS, 'min_delta': 101})
