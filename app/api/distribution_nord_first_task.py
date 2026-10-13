"""Prepare one unreviewed Nord article and cover through a named advisor."""
import hashlib
import re
from pathlib import Path
from typing import Literal
from uuid import UUID
from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from app.database import get_session
from app.security.auth import require_auth
from app.api.distribution import PrivateRoute
from app.api.distribution_nord_onboarding import context, state
from app.models.seo import SeoContentAsset, SeoDistributionConnection, SeoDistributionVariant, SeoKeywordAsset
from app.distribution_nord_packet import PACKET
from app.seo_distribution import prepare_content, platform_content_rules
from app import seo_distribution_media as media, distribution_control as core

router=APIRouter(prefix='/api/distribution/nord/v1/first-task',route_class=PrivateRoute)
COVER=Path(__file__).resolve().parents[1]/'static/nord-first-task/cover.png'
MARKER='nord-first-source-13-v1-keyword-48'

class PrepareDraft(BaseModel):
    model_config=ConfigDict(extra='forbid')
    device_id: UUID
    external_account_id: str=Field(pattern=r'^gh_[a-f0-9]{12}$')
    prepare_unreviewed_draft: Literal[True]

class ReviewMaster(BaseModel):
    model_config=ConfigDict(extra='forbid')
    device_id: UUID
    external_account_id: str=Field(pattern=r'^gh_[a-f0-9]{12}$')
    content_id: int=Field(gt=0)
    expected_version: int=Field(gt=0)
    expected_hash: str=Field(pattern=r'^[a-f0-9]{64}$')
    confirm_full_content: Literal[True]
    confirm_advisor_proxy: Literal[True]

async def binding_context(db,ctx,device_id,account):
    fresh=await context(db,ctx,device_id,account)
    await core.authorize_scope(db,fresh.user_id,{'module':'seo','tenant_id':1,'scope_id':1})
    binding=await core.one(db,'SELECT id FROM distribution_bindings WHERE tenant_id=1 AND scope_id=1 '
        "AND module='seo' AND platform='wechat-article' AND device_id=:d AND external_account_id=:a AND active",
        d=str(device_id),a=account)
    prepared=await state(db,fresh,account)
    if not binding or not prepared['connection_id']:raise HTTPException(409,'请先完成诺德账号接入')
    return fresh,binding,prepared['connection_id']

async def existing(db,connection_id):
    return await db.scalar(select(SeoDistributionVariant).join(SeoContentAsset,
        SeoContentAsset.id==SeoDistributionVariant.content_asset_id).where(
        SeoDistributionVariant.tenant_id==1,SeoContentAsset.tenant_id==1,SeoContentAsset.site_id==1,
        SeoDistributionVariant.connection_id==connection_id,
        SeoDistributionVariant.generation_instruction==MARKER).order_by(SeoDistributionVariant.id.desc()).limit(1))

async def describe(db,actor,binding,variant):
    if variant is None:return {'schema':1,'prepared':False,'published':False,'automatic_publish':False}
    master=await db.get(SeoContentAsset,variant.content_asset_id)
    preview=await media.preview(db,actor,1,1,variant.id)
    from app.api.seo import _content_confirmation_hash, _latest_content_confirmation
    master_hash=_content_confirmation_hash(master)
    approval=await _latest_content_confirmation(db,master)
    return {'schema':1,'prepared':True,'content_id':master.id,'variant_id':variant.id,
        'binding_id':str(binding['id']),'title':master.title,'body':preview['body_text'],
        'master_status':master.status,'master_version':master.version_count,
        'master_hash':master_hash,'master_confirmed':bool(approval and approval.decision=='approve'
            and approval.content_version==master.version_count and approval.content_hash==master_hash
            and approval.site_id==1 and approval.actor_user_id),
        'source_id':13,'source_version':1,'cover_requires_independent_review':True,
        'preview':preview,'published':False,'automatic_publish':False}

@router.get('')
async def read(device_id:UUID,external_account_id:str=Query(pattern=r'^gh_[a-f0-9]{12}$'),
               db=Depends(get_session),ctx=Depends(require_auth)):
    fresh,binding,connection=await binding_context(db,ctx,device_id,external_account_id)
    return await describe(db,fresh.user_id,binding,await existing(db,connection))

