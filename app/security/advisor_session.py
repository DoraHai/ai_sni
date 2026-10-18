"""Bounded per-worker session selection throttle, independent of database ACLs."""
from collections import deque
from threading import Lock
from time import monotonic

from app.security.advisor_scope import deny

_attempts = {}
_lock = Lock()


def admit_selection(user_id):
    # Count both successful and denied selections. This is a per-worker limit;
    # no token, IP, username or customer data is retained in the limiter.
    now = monotonic()
    with _lock:
        expired = [uid for uid, times in _attempts.items() if times[-1] <= now - 60]
        for uid in expired:
            del _attempts[uid]
        if user_id not in _attempts:
            if len(_attempts) >= 10000:
                deny(429, "ADVISOR_SELECTION_RATE_LIMITED", "切换客户过于频繁，请稍后重试")
            _attempts[user_id] = deque()
        times = _attempts[user_id]
        while times and times[0] <= now - 60:
            times.popleft()
        if len(times) >= 10:
            deny(429, "ADVISOR_SELECTION_RATE_LIMITED", "切换客户过于频繁，请稍后重试")
        times.append(now)
