from __future__ import annotations

import os
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "test-secret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from sqlalchemy.dialects import postgresql

from app import seo_snapshot_retention as retention


def test_candidate_query_keeps_recent_ten_and_every_human_review_anchor():
    query = retention.retention_candidate_ids(
        cutoff=datetime(2026, 8, 1), min_per_url=10, batch_size=500,
    )
    sql = str(query.compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True},
    ))

    assert "row_number() OVER" in sql
    assert "PARTITION BY seo_page_snapshots.tenant_id, seo_page_snapshots.site_id, seo_page_snapshots.url" in sql
    assert "seo_page_snapshots.discovery_source = 'single_page'" in sql
    assert "recency_rank > 10" in sql
    assert "seo_image_alt_reviews.snapshot_id" in sql and "NOT (EXISTS" in sql
    assert "LIMIT 500" in sql


def test_prune_is_bounded_and_removes_only_orphaned_runs():
    session = SimpleNamespace(
        scalars=AsyncMock(return_value=[101, 102]),
        execute=AsyncMock(return_value=SimpleNamespace(rowcount=2)),
        commit=AsyncMock(),
    )

    class SessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *_args):
            return False

    settings = SimpleNamespace(
        seo_snapshot_retention_days=30,
        seo_snapshot_retention_min_per_url=10,
        seo_snapshot_retention_batch_size=1000,
    )
    with (
        patch("app.seo_snapshot_retention.get_settings", return_value=settings),
        patch("app.seo_snapshot_retention.async_session_factory", return_value=SessionContext()),
    ):
        import asyncio
        result = asyncio.run(retention.prune_old_single_page_snapshots())

    assert result == {"snapshots": 2, "crawl_runs": 2}
    snapshot_delete = str(session.scalars.await_args.args[0].compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True},
    ))
    run_delete = str(session.execute.await_args.args[0].compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True},
    ))
    assert "DELETE FROM seo_page_snapshots" in snapshot_delete
    assert "seo_image_alt_reviews.snapshot_id" in snapshot_delete
    assert "DELETE FROM seo_crawl_runs" in run_delete
    assert "NOT (EXISTS" in run_delete
    session.commit.assert_awaited_once()
