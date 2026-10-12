"""Named assigned advisor controls; GET is strictly a projection."""
from datetime import date
import asyncio
from typing import Literal
from types import SimpleNamespace
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import PositiveInt
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError

from app import automation_projects as core
from app.automation_project_contract import Configure, Control, ConfigurationV2, parse_configuration
from app import automation_project_v2 as v2, seo_automation_sources as sources
from app.api import seo_onsite_ai as ai_api
from app.models.module_workspace import SeoSite, TenantModule
from app.models.seo import SeoSiteAdvisorAssignment
from app.models.seo_cockpit import SeoTask
from app.models.tenant import Tenant
from app.seo_demo_source import get_seo_session, require_seo_scoped_auth

COVERAGE = {'controlled':['configured_onsite_ai'], 'not_controlled':[
    'manual_onsite_ai','ranking_collection','competitor_collection','backlink_collection',
    'content_cycle','service_diagnosis_cycle','monitoring_cycle','monthly_report_cycle',
    'qa_batches','image_verification','page_capture','platform_publication',
    'website_mutation','approval','acceptance']}


class PrivateRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def private(request):
            try:
                result = await handler(request)
                result.headers['Cache-Control'] = 'no-store'
                return result
            except HTTPException as exc:
                exc.headers = {**(exc.headers or {}),'Cache-Control':'no-store'}
                raise
            except RequestValidationError as exc:
                return JSONResponse(status_code=422,headers={'Cache-Control':'no-store'},content={
                    'detail':[{'loc':list(e['loc']),'msg':e['msg'],'type':e['type']} for e in exc.errors()]})
            except (SQLAlchemyError, OSError, TimeoutError):
                raise core.problem('automation_unavailable','自动执行记录暂不可用，请稍后重新读取核对',503) from None
        return private


router = APIRouter(prefix='/workbench/automation-projects',route_class=PrivateRoute)
health_router = APIRouter(route_class=PrivateRoute)


@health_router.get('/workbench/automation-health')
async def automation_health(db=Depends(ai_api.get_primary_session), ctx=Depends(ai_api.require_auth)):
    # A live named identity and BOTH permissions; API-key superadmin fallback is insufficient.
    await ai_api.require_health_admin(ctx)
    try:
        async with asyncio.timeout(2):
            fresh = await ai_api.fresh_context(db, ctx)
            await ai_api.require_health_admin(fresh)
            value = await v2.health_snapshot(db, 'seo')
    except (SQLAlchemyError, OSError, TimeoutError):
        return JSONResponse(status_code=503, headers={'Cache-Control': 'no-store'}, content={
            'schema':1, 'module':'seo', 'scope':{'kind':'global','tenant_id':None},
            'as_of':core.now().isoformat(), 'state':'unavailable', 'contract_versions':[],
            'counts':dict.fromkeys(('projects','runs','pending_human','unknown_cost')),
            'rows':[], 'truncated':False,
            'queue':{'state':'not_connected','queued':None,'running':None,'unknown':None},
            'worker':{'state':'unverified','verified':False,'last_tick_at':None,'evidence':None},
            'overall':'unverified','alerts':[{'code':'automation_unavailable','summary':'自动执行状态暂无法核实'}]})
    return value


async def scoped(db,ctx,tenant_id,scope_id,*,lock=False):
    ctx.ensure_tenant(tenant_id)
    site = await db.get(SeoSite,scope_id,populate_existing=True,
        **({'with_for_update':True} if lock else {}))
    fresh = await ai_api.authorized(db,ctx,SimpleNamespace(tenant_id=tenant_id,site_id=scope_id),site,lock=lock)
    return site,fresh


def eligible(row):
    workflow = (row.params or {}).get('onsite') or {}
    requests = (row.params or {}).get('onsite_ai_requests') or {}
    return (row.module=='seo' and row.action_type==ai_api.onsite.ACTION_TYPE
        and row.status not in {'done','cancelled'} and workflow.get('schema')==1
        and workflow.get('phase')=='draft' and not workflow.get('ai_proposal')
        and not any(r.get('started_at') or r.get('state') in {'queued','running','ready','unknown'} for r in requests.values()))


async def validate_tasks(db,key,config,*,lock=False):
    for ident in sorted(config.task_ids):
        row = await db.get(SeoTask,ident,populate_existing=True,**({'with_for_update':True} if lock else {}))
        if not row or (row.tenant_id,row.site_id)!=(key['tenant_id'],key['scope_id']):
            raise core.problem('automation_task_not_found','所选任务不属于当前网站',404)
        if not eligible(row):
            raise core.problem('automation_task_ineligible','所选任务需人工处理或已有方案/调用，不能自动重发')


