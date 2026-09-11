"""Pure H3/H4 acceptance summaries built from already stored GEO records."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
from typing import Any, Iterable

from app.geo.read_model import ref


def _requirement(key: str, description: str, source: str, satisfied: bool, evidence: Any = None) -> dict:
    return {
        "key": key,
        "description": description,
        "source": source,
        "satisfied": bool(satisfied),
        "evidence": evidence,
    }


def _variant_fingerprint(variant) -> str:
    raw = f"{variant.article_version_id}\n{variant.title}\n{variant.body_markdown}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _trusted_checked_at(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def build_h3_h4_summary(task, articles: Iterable, variants: Iterable, publications: Iterable) -> dict:
    """Describe stored evidence and the remaining human checks without writes."""
    article_rows = list(articles)
    variant_rows = list(variants)
    publication_rows = list(publications)
    latest = max(article_rows, key=lambda row: (int(row.version_no), int(row.id)), default=None)
    latest_variants = sorted([
        row for row in variant_rows if latest is not None and row.article_version_id == latest.id
    ], key=lambda row: (str(row.channel), int(row.id)))
    latest_variant_ids = {row.id for row in latest_variants}
    current_publications = sorted([
        row
        for row in publication_rows
        if row.variant_id in latest_variant_ids
        and row.status == "published"
        and bool(row.published_url)
    ], key=lambda row: int(row.id))
    variants_by_id = {row.id: row for row in latest_variants}
    duplicate_keys = Counter(
        (row.channel, getattr(row, "canonical_url", None) or row.published_url)
        for row in current_publications
    )
    duplicate_registrations = [
        {"channel": channel, "url": url, "count": count}
        for (channel, url), count in sorted(duplicate_keys.items())
        if count > 1
    ]

    review_approved = task.review_status == "approved"
    h3_requirements = [
        _requirement(
            "latest_master_exists",
            "存在当前母稿版本",
            "system",
            latest is not None,
            ref("article_version", latest.id) if latest else None,
        ),
        _requirement(
            "customer_review_approved",
            "当前母稿已经客户确认",
            "system",
            review_approved,
            {"review_status": task.review_status},
        ),
        _requirement(
            "current_channel_variant_exists",
            "至少一份渠道稿绑定当前母稿",
            "system",
            bool(latest_variants),
            [ref("channel_variant", row.id) for row in latest_variants],
        ),
        _requirement(
            "published_record_exists",
            "至少一条当前版本的真实发布登记含公开网址",
            "system",
            bool(current_publications),
            [ref("publication", row.id) for row in current_publications],
        ),
        _requirement(
            "no_duplicate_registration",
            "同一渠道和网址没有重复发布登记",
            "system",
            not duplicate_registrations,
            duplicate_registrations,
        ),
        _requirement(
            "external_channel_exactly_once",
            "渠道后台确认目标内容恰好发布一次",
            "human",
            False,
        ),
        _requirement(
            "duplicate_request_blocked",
            "真人重复提交一次并确认后台没有新增文章",
            "human",
            False,
        ),
    ]
    h3_system_ready = all(item["satisfied"] for item in h3_requirements if item["source"] == "system")
    if not latest or not review_approved or not latest_variants:
        h3_status = "blocked"
    elif not current_publications:
        h3_status = "awaiting_real_publication"
    else:
        h3_status = "awaiting_human_evidence"

    monitor_items = []
    for publication in current_publications:
        variant = variants_by_id[publication.variant_id]
        state = dict(
            ((variant.adapt_meta or {}).get("publication_monitor") or {}).get(str(publication.id))
            or {}
        )
        evidence_reasons = []
        if state.get("state") != "healthy":
            evidence_reasons.append("monitor_not_healthy")
        if state.get("expected_fingerprint") != _variant_fingerprint(variant):
            evidence_reasons.append("fingerprint_missing_or_mismatch")
        if latest is None or state.get("article_id") != latest.id:
            evidence_reasons.append("article_version_mismatch")
        if not _trusted_checked_at(state.get("checked_at")):
            evidence_reasons.append("checked_at_missing_or_invalid")
        monitor_items.append({
            "publication_ref": ref("publication", publication.id),
            "channel": publication.channel,
            "url": publication.published_url,
            "state": state.get("state", "pending"),
            "checked_at": state.get("checked_at"),
            "next_check_at": state.get("next_check_at"),
            "failures": int(state.get("failures") or 0),
            "last_error": state.get("last_error"),
            "evidence_valid": not evidence_reasons,
            "evidence_reasons": evidence_reasons,
        })
    healthy = [item for item in monitor_items if item["evidence_valid"]]
    h4_requirements = [
        _requirement(
            "current_publication_available",
            "当前母稿存在可复核的真实发布网址",
            "system",
            bool(current_publications),
            [ref("publication", row.id) for row in current_publications],
        ),
        _requirement(
            "publication_body_matched",
            "重新抓取的正文与登记渠道稿匹配",
            "system",
            bool(healthy),
            [item["publication_ref"] for item in healthy],
        ),
        _requirement(
            "login_error_empty_pages_rejected",
            "真人确认登录页、错误页和空白页不会被判为正文匹配",
            "human",
            False,
        ),
        _requirement(
            "five_minute_repeat_uses_cache",
            "五分钟内重复检查返回同一结果且不再次抓取",
            "human",
            False,
        ),
    ]
    if not current_publications:
        h4_status = "blocked_by_h3"
    elif not healthy:
        h4_status = "awaiting_successful_recheck"
    else:
        h4_status = "awaiting_human_evidence"

    return {
        "schema_version": "geo.h3h4.acceptance.v1",
        "read_only": True,
        "task_ref": ref("content_task", task.id),
        "latest_article_ref": ref("article_version", latest.id) if latest else None,
        "latest_version_no": latest.version_no if latest else None,
        "h3": {
            "status": h3_status,
            "system_ready": h3_system_ready,
            "formal_acceptance": "requires_human_evidence",
            "requirements": h3_requirements,
        },
        "h4": {
            "status": h4_status,
            "system_ready": bool(current_publications) and bool(healthy),
            "formal_acceptance": "requires_human_evidence",
            "monitoring": monitor_items,
            "requirements": h4_requirements,
        },
    }
