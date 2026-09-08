import asyncio
import json
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.geo.routes import router
from app.geo.tenant_scope import require_geo_request_entitlement


def request(*, query: str = "", payload=None) -> Request:
    body = b"" if payload is None else json.dumps(payload).encode()
    headers = [] if payload is None else [(b"content-type", b"application/json")]
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/geo/content-tasks/12/generate",
            "query_string": query.encode(),
            "headers": headers,
        },
        receive,
    )


def test_geo_router_applies_entitlement_to_all_customer_routes():
    for route in router.routes:
        assert any(
            dependency.call is require_geo_request_entitlement
            for dependency in route.dependant.dependencies
        ), route.path


def test_query_tenant_is_checked_before_the_route_runs():
    ctx = Mock()
    session = Mock(scalar=AsyncMock(return_value=object()))
    result = asyncio.run(
        require_geo_request_entitlement(
            request=request(query="tenant_id=15"), ctx=ctx, session=session
        )
    )
    assert result is ctx
    ctx.ensure_tenant.assert_called_once_with(15)
    session.scalar.assert_awaited_once()


def test_json_body_tenant_is_checked_without_consuming_route_semantics():
    ctx = Mock()
    session = Mock(scalar=AsyncMock(return_value=object()))
    req = request(payload={"tenant_id": 16, "title": "draft"})
    asyncio.run(require_geo_request_entitlement(request=req, ctx=ctx, session=session))
    assert asyncio.run(req.json()) == {"tenant_id": 16, "title": "draft"}
    ctx.ensure_tenant.assert_called_once_with(16)


def test_conflicting_query_and_body_tenants_cannot_bypass_either_check():
    ctx = Mock()
    session = Mock(scalar=AsyncMock(side_effect=[object(), None]))
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            require_geo_request_entitlement(
                request=request(query="tenant_id=15", payload={"tenant_id": 16}),
                ctx=ctx,
                session=session,
            )
        )
    assert error.value.status_code == 403
    assert [call.args[0] for call in ctx.ensure_tenant.call_args_list] == [15, 16]


def test_routes_without_customer_context_do_not_issue_entitlement_queries():
    ctx = Mock()
    session = Mock(scalar=AsyncMock())
    assert asyncio.run(
        require_geo_request_entitlement(request=request(), ctx=ctx, session=session)
    ) is ctx
    ctx.ensure_tenant.assert_not_called()
    session.scalar.assert_not_awaited()
