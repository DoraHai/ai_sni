from __future__ import annotations

from datetime import datetime
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.geo.question_read_routes import (
    build_question_query,
    question_page,
    router,
)
from app.geo.read_routes import read_session as geo_read_session
from app.geo.tenant_scope import require_geo_read_entitlement
from app.models import GeoOptimizationBusiness, GeoOptimizationUnit, GeoPrompt
from app.security.auth import AuthContext, require_scoped_auth


NOW = datetime(2026, 9, 7, 9, 0, 0)


class ReadOnlyFakeSession:
    """Expose only execute: endpoint code cannot accidentally add, flush, or commit."""

    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return type("Rows", (), {"all": lambda inner: list(self.rows)})()


def prompt(prompt_id: int, tenant_id: int = 16, unit_id: int | None = 8) -> GeoPrompt:
    return GeoPrompt(
        id=prompt_id,
        tenant_id=tenant_id,
        unit_id=unit_id,
        question=f"问题 {prompt_id}",
        language="zh-CN",
        priority=prompt_id,
        tags=["工业", "GEO"],
        status="active",
        source="manual",
        question_group="selection",
        market="cn",
        is_brand_probe=False,
        created_at=NOW,
        updated_at=NOW,
    )


def unit(tenant_id: int = 16) -> GeoOptimizationUnit:
    return GeoOptimizationUnit(
        id=8,
        tenant_id=tenant_id,
        business_id=3,
        name="工业齿轮箱",
        status="active",
    )


def business(tenant_id: int = 16) -> GeoOptimizationBusiness:
    return GeoOptimizationBusiness(
        id=3,
        tenant_id=tenant_id,
        name="驱动产品",
        status="active",
    )


def client_for(rows, *, bound_tenant_id: int | None = 16):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/geo")
    session = ReadOnlyFakeSession(rows)
    ctx = AuthContext(
        user_id=5,
        username="workbench_test_readonly",
        role_name="workbench-readonly",
        tenant_id=bound_tenant_id,
        permissions={"geo.content": "view"},
    )
    app.dependency_overrides[require_geo_read_entitlement] = lambda: ctx
    app.dependency_overrides[require_scoped_auth] = lambda: ctx
    app.dependency_overrides[geo_read_session] = lambda: session
    return TestClient(app), session


def test_query_scopes_prompt_and_both_optional_joins_to_tenant():
    statement = build_question_query(
        tenant_id=16,
        limit=2,
        before_id=40,
        status="active",
        is_brand_probe=False,
        unit_id=8,
        business_id=3,
    )
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )

    assert "geo_prompts.tenant_id = 16" in sql
    assert "geo_optimization_units.tenant_id = 16" in sql
    assert "geo_optimization_businesses.tenant_id = 16" in sql
    assert "geo_prompts.id < 40" in sql
    assert "geo_prompts.unit_id = 8" in sql
    assert "geo_optimization_units.business_id = 3" in sql
    assert "ORDER BY geo_prompts.id DESC" in sql
    assert "LIMIT 3" in sql


def test_endpoint_returns_stable_refs_and_does_not_expose_internal_owner_fields():
    http, session = client_for([(prompt(5), unit(), business())])
    response = http.get(
        "/api/v1/geo/integration/read/questions",
        params={"tenant_id": 16, "limit": 2},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == 16
    assert body["pagination"] == {
        "limit": 2,
        "has_more": False,
        "next_before_id": None,
    }
    assert body["items"][0]["ref"] == {"module": "geo", "type": "question", "id": 5}
    assert body["items"][0]["unit_ref"]["id"] == 8
    assert body["items"][0]["business_ref"]["id"] == 3
    assert body["items"][0]["question_source"] == "manual"
    assert body["items"][0]["created_at"] == "2026-09-07T09:00:00"
    assert body["items"][0]["updated_at"] == "2026-09-07T09:00:00"
    assert body["items"][0]["timestamp_source_timezone"] == "unknown"
    assert "owner_user_id" not in body["items"][0]
    assert "created_by" not in body["items"][0]
    assert "demand_note" not in body["items"][0]
    assert len(session.statements) == 1


def test_keyset_pages_have_no_duplicates_and_out_of_range_page_is_empty():
    first = question_page(
        [(prompt(5), None, None), (prompt(4), None, None), (prompt(3), None, None)],
        tenant_id=16,
        limit=2,
    )
    second = question_page(
        [(prompt(3), None, None), (prompt(2), None, None)], tenant_id=16, limit=2
    )
    empty = question_page([], tenant_id=16, limit=2)

    first_ids = [item.ref.id for item in first.items]
    second_ids = [item.ref.id for item in second.items]
    assert first_ids == [5, 4]
    assert first.pagination.has_more is True
    assert first.pagination.next_before_id == 4
    assert second_ids == [3, 2]
    assert set(first_ids).isdisjoint(second_ids)
    assert empty.items == []
    assert empty.pagination.has_more is False
    assert empty.pagination.next_before_id is None


@pytest.mark.parametrize(
    "params",
    [
        {"tenant_id": 16, "limit": 0},
        {"tenant_id": 16, "limit": 201},
        {"tenant_id": 16, "before_id": 0},
        {"tenant_id": 16, "unit_id": 0},
        {"tenant_id": 16, "business_id": 0},
    ],
)
def test_invalid_pagination_and_scope_filters_are_rejected(params):
    http, session = client_for([])
    response = http.get("/api/v1/geo/integration/read/questions", params=params)
    assert response.status_code == 422
    assert session.statements == []


def test_tenant_bound_reader_cannot_query_another_customer():
    http, session = client_for([], bound_tenant_id=16)
    response = http.get(
        "/api/v1/geo/integration/read/questions", params={"tenant_id": 17}
    )
    assert response.status_code == 403
    assert session.statements == []


def test_endpoint_has_entitlement_and_database_read_only_dependencies():
    route = next(route for route in router.routes if route.path.endswith("/questions"))
    dependency_calls = {
        dependency.call
        for dependency in route.dependant.dependencies
        if dependency.call is not None
    }
    assert require_geo_read_entitlement in dependency_calls
    assert require_scoped_auth in dependency_calls
    assert geo_read_session in dependency_calls


def test_endpoint_uses_no_mutating_session_method():
    session = ReadOnlyFakeSession([(prompt(5), None, None)])
    assert not hasattr(session, "add")
    assert not hasattr(session, "flush")
    assert not hasattr(session, "commit")
