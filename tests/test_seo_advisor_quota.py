import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.security.seo_advisor_quota import KEY, LIMIT, admit, request_kind, reserve
from app.seo_ai_operations import _refund

PATH = "/api/v1/seo/content-ai/assist"
NOW = datetime(2026, 10, 18, 15, 59, tzinfo=timezone.utc)


def test_ten_suggestions_per_advisor_client_day_and_idempotent_recovery():
    config = {"unrelated_setting": "retained"}
    for i in range(10):
        config, receipt = reserve(config, 7, PATH, {"action": "title", "request_id": str(i)}, now=NOW)
        assert receipt["used"] == i + 1
    restored, receipt = reserve(config, 7, PATH, {"action": "title", "request_id": "9"}, now=NOW)
    assert receipt["used"] == 10 and restored == config
    with pytest.raises(HTTPException) as caught:
        reserve(config, 7, PATH, {"action": "title", "request_id": "11"}, now=NOW)
    assert caught.value.status_code == 429
    assert "10 次" in caught.value.detail["message"]
    assert config["unrelated_setting"] == "retained"
    assert reserve(config, 8, PATH, {"request_id": "0"}, now=NOW)[1]["used"] == 1
    # A different client's module JSON is independently empty.
    assert reserve({}, 7, PATH, {"request_id": "0"}, now=NOW)[1]["used"] == 1


def test_shanghai_midnight_resets_and_request_key_cannot_change_payload():
    config, _ = reserve({}, 7, PATH, {"request_id": "one", "action": "title"}, now=NOW)
    with pytest.raises(HTTPException) as caught:
        reserve(config, 7, PATH, {"request_id": "one", "action": "rewrite"}, now=NOW)
    assert caught.value.status_code == 409
    tomorrow = datetime(2026, 10, 18, 16, 0, tzinfo=timezone.utc)
    result, receipt = reserve(config, 7, PATH, {"request_id": "two"}, now=tomorrow)
    assert result[KEY]["date"] == "2026-10-19" and receipt["used"] == 1


def test_generation_has_no_daily_count_but_advice_shares_one_bucket():
    assert request_kind(PATH, {"action": "generate"}) == "generation"
    assert request_kind("/api/v1/seo/qa/research/draft", {}) == "generation"
    assert request_kind(PATH, {"action": "rewrite"}) == "suggestion"
    assert request_kind("/api/v1/seo/site/pages/ai-tdk/generate", {}) == "suggestion"
    assert request_kind("/api/v1/seo/rank-serp/collect", {"use_ai": False}) is None
    session = SimpleNamespace(commit=AsyncMock(), scalar=AsyncMock())
    asyncio.run(admit(session, SimpleNamespace(), SimpleNamespace(template=PATH), {"action": "generate"}))
    session.scalar.assert_not_awaited()
    session.commit.assert_not_awaited()


def test_failed_advisor_operation_never_refunds_another_customers_legacy_budget():
    module = SimpleNamespace(module_settings={"seo_daily_usage": {"date": "2026-10-18", "ai_requests": 8}})
    row = SimpleNamespace(kind="advisor_content_assist", charged_on="2026-10-18")
    _refund(module, row)
    assert module.module_settings["seo_daily_usage"]["ai_requests"] == 8
    assert row.status == "refunded"
