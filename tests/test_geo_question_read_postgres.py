"""Native PostgreSQL coverage for the GEO question read route."""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.database import Base, get_session
from app.geo.question_read_routes import router
from app.models import (
    GeoOptimizationBusiness,
    GeoOptimizationUnit,
    GeoPrompt,
    Tenant,
    TenantModule,
)
from app.security.auth import AuthContext, require_scoped_auth
from tests.geo_postgres_guard import require_geo_test_url


MODELS = (
    Tenant,
    TenantModule,
    GeoOptimizationBusiness,
    GeoOptimizationUnit,
    GeoPrompt,
)


def _fixture_metadata() -> MetaData:
    metadata = MetaData()
    for model in MODELS:
        model.__table__.to_metadata(metadata)
    return metadata


def test_questions_use_native_readonly_transaction_and_tenant_entitlement():
    url = require_geo_test_url()

    async def scenario():
        schema = "geo_questions_case_" + uuid.uuid4().hex
        engine = create_async_engine(
            url,
            poolclass=NullPool,
            execution_options={"schema_translate_map": {None: schema}},
        )
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        metadata = _fixture_metadata()
        created = False
        try:
            async with engine.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                created = True
                await connection.run_sync(metadata.create_all)
                tenants = metadata.tables["tenants"]
                modules = metadata.tables["tenant_modules"]
                businesses = metadata.tables["geo_optimization_businesses"]
                units = metadata.tables["geo_optimization_units"]
                prompts = metadata.tables["geo_prompts"]
                await connection.execute(
                    tenants.insert(),
                    [
                        {"id": 16, "name": "tenant-active"},
                        {"id": 17, "name": "tenant-other"},
                        {"id": 18, "name": "tenant-disabled"},
                        {"id": 19, "name": "tenant-expired"},
                        {"id": 20, "name": "tenant-expires-today"},
                    ],
                )
                await connection.execute(
                    modules.insert(),
                    [
                        {
                            "id": 1,
                            "tenant_id": 16,
                            "module_code": "geo",
                            "status": "active",
                            "expires_at": None,
                        },
                        {
                            "id": 2,
                            "tenant_id": 17,
                            "module_code": "geo",
                            "status": "trial",
                            "expires_at": None,
                        },
                        {
                            "id": 3,
                            "tenant_id": 18,
                            "module_code": "geo",
                            "status": "disabled",
                            "expires_at": None,
                        },
                        {
                            "id": 4,
                            "tenant_id": 19,
                            "module_code": "geo",
                            "status": "active",
                            "expires_at": date.today() - timedelta(days=1),
                        },
                        {
                            "id": 5,
                            "tenant_id": 20,
                            "module_code": "geo",
                            "status": "trial",
                            "expires_at": date.today(),
                        },
                    ],
                )
                await connection.execute(
                    businesses.insert(),
                    [
                        {"id": 3, "tenant_id": 16, "name": "active business", "status": "active"},
                        {"id": 30, "tenant_id": 17, "name": "other business", "status": "active"},
                    ],
                )
                await connection.execute(
                    units.insert(),
                    [
                        {
                            "id": 8,
                            "tenant_id": 16,
                            "business_id": 3,
                            "name": "active unit",
                            "status": "active",
                        },
                        {
                            "id": 80,
                            "tenant_id": 17,
                            "business_id": 30,
                            "name": "other unit",
                            "status": "active",
                        },
                    ],
                )
                await connection.execute(
                    prompts.insert(),
                    [
                        {
                            "id": prompt_id,
                            "tenant_id": 16,
                            "unit_id": 8,
                            "question": f"active question {prompt_id}",
                        }
                        for prompt_id in (103, 104, 105)
                    ]
                    + [
                        {
                            "id": 205,
                            "tenant_id": 17,
                            "unit_id": 80,
                            "question": "other tenant question",
                        }
                    ],
                )
            app = FastAPI()
            app.include_router(router, prefix="/api/v1/geo")
            bound_ctx = AuthContext(
                user_id=5,
                username="workbench_test_readonly",
                role_name="workbench-readonly",
                tenant_id=16,
                permissions={"geo.content": "view"},
            )

            async def auth_session():
                async with session_factory() as session:
                    yield session

            app.dependency_overrides[get_session] = auth_session
            app.dependency_overrides[require_scoped_auth] = lambda: bound_ctx
            transport = httpx.ASGITransport(app=app)
            with patch("app.geo.read_session.async_session_factory", session_factory):
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://geo-ci.local"
                ) as client:
                    first = await client.get(
                        "/api/v1/geo/integration/read/questions",
                        params={"tenant_id": 16, "limit": 2},
                    )
                    assert first.status_code == 200
                    first_body = first.json()
                    assert [item["ref"]["id"] for item in first_body["items"]] == [105, 104]
                    assert all(
                        item["timestamp_source_timezone"] == "unknown"
                        and not item["created_at"].endswith("Z")
                        and "+" not in item["created_at"]
                        and not item["updated_at"].endswith("Z")
                        and "+" not in item["updated_at"]
                        for item in first_body["items"]
                    )
                    assert first_body["pagination"]["next_before_id"] == 104

                    second = await client.get(
                        "/api/v1/geo/integration/read/questions",
                        params={"tenant_id": 16, "limit": 2, "before_id": 104},
                    )
                    assert second.status_code == 200
                    second_ids = [item["ref"]["id"] for item in second.json()["items"]]
                    assert second_ids == [103]
                    assert set(second_ids).isdisjoint({105, 104})
                    assert all(item["business_ref"]["id"] == 3 for item in first_body["items"])

                    cross_tenant = await client.get(
                        "/api/v1/geo/integration/read/questions", params={"tenant_id": 17}
                    )
                    assert cross_tenant.status_code == 403

                    app.dependency_overrides[require_scoped_auth] = lambda: AuthContext(
                        user_id=1,
                        username="admin-reader",
                        role_name="admin-reader",
                        tenant_id=None,
                        permissions={"geo.content": "view"},
                    )
                    for tenant_id in (18, 19):
                        denied = await client.get(
                            "/api/v1/geo/integration/read/questions",
                            params={"tenant_id": tenant_id},
                        )
                        assert denied.status_code == 403
                    expires_today = await client.get(
                        "/api/v1/geo/integration/read/questions", params={"tenant_id": 20}
                    )
                    assert expires_today.status_code == 200
                    assert expires_today.json()["items"] == []
        finally:
            if created:
                assert schema.startswith("geo_questions_case_") and len(schema) == 51
                async with engine.begin() as connection:
                    await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await engine.dispose()

    asyncio.run(scenario())
