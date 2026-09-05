from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.models.seo import SeoContentAsset, SeoKeywordAsset, SeoRankSnapshot, SeoSitePage
from app.seo_rank_optimization import (
    AUTO_RANK_DROP_AUTHOR,
    AUTO_RANK_DROP_TITLE_PREFIX,
    _rank_drop_candidates,
    _source_page_for_keyword,
    _url_lookup_values,
    create_rank_drop_content_tasks,
    create_rank_drop_content_tasks_safely,
)


def _rank(
    snapshot_id: int,
    rank: int | None,
    checked_at: datetime,
    *,
    region: str = "全国",
) -> SeoRankSnapshot:
    return SeoRankSnapshot(
        id=snapshot_id,
        tenant_id=1,
        site_id=9,
        keyword_id=2,
        engine="google",
        device="desktop",
        region=region,
        subject_type="own",
        rank=rank,
        source="dataforseo",
        checked_at=checked_at,
    )


def test_rank_drop_candidates_only_compare_new_row_with_established_history() -> None:
    now = datetime(2026, 9, 1, 12, 0, 0)
    previous = _rank(10, 12, now - timedelta(days=1))
    latest = _rank(11, 18, now)

    candidates = _rank_drop_candidates(
        [previous, latest], trigger_snapshot_ids={11}, threshold=3
    )
    assert len(candidates) == 1
    assert candidates[0].decline == 6
    assert _rank_drop_candidates(
        [previous, latest], trigger_snapshot_ids={10, 11}, threshold=3
    ) == []


def test_rank_drop_candidates_treat_missing_latest_as_outside_top_100() -> None:
    now = datetime(2026, 9, 1, 12, 0, 0)
    candidates = _rank_drop_candidates(
        [_rank(10, 8, now - timedelta(days=1)), _rank(11, None, now)],
        trigger_snapshot_ids={11},
        threshold=3,
    )
    assert candidates[0].decline == 93


def test_rank_drop_candidates_do_not_compare_different_regions() -> None:
    now = datetime(2026, 9, 1, 12, 0, 0)
    candidates = _rank_drop_candidates(
        [
            _rank(10, 8, now - timedelta(days=1), region="全国"),
            _rank(11, 18, now, region="上海"),
        ],
        trigger_snapshot_ids={11},
        threshold=3,
    )
    assert candidates == []


def test_rank_drop_candidates_ignore_improvement_and_subthreshold_change() -> None:
    now = datetime(2026, 9, 1, 12, 0, 0)
    assert _rank_drop_candidates(
        [_rank(10, 12, now - timedelta(days=1)), _rank(11, 8, now)],
        trigger_snapshot_ids={11},
        threshold=3,
    ) == []
    assert _rank_drop_candidates(
        [_rank(20, 12, now - timedelta(days=1)), _rank(21, 14, now)],
        trigger_snapshot_ids={21},
        threshold=3,
    ) == []


def test_source_page_prefers_configured_landing_url_over_keyword_assignment() -> None:
    keyword = SeoKeywordAsset(
        id=2,
        tenant_id=1,
        site_id=9,
        keyword="NORD",
        landing_page="https://www.nord.cn/cn/home-cn.jsp?utm_source=monitor",
        status="active",
    )
    keyword_page = SeoSitePage(
        id=120,
        tenant_id=1,
        site_id=9,
        url="https://www.nord.cn/cn/other.jsp",
        target_keyword_id=2,
    )
    landing_page = SeoSitePage(
        id=119,
        tenant_id=1,
        site_id=9,
        url="https://www.nord.cn/cn/home-cn.jsp",
    )

    assert "https://www.nord.cn/cn/home-cn.jsp" in _url_lookup_values(
        keyword.landing_page
    )
    assert _source_page_for_keyword(keyword, [keyword_page, landing_page], set()) is landing_page
    assert (
        _source_page_for_keyword(keyword, [keyword_page, landing_page], {119})
        is keyword_page
    )


def test_source_page_does_not_reuse_an_occupied_shared_landing_url() -> None:
    keyword = SeoKeywordAsset(
        id=2,
        tenant_id=1,
        site_id=9,
        keyword="NORD",
        landing_page="https://www.nord.cn/cn/home-cn.jsp",
        status="active",
    )
    landing_page = SeoSitePage(
        id=119,
        tenant_id=1,
        site_id=9,
        url="https://www.nord.cn/cn/home-cn.jsp",
    )

    assert _source_page_for_keyword(keyword, [landing_page], {119}) is None


def test_malformed_landing_urls_do_not_match_by_empty_canonical_value() -> None:
    keyword = SeoKeywordAsset(
        id=2,
        tenant_id=1,
        site_id=9,
        keyword="NORD",
        landing_page="https://example.com:invalid/landing",
        status="active",
    )
    malformed_page = SeoSitePage(
        id=119,
        tenant_id=1,
        site_id=9,
        url="https://other.example:invalid/page",
    )

    assert _source_page_for_keyword(keyword, [malformed_page], set()) is None


