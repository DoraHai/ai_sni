import json
from datetime import datetime, timezone

import pytest

from app.seo_demo_fixture import (
    DEMO_DOMAIN,
    FIXTURE_VERSION,
    build_seo_demo_fixture,
    validate_seo_demo_fixture,
)


def test_fixture_is_deterministic_and_has_required_scenarios():
    anchor = datetime(2026, 9, 1, 8, tzinfo=timezone.utc)
    first = build_seo_demo_fixture(anchor=anchor, proposed_tenant_id=9001)
    second = build_seo_demo_fixture(anchor=anchor, proposed_tenant_id=9001)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["fixture"]["version"] == FIXTURE_VERSION
    assert first["counts"]["seo_metric_snapshots"] == 361
    assert first["counts"]["seo_keyword_assets"] == 12
    assert first["counts"]["seo_rank_snapshots"] == 156
    assert first["counts"]["seo_serp_results"] == 36
    assert first["counts"]["seo_site_pages"] == 10
    assert first["counts"]["seo_page_index_reviews"] == 3
    assert first["counts"]["seo_content_assets"] == 8
    assert first["counts"]["seo_tasks"] == 6
    statuses = {row["status"] for row in first["tables"]["seo_content_assets"]}
    assert {"planned", "drafting", "review", "ready", "published", "archived"} <= statuses
    publication_statuses = {
        row["status"] for row in first["tables"]["seo_content_publications"]
    }
    assert {"published", "failed", "manual_required"} <= publication_statuses
    ranks = first["tables"]["seo_rank_snapshots"]
    by_keyword = {}
    for row in ranks:
        by_keyword.setdefault(row["keyword"]["key"], []).append(row["rank"])
    assert any(values[-1] < values[0] for values in by_keyword.values())
    assert any(values[-1] > values[0] for values in by_keyword.values())


def test_fixture_cannot_target_tiger_or_start_external_work():
    with pytest.raises(ValueError, match="Tiger"):
        build_seo_demo_fixture(proposed_tenant_id=4)
    package = build_seo_demo_fixture()
    assert package["tables"]["seo_sites"][0]["status"] == "paused"
    assert all(not row["enabled"] for row in package["tables"]["seo_distribution_connections"])
    assert all(not row["has_credentials"] for row in package["tables"]["seo_distribution_connections"])
    assert all(row["source"] == "demo_fixture" for row in package["tables"]["seo_metric_snapshots"])
    assert all(
        row["raw_payload"]["article_attribution"] == "unsupported"
        for row in package["tables"]["seo_metric_snapshots"]
    )
    text = json.dumps(package, ensure_ascii=False)
    assert DEMO_DOMAIN in text
    assert "provider_called\": true" not in text.lower()
    validate_seo_demo_fixture(package)


def test_validator_rejects_runnable_or_real_network_data():
    package = build_seo_demo_fixture()
    package["tables"]["seo_sites"][0]["status"] = "active"
    with pytest.raises(ValueError, match="paused"):
        validate_seo_demo_fixture(package)

    package = build_seo_demo_fixture()
    package["tables"]["seo_distribution_connections"][0]["enabled"] = True
    with pytest.raises(ValueError, match="disabled"):
        validate_seo_demo_fixture(package)

    package = build_seo_demo_fixture()
    package["tables"]["seo_backlinks"][0]["source_url"] = "https://example.com/real"
    with pytest.raises(ValueError, match="non-reserved"):
        validate_seo_demo_fixture(package)

    package = build_seo_demo_fixture()
    package["tables"]["seo_tasks"][0]["site"] = {
        "table": "seo_sites",
        "key": "missing-site",
    }
    with pytest.raises(ValueError, match="unresolved"):
        validate_seo_demo_fixture(package)
