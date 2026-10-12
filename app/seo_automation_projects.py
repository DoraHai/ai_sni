"""SEO-only queue adapter for the shared automation control library."""
from copy import deepcopy
import logging

from fastapi import HTTPException
from sqlalchemy import select,text

from app import automation_projects as core
from app import automation_project_v2 as v2, seo_automation_sources as sources
from app.api import seo_automation_projects as api, seo_onsite_ai as queue
from app.database import async_session_factory
from app.models.seo_cockpit import SeoTask
from app.security.auth import AuthContext
from app.config import get_settings
from app.seo_demo_runtime import seo_scheduler_may_start

logger=logging.getLogger(__name__)


async def lock_managed(db,task_id,tenant_id,site_id,request_id):
    """Discover token without site locks; project always locks before site/task."""
    params=await db.scalar(select(SeoTask.params).where(SeoTask.id==task_id,SeoTask.tenant_id==tenant_id,
        SeoTask.site_id==site_id,SeoTask.module=='seo',SeoTask.action_type==queue.onsite.ACTION_TYPE))
    if params is None:
        # The worker's scoped row check will stop; the project reconciler owns
        # missing/moved child settlement without reading its new scope.
        return None
    request=((params or {}).get('onsite_ai_requests') or {}).get(request_id) or {}
    token=deepcopy(request.get('automation_token'))
    if token is None:
        # An erased child marker cannot turn a managed request into a manual
        # call. Legacy installations with no automation tables remain supported.
        installed=await db.scalar(text('''SELECT EXISTS(SELECT 1 FROM information_schema.tables
            WHERE table_schema=current_schema() AND table_name=ANY(:tables))'''),{'tables':list(core.TABLES)})
        if not installed:
            await v2.check_legacy(db,core.scope('seo',tenant_id,site_id),'onsite_ai')
            return None
        await core.require_schema(db)
        match=(await db.execute(text('''SELECT r.id,r.generation,r.configuration,s.value AS step
            FROM automation_project_runs r CROSS JOIN LATERAL jsonb_array_elements(r.steps) s(value)
            WHERE r.module='seo' AND r.tenant_id=:tenant AND r.scope_id=:site
            AND s.value->>'request_id'=:request AND s.value->>'task_id'=:task LIMIT 1'''),
            {'tenant':tenant_id,'site':site_id,'request':request_id,'task':str(task_id)})).mappings().first()
        if not match:
            await v2.check_legacy(db,core.scope('seo',tenant_id,site_id),'onsite_ai')
            return None
        token={**core.scope('seo',tenant_id,site_id),'run_id':str(match['id']),'generation':match['generation'],
            'step_key':match['step']['step_key'],'task_id':task_id,'request_id':request_id,
            'owner_user_id':match['configuration']['owner_user_id']}
        if match['step'].get('target'):
            token.update(operation=match['step']['operation'],target=match['step']['target'])
    if (token.get('module'),token.get('tenant_id'),token.get('scope_id'),token.get('task_id'),
            token.get('request_id'),token.get('owner_user_id')) != (
            'seo',tenant_id,site_id,task_id,request_id,request.get('actor_user_id')):
        raise core.problem('automation_scope_mismatch','持久化自动请求范围不一致',503)
    await core.require_schema(db)
    await core.read_project(db,core.scope('seo',tenant_id,site_id),lock=True)
    return token


async def fee_evidence(db,token,request):
    refs=[f"seo_task:{token['task_id']}"]
    if not request.get('started_at'):
        run=await core.read_run(db,core.scope('seo',token['tenant_id'],token['scope_id']),token['run_id'])
        step=next((s for s in run['steps'] if s['request_id']==token['request_id']),None) if run else None
        if not step or not step.get('dispatched_at'): return 'not_called',refs
    columns=set((await db.execute(text("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='api_usage_events'"))).scalars())
    if not {'id','tenant_id','module','job_ref','state','estimated_amount'} <= columns:
        return 'unknown_charge',refs
    from app.api_usage_review_basis import accounted_amount
    try:
        amount=await accounted_amount(db)
    except RuntimeError:
        return 'unknown_charge',refs
    job=f"site:{token['scope_id']}:onsite_ai_proposal:{token['task_id']}:{token['request_id']}"
    rows=list((await db.execute(text('SELECT id,state,'+amount+' AS amount FROM api_usage_events WHERE tenant_id=:tenant AND module=\'seo\' AND job_ref=:job ORDER BY id LIMIT 21'),
        {'tenant':token['tenant_id'],'job':job})).mappings())
    refs += ['api_event:'+str(row['id']) for row in rows[:20]]
    known=bool(rows) and len(rows)<=20 and all(row['state'] in {'succeeded','error'} and row['amount'] is not None for row in rows)
    return ('recorded' if known else 'unknown_charge'),refs


async def settle_request(db,token,request,*,late=False):
    if token is None: return
    state=request['state']
    if state in {'queued','running'}: return
    fee,refs=await fee_evidence(db,token,request)
    status={'ready':'succeeded','stale':'stale','unknown':'unknown','cancelled':'cancelled','failed':'failed'}[state]
    if token.get('target'):
        run=await core.read_run(db,core.scope('seo',token['tenant_id'],token['scope_id']),token['run_id'])
        step=next((s for s in run['steps'] if s['request_id']==token['request_id']),None)
        call=next((c for c in step.get('calls',[]) if c['call_key']=='primary'),None) if step else None
        if call and call['state'] in {'admitted','unknown'}:
            await v2.finish_call(db,token,'primary',state=status,fee_state=fee,evidence_refs=refs)
    error=(request.get('error') or {}).get('code')
    link=f"/api/v1/seo/workbench/onsite-tasks/{token['task_id']}/ai-requests/{token['request_id']}?tenant_id={token['tenant_id']}&site_id={token['scope_id']}"
    changed=await core.settle_step(db,token,status=status,error_code=error,evidence_refs=refs,
        fee_state=fee,result_links=[link] if state=='ready' else [])
    if not changed and late:
        await core.append_event(db,core.scope('seo',token['tenant_id'],token['scope_id']),run_id=token['run_id'],
            code='late_provider_receipt',step_key=token['step_key'],request_id=token['request_id'],fee_state=fee,evidence_refs=refs)


