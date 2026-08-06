"""GEO visibility auto patrol: multi-prompt × multi-engine probe + optional persist."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.geo.content.probe import (
    SAMPLE_MODE_REAL,
    resolve_batch_engines,
    resolve_engine_llm,
    run_probe_draft,
)
from app.geo.content.prompt_taxonomy import brand_names_from_tenant
from app.geo.content.snapshots import apply_brand_mention_tags
from app.geo.content.snapshot_suggest import (
    extract_cited_urls_from_text,
    normalize_brand_position,
    normalize_competitors,
    normalize_sentiment,
)
from app.models import (
    GeoAnswerSnapshot,
    GeoPrompt,
    GeoVisibilityPatrolRun,
    GeoVisibilityPatrolSettings,
    Tenant,
)

logger = logging.getLogger(__name__)

# allowed interval presets (hours)
PATROL_INTERVAL_HOURS_CHOICES = (1, 2, 3, 4, 6, 8, 12, 24)


async def count_patrol_runs_today(session: AsyncSession, tenant_id: int) -> int:
    """Count patrol runs created today in Asia/Shanghai for quota."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from sqlalchemy import func

    tz = ZoneInfo("Asia/Shanghai")
    now = datetime.now(tz)
    start_local = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    # DB timestamps are naive UTC-ish (utcnow); convert window to naive UTC
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
    n = await session.scalar(
        select(func.count())
        .select_from(GeoVisibilityPatrolRun)
        .where(
            GeoVisibilityPatrolRun.tenant_id == tenant_id,
            GeoVisibilityPatrolRun.created_at >= start_utc,
            GeoVisibilityPatrolRun.created_at < end_utc,
        )
    )
    return int(n or 0)


def patrol_quota_message(*, used: int, limit: int) -> str:
    return (
        f"今日巡检次数已达上限（{used}/{limit}）。"
        f"请明日再试，或调高环境变量 GEO_PATROL_MAX_RUNS_PER_DAY。"
    )


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def clamp_hour(value: int | None, default: int) -> int:
    try:
        h = int(value if value is not None else default)
    except (TypeError, ValueError):
        h = default
    return max(0, min(23, h))


def clamp_interval_hours(value: int | None, default: int = 24) -> int:
    try:
        n = int(value if value is not None else default)
    except (TypeError, ValueError):
        n = default
    if n in PATROL_INTERVAL_HOURS_CHOICES:
        return n
    # nearest allowed
    return min(PATROL_INTERVAL_HOURS_CHOICES, key=lambda x: abs(x - max(1, min(24, n))))


def hour_in_window(hour: int, start: int, end: int) -> bool:
    """Whether local hour is inside [start, end] inclusive. Supports overnight (start > end)."""
    h = int(hour) % 24
    s = clamp_hour(start, 0)
    e = clamp_hour(end, 23)
    if s <= e:
        return s <= h <= e
    # overnight e.g. 22–6
    return h >= s or h <= e


def _as_utc_naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def should_run_scheduled_patrol(
    *,
    now: datetime,
    window_start_hour: int,
    window_end_hour: int,
    interval_hours: int,
    last_scheduled_at: datetime | None,
) -> bool:
    """Decide if a scheduled patrol should fire at ``now`` (timezone-aware preferred)."""
    local_hour = now.hour
    if not hour_in_window(local_hour, window_start_hour, window_end_hour):
        return False
    interval = clamp_interval_hours(interval_hours)
    last = _as_utc_naive(last_scheduled_at)
    if last is None:
        return True
    # compare using naive UTC-ish wall clock: convert now to naive in same fashion
    if now.tzinfo is not None:
        now_cmp = now.astimezone(timezone.utc).replace(tzinfo=None)
    else:
        now_cmp = now
    elapsed_h = (now_cmp - last).total_seconds() / 3600.0
    return elapsed_h >= float(interval)


def patrol_settings_payload(row: GeoVisibilityPatrolSettings | None, tenant_id: int) -> dict[str, Any]:
    if row is None:
        return {
            "tenant_id": tenant_id,
            "enabled": False,
            "daily_hour": 6,
            "window_start_hour": 6,
            "window_end_hour": 22,
            "interval_hours": 24,
            "last_scheduled_at": None,
            "auto_persist": True,
            "prefer_real": True,
            "prompt_limit": 20,
            "engine_keys": None,
            "interval_choices": list(PATROL_INTERVAL_HOURS_CHOICES),
        }
    return {
        "tenant_id": row.tenant_id,
        "enabled": bool(row.enabled),
        "daily_hour": int(getattr(row, "daily_hour", None) or row.window_start_hour or 6),
        "window_start_hour": clamp_hour(getattr(row, "window_start_hour", None), 6),
        "window_end_hour": clamp_hour(getattr(row, "window_end_hour", None), 22),
        "interval_hours": clamp_interval_hours(getattr(row, "interval_hours", None), 24),
        "last_scheduled_at": _iso(getattr(row, "last_scheduled_at", None)),
        "auto_persist": bool(row.auto_persist),
        "prefer_real": bool(row.prefer_real),
        "prompt_limit": int(row.prompt_limit or 20),
        "engine_keys": row.engine_keys,
        "updated_at": _iso(row.updated_at),
        "interval_choices": list(PATROL_INTERVAL_HOURS_CHOICES),
    }


