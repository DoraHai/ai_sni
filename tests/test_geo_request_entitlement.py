import asyncio
import json
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.database import get_session
from app.geo.content.oauth_public import router as public_router
from app.geo.routes import router
from app.geo.tenant_scope import require_geo_request_entitlement
from app.security.auth import require_scoped_auth


def request(
    *, query: str = "", payload=None, content_type: str = "application/json"
) -> Request:
    body = b"" if payload is None else json.dumps(payload).encode()
    headers = (
        []
        if payload is None
        else [(b"content-type", content_type.encode("ascii"))]
    )
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


def test_every_authenticated_geo_write_route_exposes_its_tenant_to_the_gate():
    write_methods = {"POST", "PUT", "PATCH", "DELETE"}
    for route in router.routes:
        if not write_methods.intersection(route.methods or set()):
            continue
        query_names = {item.name for item in route.dependant.query_params}
        body_names = {
            field_name
            for item in route.dependant.body_params
            for field_name in getattr(item.type_, "model_fields", {})
        }
        assert "tenant_id" in query_names | body_names, route.path


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


def test_application_suffix_json_body_tenant_is_checked():
    ctx = Mock()
    session = Mock(scalar=AsyncMock(return_value=object()))
    asyncio.run(
        require_geo_request_entitlement(
            request=request(
                payload={"tenant_id": 16, "title": "draft"},
                content_type="application/merge-patch+json; charset=utf-8",
            ),
            ctx=ctx,
            session=session,
        )
    )
    ctx.ensure_tenant.assert_called_once_with(16)


def test_non_application_json_suffix_is_not_treated_as_json():
    ctx = Mock()
    session = Mock(scalar=AsyncMock())
    asyncio.run(
        require_geo_request_entitlement(
            request=request(
                payload={"tenant_id": 16}, content_type="text/vendor+json"
            ),
            ctx=ctx,
            session=session,
        )
    )
    ctx.ensure_tenant.assert_not_called()
    session.scalar.assert_not_awaited()


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


def test_suffix_json_expired_tenant_is_rejected_before_real_handler(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    ctx = Mock()
    session = Mock(scalar=AsyncMock(return_value=None))
    app.dependency_overrides[require_scoped_auth] = lambda: ctx
    app.dependency_overrides[get_session] = lambda: session
    handler = AsyncMock()
    monkeypatch.setattr("app.geo.routes.audit_url", handler)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/geo/audits",
            content=json.dumps({"tenant_id": 16, "url": "https://example.com"}),
            headers={"content-type": "application/merge-patch+json"},
        )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "geo_not_available"
    ctx.ensure_tenant.assert_called_once_with(16)
    handler.assert_not_awaited()


def test_authenticated_static_route_needs_no_tenant_entitlement_lookup():
    app = FastAPI()
    app.include_router(router)
    ctx = Mock()
    session = Mock(scalar=AsyncMock())
    app.dependency_overrides[require_scoped_auth] = lambda: ctx
    app.dependency_overrides[get_session] = lambda: session

    with TestClient(app) as client:
        response = client.get("/api/v1/geo/content-brief-catalog")

    assert response.status_code == 200
    ctx.ensure_tenant.assert_not_called()
    session.scalar.assert_not_awaited()


def test_public_routes_remain_outside_authenticated_entitlement_router():
    for route in public_router.routes:
        dependency_calls = {item.call for item in route.dependant.dependencies}
        assert require_scoped_auth not in dependency_calls, route.path
        assert require_geo_request_entitlement not in dependency_calls, route.path