@router.post('/prepare')
async def prepare(req:PrepareDraft,db=Depends(get_session),ctx=Depends(require_auth)):
    fresh,binding,connection_id=await binding_context(db,ctx,req.device_id,req.external_account_id)
    await core.lock(db,'nord-first-draft:'+str(connection_id))
    prior=await existing(db,connection_id)
    if prior is not None:return await describe(db,fresh.user_id,binding,prior)
    source=await db.get(SeoContentAsset,13,with_for_update={'read':True})
    compact=lambda text:re.sub(r'\s+','',BeautifulSoup(text or '', 'html.parser').get_text())
    if (not source or source.tenant_id!=1 or source.site_id!=1 or source.version_count!=1
        or source.title!=PACKET['title'] or source.status not in ('ready','published')
        or compact(source.humanized_content or source.draft)!=compact(PACKET['body'])):
        raise HTTPException(409,'原始选型资料已变化，需要重新整理待审稿')
    keyword=await db.get(SeoKeywordAsset,48)
    if not keyword or keyword.tenant_id!=1 or keyword.site_id!=1 or keyword.keyword not in PACKET['body']:
        raise HTTPException(409,'当前诺德目标关键词不匹配')
    if hashlib.sha256(PACKET['body'].encode()).hexdigest()!=PACKET['body_sha256']:
        raise HTTPException(503,'待审稿冻结信息不一致')
    connection=await db.get(SeoDistributionConnection,connection_id)
    if len(PACKET['title'])>int(platform_content_rules(connection.platform_code)['title_max']):
        raise HTTPException(409,'标题不符合当前渠道要求')
    prepared=prepare_content(PACKET['title'],PACKET['body'],connection.platform_code)
    master=SeoContentAsset(tenant_id=1,site_id=1,keyword_id=48,keyword_ids=[48],content_type='article',
        title=PACKET['title'],draft=prepared['content_html'],status='drafting',version_count=1,
        target_platforms=['wechat_browser'],created_by=fresh.user_id)
    db.add(master);await db.flush()
    variant=SeoDistributionVariant(tenant_id=1,content_asset_id=master.id,connection_id=connection_id,
        platform_code='wechat_browser',source_version=1,revision_number=1,status='draft',
        title=prepared['title'],excerpt=prepared['excerpt'],content=prepared['content_html'],
        content_chars=len(PACKET['body']),ai_generated=False,generation_instruction=MARKER,
        keyword_checks=[{'keyword_id':48,'keyword':keyword.keyword,'in_title':keyword.keyword in PACKET['title'],'in_content':True}],
        warnings=[],created_by=fresh.user_id)
    db.add(variant);await db.flush()
    raw=COVER.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=PACKET['cover_sha256']:raise HTTPException(503,'封面冻结信息不一致')
    snapshot=await media.preview(db,fresh.user_id,1,1,variant.id)
    await media.replace_assets(db,fresh.user_id,1,1,variant.id,snapshot['edit_token'],[raw])
    await core.audit(db,fresh.user_id,'nord_first_draft_prepared',
        {'module':'seo','tenant_id':1,'scope_id':1,'binding_id':str(binding['id']),'variant_id':variant.id},'DRAFT_ONLY')
    await db.commit()
    # Fresh SQL preview reflects the cover update's new revision, never an ORM cached seal.
    return await describe(db,fresh.user_id,binding,variant)

@router.post('/master-review')
async def review_master(req:ReviewMaster,db=Depends(get_session),ctx=Depends(require_auth)):
    fresh,binding,connection=await binding_context(db,ctx,req.device_id,req.external_account_id)
    variant=await existing(db,connection)
    if variant is None or variant.content_asset_id!=req.content_id:raise HTTPException(409,'当前首条稿件已变化')
    from app.api.seo import (_content_confirmation_hash, submit_content_review,
        decide_content_review, create_content_confirmation, ContentReviewSubmit,
        ContentReviewDecision, ContentConfirmationRequest)
    master=await db.get(SeoContentAsset,req.content_id,with_for_update=True)
    if master.version_count!=req.expected_version or _content_confirmation_hash(master)!=req.expected_hash:
        raise HTTPException(409,'正文版本已变化，请重新读取完整稿件后确认')
    # All approvals below are initiated by this explicit named-human confirmation.
    if master.status=='drafting':
        await submit_content_review(master.id,1,ContentReviewSubmit(version_count=req.expected_version),session=db,ctx=fresh)
    if master.status=='review':
        await decide_content_review(master.id,1,ContentReviewDecision(decision='approve',version_count=req.expected_version),session=db,ctx=fresh)
    if master.status!='ready':raise HTTPException(409,'当前母稿不能确认，请核对原模块状态')
    await create_content_confirmation(master.id,1,ContentConfirmationRequest(version_count=req.expected_version,
        payload_hash=req.expected_hash,decision='approve',actor_mode='advisor_proxy'),session=db,ctx=fresh)
    return await describe(db,fresh.user_id,binding,variant)
