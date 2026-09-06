"""Pure mapping from SEO read models to the acquisition workbench view model.

This module performs no I/O. It keeps review, publication, page evidence and
search performance separate, and fails closed when response context is stale.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence


class WorkbenchPayloadError(ValueError):
    """The supplied read payload cannot be safely attributed or interpreted."""


class StaleWorkbenchResponse(WorkbenchPayloadError):
    """A response belongs to an older request or a different tenant/site."""


@dataclass(frozen=True)
class WorkbenchResponseContext:
    tenant_id: int
    site_id: int
    request_id: str

    def __post_init__(self) -> None:
        if self.tenant_id <= 0 or self.site_id <= 0 or not self.request_id.strip():
            raise WorkbenchPayloadError("tenant_id、site_id 和 request_id 必须有效")


def _assert_current_response(
    expected: WorkbenchResponseContext, actual: WorkbenchResponseContext
) -> None:
    if actual != expected:
        raise StaleWorkbenchResponse("响应上下文已过期或不属于当前客户/站点")


def _scope_value(row: Mapping[str, Any], key: str, expected: int, label: str) -> None:
    value = row.get(key)
    try:
        matches = value is not None and _required_id(value, label) == expected
    except WorkbenchPayloadError:
        matches = False
    if not matches:
        raise WorkbenchPayloadError(f"{label} 不属于当前 {key}")


def _required_id(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise WorkbenchPayloadError(f"{label} id 无效")
    if isinstance(value, int):
        result = value
    elif isinstance(value, float):
        if not value.is_integer():
            raise WorkbenchPayloadError(f"{label} id 无效")
        result = int(value)
    elif isinstance(value, str) and value.strip().isdigit():
        result = int(value.strip())
    else:
        raise WorkbenchPayloadError(f"{label} id 无效")
    if result <= 0:
        raise WorkbenchPayloadError(f"{label} id 无效")
    return result


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or "T" not in value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError:
        return None


def _timestamp(value: Any) -> datetime:
    return _parse_timestamp(value) or datetime.min


def _review(content: Mapping[str, Any]) -> dict[str, Any]:
    def actor_id(value: Any) -> int | None:
        try:
            return _required_id(value, "审核账号")
        except WorkbenchPayloadError:
            return None

    submitted_by = actor_id(content.get("review_submitted_by"))
    reviewed_by = actor_id(content.get("reviewed_by"))
    raw_reviewed_at = content.get("reviewed_at")
    reviewed_at = raw_reviewed_at if _parse_timestamp(raw_reviewed_at) is not None else None
    status = str(content.get("status") or "")
    approved = status in {"ready", "published"} and reviewed_at is not None
    independent = bool(
        approved
        and submitted_by is not None
        and reviewed_by is not None
        and submitted_by != reviewed_by
    )
    if approved and independent:
        label = "审核通过"
    elif approved:
        label = "历史审核，独立性未确认"
    elif status == "review":
        label = "审核中"
    else:
        label = "未审核"
    return {
        "state": "approved" if approved else "in_review" if status == "review" else "not_reviewed",
        "label": label,
        "independent": independent,
        "reviewed_at": reviewed_at,
    }


def _latest_attempt(attempts: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    rows = list(attempts)
    if not rows:
        return None
    if any(not isinstance(row, Mapping) for row in rows):
        raise WorkbenchPayloadError("发布尝试格式无效")
    row = max(
        rows,
        key=lambda item: (
            _timestamp(item.get("started_at")),
            _required_id(item.get("id"), "发布尝试"),
        ),
    )
    return {
        "id": row.get("id"),
        "action": row.get("action"),
        "status": row.get("status"),
        "error": row.get("error"),
        "started_at": row.get("started_at"),
        "completed_at": row.get("completed_at"),
    }


def _publications(
    content_id: int,
    tenant_id: int,
    rows: Sequence[Mapping[str, Any]],
    attempts_by_publication: Mapping[int, Sequence[Mapping[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise WorkbenchPayloadError("发布记录格式无效")
        _scope_value(row, "tenant_id", tenant_id, "发布记录")
        row_content_id = row.get("content_id", row.get("content_asset_id"))
        try:
            belongs_to_content = _required_id(row_content_id, "发布记录内容") == content_id
        except WorkbenchPayloadError:
            belongs_to_content = False
        if not belongs_to_content:
            raise WorkbenchPayloadError("发布记录不属于当前内容")
        publication_id = _required_id(row.get("id"), "发布记录")
        attempt = _latest_attempt(attempts_by_publication.get(publication_id, ()))
        result.append(
            {
                "id": publication_id,
                "platform_code": row.get("platform_code"),
                "publish_mode": row.get("publish_mode"),
                "state": row.get("status"),
                "published_at": row.get("published_at"),
                "page_url": row.get("page_url"),
                "failure": row.get("last_error"),
                "latest_attempt": attempt,
            }
        )
    return result, {
        "record_count": len(result),
        "successful_count": sum(row["state"] == "published" for row in result),
        "failed_count": sum(row["state"] == "failed" for row in result),
    }


def _page_evidence(
    content: Mapping[str, Any],
    publications: Sequence[Mapping[str, Any]],
    page_detail: Mapping[str, Any] | None,
    page_candidates: Sequence[Mapping[str, Any]],
    page_binding: Mapping[str, Any] | None,
    tenant_id: int,
    site_id: int,
) -> dict[str, Any]:
    source_page_id = content.get("source_page_id")
    published_rows = [row for row in publications if row.get("state") == "published"]
    publication_urls = [row.get("page_url") for row in published_rows if row.get("page_url")]
    candidate_ids: set[int] = set()
    for candidate in page_candidates:
        if not isinstance(candidate, Mapping):
            raise WorkbenchPayloadError("候选页面格式无效")
        _scope_value(candidate, "tenant_id", tenant_id, "候选页面")
        _scope_value(candidate, "site_id", site_id, "候选页面")
        if candidate.get("id") is None:
            raise WorkbenchPayloadError("候选页面缺少 id")
        candidate_ids.add(_required_id(candidate["id"], "候选页面"))

    if page_detail and isinstance(page_detail.get("page"), Mapping):
        supplied_page = page_detail["page"]
        _scope_value(supplied_page, "tenant_id", tenant_id, "页面")
        _scope_value(supplied_page, "site_id", site_id, "页面")

    if page_binding is None:
        if published_rows and not publication_urls:
            mapping_state = "missing_url"
        elif publication_urls and len(candidate_ids) > 1:
            mapping_state = "ambiguous"
        elif publication_urls:
            mapping_state = "unmapped"
        elif source_page_id is not None:
            # source_page_id binds a landing/remediation task to an audited page.
            # It does not prove the approved content was applied or published there.
            mapping_state = "source_page_only"
        else:
            mapping_state = "not_linked"
        return {
            "mapping_state": mapping_state,
            "page_id": None,
            "candidate_count": len(candidate_ids),
            "check_state": "not_checked",
            "checked_at": None,
            "latest_snapshot_id": None,
            "http_status": None,
            "failure": None,
            "passed": None,
        }

    _scope_value(page_binding, "tenant_id", tenant_id, "页面关联")
    _scope_value(page_binding, "site_id", site_id, "页面关联")
    linked_page_id = _required_id(page_binding.get("page_id"), "页面关联")
    binding_kind = page_binding.get("target_kind")
    binding_url = page_binding.get("page_url")
    if binding_kind == "content_page_url":
        if not content.get("page_url") or binding_url != content.get("page_url"):
            raise WorkbenchPayloadError("内容发布地址与页面关联不一致")
    elif binding_kind == "publication_page_url":
        publication_id = _required_id(page_binding.get("publication_id"), "页面关联发布记录")
        publication = next((row for row in publications if row.get("id") == publication_id), None)
        if publication is None or not publication.get("page_url") or binding_url != publication.get("page_url"):
            raise WorkbenchPayloadError("平台发布地址与页面关联不一致")
    else:
        raise WorkbenchPayloadError("页面关联类型无效")

    if not page_detail or not isinstance(page_detail.get("page"), Mapping):
        return {
            "mapping_state": "linked_page_unavailable",
            "page_id": linked_page_id,
            "candidate_count": 0,
            "check_state": "not_checked",
            "checked_at": None,
            "latest_snapshot_id": None,
            "http_status": None,
            "failure": None,
            "passed": None,
        }

    page = page_detail["page"]
    _scope_value(page, "tenant_id", tenant_id, "页面")
    _scope_value(page, "site_id", site_id, "页面")
    if _required_id(page.get("id"), "页面") != linked_page_id:
        raise WorkbenchPayloadError("页面详情与显式页面关联不一致")
    if page.get("url") != binding_url:
        raise WorkbenchPayloadError("页面详情地址与显式页面关联不一致")
    diagnostic = page.get("diagnostic") if isinstance(page.get("diagnostic"), Mapping) else {}
    latest = page_detail.get("latest_snapshot")
    if latest is not None and not isinstance(latest, Mapping):
        raise WorkbenchPayloadError("页面快照格式无效")
    latest_snapshot_id = None
    if latest is not None:
        latest_snapshot_id = _required_id(latest.get("id"), "页面快照")
        snapshot_urls = {
            value
            for value in (latest.get("url"), latest.get("final_url"))
            if isinstance(value, str) and value
        }
        if binding_url not in snapshot_urls:
            raise WorkbenchPayloadError("最新页面快照与显式页面关联不一致")
    check_state = str(diagnostic.get("assessment_state") or "not_checked")
    failure = None
    if latest:
        failure = latest.get("fetch_error") or latest.get("error_type")
    return {
        "mapping_state": "matched",
        "page_id": linked_page_id,
        "candidate_count": 1,
        "check_state": check_state,
        "checked_at": diagnostic.get("checked_at"),
        "latest_snapshot_id": latest_snapshot_id,
        "http_status": diagnostic.get("http_status"),
        "failure": failure,
        # Existing diagnostic payload proves that an assessment ran. It does
        # not define a whole-page pass/fail contract.
        "passed": None,
    }


def adapt_seo_workbench_item(
    raw: Mapping[str, Any],
    *,
    expected_context: WorkbenchResponseContext,
    response_context: WorkbenchResponseContext,
    attempts_by_publication: Mapping[int, Sequence[Mapping[str, Any]]] | None = None,
    page_candidates: Sequence[Mapping[str, Any]] = (),
    page_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Adapt one already-fetched SEO record without triggering collection.

    ``page_binding`` is an explicit mapping supplied by the consumer. This
    module does not discover or persist URL-to-page relationships. The current
    SEO diagnostic contract also has no whole-page pass field, so ``passed``
    remains ``None`` even when ``assessment_state`` is ``assessed``.
    """

    _assert_current_response(expected_context, response_context)
    content = raw.get("content")
    if not isinstance(content, Mapping):
        raise WorkbenchPayloadError("缺少内容记录")
    _scope_value(content, "tenant_id", expected_context.tenant_id, "内容")
    _scope_value(content, "site_id", expected_context.site_id, "内容")
    content_id = _required_id(content.get("id"), "内容")
    publication_rows = raw.get("publications") or []
    if not isinstance(publication_rows, Sequence) or isinstance(publication_rows, (str, bytes)):
        raise WorkbenchPayloadError("发布记录格式无效")
    page_detail = raw.get("page_detail")
    if page_detail is not None and not isinstance(page_detail, Mapping):
        raise WorkbenchPayloadError("页面详情格式无效")
    if page_detail is not None and page_detail.get("page") is not None and not isinstance(
        page_detail.get("page"), Mapping
    ):
        raise WorkbenchPayloadError("页面详情格式无效")
    if page_binding is not None and not isinstance(page_binding, Mapping):
        raise WorkbenchPayloadError("页面关联格式无效")
    publication_view, summary = _publications(
        content_id,
        expected_context.tenant_id,
        publication_rows,
        attempts_by_publication or {},
    )
    review = _review(content)
    content_label = (
        "已审核待发布"
        if review["state"] == "approved" and summary["successful_count"] == 0
        else "已有发布记录"
        if summary["successful_count"] > 0
        else "审核中"
        if review["state"] == "in_review"
        else "未审核"
    )
    return {
        "content": {
            "id": content_id,
            "title": content.get("title"),
            "state": content.get("status"),
            "label": content_label,
            "version": content.get("version_count"),
            "updated_at": content.get("updated_at"),
        },
        "review": review,
        "publications": publication_view,
        "publication_summary": summary,
        "page_evidence": _page_evidence(
            content,
            publication_view,
            page_detail,
            page_candidates,
            page_binding,
            expected_context.tenant_id,
            expected_context.site_id,
        ),
        "search_performance": {
            "article_clicks": None,
            "state": "unavailable",
            "reason": "SEO 当前没有可靠的单篇文章点击数据，不能从业务总点击或关键词推断。",
        },
    }
