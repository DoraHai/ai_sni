from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

import asyncio
import pytest
from datetime import datetime

from app.geo.acceptance_readiness import _variant_fingerprint, build_h3_h4_summary


def row(**values):
    if values.get("review_status") == "approved":
        values.setdefault("reviewed_at", datetime(2026, 9, 11, 2, 0))
    if "version_no" in values:
        values.setdefault("created_at", datetime(2026, 9, 11, 1, 0))
    return NS(**values)


def test_h3_h4_summary_blocks_before_current_approved_channel_draft():
    task = row(id=14, review_status="pending")
    article = row(id=23, version_no=6)

    result = build_h3_h4_summary(task, [article], [], [])

    assert result["read_only"] is True
    assert result["h3"]["status"] == "blocked"
    assert result["h4"]["status"] == "blocked_by_h3"
    assert result["h3"]["formal_acceptance"] == "requires_human_evidence"


def test_h4_fails_closed_when_h3_review_is_not_approved_despite_healthy_monitor():
    task = row(id=14, review_status="pending")
    article = row(id=23, version_no=6)
    variant = row(
        id=6,
        article_version_id=23,
        channel="website",
        title="Current title",
        body_markdown="Current body",
        adapt_meta={},
    )
    variant.adapt_meta = {
        "publication_monitor": {
            "9": {
                "state": "healthy",
                "article_id": 23,
                "expected_fingerprint": _variant_fingerprint(variant),
                "checked_at": "2026-09-11T01:00:00Z",
            }
        }
    }
    publication = row(
        id=9,
        variant_id=6,
        channel="website",
        canonical_url="https://example.com/a",
        published_url="https://example.com/a",
        status="published",
    )

    result = build_h3_h4_summary(task, [article], [variant], [publication])

    assert result["h3"]["status"] == "blocked"
    assert result["h3"]["blocking_reasons"] == ["customer_review_approved"]
    assert result["h4"]["status"] == "blocked_by_h3"
    assert result["h4"]["system_ready"] is False
    assert result["h4"]["blocking_reasons"] == ["h3:customer_review_approved"]


@pytest.mark.parametrize("reviewed_at", [None, datetime(2026, 9, 11, 0, 59)])
def test_h3_rejects_missing_or_older_review_for_latest_master(reviewed_at):
    task = row(id=14, review_status="approved", reviewed_at=reviewed_at)
    article = row(id=23, version_no=6, created_at=datetime(2026, 9, 11, 1, 0))

    result = build_h3_h4_summary(task, [article], [], [])

    assert "customer_review_approved" in result["h3"]["blocking_reasons"]
    requirement = next(
        item for item in result["h3"]["requirements"]
        if item["key"] == "customer_review_approved"
    )
    assert requirement["satisfied"] is False
    assert requirement["evidence"]["article_ref"] == {
        "module": "geo", "type": "article_version", "id": 23,
    }
    assert requirement["evidence"]["article_created_at"] == "2026-09-11T01:00:00Z"


def test_h3_h4_summary_separates_stored_proof_from_human_channel_checks():
    task = row(id=14, review_status="approved")
    article = row(id=23, version_no=6)
    variant = row(
        id=6,
        article_version_id=23,
        channel="website",
        title="Current title",
        body_markdown="Current body",
        adapt_meta={},
    )
    variant.adapt_meta = {
        "publication_monitor": {
            "9": {
                "state": "healthy",
                "article_id": 23,
                "expected_fingerprint": _variant_fingerprint(variant),
                "checked_at": "2026-09-11T01:00:00Z",
                "next_check_at": "2026-09-12T01:00:00Z",
            }
        }
    }
    publication = row(
        id=9,
        variant_id=6,
        channel="website",
        canonical_url="https://example.com/a",
        published_url="https://example.com/a",
        status="published",
    )

    result = build_h3_h4_summary(task, [article], [variant], [publication])

    assert result["h3"]["system_ready"] is True
    assert result["h3"]["status"] == "awaiting_human_evidence"
    assert result["h4"]["system_ready"] is True
    assert result["h4"]["status"] == "awaiting_human_evidence"
    human = [item for item in result["h3"]["requirements"] if item["source"] == "human"]
    assert human and not any(item["satisfied"] for item in human)


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("missing_fingerprint", "fingerprint_missing_or_mismatch"),
        ("mismatched_fingerprint", "fingerprint_missing_or_mismatch"),
        ("old_article", "article_version_mismatch"),
        ("missing_checked_at", "checked_at_missing_or_invalid"),
        ("naive_checked_at", "checked_at_missing_or_invalid"),
    ],
)
def test_h4_rejects_untrusted_or_stale_healthy_monitor_evidence(mutation, reason):
    task = row(id=14, review_status="approved")
    article = row(id=23, version_no=6)
    variant = row(
        id=6,
        article_version_id=23,
        channel="website",
        title="Current title",
        body_markdown="Current body",
        adapt_meta={},
    )
    state = {
        "state": "healthy",
        "article_id": 23,
        "expected_fingerprint": _variant_fingerprint(variant),
        "checked_at": "2026-09-11T01:00:00Z",
    }
    if mutation == "missing_fingerprint":
        state.pop("expected_fingerprint")
    elif mutation == "mismatched_fingerprint":
        state["expected_fingerprint"] = "not-current"
    elif mutation == "old_article":
        state["article_id"] = 22
    elif mutation == "missing_checked_at":
        state.pop("checked_at")
    elif mutation == "naive_checked_at":
        state["checked_at"] = "2026-09-11T01:00:00"
    variant.adapt_meta = {"publication_monitor": {"9": state}}
    publication = row(
        id=9,
        variant_id=6,
        channel="website",
        canonical_url="https://example.com/a",
        published_url="https://example.com/a",
        status="published",
    )

    result = build_h3_h4_summary(task, [article], [variant], [publication])

    assert result["h4"]["system_ready"] is False
    assert result["h4"]["status"] == "awaiting_successful_recheck"
    assert reason in result["h4"]["monitoring"][0]["evidence_reasons"]


