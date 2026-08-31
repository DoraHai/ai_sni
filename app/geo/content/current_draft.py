"""Single-current-draft primitives shared by sync and async editor flows."""

from __future__ import annotations

import hashlib
from typing import Any

from app.geo.content.review import invalidate_review


def article_fingerprint(article: Any) -> str:
    title = str(getattr(article, "title", "") or "")
    body = str(getattr(article, "body_markdown", "") or "")
    return hashlib.sha256(f"{title}\n{body}".encode("utf-8")).hexdigest()


def score_matches_current_article(rule_result: Any, article: Any) -> bool:
    if not isinstance(rule_result, dict) or article is None:
        return False
    stored = str(rule_result.get("article_fingerprint") or "")
    return bool(stored) and stored == article_fingerprint(article)


def can_overwrite_current_draft(task: Any) -> bool:
    """A delivered task is immutable so its publication/attribution chain survives."""
    return str(getattr(task, "status", "") or "").lower() != "published"


def overwrite_current_article(
    article: Any,
    *,
    title: str,
    body_markdown: str,
    outline: dict | None,
    generation_meta: dict | None,
    created_by: int | None,
    author_name: str | None = None,
) -> Any:
    """Overwrite the task's one editable article row in place."""
    article.version_no = 1
    article.kind = "master"
    article.title = title
    article.body_markdown = body_markdown
    article.body_html = None
    article.outline = dict(outline or {})
    article.generation_meta = dict(generation_meta or {})
    article.created_by = created_by
    if author_name is not None:
        article.author_name = author_name
    return article


def invalidate_current_draft(task: Any) -> None:
    """Drop every derived decision when the editable mother draft changes."""
    task.status = "editing"
    task.rule_result = None
    task.ready_at = None
    invalidate_review(task)
