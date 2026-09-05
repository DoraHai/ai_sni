"""Read-only metric computation; history is collected by a separate scheduler."""
from datetime import datetime,timedelta,timezone
from sqlalchemy import select,func
from app.models.seo import SeoKeywordAsset,SeoRankSnapshot,SeoContentAsset,SeoMetricSnapshot,SeoBacklink
from app.models.seo_cockpit import SeoImageVerification

DEFINITIONS={
 'seo.ranking.top10_keyword_count':('count','当前网站启用的 P0/P1 核心词，按百度桌面全国自有域名最新七天内观测去重，排名 1–10 的词数；无可用观测返回 null。'),
 'seo.content.published_7d_count':('count','当前网站内容资产 published_at 位于过去 7×24 小时且状态为 published 的去重篇数，多平台分发不重复计数。'),
 'seo.images.verified_repair_count':('count','当前网站未被替代的审核方案中，审批后重新抓取且唯一匹配原图并确认方案已应用的数量。'),
 'seo.images.pending_repair_count':('count','当前网站已审核、未被替代且尚未获重新抓取确认的图片方案数量，含待核实、未生效和抓取异常。'),
 'seo.images.repair_completion_rate':('percent','重新抓取确认数量除以当前网站未被替代的已审核图片方案数量×100；无已审核方案返回 null。'),
 'seo.backlinks.verified_count':('count','当前网站处于 active 且最近一次抓取证据状态为 found 的外链记录数量，按来源页面和目标页面去重；索引候选及暂停监控记录不计入。'),
}

def trend(current,previous):
    if current is None or previous is None:return None
    diff=current-previous
    return {'direction':'up' if diff>0 else 'down' if diff<0 else 'flat',
            'change_pct':round(diff/abs(previous)*100,6) if previous else None,
            'change_abs':round(diff,6)}

async def metric_values(session,tenant_id,site_id,now=None):
    now=now or datetime.utcnow()
    k,r=SeoKeywordAsset,SeoRankSnapshot
    recent=(select(r.keyword_id,r.rank,func.row_number().over(partition_by=r.keyword_id,order_by=(r.checked_at.desc(),r.id.desc())).label('rn'))
        .join(k,k.id==r.keyword_id).where(r.tenant_id==tenant_id,r.site_id==site_id,k.tenant_id==tenant_id,k.site_id==site_id,
            k.status=='active',k.priority.in_(['P0','P1']),r.subject_type=='own',r.engine=='baidu',r.device=='desktop',r.region=='全国',
            r.checked_at>=now-timedelta(days=7),r.checked_at<=now).subquery())
    ranks=list((await session.execute(select(recent.c.rank).where(recent.c.rn==1))).scalars())
    count=await session.scalar(select(func.count()).select_from(SeoContentAsset).where(SeoContentAsset.tenant_id==tenant_id,
        SeoContentAsset.site_id==site_id,SeoContentAsset.status=='published',SeoContentAsset.published_at>now-timedelta(days=7),SeoContentAsset.published_at<=now))
    states=list(await session.scalars(select(SeoImageVerification.status).where(SeoImageVerification.tenant_id==tenant_id,
        SeoImageVerification.site_id==site_id,SeoImageVerification.status!='superseded')))
    verified=states.count('verified')
    links=await session.scalar(select(func.count()).select_from(SeoBacklink).where(SeoBacklink.tenant_id==tenant_id,SeoBacklink.site_id==site_id,
        SeoBacklink.status=='active',SeoBacklink.verification['state'].astext=='found'))
    return dict(zip(DEFINITIONS,[sum(1 for rank in ranks if rank is not None and 1<=rank<=10) if ranks else None,int(count or 0),verified,len(states)-verified,round(100*verified/len(states),4) if states else None,int(links or 0)]))

async def metric_snapshot(session,tenant_id,site_id):
    now=datetime.utcnow()
    values=await metric_values(session,tenant_id,site_id,now)
    before=now-timedelta(days=7)
    history=list(await session.scalars(select(SeoMetricSnapshot).where(SeoMetricSnapshot.tenant_id==tenant_id,
        SeoMetricSnapshot.site_id==site_id,SeoMetricSnapshot.source=='cockpit_observation',
        SeoMetricSnapshot.observed_at<=before,SeoMetricSnapshot.observed_at>before-timedelta(hours=2)).order_by(SeoMetricSnapshot.observed_at.desc())))
    previous={}
    for row in history:previous.setdefault(row.metric_type,float(row.numeric_value) if row.numeric_value is not None else None)
    return [{'metric_key':key,'value':value,'unit':DEFINITIONS[key][0],'as_of':now.replace(tzinfo=timezone.utc).isoformat(),
        'trend_7d':trend(value,previous.get(key))} for key,value in values.items()]

async def collect_cockpit_metrics():
    from app.database import async_session_factory
    from app.module_scope import list_active_module_tenants
    from app.models.module_workspace import SeoSite
    from sqlalchemy.dialects.postgresql import insert
    import logging
    async with async_session_factory() as session:
        tenants=[t.id for t in await list_active_module_tenants(session,'seo')]
        sites=list((await session.execute(select(SeoSite.id,SeoSite.tenant_id).where(SeoSite.tenant_id.in_(tenants),SeoSite.status=='active'))).all())
    for site_id,tenant_id in sites:
        try:
            async with async_session_factory() as session:
                now=datetime.utcnow()
                values=await metric_values(session,tenant_id,site_id,now)
                for key,value in values.items():
                    await session.execute(insert(SeoMetricSnapshot).values(tenant_id=tenant_id,site_id=site_id,metric_type=key,dimension='total',
                        numeric_value=value,source='cockpit_observation',data_quality='verified',unit=DEFINITIONS[key][0],
                        status='available' if value is not None else 'pending',observed_at=now).on_conflict_do_nothing(constraint='uq_seo_metric_snapshot_observation'))
                await session.commit()
        except Exception:logging.getLogger(__name__).exception('SEO metric observation failed site=%s',site_id)
