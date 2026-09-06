"""Real PostgreSQL ownership checks for GEO progress recovery."""

import asyncio
from unittest.mock import patch

from sqlalchemy.ext.asyncio import create_async_engine

from tests.geo_postgres_guard import require_geo_test_url


def test_job_and_patrol_advisory_locks_exclude_live_workers():
    from app.geo.content.async_jobs import job_execution_lock
    from app.geo.content.patrol import patrol_execution_lock

    url = require_geo_test_url()

    async def scenario():
        engine = create_async_engine(url)
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
