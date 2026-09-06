import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.seo_workbench_adapter import (
    StaleWorkbenchResponse,
    WorkbenchPayloadError,
    WorkbenchResponseContext,
    adapt_seo_workbench_item,
)


FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "seo_phase1_workbench.json").read_text(
        encoding="utf-8"
    )
)
CONTEXT = WorkbenchResponseContext(tenant_id=99001, site_id=99002, request_id="request-8")


def scenario(name):
    return next(row for row in FIXTURES["scenarios"] if row["id"] == name)


def adapt(name, **kwargs):
    row = scenario(name)
    return adapt_seo_workbench_item(
        row["raw"],
        expected_context=CONTEXT,
        response_context=CONTEXT,
        **kwargs,
    )


def test_all_eight_synthetic_scenarios_are_consumable_without_expected_fields():
    for row in FIXTURES["scenarios"]:
        # expected_workbench is deliberately excluded from adapter input.
        candidates = (93001, 93002) if row["id"] == "ambiguous_url" else ()
        result = adapt_seo_workbench_item(
            row["raw"],
            expected_context=CONTEXT,
            response_context=CONTEXT,
            page_candidates=[
                {"id": page_id, "tenant_id": 99001, "site_id": 99002}
                for page_id in candidates
            ],
        )
        assert result["content"]["id"] == row["raw"]["content"]["id"]
        assert result["search_performance"]["article_clicks"] is None
        assert result["search_performance"]["state"] == "unavailable"


def test_review_publication_and_page_states_stay_independent():
    approved = adapt("approved_unpublished")
    assert approved["content"]["label"] == "已审核待发布"
    assert approved["review"] == {
        "state": "approved",
        "label": "审核通过",
        "independent": True,
        "reviewed_at": "2026-09-06T06:00:00Z",
    }
    assert approved["publication_summary"]["record_count"] == 0
    assert approved["page_evidence"]["check_state"] == "not_checked"
    assert approved["page_evidence"]["passed"] is None

    mixed = adapt("multi_platform_mixed")
    assert mixed["publication_summary"] == {
        "record_count": 2,
        "successful_count": 1,
        "failed_count": 1,
    }
    assert mixed["publications"][0]["page_url"]
    assert mixed["publications"][1]["failure"] == "虚构故障：发布接口未确认"


@pytest.mark.parametrize(
    ("name", "candidates", "expected"),
    [
        ("missing_url", (), "missing_url"),
        ("unmapped_url", (), "unmapped"),
        ("ambiguous_url", (93001, 93002), "ambiguous"),
        ("matched_not_checked", (), "source_page_only"),
    ],
)
def test_page_mapping_requires_explicit_evidence(name, candidates, expected):
    result = adapt(
        name,
        page_candidates=[
            {"id": page_id, "tenant_id": 99001, "site_id": 99002}
            for page_id in candidates
        ],
    )
    assert result["page_evidence"]["mapping_state"] == expected


def test_latest_failed_snapshot_is_current_and_old_success_is_not_reused():
    raw = deepcopy(scenario("latest_failed_old_success")["raw"])
    page_url = raw["page_detail"]["page"]["url"]
    raw["content"]["page_url"] = page_url
    result = adapt_seo_workbench_item(
        raw,
        expected_context=CONTEXT,
        response_context=CONTEXT,
        page_binding={
            "tenant_id": 99001,
            "site_id": 99002,
            "page_id": 93001,
            "target_kind": "content_page_url",
            "page_url": page_url,
        },
    )
    evidence = result["page_evidence"]
    assert evidence["check_state"] == "unavailable"
    assert evidence["passed"] is None
    assert evidence["latest_snapshot_id"] == 94002
    assert evidence["http_status"] is None
    assert evidence["failure"] == "虚构超时"


def test_historical_self_review_is_not_presented_as_independent():
    review = adapt("historical_self_review")["review"]
    assert review["state"] == "approved"
    assert review["independent"] is False
    assert review["label"] == "历史审核，独立性未确认"


