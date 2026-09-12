"""Module contracts only: no cockpit callbacks and no external task execution."""
from datetime import datetime,timezone
from typing import Literal
from urllib.parse import urlsplit,urlunsplit
from fastapi import APIRouter,Depends,HTTPException,Query
from pydantic import BaseModel,Field,PositiveInt,ConfigDict
from sqlalchemy import func,select
from app.seo_demo_source import (
    get_seo_session as get_session,
    require_seo_scoped_auth as require_scoped_auth,
)
from app.models.module_workspace import SeoSite
from app.models.seo import (
    SeoBacklink, SeoContentAsset, SeoContentPublication, SeoImageAltReview,
    SeoPublishAttempt, SeoSitePage,
)
from app.models.seo_cockpit import SeoTask,SeoImageVerification
from app.seo_cockpit_metrics import metric_snapshot,metric_values,DEFINITIONS
from app.seo_image_verification import prepare_image_verification_retry

router=APIRouter()
TASK_PERMS={'content_review':'seo.content','image_repair':'seo.site','ranking_improvement':'seo.keywords','backlink_outreach':'seo.links'}
TASK_METRICS={'content_review':'seo.content.published_7d_count','image_repair':'seo.images.verified_repair_count','ranking_improvement':'seo.ranking.top10_keyword_count','backlink_outreach':'seo.backlinks.verified_count'}

QUEUE_STATES=('pending_customer_action','pending_system_check','verified','failed_retry')
PUBLICATION_DISCOVERY_FAILURES={'unavailable','failed','unreachable','blocked'}
PUBLICATION_DISCOVERY_REASONS={
    'timeout':'公开地址核验超时','dns_error':'公开地址域名解析失败','connection_error':'公开地址连接失败',
    'tls_error':'公开地址安全连接失败','http_error':'公开地址返回异常状态',
    'http_4xx':'公开地址拒绝访问','http_5xx':'公开地址服务异常','empty_response':'公开地址没有返回可核验内容',
    'non_html':'公开地址没有返回网页内容','login_or_challenge':'公开地址要求登录或安全验证',
}
PAGE_SAFE_ISSUE_CODES={
    'title','title_missing','title_too_long','description','description_missing','h1','h1_missing','h1_multiple',
    'canonical','indexable','noindex','robots_blocked','schema','entity_schema','schema_invalid','heading_depth',
    'substantial','thin_content','faq','citations','freshness','block_definition','block_numbers','block_comparison',
    'block_howto','block_faq','NO_DEFINITION','NO_NUMBERS','NO_COMPARISON','NO_HOWTO','NO_FAQ','image_alt_missing',
    'language','html_lang_missing','https','robots','ai_crawlers','llms','http_4xx','http_5xx','empty_response',
    'non_html','timeout','too_many_redirects','dns_error','tls_error','blocked_address','connection_error',
    'robots_unavailable','invalid_url','http_status_unavailable',
}
PAGE_FAILURE_REASONS={
    'robots_blocked':'robots.txt 禁止系统核验','robots_unavailable':'robots.txt 暂时无法核实',
    'timeout':'页面核验超时','too_many_redirects':'页面重定向次数过多','dns_error':'页面域名解析失败',
    'tls_error':'页面安全连接失败','blocked_address':'页面地址不允许访问','connection_error':'页面连接失败',
    'http_4xx':'页面拒绝访问','http_5xx':'页面服务异常','empty_response':'页面没有返回可核验内容',
    'non_html':'页面没有返回 HTML 内容','invalid_url':'页面地址无效','http_status_unavailable':'页面状态不可用',
}
BACKLINK_STATES={'pending','not_checked','found','missing','unreachable','blocked','readable','internal'}
BACKLINK_REASONS={
    'timeout':'来源页核验超时','http_error':'来源页返回异常状态','empty_response':'来源页没有返回可核验内容',
    'login_or_challenge':'来源页要求登录或安全验证','same_site':'来源页不是站外页面',
}
IMAGE_REASON_CODES={
    '抓取失败或缺少完整图片观测，不能判定修复':'fetch_unavailable',
    '图片观测被截断，不能唯一核实':'observation_truncated',
    '原快照缺少完整图片观测，请重新检测并审核后核实':'baseline_incomplete',
    '原图地址缺失或重复，不能唯一匹配':'source_ambiguous',
    '原图消失、替换或重复，不能视为修复':'image_changed',
    '重新抓取确认已应用审核方案':'applied',
    '重新抓取尚未确认审核方案生效':'not_applied',
}
IMAGE_TERMINAL_STATES={'verified','unverified','unavailable'}

