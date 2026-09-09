from __future__ import annotations

import hashlib
from datetime import date

from scripts.build_sem_demo_fixture import (
    ACCOUNT_IDS,
    FIXTURE_KEY,
    PROTECTED_TENANT_IDS,
    TENANT_ID,
    build_bundle,
    canonical_bytes,
    validate_bundle,
    write_bundle,
)


def test_bundle_is_deterministic_and_has_the_reviewed_object_counts(tmp_path):
    first = build_bundle(date(2026, 9, 8))
    second = build_bundle(date(2026, 9, 8))
    assert canonical_bytes(first) == canonical_bytes(second)
    assert first["manifest"]["counts"] == {
        "tenants": 1,
        "tenant_modules": 1,
        "baidu_accounts": 2,
        "campaigns": 4,
        "adgroups": 8,
        "keywords": 24,
        "kw_report_snapshots": 4112,
        "keyword_region_reports": 1344,
        "keyword_hourly_reports": 2688,
        "search_term_reports": 48,
        "alerts": 6,
        "sem_tasks": 5,
        "operation_records": 8,
    }
    output = tmp_path / "sem-demo.json"
    digest = write_bundle(first, output)
    assert digest == hashlib.sha256(output.read_bytes()).hexdigest()
    assert write_bundle(second, output) == digest


def test_bundle_is_isolated_from_real_tenants_and_execution_paths():
    bundle = build_bundle()
    assert TENANT_ID not in PROTECTED_TENANT_IDS
    assert 4 in bundle["manifest"]["tenant"]["protected_real_tenant_ids"]
    assert bundle["manifest"]["tenant"]["name"] == "G-Snipers 全域演示"
    assert bundle["manifest"]["safety"] == {
        "database_writes": False,
        "network_calls": False,
        "baidu_sync": False,
        "writeback": False,
        "all_external_accounts_disabled_demo": True,
    }
    accounts = bundle["tables"]["baidu_accounts"]
    assert {row["id"] for row in accounts} == set(ACCOUNT_IDS)
    assert all(row["status"] == "disabled" and row["auth_mode"] == "demo" for row in accounts)
    assert all(not row["scheduler_eligible"] and not row["writeback_allowed"] for row in accounts)
    assert all(row["credentials"] is None for row in accounts)
    validate_bundle(bundle)


def test_bundle_distinguishes_missing_reports_observed_zero_and_phone_states():
    bundle = build_bundle()
    rows = bundle["tables"]["kw_report_snapshots"]
    keyword_ids = {row["keyword_id"] for row in rows}
    assert 990_100_023 not in keyword_ids  # Asset-only, phone/report no_data.
    partial_ids = {990_100_021, 990_100_022}
    assert all(sum(row["keyword_id"] == keyword_id for row in rows) == 166 for keyword_id in partial_ids)
    assert any(row["impression"] == row["click"] == 0 and row["cost"] == 0 for row in rows)
    known = [row for row in rows if row["keyword_id"] == 990_100_001]
    partial = [row for row in rows if row["keyword_id"] == 990_100_009]
    unavailable = [row for row in rows if row["keyword_id"] == 990_100_013]
    assert all("ocpcConversionsDetail2" in row["raw_metrics"] for row in known)
    assert {"ocpcConversionsDetail2" in row["raw_metrics"] for row in partial} == {True, False}
    assert {row["raw_metrics"].get("ocpcConversionsDetail2") for row in unavailable} == {"unavailable"}
    assert "phone_no_data" in bundle["manifest"]["scenarios"]


def test_cleanup_scope_is_narrow_and_owned():
    bundle = build_bundle()
    cleanup = bundle["manifest"]["cleanup"]
    assert cleanup["mode"] == "review-only"
    assert cleanup["required_match"] == {"tenant_id": TENANT_ID, "fixture_key": FIXTURE_KEY}
    assert cleanup["delete_order"][-1] == "tenants"


def test_internal_ids_and_task_api_shapes_are_stable():
    bundle = build_bundle()
    for rows in bundle["tables"].values():
        assert len({row["id"] for row in rows}) == len(rows)
    allowed_metrics = {
        "sem.accounts.active_count": "up",
        "sem.approvals.pending_count": "down",
        "sem.identity.conflict_tenant_count": "down",
    }
    for task in bundle["tables"]["sem_tasks"]:
        assert set(task["params"]) == {"metric_key", "direction", "target_value"}
        assert task["params"]["direction"] == allowed_metrics[task["params"]["metric_key"]]
        assert (task["status"] == "done") == (task["completion_evidence"] is not None)
