"""Tenant-bound video authorization and durable, explicitly confirmed publication."""
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field, PositiveInt
from sqlalchemy import select
from app.database import get_session
from app.security.auth import require_scoped_auth
from app.models.seo import SeoDistributionConnection, SeoContentAsset, SeoContentPublication, SeoPublishAttempt
from app.api.seo_cockpit import scope
from app.seo_distribution import encrypt_credentials, decrypt_credentials
from app import seo_video_platforms as video

router=APIRouter(prefix='/content-distribution/video')

class Scope(BaseModel):
    model_config=ConfigDict(extra='forbid')
    tenant_id:PositiveInt
    site_id:PositiveInt
    connection_id:PositiveInt

class Authorization(Scope):
    code:str=Field(min_length=1,max_length=2048)
    state:str=Field(min_length=32,max_length=200)

class Recovery(Scope):
    item_id:str=Field(min_length=1,max_length=255)

@router.post('/publications/{publication_id}/recover')
async def recover(publication_id:int,req:Recovery,ctx=Depends(require_scoped_auth),session=Depends(get_session)):
    row,pub,_=await publication(req,publication_id,ctx,session)
    if pub.external_id or pub.status not in {'manual_required','publishing'}:raise HTTPException(409,'仅支持恢复作品 ID 缺失且曾提交的任务')
    attempted=await session.scalar(select(SeoPublishAttempt.id).where(SeoPublishAttempt.tenant_id==req.tenant_id,SeoPublishAttempt.publication_id==pub.id,SeoPublishAttempt.action=='video_publish').limit(1))
    if not attempted:raise HTTPException(409,'该任务尚未尝试发布')
    try:result=await video.sync(row.platform_code,decrypt_credentials(row.credentials_encrypted),req.item_id)
    except video.VideoError as exc:raise HTTPException(502,str(exc)) from exc
    if not result.get('title') or result['title'].strip()!=pub.adapted_title.strip():raise HTTPException(409,'未查到当前账号下标题一致的作品，不能关联此 ID')
    pub.external_id=req.item_id;pub.status='publishing';pub.last_error=None
    session.add(SeoPublishAttempt(tenant_id=req.tenant_id,publication_id=pub.id,action='video_recover',status='succeeded',
        request_summary={'item_id':req.item_id},response_summary=result,created_by=ctx.user_id,completed_at=datetime.utcnow()))
    await session.commit();return publication_info(pub)

async def connection(req,ctx,session,write=True):
    await scope(session,ctx,req.tenant_id,req.site_id,'seo.content',write)
    row=await session.get(SeoDistributionConnection,req.connection_id,with_for_update=write,populate_existing=True)
    if not row or row.tenant_id!=req.tenant_id or row.platform_code not in video.PLATFORMS:raise HTTPException(404,'视频连接不存在')
    if not row.enabled:raise HTTPException(409,'连接已停用')
    return row

def auth_info(row):
    credentials=decrypt_credentials(row.credentials_encrypted)
    return {'connection_id':row.id,'platform_code':row.platform_code,'name':row.name,
        'authorized':bool(credentials.get('access_token')),'expires_at':credentials.get('expires_at'),
        'scope':credentials.get('scope'),'state':(row.config or {}).get('video_auth_state','not_authorized')}

@router.get('/connections')
async def list_connections(tenant_id:PositiveInt,site_id:PositiveInt,ctx=Depends(require_scoped_auth),session=Depends(get_session)):
    await scope(session,ctx,tenant_id,site_id,'seo.content')
    rows=await session.scalars(select(SeoDistributionConnection).where(SeoDistributionConnection.tenant_id==tenant_id,
        SeoDistributionConnection.platform_code.in_(video.PLATFORMS),SeoDistributionConnection.enabled.is_(True)))
    return [auth_info(row) for row in rows]

