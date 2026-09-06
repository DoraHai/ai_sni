"""Read-only eligibility of historical followups; never invent completion."""
from sqlalchemy import String, and_, cast, exists, or_, select
from sqlalchemy.orm import aliased
from app.models import GeoActionTicket, GeoContentTask, GeoChannelVariant, GeoPublication


def active_review_source(row=GeoActionTicket):
    return exists(select(GeoContentTask.id).where(
        GeoContentTask.tenant_id == row.tenant_id,
        cast(GeoContentTask.id, String) == row.progress_first['params']['content_task_id'].astext,
        GeoContentTask.status.notin_(['archived', 'cancelled'])))


def active_followup_condition(row=GeoActionTicket):
    source = aliased(GeoActionTicket)
    content = exists(select(GeoContentTask.id).where(
        GeoContentTask.id == row.content_task_id, GeoContentTask.tenant_id == row.tenant_id,
        GeoContentTask.status.notin_(['archived', 'cancelled'])))
    publication = exists(select(GeoPublication.id).join(
        GeoChannelVariant, GeoChannelVariant.id == GeoPublication.variant_id).where(
        GeoChannelVariant.task_id == row.content_task_id,
        row.advice_code == 'monitor:v1:' + cast(GeoPublication.id, String),
        GeoPublication.status == 'published', GeoPublication.published_url.is_not(None)))
    review = exists(select(source.id).where(
        source.tenant_id == row.tenant_id, source.advice_code.like('cockpit:v1:%'),
        source.status.in_(['todo', 'doing']),
        source.progress_first['params']['content_task_id'].astext == cast(row.content_task_id, String),
        row.advice_code == 'review:v1:' + cast(source.id, String)))
    return and_(content, or_(publication, review))
