"""Trusted in-process publication adoption. No HTTP write route or platform I/O."""
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.seo_distribution_sources import authorize_scope, load_source, positive


class VerifiedPublication(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    event_id: Annotated[UUID,Field(strict=False)]
    task_id: Annotated[UUID,Field(strict=False)]
    source_revision: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,100}$')
    content_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    platform: Literal['wechat-article','xiaohongshu-image']
    public_url: str = Field(min_length=1,max_length=2000)
    reported_at: int = Field(ge=946684800000,le=4102444800000)
    verification: Literal['human-verified','machine-verified']
    verified_at: int = Field(ge=946684800000,le=4102444800000)
    verified_by: int = Field(gt=0,lt=2**63)


def error(code,message,status=409):
    return HTTPException(status,{'code':'seo_distribution_result_'+code,'message':message})


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def content_digest(content):
    # Exact central v1 ordered tuple / Node JSON.stringify algorithm.
    value=[content['version'],content['title'],content['body'],[
        [a['id'],a['sha256'],a['mediaType'],a['bytes']] for a in content['assets']]]
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def validate_payload(publication,actor):
    try:
        value=VerifiedPublication.model_validate(publication)
        parsed=urlsplit(value.public_url)
        host,pattern=('mp.weixin.qq.com',r'/s/[a-zA-Z0-9_-]+') if value.platform=='wechat-article' else (
            'www.xiaohongshu.com',r'/explore/[a-f0-9]+')
        if (parsed.scheme!='https' or parsed.netloc!=host or not re.fullmatch(pattern,parsed.path)
                or value.public_url!='https://'+host+parsed.path or parsed.query or parsed.fragment):
            raise ValueError()
        if (value.verified_by!=actor or value.verified_at<value.reported_at
                or value.verified_at>int(datetime.now(timezone.utc).timestamp()*1000)+300000):
            raise ValueError()
        return value.model_dump(mode='json')
    except (ValidationError,ValueError,TypeError):
        raise error('invalid_payload','需要完整、已核验且与当前实名主体一致的规范发布结果',422) from None


async def lock(session,key):
    number=int.from_bytes(hashlib.sha256(('seo-result:'+key).encode()).digest()[:8],'big',signed=True)
    await session.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':number})


async def one(session,sql,params):
    return (await session.execute(text(sql),params)).mappings().one_or_none()


