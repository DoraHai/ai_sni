import asyncio
import os
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import text

from app.models.seo import SeoAutomationRun, SeoCrawlRun, SeoAiOperation
from app.security.auth import AuthContext
from app.seo_task_center import list_task_center, planned_checks
from app.api.seo import recover_seo_ai_operation, retry_seo_task, ManualAutomationTriggerRequest


def context(permissions=None, tenant=1, user=7):
    return AuthContext(user_id=user, username="operator", role_name="运营", tenant_id=tenant,
        permissions=permissions if permissions is not None else {f"seo.{key}": "edit" for key in
        ["dashboard", "keywords", "content", "site", "competitors", "links"]})


@pytest.mark.skipif(not os.getenv("SEO_USAGE_TEST_DATABASE_URL"), reason="requires isolated PostgreSQL")
def test_task_history_filters_tenant_site_permission_actor_and_pages():
    from test_seo_ai_operations import database

    async def scenario():
        async with database() as (sessions, _):
            async with sessions() as session:
                for table in ["seo_automation_runs", "seo_crawl_runs"]:
                    await session.execute(text(f"CREATE TABLE {table} (LIKE public.{table} INCLUDING ALL)"))
                now = datetime.utcnow()
                session.add_all([
                    SeoAutomationRun(id=1, tenant_id=1, site_id=10, job_type="ranking", trigger_type="manual", status="failed", planned_count=5, failed_count=5, started_at=now),
                    SeoAutomationRun(id=2, tenant_id=1, site_id=20, job_type="ranking", trigger_type="manual", status="failed", started_at=now),
                    SeoAutomationRun(id=3, tenant_id=2, site_id=10, job_type="ranking", trigger_type="manual", status="failed", started_at=now),
                    SeoAutomationRun(id=4, tenant_id=1, site_id=None, job_type="ranking", trigger_type="scheduled", status="partial", started_at=now),
                    SeoCrawlRun(id=1, tenant_id=1, site_id=10, status="completed", seed_url="https://example.com", max_urls=20, started_at=now),
                ])
                for id, actor, age in [("mine", "7", 1), ("another-user", "8", 1), ("expired", "7", 31)]:
                    session.add(SeoAiOperation(id=id, tenant_id=1, site_id=10, request_key=id, request_hash="hash", actor=actor,
                        kind="content_assist", charged_on=now.date().isoformat(), status="succeeded", result={"title": id},
                        created_at=now, completed_at=now - timedelta(days=age), expires_at=now))
                await session.commit()
            async with sessions() as session:
                result = await list_task_center(session, 1, 10, context(), page_size=20)
                assert result["total"] == 5
                assert {row["id"] for row in result["items"] if row["source"] == "automation"} == {"1", "4"}
                assert next(row for row in result["items"] if row["id"] == "4")["retry_site_id"] == 10
                assert next(row for row in result["items"] if row["id"] == "mine")["has_result"] is True
                assert next(row for row in result["items"] if row["id"] == "expired")["has_result"] is False
                assert result["summary"]["expired"] == 1
                only_ai = await list_task_center(session, 1, 10, context({"seo.dashboard": "view", "seo.content": "view"}), page_size=1)
                assert only_ai["total"] == 2 and len(only_ai["items"]) == 1
                assert only_ai["items"][0]["source"] == "ai"
                filtered = await list_task_center(session, 1, 10, context(), kind="ranking", status="failed")
                assert filtered["total"] == 1
                assert filtered["items"][0]["can_retry"] is True
                read_only = await list_task_center(session, 1, 10, context({"seo.dashboard": "view", "seo.keywords": "view"}))
                assert not any(row["can_retry"] for row in read_only["items"])
                assert await recover_seo_ai_operation("mine", 1, session, context()) == {"title": "mine"}
                with pytest.raises(HTTPException) as exc:
                    await recover_seo_ai_operation("another-user", 1, session, context())
                assert exc.value.status_code == 404
                with pytest.raises(HTTPException) as exc:
                    await recover_seo_ai_operation("expired", 1, session, context())
                assert exc.value.detail["code"] == "operation_result_expired"
    asyncio.run(scenario())


@pytest.mark.parametrize("status,site,expected", [("failed",10,202),("running",10,409),("failed",20,404)])
def test_task_retry_reuses_existing_bounded_trigger(status, site, expected):
    session = AsyncMock()
    session.scalar.return_value = SimpleNamespace(status=status, site_id=site)
    req = ManualAutomationTriggerRequest(tenant_id=1, site_id=10, job_type="ranking")
    trigger = AsyncMock(return_value={"message": "queued"})
    with patch("app.api.seo.trigger_seo_automation_run", new=trigger):
        if expected == 202:
            assert asyncio.run(retry_seo_task(1, req, BackgroundTasks(), session, context())) == {"message": "queued"}
            trigger.assert_awaited_once()
        else:
            with pytest.raises(HTTPException) as exc:
                asyncio.run(retry_seo_task(1, req, BackgroundTasks(), session, context()))
            assert exc.value.status_code == expected
            trigger.assert_not_awaited()


def test_task_retry_requires_both_dashboard_and_job_edit_access():
    session = AsyncMock()
    req = ManualAutomationTriggerRequest(tenant_id=1, site_id=10, job_type="ranking")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(retry_seo_task(1, req, BackgroundTasks(), session, context({"seo.dashboard":"edit", "seo.keywords":"view"})))
    assert exc.value.status_code == 403
    session.scalar.assert_not_awaited()


def test_next_check_is_timezone_aware_and_permission_filtered():
    schedules = planned_checks(SimpleNamespace(seo_rank_scheduler_hour=6, seo_rank_scheduler_minute=20), context({"seo.keywords": "view"}))
    assert len(schedules) == 1 and schedules[0]["job_type"] == "ranking"
    assert schedules[0]["next_check_at"].endswith("+08:00")
    assert "06:20:00" in schedules[0]["next_check_at"]
