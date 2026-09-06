from __future__ import annotations

import pytest

from tests.geo_postgres_guard import require_geo_test_url


def test_geo_postgres_guard_accepts_only_dedicated_loopback_contract(monkeypatch):
    expected = "postgresql+asyncpg://geo_ci:test-only@127.0.0.1:55432/geo_ci"
    monkeypatch.setenv("GEO_TEST_POSTGRES_URL", expected)
    assert require_geo_test_url() == expected


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://geo_ci:test-only@db.example.com:55432/geo_ci",
        "postgresql+asyncpg://sem_prod:test-only@127.0.0.1:55432/sem_prod",
        "postgresql+asyncpg://geo_ci:test-only@127.0.0.1:5432/geo_ci",
        "postgresql+asyncpg://geo_ci:test-only@127.0.0.1:55432/geo_ci?ssl=true",
    ],
)
def test_geo_postgres_guard_rejects_non_fixture_urls(monkeypatch, url):
    monkeypatch.setenv("GEO_TEST_POSTGRES_URL", url)
    with pytest.raises(pytest.fail.Exception, match="dedicated loopback GEO fixture"):
        require_geo_test_url()
