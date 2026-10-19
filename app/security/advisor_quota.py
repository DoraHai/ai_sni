"""Manual attempt settlement using existing patrol JSON, without a new counter.

One durable row represents one attempt. Refunding excludes that row from daily
usage; a conditional transition makes retries/concurrent cleanup idempotent.
Supplier billing/budget and the retest weekly evidence reservation are separate.
"""
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import GeoVisibilityPatrolRun

KEY = 'advisor_manual_reservation'
STATE = 'advisor_quota_state'


def transition(reservation, before, after):
    ident, tenant_id, user_id = reservation
    return update(GeoVisibilityPatrolRun).where(
        GeoVisibilityPatrolRun.id == ident,
        GeoVisibilityPatrolRun.tenant_id == tenant_id,
        GeoVisibilityPatrolRun.created_by == user_id,
        GeoVisibilityPatrolRun.summary['reservation_only'].as_boolean().is_(True),
        GeoVisibilityPatrolRun.summary[STATE].as_string() == before,
    ).values(summary={'reservation_only': True, STATE: after}).execution_options(
        advisor_scope_control=True, synchronize_session=False)


async def consume_manual_result(session):
    reservation = session.info.get(KEY)
    if reservation is not None:
        await session.execute(transition(reservation, 'reserved', 'consumed'))
        # Durable before another engine can fail. Normal commit authorization
        # still applies; rejected/uncommitted results cannot consume the attempt.
        await session.commit()


async def refund_unused_reservation(session):
    reservation = session.info.get(KEY)
    if reservation is None:
        return
    # Release the request's authorization locks and failed transaction first.
    # Cleanup must work after revocation; this new session can ONLY transition
    # this request's exact, still-unused reservation (no business content).
    await session.rollback()
    factory = async_sessionmaker(bind=session.bind, expire_on_commit=False)
    async with factory() as cleanup:
        await cleanup.execute(transition(reservation, 'reserved', 'refunded'))
        await cleanup.commit()


async def queue_search_reservation(session, job):
    reservation = session.info.get(KEY)
    if reservation is not None:
        job.request_meta = {**job.request_meta, KEY: list(reservation)}
        await session.execute(transition(reservation, 'reserved', 'queued'))
        # Job + reservation link are committed atomically by create_run.


def search_has_results(result):
    # Empty successful search results are valid evidence (e.g. not indexed).
    # Error/skipped-only items are not results. Budget/attempt metadata isn't.
    return any(not item.get('error') and item.get('source') != 'skipped'
               and ('results' in item or item.get('alive') is not None)
               for item in (result or {}).get('items', []))


async def settle_search_reservation(session, job):
    reservation = (job.request_meta or {}).get(KEY)
    if (getattr(job, 'kind', None) != 'search_visibility'
            or not isinstance(reservation, list) or len(reservation) != 3
            or any(type(value) is not int for value in reservation)
            or reservation[1:] != [job.tenant_id, job.created_by]
            or job.status not in {'failed', 'succeeded', 'cancelled'}):
        return
    state = 'consumed' if job.status == 'succeeded' or search_has_results(job.result_meta) else 'refunded'
    await session.execute(transition(reservation, 'queued', state))


def settle_patrol_quota(row):
    summary = dict(row.summary or {})
    if not summary.get('advisor_visibility_auth') or row.status not in {'failed', 'completed', 'cancelled'}:
        return
    has_result = bool(summary.get('snapshots_created') or any(
        item.get('ok') or item.get('snapshot_id') for item in row.items or []))
    summary[STATE] = 'consumed' if has_result else 'refunded'
    row.summary = summary
