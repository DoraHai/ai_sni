import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.seo_monitoring_jobs import (
    backlink_present,
    collect_scheduled_competitors,
    verify_scheduled_backlinks,
)


class _SessionContext:
    def __init__(self, session: SimpleNamespace) -> None:
        self.session = session

    async def __aenter__(self) -> SimpleNamespace:
        return self.session

    async def __aexit__(self, *_args: object) -> bool:
        return False


def test_backlink_verification_normalizes_relative_and_tracking_urls() -> None:
    body = '<html><a href="/target/?utm_source=partner#section">Brand</a></html>'

    assert backlink_present(
        body,
        "https://partner.example/article",
        "https://partner.example/target",
    ) is True
    assert backlink_present(
        body,
        "https://partner.example/article",
        "https://brand.example/target",
    ) is False


def test_scheduled_competitors_skip_queries_without_entitled_tenants() -> None:
    session = SimpleNamespace(scalars=AsyncMock())
    settings = SimpleNamespace(seo_competitor_scheduler_max_per_run=50)
    with (
        patch("app.seo_monitoring_jobs.get_settings", return_value=settings),
        patch(
            "app.seo_monitoring_jobs.list_active_module_tenants",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.seo_monitoring_jobs.async_session_factory",
            return_value=_SessionContext(session),
        ),
    ):
        result = asyncio.run(collect_scheduled_competitors())

    assert result == {"checked": 0, "created": 0, "failed": 0}
    session.scalars.assert_not_awaited()


def test_scheduled_competitors_filter_to_entitled_tenants() -> None:
    session = SimpleNamespace(scalars=AsyncMock(return_value=[]))
    settings = SimpleNamespace(seo_competitor_scheduler_max_per_run=50)
    with (
        patch("app.seo_monitoring_jobs.get_settings", return_value=settings),
        patch(
            "app.seo_monitoring_jobs.list_active_module_tenants",
            new=AsyncMock(return_value=[SimpleNamespace(id=7)]),
        ),
        patch(
            "app.seo_monitoring_jobs.async_session_factory",
            return_value=_SessionContext(session),
        ),
    ):
        result = asyncio.run(collect_scheduled_competitors())

    assert result == {"checked": 0, "created": 0, "failed": 0}
    statement = session.scalars.await_args.args[0]
    assert "seo_competitors.tenant_id IN" in str(statement)
    assert statement.compile().params["tenant_id_1"] == [7]


def test_scheduled_backlinks_skip_queries_without_entitled_tenants() -> None:
    session = SimpleNamespace(scalars=AsyncMock())
    settings = SimpleNamespace(seo_backlink_scheduler_max_per_run=200)
    with (
        patch("app.seo_monitoring_jobs.get_settings", return_value=settings),
        patch(
            "app.seo_monitoring_jobs.list_active_module_tenants",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.seo_monitoring_jobs.async_session_factory",
            return_value=_SessionContext(session),
        ),
    ):
        result = asyncio.run(verify_scheduled_backlinks())

    assert result == {"checked": 0, "found": 0, "lost": 0, "failed": 0}
    session.scalars.assert_not_awaited()


def test_scheduled_backlinks_filter_to_entitled_tenants() -> None:
    session = SimpleNamespace(scalars=AsyncMock(return_value=[]))
    settings = SimpleNamespace(seo_backlink_scheduler_max_per_run=200)
    with (
        patch("app.seo_monitoring_jobs.get_settings", return_value=settings),
        patch(
            "app.seo_monitoring_jobs.list_active_module_tenants",
            new=AsyncMock(return_value=[SimpleNamespace(id=11)]),
        ),
        patch(
            "app.seo_monitoring_jobs.async_session_factory",
            return_value=_SessionContext(session),
        ),
    ):
        result = asyncio.run(verify_scheduled_backlinks())

    assert result == {"checked": 0, "found": 0, "lost": 0, "failed": 0}
    statement = session.scalars.await_args.args[0]
    assert "seo_backlinks.tenant_id IN" in str(statement)
    assert statement.compile().params["tenant_id_1"] == [11]


