"""Module contracts only: no cockpit callbacks and no external task execution."""
from datetime import datetime,timezone
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException,Query
from pydantic import BaseModel,Field,PositiveInt,ConfigDict
from sqlalchemy import select
from app.database import get_session
from app.security.auth import require_scoped_auth
from app.models.module_workspace import SeoSite
from app.models.seo import SeoContentAsset,SeoImageAltReview
from app.models.seo_cockpit import SeoTask,SeoImageVerification
from app.seo_cockpit_metrics import metric_snapshot,metric_values,DEFINITIONS

router=APIRouter()
TASK_PERMS={'content_review':'seo.content','image_repair':'seo.site','ranking_improvement':'seo.keywords'}
TASK_METRICS={'content_review':'seo.content.published_7d_count','image_repair':'seo.images.verified_repair_count','ranking_improvement':'seo.ranking.top10_keyword_count'}

class TrendContract(BaseModel):
    direction:Literal['up','down','flat']|None
    change_pct:float|None
    change_abs:float|None

class MetricContract(BaseModel):
    metric_key:str
    value:float|int|None
    unit:str
    as_of:datetime
    trend_7d:TrendContract|None

class TaskContract(BaseModel):
    id:int
    module:Literal['seo']
    action_type:str
    title:str
    params:dict
    status:Literal['open','in_progress','done','cancelled']
    created_by:str
    assignee_role:str
    completion_evidence:dict|None
    created_at:datetime
    updated_at:datetime

async def scope(session,ctx,tenant_id,site_id,permission,write=False):
    ctx.ensure_tenant(tenant_id)
    if not (ctx.can_edit(permission) if write else ctx.can_view(permission)):
        raise HTTPException(403,'无权访问此 SEO 资源')
    site=await session.get(SeoSite,site_id)
    if site is None or site.tenant_id!=tenant_id:raise HTTPException(404,'网站不存在')
    return site

def payload(row):
    return {key:getattr(row,key) for key in ['id','module','action_type','title','params','status','created_by','assignee_role','completion_evidence','created_at','updated_at']}