def _queue_item(kind,row,state,title,detail,evidence=None,action_url=None):
    updated=getattr(row,'updated_at',None) or getattr(row,'checked_at',None) or getattr(row,'last_checked_at',None) or getattr(row,'created_at',None)
    if updated is not None and updated.tzinfo is None:updated=updated.replace(tzinfo=timezone.utc)
    return {'id':f'{kind}:{row.id}','kind':kind,'state':state,'title':title,'detail':detail,
            'source_id':int(row.id),'site_id':int(row.site_id) if getattr(row,'site_id',None) is not None else None,
            'updated_at':updated,'evidence':evidence,'action_url':action_url}

def _safe_evidence_url(value):
    if not isinstance(value,str):return None
    try:
        parsed=urlsplit(value)
        if parsed.scheme not in {'http','https'} or not parsed.hostname:return None
        host=f'[{parsed.hostname}]' if ':' in parsed.hostname else parsed.hostname
        port=parsed.port
        netloc=f'{host}:{port}' if port is not None else host
        return urlunsplit((parsed.scheme,netloc,parsed.path or '/', '', ''))
    except ValueError:
        return None

def _safe_positive_int(value):
    return value if isinstance(value,int) and not isinstance(value,bool) and value>0 else None

def _safe_evidence_time(value):
    if isinstance(value,datetime):return value
    if not isinstance(value,str) or len(value)>40:return None
    try:datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError:return None
    return value

def _safe_image_observation(evidence):
    if not isinstance(evidence,dict):return None
    current={}
    reason_code=IMAGE_REASON_CODES.get(evidence.get('reason'))
    if reason_code:current['reason_code']=reason_code
    source_url=_safe_evidence_url(evidence.get('source_url'))
    if source_url:current['source_url']=source_url
    for key in ('review_id','before_snapshot_id','after_snapshot_id'):
        value=_safe_positive_int(evidence.get(key))
        if value is not None:current[key]=value
    for key in ('before_alt_state','after_alt_state'):
        value=evidence.get(key)
        if value in {'missing','empty','whitespace','present'}:current[key]=value
    actual_alt=evidence.get('actual_alt')
    if isinstance(actual_alt,str):current['actual_alt']=actual_alt[:1000]
    if evidence.get('metric_key')=='seo.images.verified_repair_count':current['metric_key']='seo.images.verified_repair_count'
    change=evidence.get('change_abs')
    if isinstance(change,int) and not isinstance(change,bool) and change in {0,1}:current['change_abs']=change
    return current or None

def _safe_image_attempt_history(evidence):
    values=evidence.get('attempt_history') if isinstance(evidence,dict) else None
    if not isinstance(values,list):return []
    history=[]
    for raw in values[-20:]:
        if not isinstance(raw,dict):continue
        item={}
        for key in ('attempt','result_snapshot_id','before_snapshot_id','after_snapshot_id'):
            value=_safe_positive_int(raw.get(key))
            if value is not None:item[key]=value
        if raw.get('status') in IMAGE_TERMINAL_STATES:item['status']=raw['status']
        checked_at=_safe_evidence_time(raw.get('checked_at'))
        if checked_at is not None:item['checked_at']=checked_at
        reason_code=IMAGE_REASON_CODES.get(raw.get('reason'))
        if reason_code:item['reason_code']=reason_code
        change=raw.get('change_abs')
        if isinstance(change,int) and not isinstance(change,bool) and change in {0,1}:item['change_abs']=change
        if item:history.append(item)
    return history

