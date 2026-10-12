"""Bounded non-onsite v2 execution, reusing factual SEO collectors."""
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select

from app import automation_projects as core
from app import seo_automation_boundary as boundary
from app.models.seo import SeoRankSnapshot,SeoMetricSnapshot
from app.models.module_workspace import SeoSite


async def execute(token, *, sessions):
    key=core.scope('seo',token['tenant_id'],token['scope_id'])
    gate=boundary.Boundary(key,token['operation'],token,sessions)
    try:
        if token['operation']=='incremental_diagnosis':
            await execute_incremental(token,gate,sessions)
            return
        if token['operation'] in {'monthly_onsite_plan','monthly_report'}:
            await execute_draft_task(token,gate,sessions)
            return
        if token['operation']=='site_diagnosis':
            await execute_diagnosis(token,gate,sessions)
            return
        if token['operation']=='content_draft':
            await execute_content(token,gate,sessions)
            return
        if token['operation']=='indexation_collection':
            await execute_index(token,gate,sessions)
            return
        if token['operation']!='ranking_collect':
            raise core.problem('automation_operation_unsupported','该操作尚未接入')
        from app.api.seo import collect_rank_serp_for_tenant
        engine,device=token['target']['variant'].split('_')
        engine='360' if engine=='qihu360' else engine
        observed_at=datetime.now(timezone.utc).replace(tzinfo=None)
        async with sessions() as db:
            with boundary.use(gate):
                # The existing collector gates every actual HTTP via seo_serp and
                # revalidates the same token before writing any observation.
                result=await collect_rank_serp_for_tenant(session=db,tenant_id=key['tenant_id'],site_id=key['scope_id'],
                    keyword_ids=[token['target']['object_id']],devices=[device],max_keywords=1,engine=engine,
                    use_ai=False,captured_at=observed_at,commit=False)
            await gate.check(db)
            ids=list(await db.scalars(select(SeoRankSnapshot.id).where(
                SeoRankSnapshot.tenant_id==key['tenant_id'],SeoRankSnapshot.site_id==key['scope_id'],
                SeoRankSnapshot.keyword_id==token['target']['object_id'],SeoRankSnapshot.engine==engine,
                SeoRankSnapshot.device==device,SeoRankSnapshot.checked_at==observed_at)))
            run=await core.read_run(db,key,token['run_id'])
            step=next(s for s in run['steps'] if s['request_id']==token['request_id'])
            await core.settle_step(db,token,status='succeeded' if ids else 'blocked',
                error_code=None if ids else 'automation_rank_observation_unavailable',
                fee_state=step['fee_state'],evidence_refs=['seo_rank_snapshot:'+str(i) for i in ids],
                result_links=[f"/api/v1/seo/rank-serp/results?tenant_id={key['tenant_id']}&site_id={key['scope_id']}"] if ids else [])
            await db.commit()
    except Exception as exc:
        async with sessions() as db:
            await core.read_project(db,key,lock=True)
            await boundary.finish_deferred(db,gate)
            run=await core.read_run(db,key,token['run_id'],lock=True)
            step=next(s for s in run['steps'] if s['request_id']==token['request_id'])
            called=bool(step.get('calls'))
            code=exc.detail.get('code') if isinstance(exc,HTTPException) and isinstance(exc.detail,dict) else None
            stale=code in {'automation_step_stale','automation_generation_stale','automation_source_changed',
                'automation_owner_mismatch','automation_scope_mismatch','automation_not_active','automation_forbidden',
                'automation_target_invalid','automation_keyword_not_found','automation_page_not_found',
                'onsite_advisor_identity_expired','onsite_advisor_forbidden','onsite_ai_service_paused'} or (
                    isinstance(exc,HTTPException) and exc.status_code in {403,404})
            uncertain=any(c['state'] in {'admitted','unknown'} for c in step.get('calls',[])) or (called and not isinstance(exc,HTTPException))
            await core.settle_step(db,token,status='stale' if stale else 'unknown' if uncertain else 'blocked',
                error_code='automation_execution_stopped' if stale else 'automation_execution_unverified',
                fee_state=step['fee_state'])
            await db.commit()


