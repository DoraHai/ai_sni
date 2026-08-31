import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.seo_usage_limits import SeoUsageLimitError, charge_seo_usage, refund_seo_usage


def test_daily_usage_is_atomic_and_preserves_other_module_settings() -> None:
    module = SimpleNamespace(module_settings={"feature": {"enabled": True}})
    session = AsyncMock()
    session.scalar.return_value = module

    result = asyncio.run(charge_seo_usage(session, 7, "ai_requests", 2, 5))

    assert result["used"] == 2
    assert module.module_settings["feature"] == {"enabled": True}
    assert module.module_settings["seo_daily_usage"]["ai_requests"] == 2
    session.commit.assert_awaited_once()


def test_daily_usage_rejects_over_limit_and_can_refund_failures() -> None:
    module = SimpleNamespace(
        module_settings={
            "seo_daily_usage": {
                "date": __import__("datetime").datetime.now(
                    __import__("zoneinfo").ZoneInfo("Asia/Shanghai")
                ).date().isoformat(),
                "crawl_urls": 90,
            }
        }
    )
    session = AsyncMock()
    session.scalar.return_value = module

    with pytest.raises(SeoUsageLimitError):
        asyncio.run(charge_seo_usage(session, 7, "crawl_urls", 20, 100))
    session.rollback.assert_awaited_once()

    session.reset_mock()
    asyncio.run(refund_seo_usage(session, 7, "crawl_urls", 30))
    assert module.module_settings["seo_daily_usage"]["crawl_urls"] == 60
    session.commit.assert_awaited_once()
