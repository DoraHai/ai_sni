import asyncio
import os
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "1234567890abcdefsecret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from sqlalchemy.dialects import postgresql
from app.rules.writeback_health import alert_record, refresh_writeback_alerts
from app.scheduler import check_writeback_health, start_scheduler


def row(**kw):
    return SimpleNamespace(**(dict(id=7, created_at=datetime(2026, 9, 4, 23, 58),
        campaign_id=2, campaign_name="test", baidu_account_id=9,
        action_type="set_account_budget", status="pending") | kw))


def test_identity_is_stable_and_table_specific_and_errors_are_not_exposed():
    source = row(error_msg="secret-api-response")
    first = alert_record(3, "bid", source, 900)
    later = alert_record(3, "bid", source, 86400)
    assert first["entity_ref"] == later["entity_ref"] == "writeback:bid:7"
    assert first["report_date"] == later["report_date"]
    assert alert_record(3, "action", source, 0)["entity_ref"] != first["entity_ref"]
    assert first["metrics"]["age_minutes"] == 15
    assert first["metrics"]["baidu_account_id"] == 9
    assert "secret-api-response" not in str(first)
    assert "改账户日预算" in alert_record(3, "action", source, 0)["message"]


async def rows(items):
    for item in items:
        yield item


def test_queries_exclude_dry_run_scope_tenant_and_close_only_completed_sources():
    async def run():
        session = SimpleNamespace(stream=AsyncMock(side_effect=[rows([(row(), 900)]), rows([])]),
                                  execute=AsyncMock())
        assert await refresh_writeback_alerts(session, 3) == 1
        for call in session.stream.call_args_list:
            compiled = call.args[0].compile(dialect=postgresql.dialect())
            sql = str(compiled)
            assert "dry_run IS false" in sql
            assert "created_at <=" in sql and " OR " in sql
            assert "tenant_id =" in sql
            assert 3 in compiled.params.values()
        statements = [str(c.args[0].compile(dialect=postgresql.dialect()))
                      for c in session.execute.call_args_list]
        assert "ON CONFLICT" in statements[0]
        assert "resolved_at =" in statements[0]
        for sql in statements[1:]:
            assert "NOT (EXISTS" in sql
            assert "tenant_id = alerts.tenant_id" in sql
            assert "dry_run IS false" in sql
            assert "rule_code =" in sql
    asyncio.run(run())


def test_scheduler_runs_every_five_minutes_without_overlap():
    with patch("app.scheduler._acquire_scheduler_lock", return_value=True), \
         patch("app.scheduler.scheduler.add_job") as add, \
         patch("app.scheduler.scheduler.start"):
        start_scheduler()
    job = next(c for c in add.call_args_list if c.kwargs.get("id") == "check_writeback_health")
    assert "minute='*/5'" in str(job.args[1])
    assert job.kwargs["max_instances"] == 1 and job.kwargs["coalesce"]


def test_one_tenant_failure_does_not_block_next_tenant():
    class Session:
        def __init__(self):
            self.commit = AsyncMock()
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
    async def run():
        sessions = [Session(), Session(), Session()]
        refresh = AsyncMock(side_effect=[RuntimeError("test failure"), 1])
        with patch("app.scheduler.async_session_factory", side_effect=sessions), \
             patch("app.scheduler.list_active_module_tenants", new=AsyncMock(return_value=[
                 SimpleNamespace(id=3), SimpleNamespace(id=4)])), \
             patch("app.rules.writeback_health.refresh_writeback_alerts", new=refresh):
            await check_writeback_health()
        assert [c.args[1] for c in refresh.call_args_list] == [3, 4]
        sessions[1].commit.assert_not_awaited()
        sessions[2].commit.assert_awaited_once()
    asyncio.run(run())