def _safe_image_evidence(row):
    evidence=row.evidence if isinstance(row.evidence,dict) else {}
    safe={}
    attempt=_safe_positive_int(evidence.get('attempt'))
    if attempt is not None:safe['attempt']=attempt
    if row.status in IMAGE_TERMINAL_STATES:
        current=_safe_image_observation(evidence)
        if current:safe['current_observation']=current
    history=_safe_image_attempt_history(evidence)
    if history:safe['attempt_history']=history
    retry=evidence.get('retry_request')
    if isinstance(retry,dict):
        requested_at=_safe_evidence_time(retry.get('requested_at'))
        requested_by=retry.get('requested_by')
        from_status=retry.get('from_status')
        request={}
        if requested_at is not None:request['requested_at']=requested_at
        if requested_by=='service' or (isinstance(requested_by,str) and requested_by.isdigit() and len(requested_by)<=20):request['requested_by']=requested_by
        if from_status in {'unverified','unavailable'}:request['from_status']=from_status
        if request:safe['retry_request']=request
    return safe or None

def _image_observation_matches_row(row,evidence):
    current=(evidence or {}).get('current_observation') or {}
    row_review_id=_safe_positive_int(getattr(row,'review_id',None))
    row_result_id=_safe_positive_int(getattr(row,'result_snapshot_id',None))
    return bool(
        getattr(row,'checked_at',None) is not None
        and (evidence or {}).get('attempt') is not None
        and row_review_id is not None and current.get('review_id')==row_review_id
        and row_result_id is not None and current.get('after_snapshot_id')==row_result_id
        and current.get('before_snapshot_id') is not None
        and current.get('before_snapshot_id')!=current.get('after_snapshot_id')
    )

def _image_terminal_evidence_is_current(row,evidence):
    if not _image_observation_matches_row(row,evidence):return False
    current=evidence['current_observation'];reason=current.get('reason_code')
    if row.status=='verified':
        return reason=='applied' and current.get('change_abs')==1 and current.get('metric_key')=='seo.images.verified_repair_count'
    if row.status=='unverified':return reason in {'not_applied','source_ambiguous','image_changed'}
    if row.status=='unavailable':return reason in {'fetch_unavailable','observation_truncated','baseline_incomplete'}
    return False

def image_queue_item(row,allow_retry=False):
    states={'pending':'pending_system_check','checking':'pending_system_check','verified':'verified',
            'unverified':'pending_customer_action','unavailable':'failed_retry'}
    state=states.get(row.status)
    if not state:return None
    evidence=_safe_image_evidence(row)
    details={'pending':'已进入重新抓取队列','checking':'正在重新抓取页面','verified':'重新抓取已确认图片问题解决',
             'unverified':'重新抓取确认修改尚未生效，请客户完成网站修改','unavailable':'抓取或证据不可用，可重试核实'}
    detail=details[row.status]
    if row.status in IMAGE_TERMINAL_STATES and not _image_terminal_evidence_is_current(row,evidence):
        state,detail='failed_retry','当前记录缺少与本次结果一致的审核及前后快照依据，不能作为有效复核结果；请在站内优化重新检查并审核后核验'
    elif row.status=='unavailable' and ((evidence or {}).get('current_observation') or {}).get('reason_code')=='baseline_incomplete':
        detail='原始快照证据不完整；请先重新检查并审核图片建议，再发起既有核验流程'
    item=_queue_item('image_repair',row,state,f'图片修复核实 · 页面 #{row.page_id}',detail,evidence,
                     f'/seo/site?site_id={row.site_id}&page_id={row.page_id}')
    retryable=row.status in {'unverified','unavailable'}
    item['can_retry']=bool(retryable and allow_retry)
    if retryable and allow_retry:
        item['retry_action']={'method':'POST','url':f'/api/v1/seo/image-verifications/{row.id}/retry',
                              'verification_id':int(row.id),'tenant_id':int(row.tenant_id),'site_id':int(row.site_id)}
    elif retryable:
        item['retry_reason']='当前账号只有查看权限，请由具备站点编辑权限的人员重新核实'
    return item

