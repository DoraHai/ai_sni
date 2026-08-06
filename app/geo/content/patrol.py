"""GEO visibility auto patrol: multi-prompt × multi-engine probe + optional persist."""

from __future__ import annotations

import logging
from datetime import datetime
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
    Tenant,
)

logger = logging.getLogger(__name__)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


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

        for prompt in prompts:
            for engine in engines:
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