def test_stale_version_publication_does_not_make_h3_ready():
    task = row(id=14, review_status="approved")
    articles = [row(id=23, version_no=6), row(id=22, version_no=5)]
    stale_variant = row(
        id=5,
        article_version_id=22,
        channel="website",
        title="Old title",
        body_markdown="Old body",
        adapt_meta={},
    )
    publication = row(
        id=8,
        variant_id=5,
        channel="website",
        canonical_url="https://example.com/old",
        published_url="https://example.com/old",
        status="published",
    )

    result = build_h3_h4_summary(task, articles, [stale_variant], [publication])

    assert result["h3"]["status"] == "blocked"
    assert result["h4"]["status"] == "blocked_by_h3"


def test_duplicate_registration_blocks_both_stages_and_recovers_when_removed():
    task = row(id=14, review_status="approved")
    article = row(id=23, version_no=6)
    variant = row(
        id=6,
        article_version_id=23,
        channel="website",
        title="Current title",
        body_markdown="Current body",
        adapt_meta={},
    )
    publications = [
        row(id=9, variant_id=6, channel="website", canonical_url=None,
            published_url="https://example.com/a", status="published"),
        row(id=10, variant_id=6, channel="website", canonical_url=None,
            published_url="https://example.com/a", status="published"),
    ]

    blocked = build_h3_h4_summary(task, [article], [variant], publications)
    recovered = build_h3_h4_summary(task, [article], [variant], publications[:1])

    assert blocked["h3"]["status"] == "blocked"
    assert blocked["h3"]["blocking_reasons"] == ["no_duplicate_registration"]
    assert blocked["h4"]["status"] == "blocked_by_h3"
    assert recovered["h3"]["status"] == "awaiting_human_evidence"
    assert recovered["h3"]["blocking_reasons"] == []
    assert recovered["h4"]["status"] == "awaiting_successful_recheck"
    assert recovered["h4"]["blocking_reasons"] == ["publication_body_matched"]


def test_acceptance_summary_does_not_expose_legacy_monitor_error_text():
    task = row(id=14, review_status="approved")
    article = row(id=23, version_no=6)
    variant = row(
        id=6,
        article_version_id=23,
        channel="website",
        title="Current title",
        body_markdown="Current body",
        adapt_meta={
            "publication_monitor": {
                "9": {
                    "state": "unreachable",
                    "last_error": "token=must-not-leak",
                    "failures": 1,
                }
            }
        },
    )
    publication = row(
        id=9,
        variant_id=6,
        channel="website",
        canonical_url=None,
        published_url="https://example.com/a",
        status="published",
    )

    result = build_h3_h4_summary(task, [article], [variant], [publication])

    assert result["h4"]["monitoring"][0]["last_error"] is None
    assert "must-not-leak" not in str(result)


def test_acceptance_summary_route_only_reads_stored_records():
    from app.geo.read_routes import get_content_task_acceptance_summary

    task = row(id=14, review_status="pending")
    session = Mock(
        scalars=AsyncMock(side_effect=[[], [], []]),
        add=Mock(side_effect=AssertionError("write forbidden")),
        commit=AsyncMock(side_effect=AssertionError("write forbidden")),
    )
    ctx = Mock()
    with patch("app.geo.read_routes.tenant_object", AsyncMock(return_value=task)):
        result = asyncio.run(get_content_task_acceptance_summary(14, 1, ctx, session))

    ctx.ensure_tenant.assert_called_once_with(1)
    assert result["tenant_id"] == 1
    assert result["read_only"] is True
    assert session.scalars.await_count == 3
    session.add.assert_not_called()
    session.commit.assert_not_awaited()


def test_tenant16_demo_acceptance_summary_returns_explicit_404_without_db_access():
    from fastapi import HTTPException

    from app.geo.read_routes import get_content_task_acceptance_summary
    from app.geo.tenant16_demo import Tenant16DemoSession

    ctx = row(
        user_id=5,
        username="workbench_test_readonly",
        tenant_id=16,
        is_superadmin=False,
        ensure_tenant=Mock(),
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            get_content_task_acceptance_summary(
                16_030_001,
                16,
                ctx,
                Tenant16DemoSession(),
            )
        )

    assert error.value.status_code == 404
    assert "真实发布验收摘要" in error.value.detail
    ctx.ensure_tenant.assert_called_once_with(16)
