"""Explain stored SEO observations without inventing indexing or AI evidence."""

from datetime import timezone

from sqlalchemy import and_, func

FATAL_CODES = frozenset({
    "http_4xx", "http_5xx", "empty_response", "non_html", "timeout",
    "too_many_redirects", "dns_error", "tls_error", "blocked_address",
    "connection_error", "robots_blocked",
})
AI_CODES = frozenset({"ai_crawlers", "llms"})
INDEX_CODES = frozenset({"noindex", "indexable", "robots_blocked"})


def checked_iso(value):
    # Existing site-page checked_at values were written as naive UTC.
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc).isoformat() if value.tzinfo is None else value.isoformat()


def assessment_state(row):
    if getattr(row, "last_checked_at", None) is None:
        return "not_checked"
    codes = set(getattr(row, "issue_codes", None) or [])
    status = getattr(row, "http_status", None)
    if (getattr(row, "status", None) in {"pending", "error"}
            or getattr(row, "last_error", None)
            or status is None or not 200 <= status < 300 or codes & FATAL_CODES):
        return "unavailable"
    return "assessed"


def assessed_condition(model):
    """SQL counterpart of assessment_state; keep list scores and averages aligned."""
    return and_(
        model.last_checked_at.is_not(None),
        model.status.not_in(("pending", "error")),
        func.coalesce(model.last_error, "") == "",
        model.http_status >= 200, model.http_status < 300,
        *[~func.coalesce(model.issue_codes.contains([code]), False) for code in sorted(FATAL_CODES)],
    )


def diagnostic_payload(row, intent="undecided"):
    codes = set(getattr(row, "issue_codes", None) or [])
    state = assessment_state(row)
    if "robots_blocked" in codes and getattr(row, "last_checked_at", None):
        control = "crawl_blocked"
    elif state != "assessed":
        control = "unknown"
    elif codes & {"noindex", "indexable"} or getattr(row, "indexable", None) is False:
        control = "index_restricted"
    elif getattr(row, "indexable", None) is True:
        control = "no_restriction_detected"
    else:
        control = "unknown"

    if intent == "undecided":
        outcome = "needs_review"
        guidance = "先由网站负责人确认页面是否需要参与自然搜索；不要仅凭隐私页、免责声明等名称推断用途。"
    elif control in {"unknown", "crawl_blocked"}:
        outcome = "unverifiable"
        guidance = ("Robots 拦截抓取不等于禁止索引，当前无法核实页面索引指令。先人工复核访问与索引设置。"
                    if control == "crawl_blocked" else "本次检测证据不足，先核查访问失败原因或重新检测，再判断是否符合索引意图。")
    else:
        matches = ((intent == "index" and control == "no_restriction_detected")
                   or (intent == "noindex" and control == "index_restricted"))
        outcome = "matches_intent" if matches else "conflict"
        if matches:
            guidance = "当前检测到的索引设置与人工意图一致，可保持；这不代表搜索引擎已经收录或移除该页面。"
        elif intent == "index":
            guidance = "人工意图为参与搜索，但检测到索引限制。请负责人核查 robots meta / X-Robots-Tag 后决定是否调整，并复检。"
        else:
            guidance = "人工意图为不参与搜索，但当前未检测到索引限制。请负责人配置适当的 noindex 后复检；不要仅用 robots.txt 代替。"

    return {
        "assessment_state": state,
        "audit_score": getattr(row, "audit_score", None) if state == "assessed" else None,
        "detection_source": "program", "guidance_source": "rules",
        "index_intent_source": "human", "ai_used": False,
        # A failed single-page audit historically retained an earlier HTTP value.
        # Do not present that stale value as the outcome of the latest attempt.
        "http_status": (None if getattr(row, "last_error", None) else getattr(row, "http_status", None)),
        "checked_at": checked_iso(getattr(row, "last_checked_at", None)),
        "index_control": control, "search_engine_indexed": None,
        "index_intent": intent, "review_outcome": outcome, "guidance": guidance,
        "index_evidence_codes": sorted(codes & INDEX_CODES),
        "ai_crawler_codes": sorted(codes & AI_CODES),
        "note": "基于最近一次存档检测，不是实时监控；未检测到限制不等于已收录。AI 爬虫规则不代表传统搜索引擎索引状态。",
    }