def _safe_publication_discovery(discovery):
    if not isinstance(discovery,dict):return None
    safe={}
    state=discovery.get('state')
    if state in {'readable','found','unavailable','failed','unreachable','blocked','internal'}:safe['state']=state
    status=discovery.get('http_status')
    if isinstance(status,int) and not isinstance(status,bool):safe['http_status']=status
    found=discovery.get('found')
    if isinstance(found,int) and not isinstance(found,bool) and found>=0:safe['found']=found
    checked_at=discovery.get('checked_at')
    if isinstance(checked_at,(str,datetime)):safe['checked_at']=checked_at
    reason=discovery.get('reason')
    if reason in PUBLICATION_DISCOVERY_REASONS:safe['reason_code']=reason
    return safe or None

def _publication_failure_detail(discovery):
    reason=PUBLICATION_DISCOVERY_REASONS.get(discovery.get('reason')) if isinstance(discovery,dict) else None
    prefix=reason or '系统未能核实公开地址'
    return f'{prefix}；请检查页面公开权限和地址是否正确，系统将在后续周期重新核验'

def publication_queue_item(row,latest_attempt=None):
    discovery=row.link_discovery or {}
    if row.status=='failed':state,detail='failed_retry','发布处理失败；请先核对平台后台是否已产生内容，再到分发模块决定是否重试'
    elif row.status in {'manual_required','draft_created'}:state,detail='pending_customer_action','平台尚未确认正式发布，需要客户或运营人员完成发布并回填公开地址'
    elif row.status=='published' and row.page_url and (discovery.get('state') in {'readable','found'} or discovery.get('found')):state,detail='verified','系统已抓取并确认公开地址可访问'
    elif discovery.get('state') in PUBLICATION_DISCOVERY_FAILURES:state,detail='failed_retry',_publication_failure_detail(discovery)
    elif row.status=='published' and not row.page_url:state,detail='failed_retry','记录已发布但缺少公开地址，需要补录后重新核验'
    else:state,detail='pending_system_check','发布正在处理，或公开地址正在等待系统抓取核验'
    evidence={}
    if row.page_url:
        evidence.update({'page_url':row.page_url,'published_at':row.published_at,
                         'link_discovery':_safe_publication_discovery(row.link_discovery)})
    if latest_attempt is not None:
        evidence['latest_attempt']={
            'id':int(latest_attempt.id),'action':latest_attempt.action,'status':latest_attempt.status,
            'created_by':int(latest_attempt.created_by) if latest_attempt.created_by is not None else None,
            'started_at':latest_attempt.started_at,'completed_at':latest_attempt.completed_at,
        }
    return _queue_item('publication_url',row,state,f'{row.platform_name}发布地址 · {row.adapted_title or "内容"}',detail,evidence or None,
                       f'/seo/distribution?site_id={getattr(row,"site_id","") or ""}')

def page_queue_item(row):
    raw_issues=row.issue_codes if isinstance(row.issue_codes,list) else []
    issues=[code for code in raw_issues if isinstance(code,str) and code in PAGE_SAFE_ISSUE_CODES]
    if row.status in {'proposed','approved'}:state,detail='pending_customer_action','优化建议尚待客户在网站实施；完成后请回到站内优化发起既有页面检查'
    elif row.status=='needs_fix' and row.last_checked_at:state,detail='pending_customer_action','系统最近检查发现页面问题；请客户按当前建议修正，完成后再检查'
    elif row.status=='needs_fix':state,detail='pending_customer_action','页面仍有待处理问题；请客户按当前建议修正后再检查'
    elif row.status in {'pending','implemented'}:state,detail='pending_system_check','等待页面抓取并核对实际结果'
    elif row.status=='verified':state,detail='verified','重新抓取已确认修改生效'
    elif row.status=='error':
        reason=next((PAGE_FAILURE_REASONS[code] for code in issues if code in PAGE_FAILURE_REASONS),None)
        state,detail='failed_retry',f'{reason or "系统未能核实页面"}；请检查页面地址、访问权限与网站状态后再检查'
    else:return None
    safe_url=_safe_evidence_url(row.url)
    evidence={'url':safe_url,'http_status':row.http_status if isinstance(row.http_status,int) and not isinstance(row.http_status,bool) else None,
              'audit_score':row.audit_score if isinstance(row.audit_score,(int,float)) and not isinstance(row.audit_score,bool) else None,
              'issue_codes':issues,'last_checked_at':row.last_checked_at} if row.last_checked_at else None
    return _queue_item('page_recheck',row,state,f'页面重新检查 · {row.title or safe_url or ("页面 #"+str(row.id))}',detail,evidence,
                       f'/seo/site?site_id={row.site_id}')

