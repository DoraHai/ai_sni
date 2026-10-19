"""In-process URL-fetch quotas. Each worker/restart has its own counters.

No database or external service: 10 starts/advisor/minute, 20/customer/minute,
and at most 2 in flight for either dimension. Multiple workers multiply these
limits; this is deliberately not a cluster-wide quota.
"""
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from threading import Lock

from app.security.advisor_scope import deny

WINDOW_SECONDS = 60
ADVISOR_STARTS = 10
TENANT_STARTS = 20
MAX_IN_FLIGHT = 2
MAX_BUCKETS = 4096


@dataclass
class _Bucket:
    starts: deque = field(default_factory=deque)
    active: int = 0


class UrlPreviewLimiter:
    def __init__(self, clock=None):
        self.clock = clock or time.monotonic
        self.buckets = {}
        self.lock = Lock()

    @asynccontextmanager
    async def slot(self, user_id, tenant_id):
        keys = (('advisor', user_id), ('tenant', tenant_id))
        with self.lock:
            cutoff = self.clock() - WINDOW_SECONDS
            for key, bucket in list(self.buckets.items()):
                while bucket.starts and bucket.starts[0] <= cutoff:
                    bucket.starts.popleft()
                if not bucket.starts and not bucket.active:
                    del self.buckets[key]
            if len(self.buckets) + sum(key not in self.buckets for key in keys) > MAX_BUCKETS:
                deny(429, 'ADVISOR_URL_PREVIEW_BUSY', '网址预览繁忙，请稍后再试')
            buckets = [self.buckets.setdefault(key, _Bucket()) for key in keys]
            if any(len(bucket.starts) >= limit for bucket, limit in zip(buckets, (ADVISOR_STARTS, TENANT_STARTS))):
                deny(429, 'ADVISOR_URL_PREVIEW_RATE_LIMITED', '网址预览过于频繁，请稍后再试')
            if any(bucket.active >= MAX_IN_FLIGHT for bucket in buckets):
                deny(429, 'ADVISOR_URL_PREVIEW_BUSY', '网址预览繁忙，请稍后再试')
            now = self.clock()
            for bucket in buckets:
                bucket.starts.append(now)
                bucket.active += 1
        try:
            yield
        finally:
            with self.lock:
                for bucket in buckets:
                    bucket.active -= 1


_limiter = UrlPreviewLimiter()


@asynccontextmanager
async def advisor_url_preview_slot(ctx, tenant_id):
    if getattr(ctx, 'advisor_scope', None) is None:
        yield
    else:
        async with _limiter.slot(ctx.user_id, tenant_id):
            yield
