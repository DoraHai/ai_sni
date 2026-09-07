"""H1 generation reservation regressions; no model or customer data."""

import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.geo.content.routes import generate_task_article


def fact(ident):
    return NS(
        id=ident,
        title="产品说明",
        statement="示例产品采用散热壳体。",
        fact_type="product",
        source_name="已核验资料",
        source_url="https://example.invalid/source",
        trust_level="verified",
        status="active",
        author_name="示例作者",
        observed_at=None,
        expires_at=None,
        archived_at=None,
    )


def job():
    return NS(
        id=88,
        tenant_id=7,
        kind="generate_article",
        status="pending",
        ref_type="content_task",
        ref_id=12,
        request_meta={},
        result_meta={},
        error=None,
        created_by=9,
        created_at=None,
        started_at=None,
        finished_at=None,
    )


def test_second_generate_request_is_rejected_before_another_job_is_created():
    task = NS(id=12, tenant_id=7, prompt_id=3, status="editing", brief={
        "industry": "工业传动", "audience": "采购", "intent": "scenario",
        "content_type": "thought_leadership", "cta": "咨询选型",
    })
    session = NS(refresh=AsyncMock(), commit=AsyncMock(), scalar=AsyncMock(side_effect=[None, 88]))
    background = BackgroundTasks()

    async def create_once(*args, **kwargs):
        # The row transition is part of the same unit committed by create_job.
        assert task.status == "generating"
        await session.commit()
        return job()

    with (
        patch("app.geo.content.routes._get_task", AsyncMock(return_value=task)),
        patch("app.geo.content.routes._ensure_tenant_exists", AsyncMock(return_value=NS(id=7, name="示例客户"))),
        patch("app.geo.content.routes._get_prompt", AsyncMock(return_value=NS(id=3, question="产品特点是什么？"))),
        patch("app.geo.content.routes._task_facts", AsyncMock(return_value=[fact(1), fact(2), fact(3)])),
        patch("app.geo.content.evidence.prepare_facts_for_generation", return_value=([], {"ok": True})),
        patch("app.geo.content.async_jobs.create_job", AsyncMock(side_effect=create_once)) as create,
        patch("app.geo.content.async_jobs.job_payload", return_value={"id": 88, "status": "pending"}),
    ):
        first = asyncio.run(generate_task_article(
            12, tenant_id=7, run_async=True, background_tasks=background,
            ctx=NS(user_id=9, ensure_tenant=lambda _: None), session=session,
        ))
        assert first["job"] == {"id": 88, "status": "pending"}
        # A legacy/manual transition must not erase the durable job reservation.
        task.status = "editing"
        with pytest.raises(HTTPException) as error:
            asyncio.run(generate_task_article(
                12, tenant_id=7, run_async=True, background_tasks=BackgroundTasks(),
                ctx=NS(user_id=9, ensure_tenant=lambda _: None), session=session,
            ))

    assert error.value.status_code == 409
    assert "正在生成" in str(error.value.detail)
    assert create.await_count == 1
    assert session.scalar.await_count == 2
    assert session.refresh.await_count == 2
    assert all(call.kwargs == {"with_for_update": True} for call in session.refresh.await_args_list)
    session.commit.assert_awaited_once()


def test_failed_evidence_never_claims_generation_or_creates_a_job():
    task = NS(id=12, tenant_id=7, prompt_id=3, status="editing", brief={
        "industry": "工业传动", "audience": "采购", "intent": "scenario",
        "content_type": "thought_leadership", "cta": "咨询选型",
    })
    session = NS(refresh=AsyncMock(), commit=AsyncMock(), scalar=AsyncMock())
    with (
        patch("app.geo.content.routes._get_task", AsyncMock(return_value=task)),
        patch("app.geo.content.routes._ensure_tenant_exists", AsyncMock(return_value=NS(id=7, name="示例客户"))),
        patch("app.geo.content.routes._get_prompt", AsyncMock(return_value=NS(id=3, question="产品特点是什么？"))),
        patch("app.geo.content.routes._task_facts", AsyncMock(return_value=[])),
        patch("app.geo.content.evidence.prepare_facts_for_generation", return_value=([], {"ok": False, "eligible_count": 0, "minimum": 3})),
        patch("app.geo.content.async_jobs.create_job", AsyncMock()) as create,
    ):
        with pytest.raises(HTTPException) as error:
            asyncio.run(generate_task_article(
                12, tenant_id=7, run_async=True, background_tasks=BackgroundTasks(),
                ctx=NS(user_id=9, ensure_tenant=lambda _: None), session=session,
            ))
    assert error.value.status_code == 400
    assert task.status == "editing"
    session.refresh.assert_not_awaited()
    session.commit.assert_not_awaited()
    create.assert_not_awaited()