class TaskCreate(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    tenant_id:PositiveInt
    site_id:PositiveInt
    module:Literal['seo']='seo'
    action_type:Literal['content_review','image_repair','ranking_improvement']
    title:str=Field(min_length=1,max_length=240)
    params:dict=Field(default_factory=dict)
    created_by:str|int|None=None
    assignee_role:str=Field(min_length=1,max_length=80)

class TaskUpdate(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    tenant_id:PositiveInt
    site_id:PositiveInt
    title:str|None=Field(None,min_length=1,max_length=240)
    assignee_role:str|None=Field(None,min_length=1,max_length=80)
    status:Literal['open','in_progress','done','cancelled']|None=None

@router.get('/metrics/snapshot',response_model=list[MetricContract])
async def snapshot(tenant_id:PositiveInt,site_id:PositiveInt,ctx=Depends(require_scoped_auth),session=Depends(get_session)):
    for permission in TASK_PERMS.values():await scope(session,ctx,tenant_id,site_id,permission)
    return await metric_snapshot(session,tenant_id,site_id)

@router.get('/metrics/definitions')
async def definitions(ctx=Depends(require_scoped_auth)):
    if not ctx.can_view('seo.site'):raise HTTPException(403,'无权访问 SEO 指标')
    return [{'metric_key':key,'unit':unit,'description':description} for key,(unit,description) in DEFINITIONS.items()]

async def task_record(session,ctx,task_id,tenant_id,site_id,write=False):
    row=await session.get(SeoTask,task_id,with_for_update=write)
    if not row or row.tenant_id!=tenant_id or row.site_id!=site_id:raise HTTPException(404,'任务不存在')
    await scope(session,ctx,tenant_id,site_id,TASK_PERMS[row.action_type],write)
    return row

@router.post('/tasks',response_model=TaskContract)
async def create_task(req:TaskCreate,ctx=Depends(require_scoped_auth),session=Depends(get_session)):
    await scope(session,ctx,req.tenant_id,req.site_id,TASK_PERMS[req.action_type],True)
    actor=str(ctx.user_id) if ctx.user_id is not None else 'cockpit'
    if req.created_by is not None and str(req.created_by)!=actor:raise HTTPException(403,'不能冒用任务创建人')
    if req.action_type=='content_review':
        content=await session.get(SeoContentAsset,req.params.get('content_id')) if isinstance(req.params.get('content_id'),int) else None
        if not content or content.tenant_id!=req.tenant_id or content.site_id!=req.site_id:raise HTTPException(422,'需要当前网站的 content_id')
    elif req.action_type=='image_repair':
        review=await session.get(SeoImageAltReview,req.params.get('review_id')) if isinstance(req.params.get('review_id'),int) else None
        if not review or review.tenant_id!=req.tenant_id or review.site_id!=req.site_id:raise HTTPException(422,'需要当前网站的 review_id')
    import json
    if len(json.dumps(req.params,ensure_ascii=False))>10000:raise HTTPException(422,'任务参数过大')
    values=await metric_values(session,req.tenant_id,req.site_id)
    key=TASK_METRICS[req.action_type]
    row=SeoTask(tenant_id=req.tenant_id,site_id=req.site_id,module='seo',action_type=req.action_type,title=req.title.strip(),params=req.params,
        status='open',created_by=actor,assignee_role=req.assignee_role.strip(),baseline={'metric_key':key,'value':values[key],'as_of':datetime.now(timezone.utc).isoformat()})
    session.add(row);await session.commit();await session.refresh(row)
    return payload(row)

@router.get('/tasks',response_model=list[TaskContract])
async def list_tasks(tenant_id:PositiveInt,site_id:PositiveInt,status:Literal['open','in_progress','done','cancelled']|None=None,
                     limit:int=Query(50,ge=1,le=100),before_id:PositiveInt|None=None,ctx=Depends(require_scoped_auth),session=Depends(get_session)):
    ctx.ensure_tenant(tenant_id)
    allowed=[action for action,permission in TASK_PERMS.items() if ctx.can_view(permission)]
    if not allowed:raise HTTPException(403,'无权访问 SEO 任务')
    await scope(session,ctx,tenant_id,site_id,TASK_PERMS[allowed[0]])
    query=select(SeoTask).where(SeoTask.tenant_id==tenant_id,SeoTask.site_id==site_id,SeoTask.action_type.in_(allowed))
    if status:query=query.where(SeoTask.status==status)
    if before_id:query=query.where(SeoTask.id<before_id)
    return [payload(row) for row in await session.scalars(query.order_by(SeoTask.id.desc()).limit(limit))]

@router.get('/tasks/{task_id}',response_model=TaskContract)
async def get_task(task_id:int,tenant_id:PositiveInt,site_id:PositiveInt,ctx=Depends(require_scoped_auth),session=Depends(get_session)):
    return payload(await task_record(session,ctx,task_id,tenant_id,site_id))

async def completion(session,row):
    before=row.baseline.get('value');key=row.baseline['metric_key']
    values=await metric_values(session,row.tenant_id,row.site_id)
    after=values[key]
    proof={}
    if row.action_type=='content_review':
        content=await session.get(SeoContentAsset,row.params['content_id'])
        if not content or content.tenant_id!=row.tenant_id or content.site_id!=row.site_id or content.status!='published' or not content.published_at or content.published_at.replace(tzinfo=timezone.utc)<=row.created_at:
            raise HTTPException(409,'审核通过不等于产出完成，需要任务创建后的实际发布记录')
        proof={'content_id':content.id,'published_at':content.published_at.isoformat()}
    elif row.action_type=='image_repair':
        verification=await session.scalar(select(SeoImageVerification).where(SeoImageVerification.tenant_id==row.tenant_id,
            SeoImageVerification.site_id==row.site_id,SeoImageVerification.review_id==row.params['review_id'],
            SeoImageVerification.status=='verified',SeoImageVerification.checked_at>row.created_at).order_by(SeoImageVerification.id.desc()).limit(1))
        if verification is None:raise HTTPException(409,'需要重新抓取确认图片修复')
        proof={'verification_id':verification.id,**verification.evidence}
    else:
        from app.models.seo import SeoRankSnapshot,SeoKeywordAsset
        from datetime import timedelta
        observations=list(await session.scalars(select(SeoRankSnapshot.id).join(SeoKeywordAsset,SeoKeywordAsset.id==SeoRankSnapshot.keyword_id).where(
            SeoRankSnapshot.tenant_id==row.tenant_id,SeoRankSnapshot.site_id==row.site_id,
            SeoKeywordAsset.tenant_id==row.tenant_id,SeoKeywordAsset.site_id==row.site_id,
            SeoKeywordAsset.status=='active',SeoKeywordAsset.priority.in_(['P0','P1']),
            SeoRankSnapshot.subject_type=='own',SeoRankSnapshot.engine=='baidu',SeoRankSnapshot.device=='desktop',SeoRankSnapshot.region=='全国',
            SeoRankSnapshot.checked_at>=datetime.utcnow()-timedelta(days=7)).order_by(SeoRankSnapshot.id)))
        proof={'rank_snapshot_ids':observations,'engine':'baidu','device':'desktop','region':'全国'}
    if before is None or after is None or after<=before:raise HTTPException(409,'尚无可验证的目标指标增长，不能手工标记完成')
    return {'metric_key':key,'before':before,'after':after,'change_abs':after-before,'as_of':datetime.now(timezone.utc).isoformat(),'source':proof,
        'snapshot_url':f'/api/v1/seo/metrics/snapshot?tenant_id={row.tenant_id}&site_id={row.site_id}'}

@router.patch('/tasks/{task_id}',response_model=TaskContract)
async def update_task(task_id:int,req:TaskUpdate,ctx=Depends(require_scoped_auth),session=Depends(get_session)):
    row=await task_record(session,ctx,task_id,req.tenant_id,req.site_id,True)
    if row.status in ('done','cancelled'):raise HTTPException(409,'已结束任务不可修改')
    if req.status=='done':row.completion_evidence=await completion(session,row)
    if req.status:row.status=req.status
    if req.title is not None:row.title=req.title.strip()
    if req.assignee_role is not None:row.assignee_role=req.assignee_role.strip()
    row.updated_at=datetime.now(timezone.utc)
    await session.commit();await session.refresh(row)
    return payload(row)

@router.delete('/tasks/{task_id}',response_model=TaskContract)
async def cancel_task(task_id:int,tenant_id:PositiveInt,site_id:PositiveInt,ctx=Depends(require_scoped_auth),session=Depends(get_session)):
    row=await task_record(session,ctx,task_id,tenant_id,site_id,True)
    if row.status=='done':raise HTTPException(409,'保留已完成任务及证据，不允许删除')
    row.status='cancelled';row.updated_at=datetime.now(timezone.utc)
    await session.commit();await session.refresh(row)
    return payload(row)

@router.get('/image-verifications')
async def image_verifications(tenant_id:PositiveInt,site_id:PositiveInt,limit:int=Query(50,ge=1,le=100),ctx=Depends(require_scoped_auth),session=Depends(get_session)):
    await scope(session,ctx,tenant_id,site_id,'seo.site')
    return [{'id':row.id,'review_id':row.review_id,'page_id':row.page_id,'status':row.status,'evidence':row.evidence,'checked_at':row.checked_at}
        for row in await session.scalars(select(SeoImageVerification).where(SeoImageVerification.tenant_id==tenant_id,SeoImageVerification.site_id==site_id,SeoImageVerification.status!='superseded').order_by(SeoImageVerification.id.desc()).limit(limit))]

@router.post('/image-verifications/{verification_id}/retry')
async def retry_image_verification(verification_id:int,tenant_id:PositiveInt,site_id:PositiveInt,ctx=Depends(require_scoped_auth),session=Depends(get_session)):
    await scope(session,ctx,tenant_id,site_id,'seo.site',True)
    row=await session.get(SeoImageVerification,verification_id,with_for_update=True)
    if not row or row.tenant_id!=tenant_id or row.site_id!=site_id:raise HTTPException(404,'核实任务不存在')
    if row.status not in ('unverified','unavailable'):raise HTTPException(409,'只有未生效或抓取异常的任务可以重新核实')
    from datetime import timedelta
    now=datetime.now(timezone.utc)
    if row.checked_at and now-row.checked_at<timedelta(minutes=5):raise HTTPException(429,'请在上次核实五分钟后重试')
    row.status='pending';row.available_at=now
    await session.commit()
    return {'id':row.id,'status':'pending'}

async def stage_review_task(session,content,ctx,decision=None):
    """Reuse submit-review/review; approval advances work but is not completion."""
    if content.site_id is None:return
    row=await session.scalar(select(SeoTask).where(SeoTask.tenant_id==content.tenant_id,SeoTask.site_id==content.site_id,
        SeoTask.action_type=='content_review',SeoTask.params['content_id'].astext==str(content.id),SeoTask.status.in_(['open','in_progress'])).with_for_update())
    if row:
        row.status='in_progress' if decision=='approve' else 'open'
        row.updated_at=datetime.now(timezone.utc)
    elif decision is None:
        values=await metric_values(session,content.tenant_id,content.site_id)
        key=TASK_METRICS['content_review']
        session.add(SeoTask(tenant_id=content.tenant_id,site_id=content.site_id,module='seo',action_type='content_review',title=f'审核并发布：{content.title}'[:240],
            params={'content_id':content.id},status='open',created_by=str(ctx.user_id) if ctx.user_id else 'cockpit',assignee_role='content_reviewer',
            baseline={'metric_key':key,'value':values[key],'as_of':datetime.now(timezone.utc).isoformat()}))