def test_latest_attempt_is_exposed_without_changing_publication_success():
    attempts = [
        {
            "id": 1,
            "publication_id": 92001,
            "action": "publish",
            "status": "success",
            "started_at": "2026-09-06T06:00:00Z",
            "completed_at": "2026-09-06T06:01:00Z",
            "error": None,
        },
        {
            "id": 2,
            "publication_id": 92001,
            "action": "sync",
            "status": "failed",
            "started_at": "2026-09-06T07:00:00Z",
            "completed_at": "2026-09-06T07:01:00Z",
            "error": "虚构同步失败",
        },
    ]
    result = adapt("missing_url", attempts_by_publication={92001: attempts})
    publication = result["publications"][0]
    assert publication["state"] == "published"
    assert publication["latest_attempt"]["id"] == 2
    assert publication["latest_attempt"]["error"] == "虚构同步失败"
    assert publication["failure"] is None


@pytest.mark.parametrize("target", ["content", "publication", "page"])
def test_cross_scope_rows_are_rejected(target):
    raw = deepcopy(scenario("latest_failed_old_success")["raw"])
    if target == "content":
        raw["content"]["tenant_id"] = 1
    elif target == "publication":
        raw = deepcopy(scenario("multi_platform_mixed")["raw"])
        raw["publications"][0]["tenant_id"] = 1
    else:
        raw["page_detail"]["page"]["site_id"] = 1
    with pytest.raises(WorkbenchPayloadError):
        adapt_seo_workbench_item(
            raw, expected_context=CONTEXT, response_context=CONTEXT
        )


def test_late_or_switched_response_is_rejected_before_payload_mapping():
    raw = scenario("approved_unpublished")["raw"]
    for actual in (
        WorkbenchResponseContext(99001, 99002, "request-7"),
        WorkbenchResponseContext(99001, 12345, "request-8"),
        WorkbenchResponseContext(12345, 99002, "request-8"),
    ):
        with pytest.raises(StaleWorkbenchResponse):
            adapt_seo_workbench_item(
                raw, expected_context=CONTEXT, response_context=actual
            )


def test_cross_scope_page_candidate_is_rejected():
    with pytest.raises(WorkbenchPayloadError):
        adapt(
            "ambiguous_url",
            page_candidates=[{"id": 93001, "tenant_id": 1, "site_id": 99002}],
        )


def test_publication_failure_and_latest_attempt_are_not_conflated():
    attempts = [
        {
            "id": 3,
            "action": "sync",
            "status": "success",
            "started_at": "2026-09-06T08:00:00Z",
            "completed_at": "2026-09-06T08:01:00Z",
            "error": None,
        }
    ]
    result = adapt("multi_platform_mixed", attempts_by_publication={92002: attempts})
    failed_publication = result["publications"][1]
    assert failed_publication["latest_attempt"]["status"] == "success"
    assert failed_publication["failure"] == "虚构故障：发布接口未确认"


@pytest.mark.parametrize(
    "overrides",
    [
        {"publications": ["invalid"]},
        {"publications": [{"id": 1, "tenant_id": "invalid", "content_id": 91001}]},
        {"page_detail": "invalid"},
        {"page_detail": {"page": "invalid"}},
    ],
)
def test_malformed_scoped_rows_fail_closed(overrides):
    raw = deepcopy(scenario("approved_unpublished")["raw"])
    raw.update(overrides)
    with pytest.raises(WorkbenchPayloadError):
        adapt_seo_workbench_item(raw, expected_context=CONTEXT, response_context=CONTEXT)


def test_malformed_attempt_fails_closed():
    with pytest.raises(WorkbenchPayloadError):
        adapt("missing_url", attempts_by_publication={92001: ["invalid"]})


def test_fractional_scope_id_is_not_truncated_into_current_tenant():
    raw = deepcopy(scenario("approved_unpublished")["raw"])
    raw["content"]["tenant_id"] = 99001.5
    with pytest.raises(WorkbenchPayloadError):
        adapt_seo_workbench_item(raw, expected_context=CONTEXT, response_context=CONTEXT)