def _safe_backlink_verification(verification):
    if not isinstance(verification,dict):return None
    safe={}
    state=verification.get('state')
    if state in BACKLINK_STATES:safe['state']=state
    status=verification.get('http_status')
    if isinstance(status,int) and not isinstance(status,bool):safe['http_status']=status
    checked_at=verification.get('checked_at')
    if isinstance(checked_at,(str,datetime)):safe['checked_at']=checked_at
    reason=verification.get('reason')
    if reason in BACKLINK_REASONS:safe['reason_code']=reason
    rel=verification.get('rel')
    if isinstance(rel,list):safe['rel']=[value for value in rel if isinstance(value,str) and value in {'nofollow','ugc','sponsored','noopener','noreferrer','external'}]
    transition=verification.get('transition')
    if transition in {'lost','recovered'}:safe['transition']=transition
    return safe or None

def backlink_queue_item(row):
    verification=row.verification if isinstance(row.verification,dict) else {}; observed=verification.get('state')
    raw_missing_checks=getattr(row,'missing_checks',0)
    missing_checks=max(raw_missing_checks,0) if isinstance(raw_missing_checks,int) and not isinstance(raw_missing_checks,bool) else 0
    if row.status=='active' and observed=='found':state,detail='verified','抓取已确认来源页存在目标链接'
    elif observed in {None,'pending','not_checked'} and row.status!='lost':state,detail='pending_system_check','等待抓取来源页核验外链'
    elif row.status=='active' and observed=='missing' and missing_checks<2:
        state,detail='pending_system_check','首次复核未发现目标链接；等待间隔期后的第二次系统核验，暂不判定丢失'
    elif row.status=='lost' or observed=='missing':state,detail='failed_retry','连续复核未发现目标链接；请客户确认来源页链接恢复后再核验'
    elif observed in {'unreachable','blocked'}:
        reason=BACKLINK_REASONS.get(verification.get('reason')) or '系统未能读取来源页'
        state,detail='failed_retry',f'{reason}；请检查来源页公开权限与可访问性，系统后续再核验'
    else:state,detail='failed_retry','未取得有效外链证据；请在外链模块确认来源页和目标地址后再核验'
    evidence={'source_url':_safe_evidence_url(row.source_url),'target_url':_safe_evidence_url(row.target_url),
              'verification':_safe_backlink_verification(verification),'missing_checks':missing_checks,
              'last_checked_at':row.last_checked_at} if row.last_checked_at or verification else None
    return _queue_item('backlink_verification',row,state,f'外链核验 · {row.source_domain}',detail,evidence,
                       f'/seo/links?site_id={row.site_id}&tab=backlink')

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
    action_type:Literal['content_review','image_repair','ranking_improvement','backlink_outreach']
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
    note:str|None=Field(None,min_length=1,max_length=2000)

