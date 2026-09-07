"""Async channel-variant generation must have one reservation per task."""

import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.geo.content.routes import create_variants
from app.geo.content.schemas import VariantsCreate


def _job():
    return NS(id=91, status="pending")


def test_live_variant_job_blocks_a_second_async_request():
    task = NS(id=12, tenant_id=7, status="editing", target_channels=["website"])
    session = NS(
        refresh=AsyncMock(),
        commit=AsyncMock(),
        scalar=AsyncMock(side_effect=[None, 91]),
    )

    async def create_once(*args, **kwargs):
        assert task.status == "adapting"
        await session.commit()
        return _job()

    common = (
        patch("app.geo.content.routes._get_task", AsyncMock(return_value=task)),
        patch("app.geo.content.routes._latest_article", AsyncMock(return_value=NS(id=20))),
        patch("app.geo.content.routes._ensure_default_publishing_channels", AsyncMock()),
        patch("app.geo.content.async_jobs.create_job", AsyncMock(side_effect=create_once)),
        patch("app.geo.content.async_jobs.job_payload", return_value={"id": 91, "status": "pending"}),
    )
    with common[0], common[1], common[2], common[3] as create, common[4]:
        result = asyncio.run(
            create_variants(
                12,
                VariantsCreate(channels=["website"]),
                tenant_id=7,
                run_async=True,
                background_tasks=BackgroundTasks(),
                ctx=NS(user_id=9, ensure_tenant=lambda _: None),
                session=session,
            )
        )
        assert result["job"]["id"] == 91
        task.status = "editing"
        with pytest.raises(HTTPException) as error:
            asyncio.run(
                create_variants(
                    12,
                    VariantsCreate(channels=["website"]),
                    tenant_id=7,
                    run_async=True,
                    background_tasks=BackgroundTasks(),
                    ctx=NS(user_id=9, ensure_tenant=lambda _: None),
                    session=session,
                )
            )

    assert error.value.status_code == 409
    assert "渠道稿正在生成" in str(error.value.detail)
    assert create.await_count == 1
    assert session.refresh.await_count == 2
    assert session.scalar.await_count == 2
    session.commit.assert_awaited_once()