async def view(db,key,site,project,ready,actor_id):
    value=core.project_view(key,project,ready=ready,coverage=COVERAGE)
    if ready and await v2.schema_ready(db):
        value['capabilities']['available_operations']=list(sources.OPERATIONS)
    if project and (project['configuration'] or {}).get('contract_version') == 2:
        mapping={'onsite_ai':'manual_onsite_ai','ranking_collect':'ranking_collection','content_draft':'content_cycle',
            'site_diagnosis':'service_diagnosis_cycle','incremental_diagnosis':'service_diagnosis_cycle','monthly_report':'monthly_report_cycle'}
        operations=project['configuration']['operations']
        value['coverage'] = {'controlled':operations,
            'not_controlled':[item for item in COVERAGE['not_controlled'] if item not in {mapping.get(op) for op in operations}]}
    if project and project['owner_user_id']!=actor_id:
        value['capabilities']['can_control']=False
        value['allowed_actions']=[]
        value['blocker']='automation_owner_mismatch'
    return {**value,
        'scope_name':site.name,'tenant_name':await db.scalar(select(Tenant.name).where(Tenant.id==key['tenant_id']))}


@router.get('')
async def projects(tenant_id:PositiveInt|None=None,before_scope_id:PositiveInt|None=None,
                   limit:int=Query(20,ge=1,le=50),db=Depends(get_seo_session),ctx=Depends(require_seo_scoped_auth)):
    fresh = await ai_api.fresh_context(db,ctx)
    if not (fresh.can_edit('seo.site') and fresh.can_edit('seo.content') and fresh.can_view('seo.keywords')):
        raise core.problem('automation_forbidden','需要网站、内容编辑及关键词查看权限',403)
    if tenant_id is not None:
        ctx.ensure_tenant(tenant_id)
        fresh.ensure_tenant(tenant_id)
    assigned = select(SeoSiteAdvisorAssignment.id).where(
        SeoSiteAdvisorAssignment.site_id==SeoSite.id,SeoSiteAdvisorAssignment.tenant_id==SeoSite.tenant_id,
        SeoSiteAdvisorAssignment.advisor_user_id==fresh.user_id,SeoSiteAdvisorAssignment.active.is_(True)).exists()
    query = select(SeoSite).join(TenantModule,and_(TenantModule.id==SeoSite.tenant_module_id,
        TenantModule.tenant_id==SeoSite.tenant_id,TenantModule.module_code=='seo')).where(assigned,
        SeoSite.status=='active',TenantModule.status.in_(['active','trial']),
        or_(TenantModule.expires_at.is_(None),TenantModule.expires_at>=date.today()))
    for bound in (tenant_id,ctx.tenant_id,fresh.tenant_id):
        if bound is not None: query = query.where(SeoSite.tenant_id==bound)
    if before_scope_id is not None: query = query.where(SeoSite.id<before_scope_id)
    sites = list(await db.scalars(query.order_by(SeoSite.id.desc()).limit(limit+1)))
    ready = await core.schema_ready(db)
    items=[]
    for site in sites[:limit]:
        key=core.scope('seo',site.tenant_id,site.id)
        items.append(await view(db,key,site,await core.read_project(db,key) if ready else None,ready,fresh.user_id))
    return {'schema':1,'module':'seo','items':items,
        'next_before_scope_id':sites[limit-1].id if len(sites)>limit else None}


@router.get('/{scope_id}/control')
async def project(scope_id:PositiveInt,tenant_id:PositiveInt,db=Depends(get_seo_session),ctx=Depends(require_seo_scoped_auth)):
    site,fresh=await scoped(db,ctx,tenant_id,scope_id)
    key=core.scope('seo',tenant_id,scope_id)
    ready=await core.schema_ready(db)
    return await view(db,key,site,await core.read_project(db,key) if ready else None,ready,fresh.user_id)


async def write(db,ctx,scope_id,req,*,configure=False):
    key=core.scope('seo',req.tenant_id,scope_id)
    await scoped(db,ctx,req.tenant_id,scope_id)  # authorize before disclosing state
    current,_,prior=await core.command_begin(db,key,req,ctx.user_id)
    site,fresh=await scoped(db,ctx,req.tenant_id,scope_id,lock=True)
    if prior is None and (configure or req.action in {'start','resume'}):
        if not configure and not current:
            raise core.problem('automation_configuration_required','请先保存范围、周期与负责人')
        config=req.configuration if configure else parse_configuration(current['configuration'])
        if isinstance(config, ConfigurationV2):
            await v2.require_schema(db)
            if 'ranking_collect' in config.operations and not fresh.can_edit('seo.keywords'):
                raise core.problem('automation_forbidden','排名采集需要关键词编辑权限',403)
            remaining=None
            if not configure and req.action=='resume' and current['current_run_id']:
                run=await core.read_run(db,key,current['current_run_id'],lock=True)
                remaining=[step['target'] for step in run['steps'] if step['status'] in {'pending','running'}]
            await sources.validate(db,site,config,targets=remaining,lock=True,configuring=configure or req.action=='start')
        elif configure or req.action=='start':
            await validate_tasks(db,key,config,lock=True)
    if prior is None and not configure and req.action in {'start','resume'}:
        ai_api.execution_enabled(site)
    result,replayed,applied=await (core.configure_project(db,key,req,fresh.user_id) if configure
        else core.control_project(db,key,req,fresh.user_id))
    value=await view(db,key,site,result,True,fresh.user_id)
    await db.commit()
    return {**value,'replayed':replayed,'applied_version':applied}


