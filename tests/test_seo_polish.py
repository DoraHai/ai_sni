"""Read-only API projections with synthetic sessions; never connect a database."""
import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.api import seo


@pytest.mark.parametrize("ranks,expected", [([], None), ([None], None), ([21], 0), ([4, 21], 50)])
def test_overview_top10_coverage_distinguishes_absent_and_zero(ranks, expected):
    keywords = [SimpleNamespace(id=i + 1, created_at=None) for i in range(max(1, len(ranks)))]
    observations = [SimpleNamespace(id=i + 1, keyword_id=i + 1, checked_at=datetime(2026, 10, 23), rank=rank)
                    for i, rank in enumerate(ranks)]
    session = AsyncMock()
    session.scalars.side_effect = [keywords, [], [], [], [], observations, [], []]
    session.scalar.return_value = None
    session.execute.return_value = []
    site = SimpleNamespace(id=1, name="合成网站", canonical_domain="example.invalid", default_url="https://example.invalid")
    with patch.object(seo, "_tenant", AsyncMock()), patch.object(seo, "_seo_site", AsyncMock(return_value=site)), \
            patch.object(seo, "_latest_site_metrics", AsyncMock(return_value={})), \
            patch.object(seo, "_keyword_payload", return_value={"priority": "P2", "monthly_volume": None}):
        result = asyncio.run(seo.seo_overview(tenant_id=1, site_id=1, engine="baidu", days=30, session=session))
    assert result["stats"]["top10_rate"] == expected
    session.commit.assert_not_awaited()


@pytest.mark.parametrize("state,assessed", [(None, 0), ("pending", 0), ("error", 0), ("healthy", 1)])
def test_issue_summary_requires_stored_successful_assessment(state, assessed):
    pages = [] if state is None else [SimpleNamespace(
        id=1, title=None, meta_description=None, issue_codes=[], status=state,
        last_checked_at=None if state == "pending" else datetime(2026, 10, 23),
        http_status=200, last_error=None)]
    session = AsyncMock()
    session.scalars.return_value = pages
    session.execute.return_value = []
    with patch.object(seo, "_tenant", AsyncMock()), patch.object(seo, "_seo_site", AsyncMock()):
        result = asyncio.run(seo.list_site_page_issues(tenant_id=1, site_id=1, session=session))
    assert result["summary"]["assessed_pages"] == assessed
    session.commit.assert_not_awaited()
