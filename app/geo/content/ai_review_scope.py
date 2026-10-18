"""Bind generated advice to the exact master draft it evaluated."""
import hashlib
import json


def article_binding(article):
    return {
        "article_id": getattr(article, "id", None),
        "article_version": getattr(article, "version_no", None),
        "content_sha256": hashlib.sha256(json.dumps({
            "title": getattr(article, "title", None),
            "body_markdown": getattr(article, "body_markdown", None),
        }, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
    }


def current_review(review, article):
    if (article is not None and isinstance(review, dict)
            and all(review.get(key) == value for key, value in article_binding(article).items())):
        return review
    return None
