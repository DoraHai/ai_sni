from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

import asyncio

from app.geo.acceptance_readiness import build_h3_h4_summary


def row(**values):
    return NS(**values)


def test_h3_h4_summary_blocks_before_current_approved_channel_draft():
    task = row(id=14, review_status="pending")
    article = row(id=23, version_no=6)

    result = build_h3_h4_summary(task, [article], [], [])

    assert result["read_only"] is True
    assert result["h3"]["status"] == "blocked"
    assert result["h4"]["status"] == "blocked_by_h3"
    assert result["h3"]["formal_acceptance"] == "requires_human_evidence"


def test_h3_h4_summary_separates_stored_proof_from_human_channel_checks():
    task = row(id=14, review_status="approved")
    article = row(id=23, version_no=6)
    variant = row(
        id=6,
        article_version_id=23,
        channel="website",
        adapt_meta={
            "publication_monitor": {
                "9": {
                    "state": "healthy",
                    "checked_at": "2026-09-11T01:00:00Z",
                    "next_check_at": "2026-09-12T01:00:00Z",
                }
            }
        },
    )
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


def test_stale_version_publication_does_not_make_h3_ready():
    task = row(id=14, review_status="approved")
    articles = [row(id=23, version_no=6), row(id=22, version_no=5)]
    stale_variant = row(id=5, article_version_id=22, channel="website", adapt_meta={})
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
