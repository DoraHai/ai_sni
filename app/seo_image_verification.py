"""Verify approved suggestions against a new observation, never a human checkbox."""
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update
from app.database import async_session_factory
from app.models.seo import SeoImageAltReview, SeoPageSnapshot, SeoSitePage
from app.models.seo_cockpit import SeoImageVerification
from app.models.module_workspace import SeoSite
from app.seo_page_audit import collect_page_snapshot, save_page_snapshot

logger=logging.getLogger(__name__)

async def enqueue_image_verification(session, review):
    await session.flush()
    await session.execute(update(SeoImageVerification).where(
        SeoImageVerification.tenant_id==review.tenant_id,SeoImageVerification.site_id==review.site_id,
        SeoImageVerification.page_id==review.page_id,
        SeoImageVerification.review_id.in_(select(SeoImageAltReview.id).where(SeoImageAltReview.page_id==review.page_id,
            SeoImageAltReview.source_url==review.source_url)) if review.source_url else SeoImageVerification.review_id==review.id,
        SeoImageVerification.status!='superseded').values(status='superseded'))
    if review.review_status=='approved':
        session.add(SeoImageVerification(tenant_id=review.tenant_id,site_id=review.site_id,
            page_id=review.page_id,review_id=review.id,status='pending',approved_at=review.updated_at,
            available_at=datetime.now(timezone.utc)))

def evaluate_image_repair(review, original, values):
    evidence=values.get('image_alt_evidence') or {}
    if values.get('error_type') or not isinstance(evidence.get('observations'),list):
        return 'unavailable', {'reason':'抓取失败或缺少完整图片观测，不能判定修复'}
    if evidence.get('observations_truncated'):
        return 'unavailable', {'reason':'图片观测被截断，不能唯一核实'}
    old_evidence=original.image_alt_evidence or {}
    if not isinstance(old_evidence.get('observations'),list) or old_evidence.get('observations_truncated'):
        return 'unavailable', {'reason':'原快照缺少完整图片观测，请重新检测并审核后核实'}
    baseline=old_evidence['observations']
    sources=[x for x in baseline if x.get('source_url')==review.source_url]
    if not review.source_url or len(sources)!=1 or sources[0].get('source_url_truncated'):
        return 'unverified', {'reason':'原图地址缺失或重复，不能唯一匹配'}
    matches=[x for x in evidence['observations'] if x.get('source_url')==review.source_url]
    if len(matches)!=1 or matches[0].get('source_url_truncated'):
        return 'unverified', {'reason':'原图消失、替换或重复，不能视为修复'}
    actual=matches[0]
    fixed=(review.decision=='informative' and actual.get('alt_state')=='present'
           and str(actual.get('alt') or '').strip()==str(review.alt_suggestion or '').strip())
    if review.decision=='decorative':
        fixed=review.observed_alt_state!='empty' and actual.get('alt_state')=='empty' and not actual.get('in_link')
    return ('verified' if fixed else 'unverified'), {'reason':'重新抓取确认已应用审核方案' if fixed else '重新抓取尚未确认审核方案生效',
        'source_url':review.source_url,'before_alt_state':review.observed_alt_state,
        'after_alt_state':actual.get('alt_state'),'actual_alt':actual.get('alt'),
        'metric_key':'seo.images.verified_repair_count','change_abs':1 if fixed else 0}

async def verify_pending_images():
    from app.module_scope import list_active_module_tenants
    async with async_session_factory() as session:
        tenants=[t.id for t in await list_active_module_tenants(session,'seo')]
    for _ in range(10):
        job_id=None
        try:
            async with async_session_factory() as session:
                now=datetime.now(timezone.utc)
                job=await session.scalar(select(SeoImageVerification).join(SeoSite,SeoSite.id==SeoImageVerification.site_id).where(
                    SeoImageVerification.tenant_id.in_(tenants),SeoSite.tenant_id==SeoImageVerification.tenant_id,
                    SeoSite.status=='active',SeoImageVerification.status.in_(['pending','checking']),
                    SeoImageVerification.available_at<=now).order_by(SeoImageVerification.id).with_for_update(skip_locked=True,of=SeoImageVerification).limit(1))
                if job is None:break
                job_id=job.id
                job.status='checking';job.available_at=now+timedelta(minutes=5)
                review=await session.get(SeoImageAltReview,job.review_id)
                page=await session.get(SeoSitePage,job.page_id)
                if not page or not review or page.tenant_id!=job.tenant_id or page.site_id!=job.site_id or review.review_status!='approved' or review.updated_at!=job.approved_at:
                    job.status='superseded';await session.commit();continue
                url=page.url;page_id=page.id;lease=job.available_at;started=datetime.utcnow()
                await session.commit()
            values=await collect_page_snapshot(url)
            async with async_session_factory() as session:
                # Same lock order as review writes: page, then verification.
                page=await session.get(SeoSitePage,page_id,with_for_update=True)
                job=await session.get(SeoImageVerification,job_id,with_for_update=True)
                if job is None:continue
                review=await session.get(SeoImageAltReview,job.review_id)
                if job.status!='checking' or job.available_at!=lease or not page or page.tenant_id!=job.tenant_id or page.site_id!=job.site_id or page.url!=url or not review or review.updated_at!=job.approved_at or review.review_status!='approved':
                    if job.status=='checking' and job.available_at==lease:job.status='superseded'
                    await session.commit();continue
                original=await session.get(SeoPageSnapshot,review.snapshot_id)
                snapshot=await save_page_snapshot(session,page,values,review.actor_id,started)
                await session.flush()
                job.status,job.evidence=evaluate_image_repair(review,original,values)
                job.evidence={**job.evidence,'review_id':review.id,'before_snapshot_id':original.id,'after_snapshot_id':snapshot.id}
                job.result_snapshot_id=snapshot.id;job.checked_at=datetime.now(timezone.utc)
                await session.commit()
        except Exception:
            # Claimed jobs become eligible after lease expiry, including restart.
            logger.exception('SEO image verification failed job_id=%s',job_id)
