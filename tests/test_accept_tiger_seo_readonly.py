from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from urllib.request import Request
from urllib.parse import urlparse


SCRIPT = Path(__file__).parents[1] / "scripts" / "accept_tiger_seo_readonly.py"
RUNBOOK = Path(__file__).parents[1] / "docs" / "SEO_TIGER_ADMIN_EXECUTION_RUNBOOK.md"
SPEC = importlib.util.spec_from_file_location("accept_tiger_seo_readonly", SCRIPT)
assert SPEC and SPEC.loader
acceptance = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = acceptance
SPEC.loader.exec_module(acceptance)


def test_admin_runbook_blocks_unmerged_or_old_main_execution():
    runbook = RUNBOOK.read_text(encoding="utf-8")
    # Git normalizes this text file to LF. Hash those repository bytes so the
    # execution checksum is identical in Linux and Windows autocrlf checkouts.
    script_bytes = SCRIPT.read_bytes().replace(b"\r\n", b"\n")
    script_sha256 = hashlib.sha256(script_bytes).hexdigest()

    assert "execution_status=blocked_until_merged" in runbook
    assert "required_pull_request=#467" in runbook
    assert "8ba839703d91e7720bf8160b249d61ed3c704ef8" not in runbook
    assert f"expected_script_sha256={script_sha256}" in runbook
    assert f"'{script_sha256}'" in runbook
    assert "sha256sum -c -" in runbook
    assert "execution_main_sha" in runbook
    assert "git merge-base --is-ancestor \"$EXECUTION_MAIN_SHA\" origin/main" in runbook

    gate_position = runbook.index("sha256sum -c -")
    acceptance_position = runbook.index("python scripts/accept_tiger_seo_readonly.py")
    assert gate_position < acceptance_position


class FakeGet:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, path, params=None):
        self.calls.append((path, params))
        return self.responses[path]


