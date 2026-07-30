"""诊断 → 内容任务桥接。"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.geo.content.pipeline import sync_pipeline_fields
from app.models import GeoAuditRun, GeoContentTask, GeoFact, GeoPrompt, GeoTaskFact


def editor_path(*, task_id: int, tenant_id: int) -> str:
    """Deep link into the static GEO workbench (local demo default ports)."""
    return (
        "http://127.0.0.1:5176/geo/editor.html"
        f"?task_id={task_id}&tenant_id={tenant_id}"
        "&api_origin=http://127.0.0.1:8011"
        "&api_key=geo-demo-local-key"
    )


def _pick_advice(run: GeoAuditRun, advice_code: str | None) -> dict[str, Any] | None:
    if not advice_code or not run.advice:
        return None
    return next((a for a in run.advice if a.get("code") == advice_code), None)


def _pick_finding(run: GeoAuditRun, code: str | None) -> dict[str, Any] | None:
    if not code or not run.findings:
        return None
    return next((f for f in run.findings if f.get("code") == code), None)


def build_diagnosis_fact_payloads(
    run: GeoAuditRun,
    *,
    advice_code: str | None = None,
) -> list[dict[str, Any]]:
    """从诊断结果抽出与目标问题对齐的事实卡草稿（不写库）。"""
    advice = _pick_advice(run, advice_code) or (
        (run.advice or [None])[0] if run.advice else None
    )
    code = (advice or {}).get("code") or advice_code
    finding = _pick_finding(run, code)

    page = (run.page_title or run.url or "目标页面").strip()
    source_name = f"GEO 诊断 · {page}"[:200]
    source_url = run.url
    payloads: list[dict[str, Any]] = []

    if finding:
        evidence = str(finding.get("evidence") or "").strip()
        title = f"诊断证据：{finding.get('title') or code or '检查项'}"
        statement = evidence or f"页面「{page}」在「{finding.get('title')}」检查未达标。"
        payloads.append(
            {
                "title": title[:200],
                "statement": statement[:2000],
                "fact_type": "other",
                "source_name": source_name,
                "source_url": source_url,
                "trust_level": "needs_review",
                "author_name": "诊断桥",
                "meta": {
                    "from_diagnosis": True,
                    "kind": "evidence",
                    "code": finding.get("code"),
                },
            }
        )

    if advice:
        action = str(advice.get("action") or "").strip()
        title = f"整改方向：{advice.get('title') or code or '建议'}"
        statement = (
            action
            or f"围绕「{advice.get('title')}」补齐可核验内容与结构化标记。"
        )
        payloads.append(
            {
                "title": title[:200],
                "statement": statement[:2000],
                "fact_type": "policy",
                "source_name": source_name,
                "source_url": source_url,
                "trust_level": "needs_review",
                "author_name": "诊断桥",
                "meta": {
                    "from_diagnosis": True,
                    "kind": "action",
                    "code": advice.get("code"),
                },
            }
        )
        acceptance = str(
            advice.get("acceptance") or advice.get("expected_impact") or ""
        ).strip()
        if acceptance:
            payloads.append(
                {
                    "title": f"验收标准：{advice.get('title') or code or '建议'}"[:200],
                    "statement": acceptance[:2000],
                    "fact_type": "metric",
                    "source_name": source_name,
                    "source_url": source_url,
                    "trust_level": "needs_review",
                    "author_name": "诊断桥",
                    "meta": {
                        "from_diagnosis": True,
                        "kind": "acceptance",
                        "code": advice.get("code"),
                    },
                }
            )

    if len(payloads) < 3:
        payloads.append(
            {
                "title": f"页面实体：{page}"[:200],
                "statement": (
                    f"内容任务针对页面「{page}」（{source_url}）做 GEO 补强，"
                    "正文应引用可核验来源，避免无来源承诺。"
                )[:2000],
                "fact_type": "product",
                "source_name": source_name,
                "source_url": source_url,
                "trust_level": "needs_review",
                "author_name": "诊断桥",
                "meta": {"from_diagnosis": True, "kind": "page"},
            }
        )

    return payloads[:4]


async def create_and_bind_diagnosis_facts(
    session: AsyncSession,
    task: GeoContentTask,
    *,
    user_id: int | None = None,
    replace_empty_only: bool = True,
) -> list[GeoFact]:
    """为诊断来源任务创建并绑定对齐的事实卡。"""
    if not task.diagnosis_audit_id:
        raise HTTPException(400, "任务不是诊断桥创建，无法预填诊断事实")

    bound_count = await session.scalar(
        select(func.count())
        .select_from(GeoTaskFact)
        .where(GeoTaskFact.task_id == task.id)
    )
    if replace_empty_only and int(bound_count or 0) > 0:
        result = await session.scalars(
            select(GeoFact)
            .join(GeoTaskFact, GeoTaskFact.fact_id == GeoFact.id)
            .where(GeoTaskFact.task_id == task.id)
            .order_by(GeoTaskFact.sort_order.asc(), GeoFact.id.asc())
        )
        return list(result)

    run = await session.get(GeoAuditRun, task.diagnosis_audit_id)
    if run is None or run.tenant_id != task.tenant_id:
        raise HTTPException(404, "诊断记录不存在")

    payloads = build_diagnosis_fact_payloads(
        run, advice_code=task.diagnosis_advice_code
    )
    if not payloads:
        raise HTTPException(400, "诊断结果不足以生成事实卡")

    facts: list[GeoFact] = []
    for row in payloads:
        fact = GeoFact(
            tenant_id=task.tenant_id,
            title=row["title"],
            statement=row["statement"],
            fact_type=row["fact_type"],
            source_name=row["source_name"],
            source_url=row.get("source_url"),
            trust_level=row.get("trust_level") or "needs_review",
            status="active",
            meta=row.get("meta") or {},
            author_name=row.get("author_name"),
            created_by=user_id,
        )
        session.add(fact)
        facts.append(fact)
    await session.flush()

    await session.execute(delete(GeoTaskFact).where(GeoTaskFact.task_id == task.id))
    for idx, fact in enumerate(facts):
        session.add(GeoTaskFact(task_id=task.id, fact_id=fact.id, sort_order=idx))

    task.status = "facts_bound" if len(facts) >= 3 else "draft"
    sync_pipeline_fields(
        task,
        fact_count=len(facts),
        has_article=False,
        variant_count=0,
    )
    return facts


async def create_task_from_diagnosis(
    session: AsyncSession,
    *,
    tenant_id: int,
    audit_id: int,
    advice_code: str | None,
    user_id: int | None,
) -> tuple[GeoContentTask, GeoPrompt, list[GeoFact]]:
    run = await session.get(GeoAuditRun, audit_id)
    if run is None or run.tenant_id != tenant_id:
        raise HTTPException(404, "诊断记录不存在")

    advice = _pick_advice(run, advice_code)

    if advice:
        question = (
            f"如何改进页面「{run.page_title or run.url}」的 GEO 表现："
            f"{advice.get('title', '')}"
        ).strip()
        tags = ["from_diagnosis", advice_code or "general"]
    else:
        question = f"针对 {run.url} 的 GEO 内容补强"
        tags = ["from_diagnosis"]

    prompt = GeoPrompt(
        tenant_id=tenant_id,
        question=question[:500],
        tags=tags,
        source="import",
        demand_note=f"audit_id={audit_id}",
        created_by=user_id,
        owner_user_id=user_id,
    )
    session.add(prompt)
    await session.flush()

    task = GeoContentTask(
        tenant_id=tenant_id,
        prompt_id=prompt.id,
        title=question[:300],
        status="draft",
        target_channels=["website"],
        diagnosis_audit_id=audit_id,
        diagnosis_advice_code=advice_code,
        pipeline_step="opportunity",
        owner_user_id=user_id,
    )
    session.add(task)
    await session.flush()

    prompt.last_task_id = task.id
    facts = await create_and_bind_diagnosis_facts(
        session, task, user_id=user_id, replace_empty_only=False
    )
    return task, prompt, facts