async def record_publication(session, actor_user_id, tenant_id, scope_id, variant_id, publication:dict):
    """Call only with centrally verified, server-created events, never a client body.

    Caller commits. Uses a savepoint for atomic failure, no network/commit. A
    clean READ COMMITTED session is required. Replay revalidates current scope,
    review and source; it never authorizes another external publication.
    """
    await authorize_scope(session,actor_user_id,tenant_id,scope_id)
    if not positive(variant_id):raise error('invalid_payload','渠道稿编号无效',422)
    payload=validate_payload(publication,actor_user_id)
    if session.new or session.dirty or session.deleted:
        raise error('session_not_clean','请在独立的干净事务中接纳发布结果')
    identity={'actor_user_id':actor_user_id,'tenant_id':tenant_id,'scope_id':scope_id,'variant_id':variant_id}
    fingerprint=hashlib.sha256(canonical({**identity,'publication':payload}).encode()).hexdigest()
    task_fingerprint=hashlib.sha256(canonical({**identity,'publication':{k:v for k,v in payload.items() if k!='event_id'}}).encode()).hexdigest()
    try:
        async with session.begin_nested():
            await lock(session,'event:'+payload['event_id'])
            await lock(session,'task:'+payload['task_id'])
            snapshot=await load_source(session,actor_user_id,tenant_id,scope_id,variant_id,payload['platform'])
            if snapshot['source_revision']!=payload['source_revision'] or content_digest(snapshot['content'])!=payload['content_digest']:
                raise error('source_changed','已审来源版本或摘要已变化')
            prior=await one(session,'SELECT * FROM seo_distribution_result_events WHERE event_id=:id',{'id':UUID(payload['event_id'])})
            if prior:
                if prior['fingerprint']!=fingerprint:raise error('event_conflict','该事件已用于不同的发布结果')
                return {**prior['result'],'created':False,'replayed':True,'idempotent':True}
            prior=await one(session,'SELECT * FROM seo_distribution_result_events WHERE task_id=:id '
                'ORDER BY created_at,event_id LIMIT 1',{'id':UUID(payload['task_id'])})
            if prior:
                if prior['task_fingerprint']!=task_fingerprint:raise error('task_conflict','该任务已回写不同的发布结果')
                result={**prior['result'],'created':False,'replayed':True,'idempotent':True}
                await _save_event(session,identity,payload,fingerprint,task_fingerprint,result)
                return result
            # Same site lock as existing native page-capture and workflow paths.
            await session.execute(text('SELECT id FROM seo_sites WHERE id=:site AND tenant_id=:tenant FOR UPDATE'),
                {'site':scope_id,'tenant':tenant_id})
            source=await one(session,'SELECT c.id FROM seo_content_assets c JOIN seo_distribution_variants v '
                'ON v.content_asset_id=c.id WHERE v.id=:variant AND v.tenant_id=:tenant '
                'AND c.tenant_id=:tenant AND c.site_id=:site FOR UPDATE OF c',
                {'variant':variant_id,'tenant':tenant_id,'site':scope_id})
            if source is None:raise error('source_missing','当前网站没有该渠道稿',404)
            await session.execute(text('SELECT id FROM seo_distribution_variants WHERE id=:id FOR UPDATE'),{'id':variant_id})
            snapshot=await load_source(session,actor_user_id,tenant_id,scope_id,variant_id,payload['platform'])
            if snapshot['source_revision']!=payload['source_revision'] or content_digest(snapshot['content'])!=payload['content_digest']:
                raise error('source_changed','已审来源版本或摘要已变化')
            row=await one(session,'SELECT v.content_asset_id,v.connection_id,v.source_version,a.mode '
                'FROM seo_distribution_variants v JOIN seo_distribution_connections a ON a.id=v.connection_id WHERE v.id=:id',
                {'id':variant_id})
            duplicate=await one(session,'SELECT id FROM seo_content_publications '
                'WHERE tenant_id=:tenant AND content_asset_id=:content AND page_url=:url',
                {'tenant':tenant_id,'content':row['content_asset_id'],'url':payload['public_url']})
            if duplicate:raise error('publication_conflict','该内容的发布地址已登记，请核对原记录')
            published_at=datetime.fromtimestamp(payload['reported_at']/1000,timezone.utc).replace(tzinfo=None)
            verified_at=datetime.fromtimestamp(payload['verified_at']/1000,timezone.utc).replace(tzinfo=None)
            metadata={**payload,'module':'seo','time_basis':'reported_at','search_engine_indexed':None}
            published=await one(session,'INSERT INTO seo_content_publications '
                '(tenant_id,content_asset_id,connection_id,variant_id,platform_code,platform_name,publish_mode,status,'
                'source_version,adapted_title,adapted_content,page_url,published_at,created_by,idempotency_key,link_discovery) '
                "VALUES(:tenant,:content,:connection,:variant,:platform,:name,:mode,'published',:version,:title,:body,:url,:at,:actor,:key,CAST(:meta AS jsonb)) RETURNING id",
                {'tenant':tenant_id,'content':row['content_asset_id'],'connection':row['connection_id'],'variant':variant_id,
                    'platform':'wechat_official' if payload['platform']=='wechat-article' else 'xiaohongshu',
                    'name':'微信公众号' if payload['platform']=='wechat-article' else '小红书','mode':row['mode'],
                    'version':row['source_version'],'title':snapshot['content']['title'],'body':snapshot['content']['body'],
                    'url':payload['public_url'],'at':published_at,'actor':actor_user_id,
                    'key':hashlib.sha256(('central-result:'+payload['task_id']).encode()).hexdigest(),'meta':canonical(metadata)})
            attempt=await one(session,'INSERT INTO seo_publish_attempts '
                '(tenant_id,publication_id,action,status,request_summary,response_summary,created_by,completed_at) '
                "VALUES(:tenant,:publication,'central_verified','succeeded',CAST(:request AS jsonb),CAST(:response AS jsonb),:actor,:at) RETURNING id",
                {'tenant':tenant_id,'publication':published['id'],'actor':actor_user_id,'at':verified_at,
                    'request':canonical({'event_id':payload['event_id'],'task_id':payload['task_id'],
                        'source_revision':payload['source_revision'],'content_digest':payload['content_digest']}),
                    'response':canonical(metadata)})
            # Do not mark the channel variant "published": its reviewed seal is
            # required by device revalidation and other currently valid tasks.
            await session.execute(text("UPDATE seo_content_assets SET status='published',published_at=COALESCE(published_at,:at),"
                "page_url=CASE WHEN page_url IS NULL OR page_url='' THEN :url ELSE page_url END WHERE id=:id"),
                {'at':published_at,'url':payload['public_url'],'id':row['content_asset_id']})
            from app.api.seo_page_captures import reserve_publication_page_capture
            capture,reason=await reserve_publication_page_capture(session,tenant_id=tenant_id,site_id=scope_id,
                publication_id=published['id'],page_url=payload['public_url'])
            if capture is not None:
                capture.warnings={**(capture.warnings or {}),'_central_publication':True}
                await session.flush()
            if snapshot!=await load_source(session,actor_user_id,tenant_id,scope_id,variant_id,payload['platform']):
                raise error('source_changed','接纳结果期间来源发生变化')
            result={'module':'seo','tenant_id':tenant_id,'scope_id':scope_id,'variant_id':variant_id,
                'publication_id':published['id'],'attempt_id':attempt['id'],'status':'published',
                'public_url':payload['public_url'],'verification':payload['verification'],
                'monitor_state':capture.status if capture else 'not_queued',
                'reported_at':payload['reported_at'],'verified_at':payload['verified_at'],'verified_by':actor_user_id,
                'page_check':{'capture_id':capture.id if capture else None,'state':'pending' if capture else 'not_queued','reason':reason},
                'search_engine_indexed':None,'indexation_state':'not_measured','seo_effect':'not_evaluated',
                'created':True,'replayed':False,'idempotent':False}
            await _save_event(session,identity,payload,fingerprint,task_fingerprint,result)
            return result
    except (SQLAlchemyError,OSError,TimeoutError):
        raise error('unavailable','发布结果存储或结构暂不可用',503) from None