def base_responses(sites):
    return {
        "/openapi.json": {
            "paths": {
                "/api/v1/seo/metrics/snapshot": {"get": {"responses": {"200": {}}}}
            }
        },
        "/api/v1/auth/me": {"user": {
            "id": 5,
            "tenant_id": 4,
            "permissions": {
                "seo.assets": "view",
                "seo.content": "view",
                "seo.site": "view",
                "seo.keywords": "view",
                "seo.dashboard": "view",
            },
        }},
        "/api/v1/auth/modules": {
            "modules": [{"module_code": "seo", "available": True}]
        },
        "/api/v1/seo/sites": {"sites": sites},
        "/api/v1/seo/workbench/sites": {
            "selection_policy": {
                "selectable_statuses": ["active"],
                "disabled_statuses": ["paused", "archived"],
            },
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
    assert len(fake.calls) == 5
    assert all(call[0] not in {"/api/v1/seo/content-assets", "/api/v1/seo/traffic/gsc"} for call in fake.calls)


def test_no_gsc_content_or_publications_are_explicit_states():
    responses = base_responses([tiger_site()])
    responses.update(
        {
            "/api/v1/seo/content-assets": {"items": [], "total": 0, "status_counts": {}},
            "/api/v1/seo/content-distribution/publications": {"items": []},
            "/api/v1/seo/site-pages": {"items": [], "total": 0},
            "/api/v1/seo/traffic/gsc": {"enabled": False, "property_url": None, "status": "not_configured"},
            "/api/v1/seo/metrics/snapshot": [],
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


@pytest.mark.parametrize("identity_tenant", [16, None])
def test_unscoped_or_cross_tenant_identity_fails_before_module_probe(identity_tenant):
    fake = FakeGet(
        {
            "/openapi.json": {
                "paths": {"/api/v1/seo/metrics/snapshot": {"get": {}}}
            },
            "/api/v1/auth/me": {"user": {
                "id": 9,
                "tenant_id": identity_tenant,
                "permissions": {
                    "seo.assets": "view",
                    "seo.content": "view",
                    "seo.site": "view",
                    "seo.keywords": "view",
                    "seo.dashboard": "view",
                },
            }},
        }
    )

    with pytest.raises(acceptance.AcceptanceError, match="expected 4"):
        acceptance.run_acceptance(fake)

    assert fake.calls == [("/openapi.json", None), ("/api/v1/auth/me", None)]


@pytest.mark.parametrize("missing", acceptance.REQUIRED_SEO_PERMISSIONS)
def test_missing_required_permission_stops_before_module_site_and_data_probes(missing):
    responses = base_responses([tiger_site()])
    del responses["/api/v1/auth/me"]["user"]["permissions"][missing]
    fake = FakeGet(responses)

    with pytest.raises(acceptance.AcceptanceError, match=missing):
        acceptance.run_acceptance(fake)

    assert fake.calls == [("/openapi.json", None), ("/api/v1/auth/me", None)]


class StubHttpResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class RecordingOpener:
    def __init__(self, payloads):
        self.payloads = payloads
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return StubHttpResponse(self.payloads[urlparse(request.full_url).path])


def test_real_get_client_enforces_auth_me_envelope_and_permissions_before_probes():
    responses = base_responses([tiger_site()])
    responses["/api/v1/auth/me"]["user"]["permissions"]["seo.dashboard"] = "none"
    opener = RecordingOpener(responses)
    client = acceptance.GetOnlyClient("synthetic-token", opener=opener)

    with pytest.raises(acceptance.AcceptanceError, match="seo.dashboard"):
        acceptance.run_acceptance(client.get_json)

    assert [request.full_url for request, _ in opener.requests] == [
        "https://gsnipers.snipers.com.cn/openapi.json",
        "https://gsnipers.snipers.com.cn/api/v1/auth/me",
    ]
    assert all(request.get_method() == "GET" for request, _ in opener.requests)


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


@pytest.mark.parametrize(
    "value",
    [
        "http://gsnipers.snipers.com.cn",
        "https://user@gsnipers.snipers.com.cn",
        "https://gsnipers.snipers.com.cn:444",
        "https://gsnipers.snipers.com.cn?tenant_id=4",
        "https://gsnipers.snipers.com.cn#fragment",
        "https://evil.example",
    ],
)
def test_production_origin_rejects_every_override_shape(value):
    with pytest.raises(acceptance.AcceptanceError):
        acceptance._validated_base_origin(value)


def test_redirect_handler_never_forwards_authorization_off_origin():
    handler = acceptance.SameOriginRedirectHandler()
    original = Request(
        "https://gsnipers.snipers.com.cn/api/v1/auth/me",
        method="GET",
        headers={"Authorization": "Bearer synthetic"},
    )

    with pytest.raises(acceptance.AcceptanceError, match="cross-origin"):
        handler.redirect_request(
            original, None, 302, "Found", {}, "https://evil.example/steal"
        )

    redirected = handler.redirect_request(
        original, None, 302, "Found", {}, "/api/v1/auth/me?again=1"
    )
    assert redirected.full_url.startswith("https://gsnipers.snipers.com.cn/")
    assert redirected.get_header("Authorization") == "Bearer synthetic"


def test_required_metrics_route_must_be_mounted_before_identity_read():
    fake = FakeGet({"/openapi.json": {"paths": {}}})

    with pytest.raises(acceptance.AcceptanceError, match="not mounted"):
        acceptance.run_acceptance(fake)

    assert fake.calls == [("/openapi.json", None)]


@pytest.mark.parametrize("status", ["paused", "archived"])
def test_non_selectable_site_stops_before_data_probes(status):
    site = {**tiger_site(), "status": status}
    responses = base_responses([site])
    responses["/api/v1/seo/workbench/sites"]["selection_policy"] = {
        "selectable_statuses": ["active"],
        "disabled_statuses": ["paused", "archived"],
    }
    fake = FakeGet(responses)

    result = acceptance.run_acceptance(fake)

    assert result["status"] == "site_unavailable"
    assert result["site_unavailable_reasons"] == ["site_status_not_selectable"]
    assert len(fake.calls) == 5


def test_paused_selectable_policy_drift_fails_closed_before_data_probes():
    site = {**tiger_site(), "status": "paused"}
    responses = base_responses([site])
    responses["/api/v1/seo/workbench/sites"]["selection_policy"] = {
        "selectable_statuses": ["active", "paused"],
        "disabled_statuses": ["archived"],
    }
    fake = FakeGet(responses)

    result = acceptance.run_acceptance(fake)

    assert result["status"] == "site_unavailable"
    assert result["site_unavailable_reasons"] == ["selection_policy_mismatch"]
    assert len(fake.calls) == 5


@pytest.mark.parametrize(
    "workbench_site,reason",
    [
        (None, "expected_domain_presence_mismatch_between_site_lists"),
        ({**tiger_site(), "domain": "https://wrong.example/"}, "expected_domain_presence_mismatch_between_site_lists"),
        ({**tiger_site(), "domain": "http://www.tiger-coatings.cn/"}, "domain_mismatch_between_site_lists"),
        ({**tiger_site(), "status": "paused"}, "status_mismatch_between_site_lists"),
    ],
)
def test_site_list_drift_is_unavailable_and_stops(workbench_site, reason):
    responses = base_responses([tiger_site()])
    responses["/api/v1/seo/workbench/sites"]["sites"] = (
        [] if workbench_site is None else [workbench_site]
    )
    fake = FakeGet(responses)

    result = acceptance.run_acceptance(fake)

    assert result["status"] == "site_unavailable"
    assert reason in result["site_unavailable_reasons"]
    assert len(fake.calls) == 5


def test_workbench_only_expected_domain_is_unavailable_not_empty():
    responses = base_responses([])
    responses["/api/v1/seo/workbench/sites"]["sites"] = [tiger_site()]
    fake = FakeGet(responses)

    result = acceptance.run_acceptance(fake)

    assert result["status"] == "site_unavailable"
    assert result["site_unavailable_reasons"] == [
        "expected_domain_presence_mismatch_between_site_lists"
    ]
    assert len(fake.calls) == 5


def test_expected_domain_id_set_drift_is_unavailable_before_empty_decision():
    responses = base_responses([tiger_site()])
    responses["/api/v1/seo/workbench/sites"]["sites"] = [
        {**tiger_site(), "id": 45}
    ]
    fake = FakeGet(responses)

    result = acceptance.run_acceptance(fake)

    assert result["status"] == "site_unavailable"
    assert result["site_unavailable_reasons"] == [
        "expected_domain_id_set_mismatch_between_site_lists"
    ]
    assert len(fake.calls) == 5


def test_duplicate_expected_domain_is_unavailable_not_an_exception():
    duplicate = {**tiger_site(), "id": 45}
    fake = FakeGet(base_responses([tiger_site(), duplicate]))

    result = acceptance.run_acceptance(fake)

    assert result["status"] == "site_unavailable"
    assert result["site_unavailable_reasons"] == [
        "expected_domain_duplicate_in_admin_list"
    ]
    assert len(fake.calls) == 5


def test_admin_canonical_domain_drift_is_unavailable_not_empty():
    site = {**tiger_site(), "canonical_domain": "www.tiger-coatings.cn"}
    fake = FakeGet(base_responses([site]))

    result = acceptance.run_acceptance(fake)

    assert result["status"] == "site_unavailable"
    assert result["site_unavailable_reasons"] == [
        "canonical_domain_mismatch_in_admin_list"
    ]
    assert len(fake.calls) == 5