@router.post('/authorize')
async def authorize(req:Scope,ctx=Depends(require_scoped_auth),session=Depends(get_session)):
    row=await connection(req,ctx,session);credentials=decrypt_credentials(row.credentials_encrypted)
    state=secrets.token_urlsafe(40)
    url=video.authorization_url(row.platform_code,credentials,state)
    row.config={**(row.config or {}),'video_oauth_pending':{'digest':hashlib.sha256(state.encode()).hexdigest(),
        'actor':ctx.user_id,'site_id':req.site_id,'expires':time.time()+600},'video_auth_state':'awaiting_consent','video_auth_operation':secrets.token_hex(16)}
    await session.commit()
    return {'authorization_url':url,'state':state}

def valid_state(pending,req,ctx):
    return bool(pending and pending.get('actor')==ctx.user_id and pending.get('site_id')==req.site_id and
        pending.get('expires',0)>time.time() and hmac.compare_digest(pending.get('digest',''),hashlib.sha256(req.state.encode()).hexdigest()))

def app_fingerprint(platform,credentials):
    spec=video.PLATFORMS[platform]
    return hashlib.sha256(json.dumps([credentials.get(spec['app_key']),credentials.get(spec['secret_key'])]).encode()).hexdigest()

async def finish_auth(req,ctx,session,operation,original,updated=None):
    row=await connection(req,ctx,session)
    if (row.config or {}).get('video_auth_operation')!=operation or app_fingerprint(row.platform_code,decrypt_credentials(row.credentials_encrypted))!=original:
        raise HTTPException(409,'连接配置或授权流程已变化，旧授权结果未覆盖新配置')
    if updated:
        row.credentials_encrypted=encrypt_credentials(updated);row.has_credentials=True;row.status='connected'
    row.config={**(row.config or {}),'video_auth_state':'authorized' if updated else 'reauthorize_required'}
    await session.commit();return auth_info(row)

@router.post('/authorize/complete')
async def complete(req:Authorization,ctx=Depends(require_scoped_auth),session=Depends(get_session)):
    row=await connection(req,ctx,session)
    if not valid_state((row.config or {}).get('video_oauth_pending'),req,ctx):raise HTTPException(409,'授权状态已过期、不匹配或已使用，请重新授权')
    credentials=decrypt_credentials(row.credentials_encrypted)
    operation=secrets.token_hex(16);fingerprint=app_fingerprint(row.platform_code,credentials)
    row.config={**(row.config or {}),'video_oauth_pending':None,'video_auth_state':'exchanging','video_auth_operation':operation}
    await session.commit()  # Single-use code/state remains consumed even after an uncertain failure.
    try:updated=await video.token(row.platform_code,credentials,code=req.code)
    except Exception:
        await finish_auth(req,ctx,session,operation,fingerprint)
        raise HTTPException(502,'授权交换未完成，请重新发起授权') from None
    return await finish_auth(req,ctx,session,operation,fingerprint,updated)

@router.post('/authorize/refresh')
async def refresh(req:Scope,ctx=Depends(require_scoped_auth),session=Depends(get_session)):
    row=await connection(req,ctx,session)
    if (row.config or {}).get('video_auth_state')!='authorized':raise HTTPException(409,'授权操作未确认完成，请重新授权')
    credentials=decrypt_credentials(row.credentials_encrypted)
    if not credentials.get('refresh_token'):raise HTTPException(409,'请先完成用户授权')
    operation=secrets.token_hex(16);fingerprint=app_fingerprint(row.platform_code,credentials)
    row.config={**(row.config or {}),'video_auth_state':'refreshing','video_auth_operation':operation};await session.commit()
    try:updated=await video.token(row.platform_code,credentials,refresh=True)
    except Exception:
        await finish_auth(req,ctx,session,operation,fingerprint)
        raise HTTPException(502,'授权刷新未确认完成，请重新授权，不要重复刷新旧凭据') from None
    return await finish_auth(req,ctx,session,operation,fingerprint,updated)

async def file_bytes(file,maximum,image=False):
    data=await file.read(maximum+1)
    if not data or len(data)>maximum:raise HTTPException(422,'文件为空或超过大小限制')
    if image:
        if data.startswith(b'\x89PNG\r\n\x1a\n'):return ('cover.png',data,'image/png')
        if data.startswith(b'\xff\xd8\xff'):return ('cover.jpg',data,'image/jpeg')
        raise HTTPException(422,'封面必须是 JPG 或 PNG')
    if data[4:8]!=b'ftyp':raise HTTPException(422,'视频必须是 MP4 文件')
    return data

