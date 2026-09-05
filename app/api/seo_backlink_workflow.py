"""Backlink outcomes and customer-provided referral observations, SEO scoped."""
from datetime import date, datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, PositiveInt
from sqlalchemy import select
from app.database import get_session
from app.security.auth import require_scoped_auth
from app.models.seo import SeoBacklink, SeoContentAsset, SeoContentPublication
from app.api.seo_cockpit import scope
from app.seo_backlink_sources import candidate_url, index_status

router = APIRouter()

def usage(settings, now=None):
    now = now or datetime.now(timezone.utc)
    rows = []
    for key, limit in [('backlink_index', 1), ('backlink_opportunities', 4)]:
        claim = settings.get(key) or {}
        at = claim.get('attempted_at')
        active = False
        if at:
            try: active = now - datetime.fromisoformat(at).replace(tzinfo=timezone.utc) < timedelta(days=1)
            except ValueError: pass
        reserved = min(limit, max(1, int(claim.get('max_provider_calls', 1)))) if active else 0
        rows.append({'kind':key, 'limit_calls_24h':limit, 'reserved_calls':reserved,
                     'remaining_calls':0 if active else limit, 'attempted_at':at,
                     'next_available_at':(datetime.fromisoformat(at).replace(tzinfo=timezone.utc)+timedelta(days=1)).isoformat() if active else None})
    return {'provider':index_status(), 'quotas':rows, 'cost':None,
            'note':'额度按调用批次预留，失败和执行中也占用；这是调用预算，实际金额及余额以供应商账单为准。'}

@router.get('/backlinks/outcomes')
async def outcomes(tenant_id:PositiveInt, site_id:PositiveInt, ctx=Depends(require_scoped_auth), session=Depends(get_session)):
    site=await scope(session,ctx,tenant_id,site_id,'seo.links')
    links=list(await session.scalars(select(SeoBacklink).where(SeoBacklink.tenant_id==tenant_id,SeoBacklink.site_id==site_id)))
    publications=list(await session.scalars(select(SeoContentPublication).join(SeoContentAsset,SeoContentAsset.id==SeoContentPublication.content_asset_id).where(
        SeoContentPublication.tenant_id==tenant_id,SeoContentAsset.tenant_id==tenant_id,SeoContentAsset.site_id==site_id,
        SeoContentPublication.page_url.is_not(None)).order_by(SeoContentPublication.id.desc()).limit(200)))
    observations=(site.site_settings or {}).get('backlink_referrals') or {}
    items=[]
    for pub in publications:
        try: source=candidate_url(pub.page_url)
        except ValueError: continue
        found=[link for link in links if link.source_url==source and link.status=='active' and (link.verification or {}).get('state')=='found']
        observation=observations.get(source)
        items.append({'publication_id':pub.id,'source_url':source,'platform_name':pub.platform_name,'publication_status':pub.status,
            'verified_backlinks':len(found),'backlink_ids':[link.id for link in found],
            'visits':observation['visits'] if observation else None,'conversions':observation['conversions'] if observation else None,
            'observation':observation})
    return {'items':items,'usage':usage(site.site_settings or {}),
        'note':'公开发布、真实外链与引荐访问分别统计；访问和转化来自用户录入的分析平台报表，未经服务端核验，不代表因果归因。最多展示最近 200 条有链接的发布记录。'}

class Referral(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    tenant_id:PositiveInt
    site_id:PositiveInt
    source_url:str=Field(max_length=2000)
    visits:int=Field(ge=0,le=1000000000)
    conversions:int|None=Field(None,ge=0,le=1000000000)
    date_from:date
    date_to:date
    source:str=Field(min_length=1,max_length=200)

@router.post('/backlinks/referrals')
async def referral(req:Referral,ctx=Depends(require_scoped_auth),session=Depends(get_session)):
    await scope(session,ctx,req.tenant_id,req.site_id,'seo.links',True)
    if req.date_from>req.date_to or req.date_to>date.today():raise HTTPException(422,'统计日期范围无效')
    try:source=candidate_url(req.source_url)
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
    from app.models.module_workspace import SeoSite
    site=await session.get(SeoSite,req.site_id,with_for_update=True,populate_existing=True)
    if not site or site.tenant_id!=req.tenant_id:raise HTTPException(404,'网站不存在')
    from app.seo_backlinks import belongs_to_site
    if belongs_to_site(source,site.canonical_domain):raise HTTPException(422,'需要站外来源 URL')
    settings=dict(site.site_settings or {}); rows=dict(settings.get('backlink_referrals') or {})
    if source not in rows and len(rows)>=500:raise HTTPException(409,'引荐来源记录已达 500 条上限')
    rows[source]={**req.model_dump(mode='json',exclude={'tenant_id','site_id','source_url'}),
        'verification':'user_reported','actor':ctx.user_id,'recorded_at':datetime.now(timezone.utc).isoformat()}
    settings['backlink_referrals']=rows;site.site_settings=settings
    await session.commit()
    return rows[source]
