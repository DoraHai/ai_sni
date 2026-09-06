"""Real PostgreSQL ownership checks for GEO progress recovery."""

import asyncio
import os
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import create_async_engine


pytestmark = pytest.mark.skipif(
    not os.getenv("GEO_TEST_POSTGRES_URL"),
    reason="requires isolated PostgreSQL",
)


def test_job_and_patrol_advisory_locks_exclude_live_workers():
    from app.geo.content.async_jobs import job_execution_lock
    from app.geo.content.patrol import patrol_execution_lock

    async def scenario():
        engine = create_async_engine(os.environ["GEO_TEST_POSTGRES_URL"])
        try:
            with patch("app.database.engine", engine):
                async with job_execution_lock(71001) as first_job:
                    assert first_job is not None
                    async with job_execution_lock(71001) as competing_job:
                        assert competing_job is None
                async with job_execution_lock(71001) as released_job:
                    assert released_job is not None

                async with patrol_execution_lock(72001) as first_patrol:
                    assert first_patrol is True
                    async with patrol_execution_lock(72001) as competing_patrol:
                        assert competing_patrol is False
                async with patrol_execution_lock(72001) as released_patrol:
                    assert released_patrol is True
        finally:
            await engine.dispose()

    asyncio.run(scenario())
