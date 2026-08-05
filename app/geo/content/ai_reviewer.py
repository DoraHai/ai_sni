"""AI Reviewer for GEO master drafts (P3)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable

from app.geo.content.brief import normalize_brief
from app.geo.content.rules import RuleInput

SEVERITIES = ("block", "warn")
CATEGORIES = (
    "factual_consistency",
    "exaggeration",
    "missing_comparison",
    "tone",
    "other",
)


def _normalize_issues(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        cat = str(item.get("category") or "other").strip()
        if cat not in CATEGORIES:
            cat = "other"
        sev = str(item.get("severity") or "warn").strip().lower()
        if sev not in SEVERITIES:
            sev = "warn"
        msg = str(item.get("message") or "").strip()
        if not msg:
            continue
        out.append(
            {
                "category": cat,
                "severity": sev,
                "quote": str(item.get("quote") or "")[:300],
                "message": msg[:400],
                "fix_hint": str(item.get("fix_hint") or "")[:300],
            }
        )
        if len(out) >= 20:
            break
    return out


def build_reviewer_prompts(
    *,
    brand: str,
    question: str,
    brief: dict[str, Any] | None,
    rule_input: RuleInput,
) -> tuple[str, str]:
    brief_norm = normalize_brief(brief)
    facts = [
        {
            "id": f.get("id"),
            "title": f.get("title"),
            "statement": f.get("statement"),
            "source_name": f.get("source_name"),
        }
        for f in (rule_input.facts or [])[:12]
    ]
    system = (
        "你是 GEO 母稿审稿编辑。只根据提供的事实卡与正文挑问题，禁止编造新事实。"
        "返回 JSON：{\"summary\":\"一句话\",\"issues\":["
        "{\"category\":\"factual_consistency|exaggeration|missing_comparison|tone|other\","
        "\"severity\":\"block|warn\",\"quote\":\"原文摘录\",\"message\":\"问题\","
        "\"fix_hint\":\"改法\"}]}。"
        "block 仅用于：与事实矛盾、明显虚假排名/保证收录、严重夸大。"
        "缺对比、语气生硬等用 warn。无问题则 issues=[]。"
    )
    user = json.dumps(
        {
            "brand": brand,
            "question": question,
            "brief": brief_norm,
            "title": rule_input.title,
            "body_markdown": (rule_input.body_markdown or "")[:8000],
            "outline": rule_input.outline or {},
            "facts": facts,
        },
        ensure_ascii=False,
    )
    return system, user


async def run_ai_review(
    *,
    brand: str,
    question: str,
    brief: dict[str, Any] | None,
    rule_input: RuleInput,
    llm: dict[str, Any],
    chat_json: Callable,
) -> dict[str, Any]:
    """Call LLM and normalize review payload. Raises on hard failure."""
    system, user = build_reviewer_prompts(
        brand=brand, question=question, brief=brief, rule_input=rule_input
    )
    data = await chat_json(
        system,
        user,
        timeout=90.0,
        api_key=llm.get("api_key"),
        base_url=llm.get("base_url"),
        model=llm.get("model"),
    )
    if not isinstance(data, dict):
        raise ValueError("审稿模型返回非对象")
    issues = _normalize_issues(data.get("issues"))
    summary = str(data.get("summary") or "").strip() or (
        "未发现问题" if not issues else f"发现 {len(issues)} 个问题"
    )
    blocks = sum(1 for i in issues if i.get("severity") == "block")
    warns = sum(1 for i in issues if i.get("severity") == "warn")
    return {
        "summary": summary[:500],
        "issues": issues,
        "block_count": blocks,
        "warn_count": warns,
        "model": llm.get("model"),
        "provider": llm.get("provider"),
        "reviewed_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z",
    }


def reviewer_blocks_publish(
    review: dict[str, Any] | None,
    *,
    gate_enabled: bool = False,
) -> tuple[bool, str]:
    """Return (ok, message). ok=False means publish should be blocked."""
    if not gate_enabled:
        return True, ""
    if not review:
        return True, ""  # no review yet: don't hard-block unless gate requires review
    blocks = [
        i
        for i in (review.get("issues") or [])
        if isinstance(i, dict) and i.get("severity") == "block"
    ]
    if blocks:
        return False, "AI 审稿存在 block 项：" + "；".join(
            str(b.get("message") or "")[:80] for b in blocks[:3]
        )
    return True, ""
