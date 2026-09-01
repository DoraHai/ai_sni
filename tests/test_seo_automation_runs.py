import asyncio
import os
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "test-secret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00+00:00")
os.environ.setdefault(
    "CRYPTO_MASTER_KEY_B64",
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
)
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")


from app.api.seo import _automation_run_payload, list_seo_automation_runs
from app.seo_automation_runs import (
    automation_run_status,
    finish_automation_run,
    start_automation_run,
)


class _SessionContext:
    def __init__(self, session: SimpleNamespace) -> None:
        self.session = session

    async def __aenter__(self) -> SimpleNamespace:
        return self.session

    async def __aexit__(self, *_args: object) -> bool:
        return False


def _row(**overrides: object) -> SimpleNamespace:
    values = {
        "id": 9,
        "tenant_id": 7,
        "site_id": None,
        "job_type": "ranking",
        "trigger_type": "scheduled",
        "status": "completed",
        "planned_count": 8,
        "success_count": 7,
        "failed_count": 0,
        "skipped_count": 1,
        "error_summary": None,
        "started_at": datetime.utcnow() - timedelta(minutes=5),
        "completed_at": datetime.utcnow(),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_automation_status_distinguishes_completed_partial_and_failed() -> None:
    assert automation_run_status(success_count=3, failed_count=0) == "completed"
    assert automation_run_status(success_count=3, failed_count=1) == "partial"
    assert automation_run_status(success_count=0, failed_count=1) == "failed"


def test_start_automation_run_persists_a_tenant_scoped_summary() -> None:
    session = SimpleNamespace(
        add=MagicMock(),
        commit=AsyncMock(),
        refresh=AsyncMock(side_effect=lambda row: setattr(row, "id", 42)),
    )
    with patch(
        "app.seo_automation_runs.async_session_factory",
        return_value=_SessionContext(session),
    ):
        run_id = asyncio.run(
            start_automation_run(
                tenant_id=7,
                job_type="competitor",
                planned_count=3,
            )
        )

    assert run_id == 42
    row = session.add.call_args.args[0]
    assert row.tenant_id == 7
    assert row.job_type == "competitor"
    assert row.planned_count == 3
    assert row.status == "running"
    session.commit.assert_awaited_once_with()


def test_finish_automation_run_caps_errors_and_marks_partial() -> None:
    row = _row(status="running", completed_at=None)
    session = SimpleNamespace(get=AsyncMock(return_value=row), commit=AsyncMock())
    with patch(
        "app.seo_automation_runs.async_session_factory",
        return_value=_SessionContext(session),
    ):
        asyncio.run(
            finish_automation_run(
                9,
                planned_count=4,
                success_count=3,
                failed_count=1,
                error_summary="x" * 3000,
            )
        )

    assert row.status == "partial"
    assert row.success_count == 3
    assert row.failed_count == 1
    assert len(row.error_summary) == 2000
    assert row.completed_at is not None
    session.commit.assert_awaited_once_with()


def test_payload_marks_old_running_jobs_as_stale() -> None:
    payload = _automation_run_payload(
        _row(
            status="running",
            started_at=datetime.utcnow() - timedelta(hours=3),
            completed_at=None,
        )
    )

    assert payload["stale"] is True
    assert payload["started_at"].endswith("Z")


def test_list_automation_runs_is_tenant_scoped_and_returns_latest_by_job() -> None:
    row = _row()
    session = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(id=7)),
        scalars=AsyncMock(return_value=[row]),
    )

    result = asyncio.run(
        list_seo_automation_runs(
            tenant_id=7,
            site_id=None,
            job_type=None,
            limit=30,
            session=session,
        )
    )

    statement = session.scalars.await_args.args[0]
    assert "seo_automation_runs.tenant_id" in str(statement)
    assert statement.compile().params["tenant_id_1"] == 7
    assert result["items"][0]["id"] == 9
    assert result["latest_by_job"]["ranking"]["id"] == 9