async def _save_event(session,identity,payload,fingerprint,task_fingerprint,result):
    await session.execute(text('INSERT INTO seo_distribution_result_events '
        '(event_id,task_id,tenant_id,site_id,variant_id,actor_user_id,fingerprint,task_fingerprint,publication_id,attempt_id,capture_id,payload,result) '
        'VALUES(:event,:task,:tenant,:site,:variant,:actor,:fingerprint,:task_fingerprint,:publication,:attempt,:capture,CAST(:payload AS jsonb),CAST(:result AS jsonb))'),
        {'event':UUID(payload['event_id']),'task':UUID(payload['task_id']),'tenant':identity['tenant_id'],
            'site':identity['scope_id'],'variant':identity['variant_id'],'actor':identity['actor_user_id'],
            'fingerprint':fingerprint,'task_fingerprint':task_fingerprint,'publication':result['publication_id'],
            'attempt':result['attempt_id'],'capture':result['page_check']['capture_id'],
            'payload':canonical(payload),'result':canonical(result)})


async def pending_page_checks(session,actor_user_id,tenant_id,scope_id):
    """Read-only recovery listing; caller dispatches existing capture worker after commit."""
    await authorize_scope(session,actor_user_id,tenant_id,scope_id)
    rows=(await session.execute(text('SELECT DISTINCT c.id AS capture_id,c.relation_id AS publication_id,c.source_url,c.status '
        'FROM seo_page_captures c JOIN seo_distribution_result_events e ON e.capture_id=c.id '
        "WHERE e.tenant_id=:tenant AND e.site_id=:site AND c.tenant_id=:tenant AND c.site_id=:site AND c.status='pending' "
        "AND c.relation_type='publication' AND c.relation_id=e.publication_id ORDER BY c.id LIMIT 50"),
        {'tenant':tenant_id,'site':scope_id})).mappings().all()
    return [dict(row) for row in rows]