@router.get('/metrics/snapshot',response_model=list[MetricContract])
async def snapshot(tenant_id:PositiveInt,site_id:PositiveInt,ctx=Depends(require_scoped_auth),session=Depends(get_session)):
    for permission in ('seo.content','seo.site','seo.keywords'):await scope(session,ctx,tenant_id,site_id,permission)
    values=await metric_snapshot(session,tenant_id,site_id)
    return [value for value in values if value['metric_key']!='seo.backlinks.verified_count' or ctx.can_view('seo.links')]

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
    site=await scope(session,ctx,req.tenant_id,req.site_id,TASK_PERMS[req.action_type],True)
    actor=str(ctx.user_id) if ctx.user_id is not None else 'cockpit'
    if req.created_by is not None and str(req.created_by)!=actor:raise HTTPException(403,'不能冒用任务创建人')
    if req.action_type=='content_review':
        content=await session.get(SeoContentAsset,req.params.get('content_id')) if isinstance(req.params.get('content_id'),int) else None
        if not content or content.tenant_id!=req.tenant_id or content.site_id!=req.site_id:raise HTTPException(422,'需要当前网站的 content_id')
    elif req.action_type=='image_repair':
        review=await session.get(SeoImageAltReview,req.params.get('review_id')) if isinstance(req.params.get('review_id'),int) else None
        if not review or review.tenant_id!=req.tenant_id or review.site_id!=req.site_id:raise HTTPException(422,'需要当前网站的 review_id')
    elif req.action_type=='backlink_outreach':
        from app.seo_backlink_sources import candidate_url
        from urllib.parse import urlparse
        try:source=candidate_url(req.params.get('source_url'))
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc
        from app.seo_backlinks import belongs_to_site
        if belongs_to_site(source,site.canonical_domain):raise HTTPException(422,'外链机会必须来自站外')
        req.params={'source_url':source,'source_domain':urlparse(source).hostname,
                    'opportunity_request_id':str(req.params.get('opportunity_request_id') or '')[:64]}
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
    elif row.action_type=='backlink_outreach':
        from app.models.seo import SeoBacklink
        created=row.created_at.astimezone(timezone.utc).replace(tzinfo=None)
        link=await session.scalar(select(SeoBacklink).where(SeoBacklink.tenant_id==row.tenant_id,SeoBacklink.site_id==row.site_id,
            SeoBacklink.source_domain==row.params['source_domain'],SeoBacklink.status=='active',
            SeoBacklink.verification['state'].astext=='found',SeoBacklink.last_checked_at>created,
            SeoBacklink.first_seen_at>created).order_by(SeoBacklink.id.desc()).limit(1))
        if link is None:raise HTTPException(409,'需要任务创建后从该来源实际发现并核实的新外链')
        proof={'backlink_id':link.id,'source_url':link.source_url,'target_url':link.target_url,'checked_at':link.last_checked_at.isoformat()}
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
    if req.note is not None:
        notes=list((row.params or {}).get('followups') or [])
        if len(notes)>=100:raise HTTPException(409,'跟进记录已达 100 条上限，请保留现有记录')
        notes.append({'note':req.note,'actor':str(ctx.user_id) if ctx.user_id is not None else 'cockpit','at':datetime.now(timezone.utc).isoformat()})
        row.params={**row.params,'followups':notes}
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

