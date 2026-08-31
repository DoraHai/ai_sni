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
