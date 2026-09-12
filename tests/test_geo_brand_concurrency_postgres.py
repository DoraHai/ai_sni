"""Brand gates must see commits made by another session before final writes."""

import asyncio
import os
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.geo.content import routes, variant_execute
from app.geo.content.gate import PublishGateError
from app.models import (
    GeoChannelVariant,
    GeoContentTask,
    GeoOptimizationBusiness,
    GeoPublishingChannel,
    Tenant,
)


pytestmark = pytest.mark.skipif(
    not os.getenv("GEO_TEST_POSTGRES_URL"), reason="requires authorized PostgreSQL"
)


async def _schema_engines(tables):
    url = os.environ["GEO_TEST_POSTGRES_URL"]
    schema = "geo_brand_gate_" + uuid4().hex
    admin = create_async_engine(url)
    async with admin.begin() as connection:
        await connection.execute(text(f"CREATE SCHEMA {schema}"))
        for table in tables:
            await connection.execute(
                text(
                    f"CREATE TABLE {schema}.{table} AS "
                    f"SELECT * FROM public.{table} WITH NO DATA"
                )
            )
    engine = create_async_engine(
        url,
        connect_args={
            "server_settings": {"search_path": schema, "statement_timeout": "15000"}
        },
    )
    return schema, admin, engine


async def _drop_schema(schema, admin, engine, tables):
    await engine.dispose()
    async with admin.begin() as connection:
        for table in reversed(tables):
            await connection.execute(text(f"DROP TABLE {schema}.{table}"))
        await connection.execute(text(f"DROP SCHEMA {schema}"))
    await admin.dispose()


def test_publication_write_sees_business_brand_changed_by_other_session():
    async def run():
        tables = [
            "tenants",
            "geo_optimization_businesses",
            "geo_content_tasks",
            "geo_article_versions",
            "geo_channel_variants",
            "geo_publications",
        ]
        schema, admin, engine = await _schema_engines(tables)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with engine.begin() as connection:
                await connection.execute(text("INSERT INTO tenants(id,name) VALUES(7,'租户名')"))
                await connection.execute(
                    text(
                        "INSERT INTO geo_optimization_businesses"
                        "(id,tenant_id,name,profile,status,sort_order) "
                        "VALUES(20,7,'业务',CAST(:profile AS jsonb),'active',0)"
                    ),
                    {"profile": '{"product_name":"旧品牌"}'},
                )
                await connection.execute(
                    text(
                        "INSERT INTO geo_content_tasks"
                        "(id,tenant_id,business_id,review_status,title,status) "
                        "VALUES(12,7,20,'approved','title','ready')"
                    )
                )
                await connection.execute(
                    text(
                        "INSERT INTO geo_article_versions"
                        "(id,task_id,version_no,title,body_markdown) "
                        "VALUES(16,12,1,'title','旧品牌正文。\n\n## 结论\n选择旧品牌。')"
                    )
                )
                await connection.execute(
                    text(
                        "INSERT INTO geo_channel_variants"
                        "(id,task_id,article_version_id,channel,title,body_markdown,status,adapt_meta) "
                        "VALUES(3,12,16,'website','title','旧品牌正文','draft','{}')"
                    )
                )

            async with sessions() as first:
                task = await first.get(GeoContentTask, 12)
                variant = await first.get(GeoChannelVariant, 3)
                assert (await first.get(GeoOptimizationBusiness, 20)).profile["product_name"] == "旧品牌"
                async with sessions() as other:
                    business = await other.get(GeoOptimizationBusiness, 20)
                    business.profile = {"product_name": "新品牌"}
                    await other.commit()

                seen = []

                def gate(_, *, task, brand, article_id):
                    seen.append((brand, article_id))
                    if brand == "新品牌":
                        raise PublishGateError("品牌标准未通过")

                with (
                    patch.object(routes, "_build_rule_input", AsyncMock(return_value=object())),
                    patch.object(routes, "assert_can_publish", side_effect=gate),
                    pytest.raises(PublishGateError, match="品牌标准未通过"),
                ):
                    await routes._write_publication(
                        first,
                        task=task,
                        variant=variant,
                        channel="website",
                        published_url="https://example.com/article",
                        note=None,
                        publish_mode="manual",
                    )
                await first.rollback()

            assert seen == [("新品牌", 16)]
            async with sessions() as check:
                assert await check.scalar(text("SELECT count(*) FROM geo_publications")) == 0
                assert (await check.get(GeoContentTask, 12)).status == "ready"
                assert (await check.get(GeoChannelVariant, 3)).status == "draft"
        finally:
            await _drop_schema(schema, admin, engine, tables)

    asyncio.run(run())