def publication_info(row):
    return {key:getattr(row,key) for key in ('id','content_asset_id','connection_id','platform_code','status','adapted_title','external_id','page_url','last_error','source_version')}

@router.get('/publications')
async def publications(tenant_id:PositiveInt,site_id:PositiveInt,ctx=Depends(require_scoped_auth),session=Depends(get_session)):
    await scope(session,ctx,tenant_id,site_id,'seo.content')
    rows=await session.scalars(select(SeoContentPublication).join(SeoContentAsset,SeoContentAsset.id==SeoContentPublication.content_asset_id).where(
        SeoContentPublication.tenant_id==tenant_id,SeoContentAsset.tenant_id==tenant_id,SeoContentAsset.site_id==site_id,
        SeoContentPublication.platform_code.in_(video.PLATFORMS)).order_by(SeoContentPublication.id.desc()).limit(100))
    return [publication_info(row) for row in rows]

@router.post('/upload')
async def upload(tenant_id:PositiveInt=Form(...),site_id:PositiveInt=Form(...),connection_id:PositiveInt=Form(...),content_id:PositiveInt=Form(...),
                 source_version:PositiveInt=Form(...),request_id:UUID=Form(...),title:str=Form(...,min_length=1,max_length=55),file:UploadFile=File(...),
                 ctx=Depends(require_scoped_auth),session=Depends(get_session)):
    req=Scope(tenant_id=tenant_id,site_id=site_id,connection_id=connection_id)
    row=await connection(req,ctx,session);credentials=decrypt_credentials(row.credentials_encrypted)
    try:video.require_token(credentials)
    except video.VideoError as exc:raise HTTPException(409,str(exc)) from exc
    content=await session.get(SeoContentAsset,content_id)
    if not content or content.tenant_id!=tenant_id or content.site_id!=site_id:raise HTTPException(404,'内容不存在')
    if content.status not in {'ready','published'} or (content.version_count or 1)!=source_version:raise HTTPException(409,'内容必须通过审核且版本一致')
    key=hashlib.sha256(f'video:{tenant_id}:{site_id}:{connection_id}:{request_id}'.encode()).hexdigest()
    previous=await session.scalar(select(SeoContentPublication).where(SeoContentPublication.idempotency_key==key))
    if previous:return publication_info(previous)
    data=await file_bytes(file,(48 if row.platform_code=='douyin_video' else 8)*1024*1024)
    pub=SeoContentPublication(tenant_id=tenant_id,content_asset_id=content_id,connection_id=connection_id,
        platform_code=row.platform_code,platform_name=row.name,publish_mode='official_video',status='uploading',source_version=source_version,
        adapted_title=title.strip(),idempotency_key=key,created_by=ctx.user_id)
    session.add(pub);await session.flush()
    attempt=SeoPublishAttempt(tenant_id=tenant_id,publication_id=pub.id,action='video_upload',status='running',created_by=ctx.user_id,
        request_summary={'bytes':len(data),'source_version':source_version,'account_fingerprint':hashlib.sha256(credentials['open_id'].encode()).hexdigest()})
    session.add(attempt);await session.commit()
    try:
        media=await video.upload(row.platform_code,credentials,data)
        # Upload handles are sensitive; encrypt at rest. API responses omit this field.
        attempt.response_summary={'sealed_video_media':encrypt_credentials(media)}
        attempt.status='succeeded';pub.status='draft'
    except Exception:
        attempt.status='failed';pub.status='manual_required';pub.last_error='素材上传未确认完成，请先核实平台素材库；未自动重试'
    attempt.completed_at=datetime.utcnow();await session.commit();return publication_info(pub)

async def publication(req,pub_id,ctx,session):
    row=await connection(req,ctx,session)
    pub=await session.get(SeoContentPublication,pub_id,with_for_update=True,populate_existing=True)
    if not pub or pub.tenant_id!=req.tenant_id or pub.connection_id!=row.id:raise HTTPException(404,'发布任务不存在')
    content=await session.get(SeoContentAsset,pub.content_asset_id)
    if not content or content.tenant_id!=req.tenant_id or content.site_id!=req.site_id:raise HTTPException(404,'发布任务不存在')
    return row,pub,content

