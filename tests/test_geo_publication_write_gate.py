import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.geo.content import routes
from app.geo.content.gate import PublishGateError


def test_publication_write_rechecks_fresh_article_and_brand_under_lock():
    task = NS(id=12, tenant_id=7, review_status="approved", business_id=20)
    variant = NS(id=3, task_id=12, article_version_id=16, status="draft")
    article = NS(id=16)
    session = NS(refresh=AsyncMock(), scalar=AsyncMock(), add=Mock(), flush=AsyncMock())
    latest = AsyncMock(return_value=article)
    build = AsyncMock(return_value=object())
    tenant = NS(id=7, name="租户名")
    ensure = AsyncMock(return_value=tenant)
    brand = AsyncMock(return_value=("新品牌", ["新品牌"]))

    with (
        patch.object(routes, "_latest_article", latest),
        patch.object(routes, "_build_rule_input", build),
        patch.object(routes, "_ensure_tenant_exists", ensure),
        patch.object(routes, "_brand_context_for_task", brand),
        patch.object(
            routes,
            "assert_can_publish",
            side_effect=PublishGateError("品牌标准未通过"),
        ),
        pytest.raises(PublishGateError, match="品牌标准未通过"),
    ):
        asyncio.run(
            routes._write_publication(
                session,
                task=task,
                variant=variant,
                channel="website",
                published_url="https://example.com/article",
                note=None,
                publish_mode="manual",
            )
        )

    session.refresh.assert_any_await(task, with_for_update=True)
    session.refresh.assert_any_await(variant, with_for_update=True)
    assert latest.await_args.kwargs["fresh"] is True
    assert build.await_args.kwargs["fresh"] is True
    assert ensure.await_args.kwargs["fresh"] is True
    assert brand.await_args.kwargs["fresh"] is True
    session.add.assert_not_called()
    session.flush.assert_not_awaited()
    assert task.__dict__.get("status") is None
    assert variant.status == "draft"