def test_variant_generation_fails_closed_when_brand_changes_during_generation():
    async def run():
        tables = [
            "tenants",
            "tenant_modules",
            "geo_optimization_businesses",
            "geo_content_tasks",
            "geo_article_versions",
            "geo_channel_variants",
            "geo_publishing_channels",
            "geo_facts",
            "geo_task_facts",
        ]
        schema, admin, engine = await _schema_engines(tables)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with engine.begin() as connection:
                await connection.execute(text("INSERT INTO tenants(id,name) VALUES(7,'租户名')"))
                await connection.execute(
                    text(
                        "INSERT INTO tenant_modules(tenant_id,module_code,status) "
                        "VALUES(7,'geo','active')"
                    )
                )
                await connection.execute(
                    text(
                        "INSERT INTO geo_optimization_businesses"
                        "(id,tenant_id,name,profile,status,sort_order) "
                        "VALUES(20,7,'业务',CAST(:profile AS jsonb),'active',0)"
                    ),
                    {"profile": '{"product_name":"旧品牌"}'},
                )
                await connection.execute(
                    text(
                        "INSERT INTO geo_content_tasks"
                        "(id,tenant_id,business_id,review_status,title,status,target_channels) "
                        "VALUES(12,7,20,'approved','title','ready','[\"website\"]')"
                    )
                )
                await connection.execute(
                    text(
                        "INSERT INTO geo_article_versions"
                        "(id,task_id,version_no,title,body_markdown) "
                        "VALUES(16,12,1,'title','旧品牌正文。\n\n## 结论\n选择旧品牌。')"
                    )
                )
                await connection.execute(
                    text(
                        "INSERT INTO geo_publishing_channels"
                        "(id,tenant_id,name,channel_type,publish_mode,enabled,sort_order) "
                        "VALUES(5,7,'官网','website','auto_publish',true,0)"
                    )
                )

            async def polish(*args, **kwargs):
                async with sessions() as other:
                    business = await other.get(GeoOptimizationBusiness, 20)
                    business.profile = {"product_name": "新品牌"}
                    await other.commit()
                return (
                    "渠道标题",
                    "旧品牌渠道正文。\n\n## 结论\n选择旧品牌。",
                    {"quality": "publish_ready"},
                )

            async with sessions() as first:
                with (
                    patch.object(variant_execute, "enabled_types_from_rows", return_value=["website"]),
                    patch.object(variant_execute, "resolve_for_channel", AsyncMock(return_value={})),
                    patch.object(variant_execute, "adapt_or_polish_for_channel", side_effect=polish),
                    pytest.raises(ValueError, match="品牌标准"),
                ):
                    await variant_execute.execute_variants_for_task(
                        first,
                        task_id=12,
                        tenant_id=7,
                        channels=["website"],
                        use_llm=False,
                    )

            async with sessions() as check:
                task = await check.get(GeoContentTask, 12)
                assert task.status == "needs_fix"
                assert task.review_status == "none"
                assert task.rule_result["brand_validation"]["passed"] is False
                assert await check.scalar(text("SELECT count(*) FROM geo_channel_variants")) == 0
                assert (await check.get(GeoOptimizationBusiness, 20)).profile["product_name"] == "新品牌"
        finally:
            await _drop_schema(schema, admin, engine, tables)

    asyncio.run(run())