@router.post('/publications/{publication_id}/publish')
async def publish(publication_id:int,tenant_id:PositiveInt=Form(...),site_id:PositiveInt=Form(...),connection_id:PositiveInt=Form(...),
                  confirmed:bool=Form(False),cover:UploadFile|None=File(None),ctx=Depends(require_scoped_auth),session=Depends(get_session)):
    req=Scope(tenant_id=tenant_id,site_id=site_id,connection_id=connection_id)
    row,pub,content=await publication(req,publication_id,ctx,session)
    if not confirmed:raise HTTPException(422,'请确认本次视频及账号后再发布')
    if pub.status!='draft':raise HTTPException(409,'任务不是可发布草稿；已提交或结果不确定的任务不能重发')
    if content.status not in {'ready','published'} or (content.version_count or 1)!=pub.source_version:raise HTTPException(409,'内容状态或版本已变化，请重新审核制作素材')
    credentials=decrypt_credentials(row.credentials_encrypted)
    try:video.require_token(credentials)
    except video.VideoError as exc:raise HTTPException(409,str(exc)) from exc
    image=await file_bytes(cover,3*1024*1024,True) if cover else None
    if row.platform_code=='kuaishou_video' and not image:raise HTTPException(422,'快手需要封面，最大 3 MB')
    previous=await session.scalar(select(SeoPublishAttempt).where(SeoPublishAttempt.tenant_id==tenant_id,SeoPublishAttempt.publication_id==pub.id,
        SeoPublishAttempt.action=='video_upload',SeoPublishAttempt.status=='succeeded').order_by(SeoPublishAttempt.id.desc()).limit(1))
    if not previous:raise HTTPException(409,'缺少已确认的素材上传记录')
    if (previous.request_summary or {}).get('account_fingerprint')!=hashlib.sha256(credentials['open_id'].encode()).hexdigest():raise HTTPException(409,'授权账号已变化，不能使用旧账号素材发布')
    media=decrypt_credentials((previous.response_summary or {}).get('sealed_video_media'))
    pub.status='publishing'
    attempt=SeoPublishAttempt(tenant_id=tenant_id,publication_id=pub.id,action='video_publish',status='running',created_by=ctx.user_id,request_summary={'confirmed':True,'title':pub.adapted_title})
    session.add(attempt);await session.commit()  # Claim before network call, never blind-retry.
    try:
        pub.external_id=await video.publish(row.platform_code,credentials,media,pub.adapted_title,image)
        attempt.status='succeeded';attempt.response_summary={'item_id':pub.external_id,'state':'submitted'}
    except Exception:
        pub.status='manual_required';pub.last_error='发布结果未确认，请到平台检查；不能直接重复提交';attempt.status='failed'
    attempt.completed_at=datetime.utcnow();await session.commit();return publication_info(pub)

@router.post('/publications/{publication_id}/sync')
async def sync(publication_id:int,req:Scope,ctx=Depends(require_scoped_auth),session=Depends(get_session)):
    row,pub,content=await publication(req,publication_id,ctx,session)
    if not pub.external_id:raise HTTPException(409,'尚无作品 ID，请先到平台核实提交结果')
    try:result=await video.sync(row.platform_code,decrypt_credentials(row.credentials_encrypted),pub.external_id)
    except video.VideoError as exc:raise HTTPException(502,str(exc)) from exc
    pub.status=result['status'];pub.page_url=result['page_url'];pub.last_synced_at=datetime.utcnow()
    if pub.status=='published' and not pub.published_at:pub.published_at=datetime.utcnow()
    if pub.status=='published' and (content.version_count or 1)==pub.source_version and content.status in {'ready','published'}:
        content.status='published';content.published_at=content.published_at or pub.published_at
    session.add(SeoPublishAttempt(tenant_id=req.tenant_id,publication_id=pub.id,action='video_sync',status='succeeded',response_summary=result,created_by=ctx.user_id,completed_at=datetime.utcnow()))
    await session.commit();return publication_info(pub)