@pytest.mark.parametrize("bad_content_id", [91001.9, True])
def test_publication_content_id_uses_strict_integer_validation(bad_content_id):
    raw = deepcopy(scenario("multi_platform_mixed")["raw"])
    raw["publications"][0]["content_id"] = bad_content_id
    with pytest.raises(WorkbenchPayloadError):
        adapt_seo_workbench_item(raw, expected_context=CONTEXT, response_context=CONTEXT)


@pytest.mark.parametrize(
    ("submitted_by", "reviewed_by", "independent"),
    [(1, "1", False), (1, "2", True), (True, 2, False), (None, 2, False)],
)
def test_review_actor_ids_are_normalized_before_independence_check(
    submitted_by, reviewed_by, independent
):
    raw = deepcopy(scenario("approved_unpublished")["raw"])
    raw["content"]["review_submitted_by"] = submitted_by
    raw["content"]["reviewed_by"] = reviewed_by
    result = adapt_seo_workbench_item(raw, expected_context=CONTEXT, response_context=CONTEXT)
    assert result["review"]["independent"] is independent


def test_assessed_without_explicit_pass_basis_remains_unknown():
    raw = deepcopy(scenario("matched_not_checked")["raw"])
    page_url = raw["page_detail"]["page"]["url"]
    raw["content"]["page_url"] = page_url
    raw["page_detail"]["page"]["diagnostic"].update(
        assessment_state="assessed", checked_at="2026-09-06T08:00:00Z", http_status=200
    )
    result = adapt_seo_workbench_item(
        raw,
        expected_context=CONTEXT,
        response_context=CONTEXT,
        page_binding={
            "tenant_id": 99001,
            "site_id": 99002,
            "page_id": 93001,
            "target_kind": "content_page_url",
            "page_url": page_url,
        },
    )
    assert result["page_evidence"]["check_state"] == "assessed"
    assert result["page_evidence"]["passed"] is None


def test_source_page_detail_is_not_used_as_publication_page_evidence():
    result = adapt("latest_failed_old_success")
    assert result["page_evidence"] == {
        "mapping_state": "source_page_only",
        "page_id": None,
        "candidate_count": 0,
        "check_state": "not_checked",
        "checked_at": None,
        "latest_snapshot_id": None,
        "http_status": None,
        "failure": None,
        "passed": None,
    }


def test_platform_page_check_requires_an_explicit_publication_binding():
    raw = deepcopy(scenario("multi_platform_mixed")["raw"])
    page_url = raw["publications"][0]["page_url"]
    raw["page_detail"] = {
        "page": {
            "id": 93001,
            "tenant_id": 99001,
            "site_id": 99002,
            "url": page_url,
            "diagnostic": {
                "assessment_state": "assessed",
                "checked_at": "2026-09-06T08:00:00Z",
                "http_status": 200,
            },
        },
        "latest_snapshot": {"id": 94003, "status_code": 200, "fetch_error": None},
    }
    binding = {
        "tenant_id": 99001,
        "site_id": 99002,
        "page_id": 93001,
        "target_kind": "publication_page_url",
        "publication_id": 92001,
        "page_url": page_url,
    }
    result = adapt_seo_workbench_item(
        raw,
        expected_context=CONTEXT,
        response_context=CONTEXT,
        page_binding=binding,
    )
    assert result["page_evidence"]["mapping_state"] == "matched"
    assert result["page_evidence"]["check_state"] == "assessed"
    assert result["page_evidence"]["passed"] is None

    bad = deepcopy(binding)
    bad["page_url"] = "https://example.com/different"
    with pytest.raises(WorkbenchPayloadError):
        adapt_seo_workbench_item(
            raw,
            expected_context=CONTEXT,
            response_context=CONTEXT,
            page_binding=bad,
        )


def test_attempt_order_normalizes_timezone_offsets():
    attempts = [
        {"id": 1, "status": "failed", "started_at": "2026-09-06T09:30:00+08:00"},
        {"id": 2, "status": "success", "started_at": "2026-09-06T02:00:00Z"},
    ]
    result = adapt("missing_url", attempts_by_publication={92001: attempts})
    assert result["publications"][0]["latest_attempt"]["id"] == 2
