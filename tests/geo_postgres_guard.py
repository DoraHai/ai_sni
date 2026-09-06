"""Guardrails for opt-in GEO tests that use a disposable PostgreSQL database."""

from __future__ import annotations

import os

import pytest
from sqlalchemy.engine import make_url


def require_geo_test_url() -> str:
    url = os.environ.get("GEO_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("requires a dedicated loopback geo_ci database")
    parsed = make_url(url)
    if (
        parsed.drivername != "postgresql+asyncpg"
        or parsed.host != "127.0.0.1"
        or parsed.username != "geo_ci"
        or parsed.database != "geo_ci"
        or not parsed.port
        or parsed.port == 5432
        or parsed.query
    ):
        pytest.fail("Refusing a database outside the dedicated loopback GEO fixture contract")
    return url