def test_scheduled_competitors_persist_one_tenant_run_summary() -> None:
    candidate = SimpleNamespace(
        id=21,
        tenant_id=7,
        site_id=3,
        domain="competitor.example",
        status="active",
        last_checked_at=None,
    )
    session = SimpleNamespace(
        scalars=AsyncMock(side_effect=[[candidate], []]),
        get=AsyncMock(return_value=candidate),
        add=lambda _row: None,
        commit=AsyncMock(),
    )
    settings = SimpleNamespace(seo_competitor_scheduler_max_per_run=50)
    finish_run = AsyncMock()
    with (
        patch("app.seo_monitoring_jobs.get_settings", return_value=settings),
        patch(
            "app.seo_monitoring_jobs.list_active_module_tenants",
            new=AsyncMock(return_value=[SimpleNamespace(id=7)]),
        ),
        patch(
            "app.seo_monitoring_jobs.async_session_factory",
            return_value=_SessionContext(session),
        ),
        patch(
            "app.seo_monitoring_jobs.collect_competitor_content",
            new=AsyncMock(return_value=SimpleNamespace(pages=[])),
        ),
        patch(
            "app.seo_monitoring_jobs.start_automation_run",
            new=AsyncMock(return_value=81),
        ) as start_run,
        patch(
            "app.seo_monitoring_jobs.finish_automation_run",
            new=finish_run,
        ),
    ):
        result = asyncio.run(collect_scheduled_competitors())

    assert result == {"checked": 1, "created": 0, "failed": 0}
    start_run.assert_awaited_once_with(
        tenant_id=7,
        job_type="competitor",
        planned_count=1,
    )
    finish_run.assert_awaited_once_with(
        81,
        planned_count=1,
        success_count=1,
        failed_count=0,
        skipped_count=0,
        error_summary="",
    )


def test_scheduled_backlinks_persist_one_tenant_run_summary() -> None:
    candidate = SimpleNamespace(
        id=31,
        tenant_id=11,
        site_id=4,
        source_url="https://partner.example/article",
        target_url="https://brand.example/target",
        status="active",
        last_checked_at=None,
        last_seen_at=None,
        missing_checks=0,
    )
    session = SimpleNamespace(
        scalars=AsyncMock(return_value=[candidate]),
        get=AsyncMock(return_value=candidate),
        commit=AsyncMock(),
    )
    settings = SimpleNamespace(seo_backlink_scheduler_max_per_run=200)
    fetch_result = SimpleNamespace(
        error_type=None,
        body='<a href="https://brand.example/target">Brand</a>',
        final_url=candidate.source_url,
    )
    finish_run = AsyncMock()
    with (
        patch("app.seo_monitoring_jobs.get_settings", return_value=settings),
        patch(
            "app.seo_monitoring_jobs.list_active_module_tenants",
            new=AsyncMock(return_value=[SimpleNamespace(id=11)]),
        ),
        patch(
            "app.seo_monitoring_jobs.async_session_factory",
            return_value=_SessionContext(session),
        ),
        patch("app.seo_monitoring_jobs.fetch_url", new=AsyncMock(return_value=fetch_result)),
        patch(
            "app.seo_monitoring_jobs.start_automation_run",
            new=AsyncMock(return_value=91),
        ) as start_run,
        patch(
            "app.seo_monitoring_jobs.finish_automation_run",
            new=finish_run,
        ),
    ):
        result = asyncio.run(verify_scheduled_backlinks())

    assert result == {"checked": 1, "found": 1, "lost": 0, "failed": 0}
    start_run.assert_awaited_once_with(
        tenant_id=11,
        job_type="backlink",
        planned_count=1,
    )
    finish_run.assert_awaited_once_with(
        91,
        planned_count=1,
        success_count=1,
        failed_count=0,
        skipped_count=0,
        error_summary="",
    )