@router.get('/{scope_id}/configuration-basis')
async def configuration_basis(scope_id:PositiveInt,tenant_id:PositiveInt,operation:str,
        before_object_id:PositiveInt|None=None,limit:int=Query(25,ge=1,le=50),
        db=Depends(get_seo_session),ctx=Depends(require_seo_scoped_auth)):
    site,fresh=await scoped(db,ctx,tenant_id,scope_id)
    if operation=='ranking_collect' and not fresh.can_edit('seo.keywords'):
        raise core.problem('automation_forbidden','排名采集需要关键词编辑权限',403)
    return await sources.basis(db,site,operation,before_object_id,limit)


@router.get('/{scope_id}/events/export')
async def export_events(scope_id:PositiveInt,tenant_id:PositiveInt,format:Literal['json','csv']='json',
        after_id:int=Query(0,ge=0),through_id:int|None=Query(None,ge=0),limit:int=Query(100,ge=1,le=500),
        db=Depends(get_seo_session),ctx=Depends(require_seo_scoped_auth)):
    key=await read_key(db,ctx,tenant_id,scope_id)
    page=await v2.events_export_page(db,key,after_id=after_id,through_id=through_id,limit=limit)
    if format=='json': return page
    return Response(v2.csv_export(page),media_type='text/csv',headers={
        'Content-Disposition':'attachment; filename="seo-automation-events.csv"',
        'X-Snapshot-Upper-Id':str(page['snapshot_upper_id']),
        'X-Next-After-Id':str(page['next_after_id']) if page['next_after_id'] is not None else ''})


@router.put('/{scope_id}/control')
async def configure(scope_id:PositiveInt,req:Configure,db=Depends(get_seo_session),ctx=Depends(require_seo_scoped_auth)):
    return await write(db,ctx,scope_id,req,configure=True)


@router.post('/{scope_id}/control')
async def control(scope_id:PositiveInt,req:Control,db=Depends(get_seo_session),ctx=Depends(require_seo_scoped_auth)):
    return await write(db,ctx,scope_id,req)


async def read_key(db,ctx,tenant_id,scope_id):
    await scoped(db,ctx,tenant_id,scope_id)
    await core.require_schema(db)
    return core.scope('seo',tenant_id,scope_id)


@router.get('/{scope_id}/runs')
async def runs(scope_id:PositiveInt,tenant_id:PositiveInt,before_run_id:UUID|None=None,
               limit:int=Query(20,ge=1,le=50),db=Depends(get_seo_session),ctx=Depends(require_seo_scoped_auth)):
    return await core.runs_page(db,await read_key(db,ctx,tenant_id,scope_id),before_run_id,limit)


@router.get('/{scope_id}/events')
async def events(scope_id:PositiveInt,tenant_id:PositiveInt,after_id:int=Query(0,ge=0),
                 limit:int=Query(50,ge=1,le=100),db=Depends(get_seo_session),ctx=Depends(require_seo_scoped_auth)):
    return await core.project_events_page(db,await read_key(db,ctx,tenant_id,scope_id),after_id,limit)


@router.get('/{scope_id}/runs/{run_id}')
async def run(scope_id:PositiveInt,run_id:UUID,tenant_id:PositiveInt,
              db=Depends(get_seo_session),ctx=Depends(require_seo_scoped_auth)):
    key=await read_key(db,ctx,tenant_id,scope_id)
    return core.run_view(key,await core.read_run(db,key,run_id))


@router.get('/{scope_id}/runs/{run_id}/events')
async def run_events(scope_id:PositiveInt,run_id:UUID,tenant_id:PositiveInt,after_id:int=Query(0,ge=0),
                     limit:int=Query(50,ge=1,le=100),db=Depends(get_seo_session),ctx=Depends(require_seo_scoped_auth)):
    return await core.events_page(db,await read_key(db,ctx,tenant_id,scope_id),run_id,after_id,limit)
