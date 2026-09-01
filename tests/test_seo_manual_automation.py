import asyncio
import os
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import BackgroundTasks, HTTPException


os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "test-secret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00+00:00")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")


from app.api.seo import ManualAutomationTriggerRequest, trigger_seo_automation_run
from app.seo_manual_automation import (
    ManualAutomationError,
    _run_backlinks,
    _run_competitors,
    execute_manual_automation_run,
    reserve_manual_automation_run,
)


class _SessionContext:
    def __init__(self, session: SimpleNamespace) -> None:
        self.session = session

    async def __aenter__(self) -> SimpleNamespace:
        return self.session

    async def __aexit__(self, *_args: object) -> bool:
        return False


def _site(**overrides: object) -> SimpleNamespace:
    values = {"id": 3, "tenant_id": 7, "status": "active"}
    values.update(overrides)
    return SimpleNamespace(**values)


def _run(**overrides: object) -> SimpleNamespace:
    values = {
        "id": 19,
        "tenant_id": 7,
        "site_id": 3,
        "job_type": "backlink",
        "trigger_type": "manual",
        "status": "queued",
        "planned_count": 2,
        "success_count": 0,
        "failed_count": 0,
        "skipped_count": 0,
        "error_summary": None,
        "requested_by": 11,
        "started_at": datetime.utcnow(),
        "completed_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _reservation_session(*scalar_values: object) -> SimpleNamespace:
    return SimpleNamespace(
        scalar=AsyncMock(side_effect=scalar_values),
        add=MagicMock(),
        commit=AsyncMock(),
        refresh=AsyncMock(side_effect=lambda row: setattr(row, "id", 19)),
    )


def test_reservation_is_site_scoped_queued_and_audited() -> None:
    session = _reservation_session(_site(), None, None)
    settings = SimpleNamespace(seo_manual_automation_cooldown_seconds=3600)
    with (
        patch("app.seo_manual_automation.manual_target_count", AsyncMock(return_value=2)),
        patch("app.seo_manual_automation.get_settings", return_value=settings),
    ):
        row = asyncio.run(
            reserve_manual_automation_run(
                session,
                tenant_id=7,
                site_id=3,
                job_type="backlink",
                requested_by=11,
            )
        )

    site_query = session.scalar.await_args_list[0].args[0]
    assert "seo_sites.id" in str(site_query)
    assert "seo_sites.tenant_id" in str(site_query)
    assert row.status == "queued"
    assert row.tenant_id == 7
    assert row.site_id == 3
    assert row.requested_by == 11
    assert row.planned_count == 2
    session.commit.assert_awaited_once_with()


def test_reservation_rejects_sites_without_targets() -> None:
    session = _reservation_session(_site())
    with patch("app.seo_manual_automation.manual_target_count", AsyncMock(return_value=0)):
        with pytest.raises(ManualAutomationError) as raised:
            asyncio.run(
                reserve_manual_automation_run(
                    session,
                    tenant_id=7,
                    site_id=3,
                    job_type="competitor",
                    requested_by=11,
                )
            )

    assert raised.value.code == "no_targets"
    session.commit.assert_not_awaited()


@pytest.mark.parametrize("status", ["queued", "running"])
def test_reservation_rejects_an_active_duplicate(status: str) -> None:
    latest = _run(status=status, started_at=datetime.utcnow() - timedelta(minutes=5))
    session = _reservation_session(_site(), latest)
    with patch("app.seo_manual_automation.manual_target_count", AsyncMock(return_value=2)):
        with pytest.raises(ManualAutomationError) as raised:
            asyncio.run(
                reserve_manual_automation_run(
                    session,
                    tenant_id=7,
                    site_id=3,
                    job_type="backlink",
                    requested_by=11,
                )
            )

    assert raised.value.code == "run_in_progress"


def test_reservation_rejects_a_tenant_wide_scheduled_run() -> None:
    scheduled = _run(
        site_id=None,
        trigger_type="scheduled",
        status="running",
        started_at=datetime.utcnow() - timedelta(minutes=5),
    )
    session = _reservation_session(_site(), scheduled)
    with patch("app.seo_manual_automation.manual_target_count", AsyncMock(return_value=2)):
        with pytest.raises(ManualAutomationError) as raised:
            asyncio.run(
                reserve_manual_automation_run(
                    session,
                    tenant_id=7,
                    site_id=3,
                    job_type="backlink",
                    requested_by=11,
                )
            )

    assert raised.value.code == "run_in_progress"


def test_successful_run_enforces_cooldown_but_failed_run_can_retry() -> None:
    settings = SimpleNamespace(seo_manual_automation_cooldown_seconds=3600)
    completed = _run(status="completed", started_at=datetime.utcnow() - timedelta(minutes=2))
    blocked_session = _reservation_session(_site(), None, completed)
    with (
        patch("app.seo_manual_automation.manual_target_count", AsyncMock(return_value=2)),
        patch("app.seo_manual_automation.get_settings", return_value=settings),
    ):
        with pytest.raises(ManualAutomationError) as raised:
            asyncio.run(
                reserve_manual_automation_run(
                    blocked_session,
                    tenant_id=7,
                    site_id=3,
                    job_type="backlink",
                    requested_by=11,
                )
            )
    assert raised.value.code == "run_cooldown"
    assert raised.value.status_code == 429
    assert raised.value.retry_after > 0

    failed = _run(status="failed", started_at=datetime.utcnow() - timedelta(seconds=5))
    retry_session = _reservation_session(_site(), None, failed)
    with (
        patch("app.seo_manual_automation.manual_target_count", AsyncMock(return_value=2)),
        patch("app.seo_manual_automation.get_settings", return_value=settings),
    ):
        row = asyncio.run(
            reserve_manual_automation_run(
                retry_session,
                tenant_id=7,
                site_id=3,
                job_type="backlink",
                requested_by=11,
            )
        )
    assert row.status == "queued"


def test_executor_claims_queued_run_once_and_records_result() -> None:
    row = _run(status="running")
    session = SimpleNamespace(get=AsyncMock(return_value=row))
    finish = AsyncMock()
    with (
        patch("app.seo_manual_automation.mark_automation_run_running", AsyncMock(return_value=True)),
        patch("app.seo_manual_automation.async_session_factory", return_value=_SessionContext(session)),
        patch("app.seo_manual_automation._run_backlinks", AsyncMock(return_value=(1, 1, 0, "2:timeout"))),
        patch("app.seo_manual_automation.finish_automation_run", finish),
    ):
        asyncio.run(execute_manual_automation_run(19))

    finish.assert_awaited_once_with(
        19,
        planned_count=2,
        success_count=1,
        failed_count=1,
        skipped_count=0,
        error_summary="2:timeout",
    )


def test_executor_stops_when_another_worker_already_claimed_the_run() -> None:
    factory = MagicMock()
    with (
        patch("app.seo_manual_automation.mark_automation_run_running", AsyncMock(return_value=False)),
        patch("app.seo_manual_automation.async_session_factory", factory),
    ):
        asyncio.run(execute_manual_automation_run(19))
    factory.assert_not_called()


def test_backlink_result_is_not_written_after_asset_url_changes() -> None:
    candidate = SimpleNamespace(
        id=5,
        tenant_id=7,
        site_id=3,
        status="active",
        source_url="https://source.example/page",
        target_url="https://brand.example/landing",
    )
    changed = SimpleNamespace(
        **{
            **candidate.__dict__,
            "source_url": "https://source.example/replaced",
            "missing_checks": 0,
        }
    )
    list_session = SimpleNamespace(scalars=AsyncMock(return_value=[candidate]))
    update_session = SimpleNamespace(get=AsyncMock(return_value=changed), commit=AsyncMock())
    factory = MagicMock(
        side_effect=[_SessionContext(list_session), _SessionContext(update_session)]
    )
    fetch = AsyncMock(
        return_value=SimpleNamespace(
            error_type=None,
            body='<a href="https://brand.example/landing">brand</a>',
            final_url=candidate.source_url,
        )
    )
    with (
        patch("app.seo_manual_automation.async_session_factory", factory),
        patch("app.seo_manual_automation.fetch_url", fetch),
    ):
        result = asyncio.run(_run_backlinks(_run(planned_count=1)))

    assert result[:3] == (0, 0, 1)
    update_session.commit.assert_not_awaited()


def test_competitor_result_is_not_written_after_asset_reassignment() -> None:
    candidate = SimpleNamespace(
        id=6,
        tenant_id=7,
        site_id=3,
        status="active",
        domain="competitor.example",
    )
    first_check = SimpleNamespace(**candidate.__dict__)
    reassigned = SimpleNamespace(**{**candidate.__dict__, "site_id": 4})
    list_session = SimpleNamespace(scalars=AsyncMock(return_value=[candidate]))
    first_session = SimpleNamespace(get=AsyncMock(return_value=first_check), commit=AsyncMock())
    final_session = SimpleNamespace(get=AsyncMock(return_value=reassigned), commit=AsyncMock())
    factory = MagicMock(
        side_effect=[
            _SessionContext(list_session),
            _SessionContext(first_session),
            _SessionContext(final_session),
        ]
    )
    collect = AsyncMock(
        return_value=SimpleNamespace(
            pages=[SimpleNamespace(url="https://competitor.example/news", title="News")]
        )
    )
    with (
        patch("app.seo_manual_automation.async_session_factory", factory),
        patch("app.seo_manual_automation.collect_competitor_content", collect),
    ):
        result = asyncio.run(
            _run_competitors(_run(job_type="competitor", planned_count=1))
        )

    assert result[:3] == (0, 0, 1)
    first_session.commit.assert_awaited_once_with()
    final_session.commit.assert_not_awaited()


def test_trigger_api_queues_background_work_and_preserves_actor() -> None:
    row = _run()
    reserve = AsyncMock(return_value=row)
    background = BackgroundTasks()
    ctx = SimpleNamespace(user_id=11, ensure_tenant=MagicMock())
    with patch("app.api.seo.reserve_manual_automation_run", reserve):
        result = asyncio.run(
            trigger_seo_automation_run(
                ManualAutomationTriggerRequest(
                    tenant_id=7,
                    site_id=3,
                    job_type="backlink",
                ),
                background,
                session=SimpleNamespace(),
                ctx=ctx,
            )
        )

    ctx.ensure_tenant.assert_called_once_with(7)
    assert reserve.await_args.kwargs["requested_by"] == 11
    assert result["run"]["status"] == "queued"
    assert result["run"]["requested_by"] == 11
    assert len(background.tasks) == 1


def test_trigger_api_returns_retry_after_for_cooldown() -> None:
    error = ManualAutomationError("run_cooldown", "请稍后重试", 429, 123)
    background = BackgroundTasks()
    ctx = SimpleNamespace(user_id=11, ensure_tenant=MagicMock())
    with patch("app.api.seo.reserve_manual_automation_run", AsyncMock(side_effect=error)):
        with pytest.raises(HTTPException) as raised:
            asyncio.run(
                trigger_seo_automation_run(
                    ManualAutomationTriggerRequest(
                        tenant_id=7,
                        site_id=3,
                        job_type="ranking",
                    ),
                    background,
                    session=SimpleNamespace(),
                    ctx=ctx,
                )
            )

    assert raised.value.status_code == 429
    assert raised.value.headers == {"Retry-After": "123"}
    assert not background.tasks
