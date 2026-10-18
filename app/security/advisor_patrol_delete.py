"""Delete permitted history without losing sample provenance or retry references."""
from datetime import datetime, timezone

from sqlalchemy import select


async def detach_run_evidence(session, ctx, run):
    if getattr(ctx, 'advisor_scope', None) is None:
        return
    from app.models import GeoActionTicket, GeoAnswerSnapshot, GeoVisibilityPatrolRun

    stamp = datetime.now(timezone.utc).isoformat()
    # The deleted run is a durable attempt counter too. Retain only its original
    # actor/time, hidden from project history, so deletion cannot reset quotas.
    session.add(GeoVisibilityPatrolRun(tenant_id=ctx.tenant_id, status='completed',
        trigger='quota_history', auto_persist=False, prefer_real=True, prompt_limit=1,
        created_by=run.created_by, created_at=run.created_at,
        summary={'reservation_only': True, 'deleted_run_id': run.id}))
    note = f'[来源巡检记录 #{run.id} 已由顾问 {ctx.user_id} 于 {stamp} 删除；样本保留]'
    # These queries use the request's project scope; no other project is updated.
    snapshots = list(await session.scalars(select(GeoAnswerSnapshot).where(
        GeoAnswerSnapshot.tenant_id == ctx.tenant_id, GeoAnswerSnapshot.patrol_run_id == run.id)))
    for snapshot in snapshots:
        snapshot.patrol_run_id = None
        snapshot.note = '\n'.join(part for part in (snapshot.note, note) if part)
        # Keep raw answer, sample_mode and simulated unchanged. Daily metrics
        # aggregate those retained values, never patrol_run_id, so stay valid.
    tickets = list(await session.scalars(select(GeoActionTicket).where(
        GeoActionTicket.tenant_id == ctx.tenant_id)))
    for ticket in tickets:
        progress = dict(ticket.progress or {})
        reservations = dict(progress.get('retest_runs') or {})
        removed = [period for period, ident in reservations.items() if ident == run.id]
        if not removed:
            continue
        tombstones = dict(progress.get('deleted_retest_runs') or {})
        tombstones[str(run.id)] = {'run_id': run.id, 'window_starts': removed,
            'deleted_by': ctx.user_id, 'deleted_at': stamp, 'status': run.status}
        progress['deleted_retest_runs'] = tombstones
        progress['retest_runs'] = {period: ident for period, ident in reservations.items() if period not in removed}
        ticket.progress = progress
        # A future retry creates a new durable run and consumes the same daily
        # manual-detection quota; it cannot return a deleted run as existing.