async def execute_incremental(token,gate,sessions):
    from app.seo_service_workflows import reserve_service_workflow,execute_discovery,execute_diagnosis_page
    from app.models.seo_cockpit import SeoTask
    async with sessions() as db:
        await gate.check(db)
        site=await db.get(SeoSite,token['scope_id'])
        task,_=await reserve_service_workflow(db,site,'website',token['request_id'],token['owner_user_id'],scheduled=True)
        task.params={**task.params,'automation_token':token}
        ident=task.id
        await db.commit()
    with boundary.use(gate):
        await execute_discovery(ident,sessions=sessions)
        async with sessions() as db:
            await gate.check(db)
            task=await db.get(SeoTask,ident)
            pages=list((task.params.get('pages') or {}).keys())
            # Server plan bounded; the external-call gate remains authoritative.
            if len(pages)>20: raise core.problem('automation_page_limit','单轮最多检查 20 页')
            await db.commit()
        for _ in pages:
            await execute_diagnosis_page(ident,sessions=sessions)
    async with sessions() as db:
        await gate.check(db)
        task=await db.get(SeoTask,ident,populate_existing=True)
        pages=list((task.params.get('pages') or {}).values())
        ready=task.params.get('incremental',{}).get('state')=='complete' and bool(pages) and all(p['state']=='observed' for p in pages)
        refs=['seo_task:'+str(ident)]+['seo_page_snapshot:'+str(p['snapshot_id']) for p in pages if p.get('snapshot_id')]
        await core.settle_step(db,token,status='succeeded' if ready else 'blocked',fee_state='not_called',
            error_code=None if ready else 'automation_diagnosis_requires_advisor',evidence_refs=refs)
        await db.commit()


async def execute_draft_task(token,gate,sessions):
    from app.models.seo_cockpit import SeoTask
    async with sessions() as db:
        await gate.check(db)
        site=await db.get(SeoSite,token['scope_id'])
        if token['operation']=='monthly_onsite_plan':
            from app.api.seo_onsite import Create,create_task
            from app.api.seo_onsite_ai import fresh_context
            from app.security.auth import AuthContext
            from app.seo_automation_sources import monthly_source
            fresh=await fresh_context(db,AuthContext(token['owner_user_id'],'','',None,{}))
            material=await monthly_source(db,site,lock=True)
            result=await create_task(Create(tenant_id=token['tenant_id'],site_id=token['scope_id'],
                request_id=token['request_id'],work_type='monthly',month=material['month'],
                keyword_ids=[k['id'] for k in material['keywords']],page_ids=[p['id'] for p in material['pages']],
                owner_name=fresh.username),db,fresh,commit=False)
            ident=result['id']
            ready=True
            link=f"/api/v1/seo/workbench/onsite-tasks?tenant_id={token['tenant_id']}&site_id={token['scope_id']}"
        else:
            from app.seo_service_workflows import prepare_report
            row=await db.get(SeoTask,token['target']['object_id'],with_for_update=True,populate_existing=True)
            await prepare_report(db,site,row,core.now())
            ident=row.id
            ready=bool(row.params.get('report'))
            link=f"/api/v1/seo/workbench/executions/{ident}/report?tenant_id={token['tenant_id']}&site_id={token['scope_id']}"
        # Local draft + shared result are one transaction. No approval/acceptance.
        await core.settle_step(db,token,status='succeeded' if ready else 'blocked',fee_state='not_called',
            error_code=None if ready else 'automation_report_requires_advisor',
            evidence_refs=['seo_task:'+str(ident)],result_links=[link] if ready else [])
        await db.commit()


async def execute_diagnosis(token,gate,sessions):
    from app.seo_page_audit import collect_page_snapshot,save_page_snapshot
    from app.seo_incremental_crawl import site_hosts
    from app.seo_usage_limits import charge_seo_usage
    from app.config import get_settings
    from app.models.seo import SeoSitePage
    async with sessions() as db:
        await gate.check(db)
        page=await db.get(SeoSitePage,token['target']['object_id'])
        site=await db.get(SeoSite,token['scope_id'])
        url,hosts=page.url,site_hosts(site.canonical_domain)
        previous_checked_at=page.last_checked_at
        await charge_seo_usage(db,token['tenant_id'],'crawl_urls',1,
            get_settings().seo_manual_crawl_max_urls_per_tenant_per_day,commit=False)
        await db.commit()
    started=core.now().replace(tzinfo=None)
    with boundary.use(gate):
        values=await collect_page_snapshot(url,allowed_hosts=hosts)
    async with sessions() as db:
        await gate.check(db)
        page=await db.get(SeoSitePage,token['target']['object_id'],with_for_update=True,populate_existing=True)
        if page.last_checked_at!=previous_checked_at:
            raise core.problem('automation_source_changed','已有更新的页面检查，迟到结果未采用')
        snapshot=await save_page_snapshot(db,page,values,token['owner_user_id'],started)
        await db.flush()
        await core.settle_step(db,token,status='failed' if values.get('error_type') else 'succeeded',
            error_code='automation_page_fetch_failed' if values.get('error_type') else None,fee_state='not_called',
            evidence_refs=['seo_page_snapshot:'+str(snapshot.id)],
            result_links=[f"/api/v1/seo/site-pages/diagnostics?tenant_id={token['tenant_id']}&site_id={token['scope_id']}"])
        await db.commit()