async def dispatch_project(key,*,sessions=None):
    """One bounded step; durable claim, event and child enqueue commit together."""
    sessions=sessions or async_session_factory
    external_token=None
    async with sessions() as db:
        await core.require_schema(db)
        project=await core.read_project(db,key,lock=True)
        if project is None: return
        # Reconcile terminal child records (e.g. manual cancel or prior worker exit).
        run=await core.read_run(db,key,project['current_run_id'],lock=True) if project['current_run_id'] else None
        if run:
            for step in run['steps']:
                if step['status']!='running': continue
                if step.get('target') and step.get('operation')!='onsite_ai':
                    from app.seo_automation_execution import recover
                    await recover(db,key,run,step)
                    continue
                row=await db.get(SeoTask,step['task_id'],populate_existing=True)
                child=((row.params or {}).get('onsite_ai_requests') or {}).get(step['request_id']) if row and (row.tenant_id,row.site_id)==(key['tenant_id'],key['scope_id']) else None
                marker=child.get('automation_token') if child else None
                expected={**key,'run_id':str(run['id']),'step_key':step['step_key'],'task_id':step['task_id'],
                    'request_id':step['request_id'],'owner_user_id':run['configuration']['owner_user_id']}
                if isinstance(marker,dict) and all(marker.get(k)==v for k,v in expected.items()):
                    await settle_request(db,marker,child)
                else:
                    # Queue creation is atomic with the shared claim. A missing
                    # scoped child now means deletion/scope change, never retry.
                    token={**key,'run_id':str(run['id']),'generation':run['generation'],
                        'step_key':step['step_key'],'task_id':step['task_id'],
                        'request_id':step['request_id'],'owner_user_id':project['owner_user_id']}
                    fee,refs=await fee_evidence(db,token,{'started_at':step.get('dispatched_at')})
                    await core.settle_step(db,token,status='unknown',error_code='automation_child_scope_changed',
                        fee_state=fee,evidence_refs=refs)
        project=await core.read_project(db,key,lock=True)
        ctx=AuthContext(project['owner_user_id'],'','',None,{})
        if project['state']=='idle' and project['cycle_enabled'] and project['next_due_at'] and project['next_due_at']<=core.now():
            site,_=await api.scoped(db,ctx,key['tenant_id'],key['scope_id'])
            queue.execution_enabled(site)
            if project['configuration'].get('contract_version')==2:
                await sources.validate(db,site,project['configuration'],lock=True,configuring=True)
            await core.start_run(db,key,project,actor_kind='system')
        token=await core.claim_step(db,key)
        if token is not None:
            try:
                if token.get('target'):
                    site,_=await api.scoped(db,ctx,key['tenant_id'],key['scope_id'])
                    await sources.validate_token(db,token,site,lock=False)
                    if token['operation']!='onsite_ai':
                        external_token=token
                        await db.commit()
                        break_dispatch=True
                    else: break_dispatch=False
                else: break_dispatch=False
                # No site lock before enqueue's nonce lock; enqueue rechecks live
                # identity, module, assignment and quota under its normal locks.
                if not break_dispatch:
                    row=await db.get(SeoTask,token['task_id'],populate_existing=True)
                    if not row or (row.tenant_id,row.site_id)!=(key['tenant_id'],key['scope_id']) or not api.eligible(row):
                        raise core.problem('automation_task_ineligible','任务已处理或不可自动起草')
                    req=queue.Request(tenant_id=key['tenant_id'],site_id=key['scope_id'],request_id=token['request_id'],
                        expected_revision=row.params['onsite']['revision'],mode='initial')
                    await queue.enqueue_proposal(row.id,req,db,ctx,automation_token=token,commit=False)
            except HTTPException:
                await core.settle_step(db,token,status='blocked',error_code='automation_dispatch_blocked',fee_state='not_called')
        await db.commit()
    if external_token:
        from app.seo_automation_execution import execute
        await execute(external_token,sessions=sessions)


async def run_automation_projects(*,sessions=None):
    settings=get_settings()
    if not seo_scheduler_may_start(settings) or not settings.seo_external_actions_enabled: return
    sessions=sessions or async_session_factory
    async with sessions() as db:
        if not await core.schema_ready(db): return
        keys=[core.scope('seo',row.tenant_id,row.scope_id) for row in (await db.execute(text("""SELECT p.tenant_id,p.scope_id
            FROM automation_projects p LEFT JOIN automation_project_runs r
            ON r.id=p.current_run_id AND r.module=p.module AND r.tenant_id=p.tenant_id AND r.scope_id=p.scope_id
            WHERE p.module='seo' AND ((p.state='active' AND r.state IN ('queued','running'))
            OR p.state IN ('pausing','taking_over','ending') OR
            (p.state='idle' AND p.cycle_enabled AND p.next_due_at<=CURRENT_TIMESTAMP))
            ORDER BY p.updated_at,p.scope_id LIMIT 20"""))).all()]
    for key in keys:
        try:
            await dispatch_project(key,sessions=sessions)
        except Exception as exc:
            logger.warning('[SEO][automation] scope=%s failure_type=%s',key['scope_id'],type(exc).__name__)