@router.get('/overview/customer-verification-queue')
async def customer_verification_queue(
    tenant_id:PositiveInt,site_id:PositiveInt,
    state:Literal['pending_customer_action','pending_system_check','verified','failed_retry']|None=None,
    kind:Literal['image_repair','publication_url','page_recheck','backlink_verification']|None=None,
    page:int=Query(1,ge=1,le=10000),page_size:int=Query(20,ge=1,le=50),
    ctx=Depends(require_scoped_auth),session=Depends(get_session),
):
    """Evidence-backed handoff queue. Reading never starts a crawl or publication."""
    ctx.ensure_tenant(tenant_id)
    if not ctx.can_view('seo.dashboard'):raise HTTPException(403,'没有任务中心查看权限')
    site_row=await session.get(SeoSite,site_id)
    if site_row is None or site_row.tenant_id!=tenant_id:raise HTTPException(404,'网站不存在')
    items=[];truncated_sources=[];source_counts={}
    if ctx.can_view('seo.site') and kind in (None,'image_repair'):
        rows=list(await session.scalars(select(SeoImageVerification).where(
            SeoImageVerification.tenant_id==tenant_id,SeoImageVerification.site_id==site_id,
            SeoImageVerification.status!='superseded').order_by(SeoImageVerification.id.desc()).limit(501)))
        source_counts['image_repair']=min(len(rows),500)
        if len(rows)>500:truncated_sources.append('image_repair')
        rows=rows[:500]
        items.extend(filter(None,(image_queue_item(row,ctx.can_edit('seo.site')) for row in rows)))
    if ctx.can_view('seo.content') and kind in (None,'publication_url'):
        rows=(await session.execute(select(SeoContentPublication,SeoContentAsset.site_id).join(
            SeoContentAsset,SeoContentAsset.id==SeoContentPublication.content_asset_id).where(
            SeoContentPublication.tenant_id==tenant_id,SeoContentAsset.tenant_id==tenant_id,
            SeoContentAsset.site_id==site_id).order_by(SeoContentPublication.id.desc()).limit(501))).all()
        source_counts['publication_url']=min(len(rows),500)
        if len(rows)>500:truncated_sources.append('publication_url')
        rows=rows[:500]
        publication_ids=[int(row.id) for row,_ in rows]
        latest_attempts={}
        if publication_ids:
            ranked_attempts=select(
                SeoPublishAttempt.id.label('attempt_id'),
                func.row_number().over(
                    partition_by=SeoPublishAttempt.publication_id,
                    order_by=(SeoPublishAttempt.started_at.desc(),SeoPublishAttempt.id.desc()),
                ).label('recency_rank'),
            ).where(
                SeoPublishAttempt.tenant_id==tenant_id,
                SeoPublishAttempt.publication_id.in_(publication_ids),
            ).subquery()
            attempts=list(await session.scalars(select(SeoPublishAttempt).join(
                ranked_attempts,ranked_attempts.c.attempt_id==SeoPublishAttempt.id,
            ).where(
                SeoPublishAttempt.tenant_id==tenant_id,
                ranked_attempts.c.recency_rank==1,
            )))
            latest_attempts={int(attempt.publication_id):attempt for attempt in attempts}
        for row,row_site_id in rows:
            row.site_id=row_site_id;items.append(publication_queue_item(row,latest_attempts.get(int(row.id))))
    if ctx.can_view('seo.site') and kind in (None,'page_recheck'):
        rows=list(await session.scalars(select(SeoSitePage).where(SeoSitePage.tenant_id==tenant_id,
            SeoSitePage.site_id==site_id,SeoSitePage.status.in_(['proposed','approved','needs_fix','pending','implemented','verified','error']))
            .order_by(SeoSitePage.updated_at.desc(),SeoSitePage.id.desc()).limit(501)))
        source_counts['page_recheck']=min(len(rows),500)
        if len(rows)>500:truncated_sources.append('page_recheck')
        rows=rows[:500]
        items.extend(filter(None,(page_queue_item(row) for row in rows)))
    if ctx.can_view('seo.links') and kind in (None,'backlink_verification'):
        rows=list(await session.scalars(select(SeoBacklink).where(SeoBacklink.tenant_id==tenant_id,
            SeoBacklink.site_id==site_id,SeoBacklink.status!='disavow').order_by(SeoBacklink.updated_at.desc(),SeoBacklink.id.desc()).limit(501)))
        source_counts['backlink_verification']=min(len(rows),500)
        if len(rows)>500:truncated_sources.append('backlink_verification')
        rows=rows[:500]
        items.extend(backlink_queue_item(row) for row in rows)
    summary={value:sum(item['state']==value for item in items) for value in QUEUE_STATES}
    if state:items=[item for item in items if item['state']==state]
    items.sort(key=lambda item:(item['updated_at'] is not None,item['updated_at'] or datetime.min.replace(tzinfo=timezone.utc),item['id']),reverse=True)
    total=len(items);start=(page-1)*page_size
    return {'items':items[start:start+page_size],'total':total,'page':page,'page_size':page_size,'summary':summary,
            'state_definitions':{
                'pending_customer_action':'需要客户或运营人员先完成真实网站/平台操作',
                'pending_system_check':'客户动作已有记录，等待系统抓取或平台核验',
                'verified':'系统已取得真实页面或平台证据',
                'failed_retry':'核验失败或证据不可用，可以重试'},
            'read_only':True,'as_of':datetime.now(timezone.utc),'scanned_count':sum(source_counts.values()),
            'source_counts':source_counts,'truncated':bool(truncated_sources),'truncated_sources':truncated_sources,'has_more':bool(truncated_sources)}

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
    row.evidence=prepare_image_verification_retry(row,now,ctx.user_id)
    row.status='pending';row.available_at=now
    await session.commit()
    return {'id':row.id,'status':'pending','attempt':row.evidence['attempt'],'retry_request':row.evidence['retry_request']}

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
