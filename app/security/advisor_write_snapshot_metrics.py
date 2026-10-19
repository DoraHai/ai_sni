"""Update only the deleted snapshot's project slices in its own transaction."""
from sqlalchemy import or_, select


async def rebuild_before_delete(session, ctx, snapshot):
    from app.geo.content.daily_metrics import (
        MetricBucket, _metric_day_from_captured, aggregate_buckets, load_prompt_unit_maps,
        parse_scope_key, scope_business, scope_prompt, scope_unit, upsert_metric_row,
    )
    from app.geo.content.time_windows import shanghai_day_bounds_utc_naive
    from app.models import GeoAnswerSnapshot, GeoDailyMetric, GeoOptimizationUnit, GeoPrompt
    from app.security.advisor_scope import deny
    from app.security.advisor_write_reads import assigned_scope

    prompt = await session.get(GeoPrompt, snapshot.prompt_id)
    unit = await session.get(GeoOptimizationUnit, prompt.unit_id) if prompt and prompt.unit_id else None
    _, owned = await assigned_scope(session, ctx)
    if unit is None or unit.business_id not in owned:
        deny(403, "ADVISOR_ASSIGNMENT_REQUIRED", "需要快照所属项目的有效顾问分配")
    ctx.ensure_tenant(prompt.tenant_id)
    ctx.ensure_tenant(unit.tenant_id)
    day = _metric_day_from_captured(snapshot.captured_at)
    start, end = shanghai_day_bounds_utc_naive(day)
    prompts = select(GeoPrompt.id).where(GeoPrompt.tenant_id == ctx.tenant_id,
        GeoPrompt.unit_id.in_(select(GeoOptimizationUnit.id).where(
            GeoOptimizationUnit.tenant_id == ctx.tenant_id,
            GeoOptimizationUnit.business_id == unit.business_id)))
    # The target still exists for the commit hook's final ownership check.
    # Calculate its removal without flushing DELETE ahead of that check.
    snaps = list(await session.scalars(select(GeoAnswerSnapshot).where(
        GeoAnswerSnapshot.tenant_id == ctx.tenant_id, GeoAnswerSnapshot.prompt_id.in_(prompts),
        GeoAnswerSnapshot.id != snapshot.id,
        GeoAnswerSnapshot.captured_at >= start, GeoAnswerSnapshot.captured_at < end)))
    probe, units, businesses = await load_prompt_unit_maps(session, ctx.tenant_id, {s.prompt_id for s in snaps})
    buckets = aggregate_buckets(snaps, probe_map=probe, unit_of_prompt=units, business_of_unit=businesses)
    bases = {scope_business(unit.business_id), scope_unit(unit.id), scope_prompt(prompt.id)}
    relevant = {key: value for key, value in buckets.items() if key.split("@", 1)[0] in bases}
    existing = list(await session.scalars(select(GeoDailyMetric).where(
        GeoDailyMetric.tenant_id == ctx.tenant_id, GeoDailyMetric.metric_date == day,
        or_(GeoDailyMetric.scope_key.in_(bases),
            *(GeoDailyMetric.scope_key.like(base + "@%") for base in sorted(bases))))))
    for key in bases | {row.scope_key for row in existing}:
        relevant.setdefault(key, MetricBucket(business_id=unit.business_id,
            unit_id=None if parse_scope_key(key)["level"] == "business" else unit.id))
    for key, bucket in relevant.items():
        await upsert_metric_row(session, tenant_id=ctx.tenant_id, day=day, scope_key=key, bucket=bucket)
