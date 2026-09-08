from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "accept_tiger_seo_readonly.py"
SPEC = importlib.util.spec_from_file_location("accept_tiger_seo_readonly", SCRIPT)
assert SPEC and SPEC.loader
acceptance = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = acceptance
SPEC.loader.exec_module(acceptance)


class FakeGet:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, path, params=None):
        self.calls.append((path, params))
        return self.responses[path]


def base_responses(sites):
    return {
        "/api/v1/auth/me": {
            "id": 5,
            "tenant_id": 4,
            "permissions": {"seo.content": "view", "seo.site": "view"},
        },
        "/api/v1/auth/modules": {
            "modules": [{"module_code": "seo", "available": True}]
        },
        "/api/v1/seo/sites": {"sites": sites},
        "/api/v1/seo/workbench/sites": {
            "selection_policy": {"selectable_statuses": ["active"]},
            "sites": sites,
        },
    }


def tiger_site():
    return {
        "id": 44,
        "tenant_id": 4,
        "domain": "https://www.tiger-coatings.cn/",
        "canonical_domain": "tiger-coatings.cn",
        "status": "active",
    }


def test_empty_site_stops_before_site_specific_probes():
    fake = FakeGet(base_responses([]))
    result = acceptance.run_acceptance(fake)

    assert result["status"] == "empty_site"
    assert result["sites"]["expected_domain_matches"] == 0
    assert len(fake.calls) == 4
    assert all(call[0] not in {"/api/v1/seo/content-assets", "/api/v1/seo/traffic/gsc"} for call in fake.calls)


def test_no_gsc_content_or_publications_are_explicit_states():
    responses = base_responses([tiger_site()])
    responses.update(
        {
            "/api/v1/seo/content-assets": {"items": [], "total": 0, "status_counts": {}},
            "/api/v1/seo/content-distribution/publications": {"items": []},
            "/api/v1/seo/site-pages": {"items": [], "total": 0},
            "/api/v1/seo/traffic/gsc": {"enabled": False, "property_url": None, "status": "not_configured"},
            "/api/v1/seo/cockpit/metrics/snapshot": [],
        }
    )
    fake = FakeGet(responses)

    result = acceptance.run_acceptance(fake)

    assert result["status"] == "readable"
    assert result["site_id"] == 44
    assert result["states"] == {
        "no_content": True,
        "no_publications": True,
        "no_pages": True,
        "no_gsc": True,
    }
    assert {item["name"]: item["count"] for item in result["probes"]} == {
        "content": 0,
        "publications": 0,
        "pages": 0,
        "gsc": 0,
        "metrics": 0,
    }


def test_public_crawl_is_labelled_preflight_not_production(tmp_path):
    crawl = tmp_path / "crawl.json"
    crawl.write_text(
        json.dumps(
            {
                "captured_at": "2026-09-08T09:49:43+08:00",
                "candidate_site": {"canonical_domain": "tiger-coatings.cn"},
                "crawl": {
                    "discovered": 2,
                    "snapshots": [
                        {"status_code": 200, "fetch_error": None},
                        {"status_code": 500, "fetch_error": "timeout"},
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    summary = acceptance.summarize_public_preflight(crawl)

    assert summary["source"] == "public_preflight"
    assert summary["production_data"] is False
    assert summary["snapshots"] == 2
    assert summary["http_200"] == 1
    assert summary["fetch_errors"] == 1


def test_cross_tenant_identity_fails_before_module_probe():
    fake = FakeGet({"/api/v1/auth/me": {"id": 9, "tenant_id": 16}})

    with pytest.raises(acceptance.AcceptanceError, match="expected 4"):
        acceptance.run_acceptance(fake)

    assert fake.calls == [("/api/v1/auth/me", None)]


def test_script_has_no_write_http_methods():
    source = SCRIPT.read_text(encoding="utf-8")
    for method in ('method="POST"', 'method="PUT"', 'method="PATCH"', 'method="DELETE"'):
        assert method not in source


def test_freshness_compares_instants_instead_of_timestamp_text():
    # 10:00+08 is earlier than 03:00Z even though its text sorts later.
    payload = {
        "items": [
            {"updated_at": "2026-09-08T10:00:00+08:00"},
            {"observed_at": "2026-09-08T03:00:00Z"},
        ]
    }

    assert acceptance._latest_timestamp(payload) == "2026-09-08T03:00:00Z"