async def publication_monitor_status(session, actor_user_id, tenant_id, scope_id, publication_id):
    """Live, read-only evidence state; never revalidate an article's later edits.

    Core savepoint preserves the caller's transaction on missing structure and
    avoids ORM begin_nested's unconditional flush of caller pending changes.
    """
    if not positive(publication_id): raise error('invalid_publication','发布编号无效',422)
    base={'module':'seo','publication_id':publication_id,'basis':'page-capture','state':'unavailable',
          'evidence_source':'none','observed_at':None,'next_check_at':None,'evidence_id':None,'code':'MONITOR_UNAVAILABLE'}
    try:
        with session.no_autoflush:
            async with (await session.connection()).begin_nested():
                await authorize_scope(session,actor_user_id,tenant_id,scope_id)
                present=await session.scalar(text("SELECT to_regclass('seo_content_publications') IS NOT NULL "
                    "AND to_regclass('seo_content_assets') IS NOT NULL AND to_regclass('seo_page_captures') IS NOT NULL"))
                if not present: return base
                publication=await one(session,'SELECT p.page_url,p.link_discovery FROM seo_content_publications p '
                    'JOIN seo_content_assets a ON a.id=p.content_asset_id WHERE p.id=:id AND p.tenant_id=:tenant '
                    'AND a.tenant_id=:tenant AND a.site_id=:site',{'id':publication_id,'tenant':tenant_id,'site':scope_id})
                if publication is None: raise error('publication_scope','发布记录不属于当前授权网站',403)
                central=isinstance(publication['link_discovery'],dict) and publication['link_discovery'].get('module')=='seo'
                if central and not await session.scalar(text("SELECT to_regclass('seo_distribution_result_events') IS NOT NULL "
                        "AND to_regclass('distribution_controls') IS NOT NULL")): return base
                row=await one(session,"SELECT id,source_url,status,source,captured_at,error_code,http_status,warnings,sha256,storage_key,uploaded_by,uploaded_at "
                    "FROM seo_page_captures WHERE tenant_id=:tenant AND site_id=:site AND relation_type='publication' "
                    "AND relation_id=:id ORDER BY captured_at DESC,id DESC LIMIT 1",{'tenant':tenant_id,'site':scope_id,'id':publication_id})
                if row is None: return {**base,'state':'not_queued','code':'PAGE_CHECK_NOT_QUEUED'}
                warnings=row['warnings'] if isinstance(row['warnings'],dict) else {}
                if warnings.get('_central_publication') and not await session.scalar(text(
                        "SELECT to_regclass('seo_distribution_result_events') IS NOT NULL AND to_regclass('distribution_controls') IS NOT NULL")):
                    return base
                if row['source'] not in {'auto','manual'}: return base
                if row['source']=='manual' and (row['uploaded_by'] is None or row['uploaded_at'] is None): return base
                result={**base,'evidence_source':row['source'],'evidence_id':row['id']}
                if row['source_url']!=publication['page_url']:
                    return {**result,'state':'mismatch','code':'PAGE_LINK_CHANGED'}
                state={'pending':'pending','running':'running','failed':'failed','succeeded':'captured'}.get(row['status'])
                if state is None: return base
                if state=='captured' and (not row['sha256'] or not row['storage_key']): return base
                code={'pending':'PAGE_CHECK_PENDING','running':'PAGE_CHECK_RUNNING','failed':'PAGE_CHECK_FAILED','captured':'PAGE_CAPTURED'}[state]
                if row['error_code']=='source_changed':state,code='version_changed','SOURCE_VERSION_CHANGED'
                elif row['error_code'] in {'project_paused','project_ended'}: code='PROJECT_NOT_RUNNING'
                elif row['error_code']=='retry_exhausted':code='PAGE_CHECK_RETRY_EXHAUSTED'
                elif row['error_code']=='publication_url_mismatch':state,code='mismatch','PAGE_LINK_CHANGED'
                meta=warnings.get('_publication_dispatch',{})
                if not isinstance(meta,dict): meta={}
                next_at=meta.get('next_attempt_at')
                if type(next_at) is not int or next_at<=0 or meta.get('terminal'): next_at=None
                if next_at is not None:
                    if not await session.scalar(text("SELECT to_regclass('distribution_controls') IS NOT NULL")):
                        next_at=None
                    elif await session.scalar(text("SELECT state FROM distribution_controls WHERE module='seo' "
                            "AND tenant_id=:tenant AND scope_id=:site"),{'tenant':tenant_id,'site':scope_id})!='running':
                        next_at=None
                observed=int(row['captured_at'].timestamp()*1000) if state=='captured' or state=='failed' and row['http_status'] is not None else None
                return {**result,'state':state,'code':code,'observed_at':observed,'next_check_at':next_at}
    except HTTPException as exc:
        if exc.status_code>=500: return base
        raise
    except (SQLAlchemyError,OSError,TimeoutError):
        return base
