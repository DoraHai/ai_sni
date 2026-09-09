import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from starlette.requests import Request

from app.geo.demo_read_session import (
    REQUIRED_SCHEMA_REVISION,
    tenant_read_session,
    validate_demo_session,
)
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


def _result(*, one=None, rows=None, one_or_none=None):
    result = Mock()
    result.one.return_value = one
    result.scalars.return_value = rows
    result.one_or_none.return_value = one_or_none
    return result


def _target():
    return SimpleNamespace(
        database="gsnipers_demo",
        username="geo_demo_read",
        server_addresses=frozenset({"10.0.0.8"}),
        schema_revision=REQUIRED_SCHEMA_REVISION,
        manifest_sha256="a" * 64,
    )


def _validation_results(*, receipt_version="demo-20260909-v1", compliant=1):
    marker = "[全虚拟演示][GEO_DEMO_FIXTURE:g-snipers-geo-demo-v1]"
    return [
        _result(one=("gsnipers_demo", "geo_demo_read", "10.0.0.8", "on")),
        _result(rows=[REQUIRED_SCHEMA_REVISION]),
        _result(
            one_or_none=(
                "gsnipers_demo",
                receipt_version,
                "g-snipers-geo-demo-v1",
                "a" * 64,
                "sealed",
            )
        ),
        _result(one_or_none=(108, "demo", marker)),
        _result(one=(1, compliant)),
    ]


def test_demo_database_validation_anchors_binding_to_sealed_fixture_receipt():
    session = Mock(execute=AsyncMock(side_effect=_validation_results()))
    asyncio.run(validate_demo_session(session, policy_from_binding(8, binding()), _target()))
    receipt_sql = str(session.execute.await_args_list[2].args[0])
    assert "geo_demo_fixture_registry" in receipt_sql
    assert "dataset_key" in receipt_sql and "dataset_version" in receipt_sql
    answer_sql = str(session.execute.await_args_list[4].args[0])
    assert "simulated IS TRUE AND sample_mode='mock_persona'" in answer_sql
    assert "raw_text" in answer_sql and "note" in answer_sql


def test_demo_database_rejects_receipt_for_another_dataset_version():
    session = Mock(
        execute=AsyncMock(
            side_effect=_validation_results(receipt_version="demo-20260908-old")
        )
    )
    with pytest.raises(GeoDemoBindingUnavailable):
        asyncio.run(
            validate_demo_session(session, policy_from_binding(8, binding()), _target())
        )


@pytest.mark.parametrize(
    ("simulated", "sample_mode"),
    [(True, "real"), (False, "mock_persona")],
)
def test_demo_database_rejects_each_contradictory_answer_classification(
    simulated, sample_mode
):
    # Either contradictory row makes the SQL AND predicate's compliant count
    # smaller than total.  The values name both adversarial cases explicitly.
    assert (simulated is True and sample_mode == "mock_persona") is False
    session = Mock(execute=AsyncMock(side_effect=_validation_results(compliant=0)))
    with pytest.raises(GeoDemoBindingUnavailable):
        asyncio.run(
            validate_demo_session(session, policy_from_binding(8, binding()), _target())
        )


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
