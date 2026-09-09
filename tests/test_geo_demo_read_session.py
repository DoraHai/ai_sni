import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from starlette.requests import Request

from app.geo.demo_read_session import tenant_read_session
from app.geo.demo_tenant import GeoDemoBindingUnavailable, policy_from_binding
from app.geo.read_routes import get_demo_summary


def binding():
    return {
        "tenant_id": 8,
        "demo_tenant_id": 108,
        "dataset_key": "gsnipers_demo",
        "dataset_version": "demo-20260909-v1",
        "status": "active",
        "version": 1,
    }


def request():
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/geo/integration/read/answers",
            "query_string": b"tenant_id=8",
            "headers": [],
        }
    )


def test_demo_session_never_falls_back_when_target_open_fails():
    ctx = Mock()
    control = Mock(scalar=AsyncMock(return_value=binding()))
    primary_opened = False

    async def forbidden_primary():
        nonlocal primary_opened
        primary_opened = True
        yield None

    async def consume():
        async for _session in tenant_read_session(request(), 8, ctx, control):
            raise AssertionError("unreachable")

    with patch(
        "app.geo.demo_read_session.resolve_demo_database_target",
        side_effect=GeoDemoBindingUnavailable("unavailable"),
    ), patch("app.geo.demo_read_session.production_read_session", forbidden_primary):
        with pytest.raises(GeoDemoBindingUnavailable):
            asyncio.run(consume())
    assert not primary_opened
    ctx.ensure_tenant.assert_called_once_with(8)


def test_demo_session_yields_verified_read_only_source_and_translated_tenant():
    ctx = Mock()
    control = Mock(scalar=AsyncMock(return_value=binding()))
    target = SimpleNamespace(database_url="redacted", database="gsnipers_demo")
    demo = SimpleNamespace(info={}, execute=AsyncMock(), rollback=AsyncMock())

    @asynccontextmanager
    async def opened(**kwargs):
        assert kwargs == {"autoflush": False}
        yield demo

    def factory(_url):
        return opened

    async def consume():
        async for session in tenant_read_session(request(), 8, ctx, control):
            assert session is demo
            assert session.info["geo_control_tenant_id"] == 8
            assert session.info["geo_data_tenant_id"] == 108

    with patch(
        "app.geo.demo_read_session.resolve_demo_database_target",
        return_value=target,
    ), patch("app.geo.demo_read_session._demo_session_factory", factory), patch(
        "app.geo.demo_read_session.validate_demo_session", AsyncMock()
    ) as validate:
        asyncio.run(consume())
    assert "READ ONLY" in str(demo.execute.await_args.args[0])
    validate.assert_awaited_once()
    demo.rollback.assert_awaited_once()


def test_demo_summary_is_explicitly_synthetic_and_never_official():
    policy = policy_from_binding(8, binding())
    rows = [
        SimpleNamespace(captured_at=datetime(2026, 8, 26), mentions_brand=False),
        SimpleNamespace(captured_at=datetime(2026, 8, 27), mentions_brand=True),
        SimpleNamespace(captured_at=datetime(2026, 9, 2), mentions_brand=True),
        SimpleNamespace(captured_at=datetime(2026, 9, 3), mentions_brand=True),
    ]
    session = SimpleNamespace(
        info={
            "geo_control_tenant_id": 8,
            "geo_data_tenant_id": 108,
            "geo_demo_policy": policy,
        },
        scalars=AsyncMock(return_value=rows),
    )
    result = asyncio.run(
        get_demo_summary(8, date(2026, 9, 7), Mock(), session)
    )
    assert result["official"] is False
    assert result["source_kind"] == "synthetic"
    assert result["excluded_from_official_metrics"] is True
    assert result["exclusion_reason"]["code"] == "demo_tenant"
    assert result["window"]["previous"]["mention_count"] == 1
    assert result["window"]["current"]["mention_count"] == 2
    assert result["trend_7d"]["mention_count"]["change_abs"] == 1
    sql = str(session.scalars.await_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "tenant_id = 108" in sql
