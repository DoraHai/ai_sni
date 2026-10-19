import asyncio

import pytest
from fastapi import HTTPException

from app.geo.content import article_import_throttle as throttle


@pytest.mark.parametrize('dimension', ['advisor', 'tenant'])
def test_rate_limits_are_independent_and_expire(monkeypatch, dimension):
    monkeypatch.setattr(throttle, 'ADVISOR_STARTS', 2)
    monkeypatch.setattr(throttle, 'TENANT_STARTS', 2)
    now = [0.0]
    limiter = throttle.UrlPreviewLimiter(clock=lambda: now[0])

    async def run():
        for index in (1, 2):
            async with limiter.slot(1 if dimension == 'advisor' else index,
                                    index if dimension == 'advisor' else 1):
                pass
        with pytest.raises(HTTPException) as error:
            async with limiter.slot(1 if dimension == 'advisor' else 3,
                                    3 if dimension == 'advisor' else 1):
                pytest.fail('rate limit admitted a fetch')
        assert error.value.status_code == 429
        assert error.value.detail['code'] == 'ADVISOR_URL_PREVIEW_RATE_LIMITED'
        async with limiter.slot(4, 4):
            pass
        now[0] = 61.0
        async with limiter.slot(1, 1):
            pass
        assert len(limiter.buckets) == 2
    asyncio.run(run())


@pytest.mark.parametrize('dimension', ['advisor', 'tenant'])
def test_concurrency_limits_are_independent_and_release_on_error(monkeypatch, dimension):
    monkeypatch.setattr(throttle, 'MAX_IN_FLIGHT', 1)
    limiter = throttle.UrlPreviewLimiter()

    async def run():
        with pytest.raises(ValueError):
            async with limiter.slot(1, 1):
                with pytest.raises(HTTPException) as error:
                    async with limiter.slot(1 if dimension == 'advisor' else 2,
                                            2 if dimension == 'advisor' else 1):
                        pytest.fail('concurrency limit admitted a fetch')
                assert error.value.status_code == 429
                assert error.value.detail['code'] == 'ADVISOR_URL_PREVIEW_BUSY'
                async with limiter.slot(3, 3):
                    pass
                raise ValueError('fixture fetch failure')
        async with limiter.slot(1, 1):
            pass
        assert all(bucket.active == 0 for bucket in limiter.buckets.values())
    asyncio.run(run())


def test_cancellation_releases_concurrency():
    limiter = throttle.UrlPreviewLimiter()

    async def run():
        entered = asyncio.Event()
        async def fetch():
            async with limiter.slot(1, 1):
                entered.set()
                await asyncio.Event().wait()
        task = asyncio.create_task(fetch())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert all(bucket.active == 0 for bucket in limiter.buckets.values())
    asyncio.run(run())


def test_bucket_memory_is_bounded(monkeypatch):
    monkeypatch.setattr(throttle, 'MAX_BUCKETS', 2)
    limiter = throttle.UrlPreviewLimiter()

    async def run():
        async with limiter.slot(1, 1):
            pass
        with pytest.raises(HTTPException) as error:
            async with limiter.slot(2, 2):
                pass
        assert error.value.status_code == 429
        assert len(limiter.buckets) == 2
    asyncio.run(run())