def patrol_run_payload(row: GeoVisibilityPatrolRun) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "status": row.status,
        "trigger": row.trigger,
        "auto_persist": bool(row.auto_persist),
        "prefer_real": bool(row.prefer_real),
        "prompt_limit": int(row.prompt_limit or 20),
        "engine_keys": row.engine_keys,
        "summary": row.summary or {},
        "items": row.items or [],
        "error": row.error,
        "started_at": _iso(row.started_at),
        "finished_at": _iso(row.finished_at),
        "created_by": row.created_by,
        "created_at": _iso(row.created_at),
    }


async def execute_patrol_run(session: AsyncSession, run_id: int) -> GeoVisibilityPatrolRun:
    """Run patrol to completion inside one session (commit at end of phases)."""
    from app.ai.deepseek import DeepSeekError, chat_json
    from app.geo.content.ai_settings import resolve_llm_credentials
    from app.geo.content.engines import default_engine_rows
    from app.models import GeoTrackingEngine

    row = await session.get(GeoVisibilityPatrolRun, run_id)
    if row is None:
        raise ValueError(f"patrol run {run_id} not found")

    row.status = "running"
    row.started_at = datetime.utcnow()
    row.error = None
    await session.commit()

    items: list[dict[str, Any]] = []
    summary = {
        "prompts": 0,
        "engines": 0,
        "cells_ok": 0,
        "cells_fail": 0,
        "snapshots_created": 0,
        "real_samples": 0,
        "persona_samples": 0,
    }

    try:
        tenant = await session.get(Tenant, row.tenant_id)
        if tenant is None:
            raise ValueError("租户不存在")
        tenant_llm = await resolve_llm_credentials(session, row.tenant_id)
        engine_rows = list(
            await session.scalars(
                select(GeoTrackingEngine)
                .where(GeoTrackingEngine.tenant_id == row.tenant_id)
                .order_by(GeoTrackingEngine.sort_order, GeoTrackingEngine.id)
            )
        )
        if not engine_rows:
            for item in default_engine_rows(row.tenant_id):
                eng = GeoTrackingEngine(**item)
                session.add(eng)
                engine_rows.append(eng)
            await session.flush()
        row_by_key = {r.engine_key: r for r in engine_rows}
        enabled_keys = [r.engine_key for r in engine_rows if r.enabled]
        if not enabled_keys:
            enabled_keys = [r.engine_key for r in engine_rows]
        engines = resolve_batch_engines(row.engine_keys, enabled_keys)
        if not engines:
            raise ValueError("没有可探测的引擎")
        summary["engines"] = len(engines)

        # cell budget (productization must-do: avoid runaway LLM cost)
        try:
            from app.config import get_settings

            max_cells = int(getattr(get_settings(), "geo_patrol_max_cells_per_run", 200) or 200)
        except Exception:  # noqa: BLE001
            max_cells = 200
        max_cells = max(1, min(max_cells, 500))
        summary["max_cells"] = max_cells

        brand = getattr(tenant, "name", None) or f"租户{row.tenant_id}"
        brand_names = brand_names_from_tenant(
            name=getattr(tenant, "name", None),
            brand_terms=getattr(tenant, "brand_terms", None),
        ) or [brand]

        prompts = list(
            await session.scalars(
                select(GeoPrompt)
                .where(
                    GeoPrompt.tenant_id == row.tenant_id,
                    GeoPrompt.status == "active",
                )
                .order_by(GeoPrompt.priority.desc(), GeoPrompt.id.desc())
                .limit(max(1, min(int(row.prompt_limit or 20), 50)))
            )
        )
        if not prompts:
            # fallback any prompts
            prompts = list(
                await session.scalars(
                    select(GeoPrompt)
                    .where(GeoPrompt.tenant_id == row.tenant_id)
                    .order_by(GeoPrompt.id.desc())
                    .limit(max(1, min(int(row.prompt_limit or 20), 50)))
                )
            )
        summary["prompts"] = len(prompts)
        if not prompts:
            raise ValueError("没有可巡检的机会词，请先在「机会词」中创建")

        cells_planned = 0
        for prompt in prompts:
            for engine in engines:
                if cells_planned >= max_cells:
                    summary["truncated"] = True
                    summary["truncated_reason"] = (
                        f"达到单次巡检格数上限 {max_cells}（可调 GEO_PATROL_MAX_CELLS_PER_RUN）"
                    )
                    break
                cells_planned += 1
                cell: dict[str, Any] = {
                    "prompt_id": prompt.id,
                    "prompt_question": prompt.question,
                    "engine": engine,
                    "ok": False,
                    "error": None,
                    "snapshot_id": None,
                    "sample_mode": None,
                    "simulated": None,
                }
                try:
                    engine_row = row_by_key.get(engine)
                    # prefer_real: if engine is mock but tenant has llm, still try resolve
                    llm, sample_mode, fallback_reason = resolve_engine_llm(
                        engine=engine,
                        tenant_llm=tenant_llm,
                        engine_row=engine_row,
                    )
                    if row.prefer_real and sample_mode != SAMPLE_MODE_REAL and engine_row is not None:
                        # force attempt real if engine has encrypted key even if mode wrong
                        if getattr(engine_row, "api_key_encrypted", None):
                            engine_row.sample_mode = SAMPLE_MODE_REAL  # type: ignore[attr-defined]
                            llm, sample_mode, fallback_reason = resolve_engine_llm(
                                engine=engine,
                                tenant_llm=tenant_llm,
                                engine_row=engine_row,
                            )
                    if not llm or not llm.get("api_key"):
                        raise ValueError("无可用 LLM 凭证（请配置 AI 能力或引擎 openai_compat）")

                    draft = await run_probe_draft(
                        question=prompt.question,
                        brand=brand,
                        brand_names=brand_names,
                        engine=engine,
                        llm=llm,
                        chat_json=chat_json,
                        sample_mode=sample_mode,
                        fallback_reason=fallback_reason,
                    )
                    cell.update(
                        {
                            "ok": True,
                            "raw_text": draft.get("raw_text"),
                            "sample_mode": draft.get("sample_mode"),
                            "simulated": draft.get("simulated"),
                            "suggested_mentions_brand": draft.get("suggested_mentions_brand"),
                            "competitors": draft.get("competitors") or draft.get("suggested_competitors"),
                            "brand_position": draft.get("brand_position")
                            or draft.get("suggested_brand_position"),
                            "sentiment": draft.get("sentiment") or draft.get("suggested_sentiment"),
                            "fallback_reason": draft.get("fallback_reason"),
                            "model": draft.get("model"),
                            "provider": draft.get("provider"),
                        }
                    )
                    if draft.get("simulated"):
                        summary["persona_samples"] += 1
                    else:
                        summary["real_samples"] += 1
                    summary["cells_ok"] += 1

                    if row.auto_persist:
                        raw_text = str(draft.get("raw_text") or "").strip()
                        mentions = bool(
                            draft.get("suggested_mentions_brand")
                            if draft.get("suggested_mentions_brand") is not None
                            else draft.get("mentions_brand")
                        )
                        comps = normalize_competitors(
                            draft.get("competitors") or draft.get("suggested_competitors")
                        )
                        pos = normalize_brand_position(
                            draft.get("brand_position")
                            or draft.get("suggested_brand_position")
                        )
                        sent = normalize_sentiment(
                            draft.get("sentiment") or draft.get("suggested_sentiment")
                        )
                        cited = extract_cited_urls_from_text(raw_text)
                        note = (
                            f"auto-patrol #{run_id} · {draft.get('sample_mode')} · "
                            f"{'模拟' if draft.get('simulated') else '真采样'}"
                        )
                        snap = GeoAnswerSnapshot(
                            tenant_id=row.tenant_id,
                            prompt_id=prompt.id,
                            engine=engine,
                            raw_text=raw_text,
                            captured_at=datetime.utcnow(),
                            mentions_brand=mentions,
                            cited_urls=cited,
                            competitors=comps,
                            brand_position=pos,
                            sentiment=sent,
                            note=note,
                            created_by=row.created_by,
                        )
                        session.add(snap)
                        # brand mention tags on prompt
                        tags = list(prompt.tags or [])
                        prompt.tags = apply_brand_mention_tags(tags, mentions_brand=mentions)
                        await session.flush()
                        cell["snapshot_id"] = snap.id
                        summary["snapshots_created"] += 1
                except (DeepSeekError, ValueError) as exc:
                    cell["ok"] = False
                    cell["error"] = str(exc)
                    summary["cells_fail"] += 1
                    logger.warning(
                        "patrol cell fail tenant=%s prompt=%s engine=%s: %s",
                        row.tenant_id,
                        prompt.id,
                        engine,
                        exc,
                    )
                except Exception as exc:  # noqa: BLE001
                    cell["ok"] = False
                    cell["error"] = f"unexpected: {exc}"
                    summary["cells_fail"] += 1
                    logger.exception("patrol cell unexpected")
                items.append(cell)
                # periodic commit so long runs don't hold huge txn
                if len(items) % 5 == 0:
                    row.items = list(items)
                    row.summary = dict(summary)
                    await session.commit()
            if summary.get("truncated"):
                break

        row.items = items
        row.summary = summary
        row.status = "completed"
        row.finished_at = datetime.utcnow()
        await session.commit()
        await session.refresh(row)
        return row
    except Exception as exc:  # noqa: BLE001
        logger.exception("patrol run %s failed", run_id)
        row = await session.get(GeoVisibilityPatrolRun, run_id)
        if row:
            row.status = "failed"
            row.error = str(exc)[:2000]
            row.items = items
            row.summary = summary
            row.finished_at = datetime.utcnow()
            await session.commit()
            await session.refresh(row)
            return row
        raise