class _FakeSession:
    def __init__(self, scalar_results: list[list[object]]) -> None:
        self.scalar_results = iter(scalar_results)
        self.added: list[object] = []

    async def scalars(self, _statement):
        return next(self.scalar_results)

    def add(self, row: object) -> None:
        setattr(row, "id", 100 + len(self.added))
        self.added.append(row)

    async def scalar(self, _statement):
        return None

    async def flush(self) -> None:
        return None


class _NestedTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc, _traceback):
        return False


class _SafeSession:
    def begin_nested(self):
        return _NestedTransaction()


def test_recommendation_failure_is_reported_without_escaping_outer_write() -> None:
    session = _SafeSession()
    with patch(
        "app.seo_rank_optimization.create_rank_drop_content_tasks",
        new=AsyncMock(side_effect=RuntimeError("recommendation failed")),
    ):
        result = asyncio.run(
            create_rank_drop_content_tasks_safely(
                session,
                tenant_id=1,
                site_id=9,
                trigger_snapshot_ids={11},
            )
        )
    assert result == {
        "created": 0,
        "task_ids": [],
        "skipped_existing": 0,
        "error": "optimization_task_generation_failed",
    }


def test_material_drop_creates_review_only_task_without_ai_or_publish() -> None:
    now = datetime(2026, 9, 1, 12, 0, 0)
    previous = _rank(10, 12, now - timedelta(days=1))
    latest = _rank(11, 18, now)
    keyword = SeoKeywordAsset(
        id=2,
        tenant_id=1,
        site_id=9,
        keyword="NORDAC 变频器",
        landing_page="https://example.com/nordac",
        status="active",
        priority="P1",
        source="manual",
    )
    session = _FakeSession([[latest], [latest, previous], [keyword], [], [], []])
    settings = SimpleNamespace(
        seo_rank_drop_tasks_enabled=True,
        seo_rank_drop_task_threshold=3,
    )

    with patch("app.seo_rank_optimization.get_settings", return_value=settings):
        result = asyncio.run(
            create_rank_drop_content_tasks(
                session, tenant_id=1, site_id=9, trigger_snapshot_ids={11}
            )
        )

    assert result == {"created": 1, "task_ids": [100], "skipped_existing": 0}
    task = session.added[0]
    assert isinstance(task, SeoContentAsset)
    assert task.status == "planned"
    assert task.author == AUTO_RANK_DROP_AUTHOR
    assert task.title.startswith(AUTO_RANK_DROP_TITLE_PREFIX)
    assert task.draft is None
    assert task.published_at is None
    assert "12 位" in task.outline and "18 位" in task.outline


def test_material_drop_binds_the_configured_landing_page_without_target_keyword() -> None:
    now = datetime(2026, 9, 1, 12, 0, 0)
    previous = _rank(10, 12, now - timedelta(days=1))
    latest = _rank(11, 18, now)
    keyword = SeoKeywordAsset(
        id=2,
        tenant_id=1,
        site_id=9,
        keyword="NORD",
        landing_page="https://www.nord.cn/cn/home-cn.jsp",
        status="active",
        source="manual",
    )
    page = SeoSitePage(
        id=119,
        tenant_id=1,
        site_id=9,
        url="https://www.nord.cn/cn/home-cn.jsp",
        target_keyword_id=None,
    )
    session = _FakeSession([[latest], [latest, previous], [keyword], [], [], [page]])
    settings = SimpleNamespace(
        seo_rank_drop_tasks_enabled=True,
        seo_rank_drop_task_threshold=3,
    )

    with patch("app.seo_rank_optimization.get_settings", return_value=settings):
        result = asyncio.run(
            create_rank_drop_content_tasks(
                session, tenant_id=1, site_id=9, trigger_snapshot_ids={11}
            )
        )

    assert result == {"created": 1, "task_ids": [100], "skipped_existing": 0}
    assert session.added[0].source_page_id == 119
    assert session.added[0].content_type == "landing"


def test_existing_active_keyword_task_prevents_duplicate() -> None:
    now = datetime(2026, 9, 1, 12, 0, 0)
    previous = _rank(10, 12, now - timedelta(days=1))
    latest = _rank(11, 18, now)
    keyword = SeoKeywordAsset(
        id=2,
        tenant_id=1,
        site_id=9,
        keyword="NORDAC",
        status="active",
        priority="P1",
        source="manual",
    )
    existing = SeoContentAsset(
        id=90,
        tenant_id=1,
        site_id=9,
        keyword_id=2,
        keyword_ids=[2],
        content_type="article",
        title="已有优化任务",
        status="drafting",
    )
    session = _FakeSession([[latest], [latest, previous], [keyword], [existing], [], []])
    settings = SimpleNamespace(
        seo_rank_drop_tasks_enabled=True,
        seo_rank_drop_task_threshold=3,
    )

    with patch("app.seo_rank_optimization.get_settings", return_value=settings):
        result = asyncio.run(
            create_rank_drop_content_tasks(
                session, tenant_id=1, site_id=9, trigger_snapshot_ids={11}
            )
        )

    assert result == {"created": 0, "task_ids": [], "skipped_existing": 1}
    assert session.added == []
