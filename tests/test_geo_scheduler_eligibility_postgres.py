"""Disposable PostgreSQL proof that scheduler eligibility is strictly read-only."""

import asyncio
import os
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from sqlalchemy import Column, MetaData, Table, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.skipif(
    not os.getenv("GEO_TEST_POSTGRES_URL"),
    reason="requires explicitly configured PostgreSQL",
)
def test_scheduler_eligibility_uses_read_only_transaction_without_initialization():
    from app.geo import read_routes as api
    from app.models import GeoPrompt, GeoVisibilityPatrolSettings

    async def run():
        schema = "geo_scheduler_eligibility_" + uuid4().hex
        admin = create_async_engine(os.environ["GEO_TEST_POSTGRES_URL"])
        engine = None
        created = False
        metadata = MetaData(schema=schema)
        for model in (GeoVisibilityPatrolSettings, GeoPrompt):
            Table(
                model.__tablename__,
                metadata,
                *(Column(column.name, column.type, nullable=True) for column in model.__table__.columns),
            )
        try:
            async with admin.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                created = True
                await connection.run_sync(metadata.create_all)
                await connection.execute(
                    text(
                        f'INSERT INTO "{schema}".geo_visibility_patrol_settings '
                        "(tenant_id, enabled) VALUES (4, false)"
                    )
                )
                await connection.execute(
                    text(
                        f'INSERT INTO "{schema}".geo_prompts '
                        "(id, tenant_id, question, status) VALUES "
                        "(1, 4, 'active question', 'active'), "
                        "(2, 4, 'archived question', 'archived')"
                    )
                )

            engine = create_async_engine(
                os.environ["GEO_TEST_POSTGRES_URL"],
                connect_args={
                    "server_settings": {
                        "search_path": schema,
                        "statement_timeout": "10000",
                    }
                },
            )
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            with patch.object(api, "async_session_factory", sessions):
                async for session in api.read_session():
                    assert await session.scalar(text("SHOW transaction_read_only")) == "on"
                    result = await api.get_scheduler_eligibility(4, Mock(), session)
                    assert result["patrol_settings"] == {
                        "exists": True,
                        "enabled": False,
                    }
                    assert result["active_prompt_count"] == 1
                    assert result["scheduler_eligible"] is False
                    with pytest.raises(DBAPIError):
                        async with session.begin_nested():
                            await session.execute(
                                text(
                                    "UPDATE geo_visibility_patrol_settings "
                                    "SET enabled=true WHERE tenant_id=4"
                                )
                            )

            async with admin.connect() as connection:
                enabled = await connection.scalar(
                    text(
                        f'SELECT enabled FROM "{schema}".'
                        "geo_visibility_patrol_settings WHERE tenant_id=4"
                    )
                )
                assert enabled is False
        finally:
            if engine is not None:
                await engine.dispose()
            if created:
                async with admin.begin() as connection:
                    await connection.run_sync(metadata.drop_all)
                    await connection.execute(text(f'DROP SCHEMA "{schema}"'))
            await admin.dispose()

    asyncio.run(run())