async def execute_content(token,gate,sessions):
    from app.seo_content_workflow import reserve_content_workflow
    from app import seo_content_drafting as drafts
    from app.models.seo_cockpit import SeoTask
    async with sessions() as db:
        await gate.check(db)
        site=await db.get(SeoSite,token['scope_id'])
        row,_=await reserve_content_workflow(db,site,request_key=token['request_id'],actor_id=token['owner_user_id'],scheduled=True)
        row.params={**row.params,'automation_token':token}
        ident=row.id
        await db.commit()
    with boundary.use(gate):
        await drafts.execute_content_draft(ident,sessions=sessions)
    async with sessions() as db:
        await gate.check(db)
        row=await db.get(SeoTask,ident,populate_existing=True)
        state=(row.params.get('ai_draft') or {}).get('status')
        run=await core.read_run(db,gate.key,token['run_id'])
        step=next(s for s in run['steps'] if s['request_id']==token['request_id'])
        await core.settle_step(db,token,status='succeeded' if state=='succeeded' else 'unknown' if state=='claimed' else 'blocked',
            error_code=None if state=='succeeded' else 'automation_content_requires_advisor',fee_state=step['fee_state'],
            evidence_refs=['seo_task:'+str(ident),'seo_content:'+str(row.params['content_id'])],
            result_links=[f"/api/v1/seo/workbench/executions/{ident}?tenant_id={token['tenant_id']}&site_id={token['scope_id']}"])
        await db.commit()


async def execute_index(token,gate,sessions):
    from app.seo_chinaz import fetch_index
    from app.api.seo import _provider_metric_status
    async with sessions() as db:
        await gate.check(db)
        site=await db.get(SeoSite,token['scope_id'])
        url=site.default_url or 'https://'+site.canonical_domain
        await db.commit()
    with boundary.use(gate), boundary.background_scope(tenant_id=token['tenant_id'],module='seo',
            user_id=token['owner_user_id'],operation='indexation_collection',job_ref='automation:'+token['request_id']+':indexation'):
        payload=await fetch_index(url)
    async with sessions() as db:
        await boundary.finish_deferred(db,gate)
        await db.commit()
    gate.deferred_receipts.clear()
    async with sessions() as db:
        await gate.check(db)
        stamp=payload.get('queried_at')
        observed=(datetime.fromisoformat(stamp).astimezone(timezone.utc).replace(tzinfo=None)
            if stamp else core.now().replace(tzinfo=None))
        row=await db.scalar(select(SeoMetricSnapshot).where(SeoMetricSnapshot.tenant_id==token['tenant_id'],
            SeoMetricSnapshot.site_id==token['scope_id'],SeoMetricSnapshot.metric_type=='baidu_index_estimate',
            SeoMetricSnapshot.dimension=='total',SeoMetricSnapshot.source=='chinaz',SeoMetricSnapshot.observed_at==observed))
        status=_provider_metric_status(payload)
        if row is None:
            # Whitelisted provider evidence only, no arbitrary payload or reason text.
            raw={k:payload.get(k) for k in ('status','queried_at','cache_hit','is_estimate','site_count','methodology','source_url')}
            row=SeoMetricSnapshot(tenant_id=token['tenant_id'],site_id=token['scope_id'],
                metric_type='baidu_index_estimate',dimension='total',source='chinaz',data_quality='estimated',
                status=status,numeric_value=payload.get('site_count') if status=='available' else None,unit='pages',
                error_message=None if status=='available' else '收录量来源暂不可用',raw_payload=raw,observed_at=observed)
            db.add(row)
            await db.flush()
        run=await core.read_run(db,gate.key,token['run_id'])
        step=next(s for s in run['steps'] if s['request_id']==token['request_id'])
        await core.settle_step(db,token,status='succeeded' if status=='available' else 'blocked',
            error_code=None if status=='available' else 'automation_indexation_unavailable',fee_state=step['fee_state'],
            evidence_refs=['seo_metric_snapshot:'+str(row.id)])
        await db.commit()


async def recover(db,key,run,step):
    """No repeated provider execution after a committed worker claim."""
    stamps=[step['started_at']]+[c['admitted_at'] for c in step.get('calls',[])]
    started=max(datetime.fromisoformat(stamp) for stamp in stamps)
    if (core.now()-started).total_seconds()<180: return
    token={**key,'run_id':str(run['id']),'generation':run['generation'],
        'owner_user_id':run['configuration']['owner_user_id'],'step_key':step['step_key'],
        'request_id':step['request_id'],'task_id':None,'target':step['target'],'operation':step['operation']}
    for call in step.get('calls',[]):
        if call['state']=='admitted':
            await boundary.v2.finish_call(db,token,call['call_key'],state='unknown',fee_state=call['fee_state'])
    await core.settle_step(db,token,status='unknown',error_code='automation_execution_interrupted',
        fee_state=step['fee_state'])
