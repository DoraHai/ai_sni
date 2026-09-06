"""Permission mapping parity for the GEO cockpit contract."""

import pytest

from app.security.auth import _required


@pytest.mark.parametrize(
    ("path", "method", "expected"),
    [
        ("/api/v1/geo/integration/metrics/snapshot", "GET", ({"geo.content"}, False)),
        ("/api/v1/geo/integration/metrics/dictionary", "HEAD", ({"geo.content"}, False)),
        ("/api/v1/geo/integration/read/period-context", "GET", ({"geo.content"}, False)),
        ("/api/v1/geo/integration/read/questions", "GET", ({"geo.content"}, False)),
        ("/api/v1/geo/integration/read/answers", "OPTIONS", ({"geo.content"}, False)),
        ("/api/v1/geo/integration/read/answers/8", "GET", ({"geo.content"}, False)),
        ("/api/v1/geo/integration/read/capabilities", "GET", ({"geo.content"}, False)),
        ("/api/v1/geo/integration/read/async-jobs", "GET", ({"geo.content"}, False)),
        ("/api/v1/geo/integration/read/async-jobs/8", "GET", ({"geo.content"}, False)),
        ("/api/v1/geo/integration/read/patrol-runs", "GET", ({"geo.content"}, False)),
        ("/api/v1/geo/integration/read/patrol-runs/8", "GET", ({"geo.content"}, False)),
        ("/api/v1/geo/integration/read/content-tasks/8", "GET", ({"geo.content"}, False)),
        ("/api/v1/geo/integration/tasks", "GET", ({"geo.content"}, False)),
        ("/api/v1/geo/integration/tasks", "POST", ({"geo.content"}, True)),
        ("/api/v1/geo/integration/tasks/7", "GET", ({"geo.content"}, False)),
        ("/api/v1/geo/integration/tasks/7", "PATCH", ({"geo.content"}, True)),
        ("/api/v1/geo/integration/tasks/7/baseline", "POST", ({"geo.content"}, True)),
        ("/api/v1/geo/integration/tasks/7/retest-plan", "GET", ({"geo.content"}, False)),
        ("/api/v1/geo/integration/tasks/7/retest", "POST", ({"geo.content"}, True)),
        ("/api/v1/geo/integration/tasks/7/publication-check", "POST", ({"geo.content"}, True)),
        ("/api/v1/geo/integration/tasks/7/execution-readiness", "GET", ({"geo.content"}, False)),
        ("/api/v1/geo/integration/tasks/7/baseline-readiness", "GET", ({"geo.content"}, False)),
        ("/api/v1/geo/integration/read/future", "DELETE", ({"geo.content"}, True)),
    ],
)
def test_integration_routes_match_production_geo_content_permissions(path, method, expected):
    assert _required(path, method) == expected


@pytest.mark.parametrize(
    ("path", "method", "expected"),
    [
        ("/api/v1/geo/integration", "GET", ({"geo.diagnosis"}, False)),
        ("/api/v1/geo/integration-other", "GET", ({"geo.diagnosis"}, False)),
        ("/api/v1/geo/prompts", "GET", ({"geo.content"}, False)),
        ("/api/v1/geo/prompts", "POST", ({"geo.content"}, True)),
        ("/api/v1/geo/audits", "POST", ({"geo.diagnosis"}, False)),
        ("/api/v1/geo/unknown", "GET", ({"geo.diagnosis"}, False)),
    ],
)
def test_integration_mapping_keeps_boundary_and_existing_geo_rules(path, method, expected):
    assert _required(path, method) == expected
