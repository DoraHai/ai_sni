"""Explain customer visibility without changing any delivery or review gate."""
from datetime import datetime

from sqlalchemy import select

from app.geo.content.time_windows import to_utc_naive
from app.models import GeoArticleVersion, GeoOptimizationUnit, GeoProject


def check_current_master(master, result):
    if master is None:
        return 'no_master'
    result = result if isinstance(result, dict) else {}
    try:
        checked = datetime.fromisoformat(result.get('checked_at', '').replace('Z', '+00:00'))
    except (ValueError, TypeError, AttributeError):
        checked = None
    if (type(result.get('article_id')) is not int or result['article_id'] != master.id
            or not checked or not master.created_at
            or to_utc_naive(checked) < to_utc_naive(master.created_at)):
        return 'current_check_missing'
    return 'ready' if result.get('ready') is True else 'not_ready'


async def customer_readiness(session, task, prompt):
    master = (await session.execute(select(GeoArticleVersion.id, GeoArticleVersion.version_no,
        GeoArticleVersion.created_at).where(GeoArticleVersion.task_id == task.id,
        GeoArticleVersion.kind == 'master').order_by(GeoArticleVersion.version_no.desc(),
        GeoArticleVersion.id.desc()).limit(1))).first()
    check = check_current_master(master, task.rule_result)
    unit = await session.scalar(select(GeoOptimizationUnit).where(
        GeoOptimizationUnit.id == prompt.unit_id, GeoOptimizationUnit.tenant_id == task.tenant_id)) \
        if prompt and prompt.tenant_id == task.tenant_id and prompt.unit_id else None
    chain = 'unbound'
    if unit:
        from app.geo.project_scope import binding
        scoped_projects = list(await session.scalars(select(GeoProject).where(
            GeoProject.tenant_id == task.tenant_id).limit(1001)))
        if len(scoped_projects) > 1000:
            return {'master_version': master.version_no if master else None, 'current_check': check,
                'project_chain': 'unverified', 'review_status': 'unknown',
                'review_covers_current_master': False, 'deliverable': False, 'pending_deliverable': False}
        projects = [p for p in scoped_projects if unit.business_id in binding(p)['business_ids']]
        if len(projects) == 1:
            chain = 'matched' if task.business_id in {None, unit.business_id} else 'mismatch'
        elif len(projects) > 1:
            chain = 'ambiguous'
    review = task.review_status if task.review_status in {'none', 'pending', 'approved', 'rejected'} else 'unknown'
    covers = bool(review == 'approved' and master and master.created_at and task.reviewed_at
        and to_utc_naive(task.reviewed_at) >= to_utc_naive(master.created_at))
    return {'master_version': master.version_no if master else None, 'current_check': check,
        'project_chain': chain, 'review_status': review, 'review_covers_current_master': covers,
        'deliverable': check == 'ready' and chain == 'matched',
        'pending_deliverable': check == 'ready' and chain == 'matched' and review == 'pending'}
