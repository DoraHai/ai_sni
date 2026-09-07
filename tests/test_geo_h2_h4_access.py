import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException

from app.geo.content import routes
from app.geo.content.delivery_recovery import DeliveryResolution
from app.geo.content.schemas import (
    ChannelAccountCreate,
    PublicationCreate,
    PublishingChannelCreate,
    PushBatchRequest,
    WebhookPushRequest,
)
from app.geo.tenant_scope import require_geo_read_entitlement


ENTITLEMENT_QUERY_ROUTES = {
    ("/content-tasks/{task_id}/article", "PUT"),
    ("/content-tasks/{task_id}/check", "POST"),
    ("/content-tasks/{task_id}/variants", "POST"),
    ("/content-tasks/{task_id}/variants/{channel}", "PATCH"),
    ("/content-tasks/{task_id}/export", "GET"),
    ("/content-tasks/{task_id}/export", "POST"),
    ("/content-tasks/{task_id}/submit-review", "POST"),
    ("/content-tasks/{task_id}/review", "POST"),
    ("/content-tasks/{task_id}/deliveries", "GET"),
    ("/content-tasks/{task_id}/push-targets", "GET"),
    ("/content-tasks/{task_id}/publication-monitor", "GET"),
    ("/content-tasks/{task_id}/publication-monitor/{publication_id}/check", "POST"),
    ("/publishing-channels", "GET"),
    ("/publishing-channels/enable-multi-media-auto", "POST"),
    ("/publishing-channels/{channel_id}", "DELETE"),
    ("/publishing-channels/{channel_id}", "PATCH"),
    ("/channel-accounts", "GET"),
    ("/channel-accounts/{account_id}", "PATCH"),
    ("/channel-accounts/{account_id}", "DELETE"),
    ("/channel-accounts/{account_id}/verify-social", "POST"),
    ("/oauth/social/start", "POST"),
    ("/oauth/social/refresh", "POST"),
}


def test_h2_h4_query_routes_use_authoritative_geo_entitlement():
    found = set()
    for route in routes.router.routes:
        for method in route.methods or set():
            key = (route.path, method)
            if key not in ENTITLEMENT_QUERY_ROUTES:
                continue
            found.add(key)
            assert any(
                dependency.call is require_geo_read_entitlement
                for dependency in route.dependant.dependencies
            ), key
    assert found == ENTITLEMENT_QUERY_ROUTES


@pytest.mark.parametrize(
    ("operation", "payload"),
    [
        (
            routes.record_publication,
            PublicationCreate(
                tenant_id=7,
                channel="website",
                published_url="https://example.com/article",
            ),
        ),
        (
            routes.push_variant_webhook,
            WebhookPushRequest(tenant_id=7, channel="website", account_id=3),
        ),
        (routes.push_variant_batch, PushBatchRequest(tenant_id=7)),
    ],
)
def test_body_tenant_publish_routes_reject_unavailable_geo_before_task_lookup(
    operation, payload
):
    session = NS()
    context = NS(ensure_tenant=Mock())
    denied = AsyncMock(side_effect=HTTPException(403, "GEO unavailable"))
    lookup = AsyncMock()
    kwargs = {"ctx": context, "session": session}
    if operation is routes.push_variant_batch:
        kwargs.update(run_async=True, background_tasks=None)
    with patch.object(routes, "ensure_geo_entitlement", denied), patch.object(
        routes, "_get_task", lookup
    ), pytest.raises(HTTPException) as error:
        asyncio.run(operation(14, payload, **kwargs))
    assert error.value.status_code == 403
    context.ensure_tenant.assert_called_once_with(7)
    denied.assert_awaited_once_with(session, 7)
    lookup.assert_not_awaited()


@pytest.mark.parametrize("case", ["create_channel", "create_account", "resolve_delivery"])
def test_body_tenant_configuration_and_recovery_routes_fail_closed(case):
    session = NS()
    context = NS(ensure_tenant=Mock(), user_id=9)
    denied = AsyncMock(side_effect=HTTPException(403, "GEO unavailable"))
    channel_lookup = AsyncMock()
    task_lookup = AsyncMock()
    with patch.object(routes, "ensure_geo_entitlement", denied), patch.object(
        routes, "_get_publishing_channel", channel_lookup
    ), patch.object(routes, "_get_task", task_lookup), pytest.raises(HTTPException):
        if case == "create_channel":
            operation = routes.create_publishing_channel(
                PublishingChannelCreate(
                    tenant_id=7, name="官网", channel_type="website"
                ),
                context,
                session,
            )
        elif case == "create_account":
            operation = routes.create_channel_account(
                ChannelAccountCreate(
                    tenant_id=7, channel_id=3, display_name="测试账号"
                ),
                context,
                session,
            )
        else:
            operation = routes.resolve_task_delivery(
                14,
                2,
                "delivery-key",
                DeliveryResolution(
                    tenant_id=7,
                    action="allow_retry",
                    note="已人工核对渠道后台没有文章",
                    confirmed_not_published=True,
                ),
                context,
                session,
            )
        asyncio.run(operation)
    context.ensure_tenant.assert_called_once_with(7)
    denied.assert_awaited_once_with(session, 7)
    channel_lookup.assert_not_awaited()
    task_lookup.assert_not_awaited()


def test_push_targets_is_read_only_and_explains_zero_accounts():
    task = NS(id=14, review_status="approved")
    variant = NS(channel="website", status="exported", body_markdown="正文")
    virtual_channel = NS(
        id=None,
        name="官网",
        channel_type="website",
        publish_mode="auto_publish",
        enabled=True,
        sort_order=0,
    )
    session = NS(
        scalars=AsyncMock(return_value=[]),
        commit=AsyncMock(),
        flush=AsyncMock(),
        add=Mock(),
        add_all=Mock(),
    )
    context = NS(ensure_tenant=Mock())
    with patch.object(routes, "_get_task", AsyncMock(return_value=task)), patch.object(
        routes, "_publishing_channel_view_rows", AsyncMock(return_value=[virtual_channel])
    ), patch.object(routes, "_variants", AsyncMock(return_value=[variant])):
        result = asyncio.run(routes.list_task_push_targets(14, 7, context, session))

    assert result["ready_count"] == 0
    assert result["ready_targets"] == []
    assert len(result["targets"]) == 1
    assert result["targets"][0]["channel_id"] is None
    assert result["targets"][0]["block_reasons"] == ["缺少 webhook 账号+凭证"]
    session.commit.assert_not_awaited()
    session.flush.assert_not_awaited()
    session.add.assert_not_called()
    session.add_all.assert_not_called()
