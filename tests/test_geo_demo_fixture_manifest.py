from datetime import date
from copy import deepcopy
from types import SimpleNamespace

from app.geo.demo_fixture_manifest import (
    EXPECTED_COUNTS,
    FIXTURE_MARKER,
    PROTECTED_TENANT_IDS,
    build_manifest,
    manifest_digest,
    validate_manifest,
)
from app.geo.content.sample_provenance import eligible_visibility_sample, sample_exclusion_reasons


def test_demo_manifest_is_deterministic_and_valid():
    first = build_manifest()
    second = build_manifest()
    assert validate_manifest(first) == []
    assert manifest_digest(first) == manifest_digest(second)
    assert first == second


def test_demo_manifest_has_required_coverage_and_isolation():
    manifest = build_manifest(date(2026, 9, 7))
    counts = manifest["counts"]
    assert counts == EXPECTED_COUNTS
    tenant = manifest["entities"]["tenants"][0]
    assert tenant["physical_id"] is None
    assert all(protected != tenant["physical_id"] for protected in PROTECTED_TENANT_IDS)
    assert manifest["time_contract"]["previous"] == {
        "start": "2026-08-24",
        "end": "2026-08-31",
    }
    assert manifest["time_contract"]["current"] == {
        "start": "2026-08-31",
        "end": "2026-09-07",
    }


def test_every_answer_is_visibly_simulated_and_formally_excluded():
    manifest = build_manifest()
    answers = manifest["entities"]["answer_snapshots"]
    assert len(answers) == 72
    assert {row["engine"] for row in answers} == {"deepseek", "qwen", "kimi"}
    assert all(row["simulated"] is True for row in answers)
    assert all(row["sample_mode"] == "mock_persona" for row in answers)
    assert all(FIXTURE_MARKER in row["raw_text"] for row in answers)
    assert all(row["formal_metric_eligible"] is False for row in answers)
    for row in answers:
        snapshot = SimpleNamespace(**row)
        assert eligible_visibility_sample(snapshot) is False
        assert "simulated_sample" in sample_exclusion_reasons(snapshot)
    official = manifest["expectations"]["official_metrics"]
    assert official["geo.visibility.ai_mention_count_7d"] == {
        "value": None,
        "trend_7d": None,
    }
    assert official["geo.visibility.ai_mention_rate_7d"] == {
        "value": None,
        "trend_7d": None,
    }
    assert official["geo.visibility.ai_visibility_score"] == {
        "value": None,
        "trend_7d": None,
    }


def test_demo_raw_comparison_is_non_official_and_has_two_complete_cohorts():
    manifest = build_manifest()
    comparison = manifest["expectations"]["demo_only_raw_comparison"]
    assert "never official" in comparison["label"]
    assert comparison["previous"]["sample_count"] == 36
    assert comparison["current"]["sample_count"] == 36
    assert comparison["previous"]["mention_count"] == 12
    assert comparison["current"]["mention_count"] == 18
    assert comparison["trend_7d"]["mention_count"] == {
        "direction": "up",
        "change_pct": 50.0,
        "change_abs": 6,
    }


def test_execution_and_publishing_surfaces_are_disabled():
    manifest = build_manifest()
    entities = manifest["entities"]
    assert entities["patrol_settings"] == [
        {
            "tenant_key": "g-snipers-geo-demo-v1:tenant:root",
            "enabled": False,
            "auto_persist": False,
            "prefer_real": False,
            "prompt_limit": 0,
            "engine_keys": [],
        }
    ]
    assert all(not engine["enabled"] for engine in entities["tracking_engines"])
    assert all(not channel["enabled"] for channel in entities["publishing_channels"])
    assert entities["channel_accounts"] == []
    assert entities["publications"] == []
    assert all(ticket["status"] != "done" for ticket in entities["action_tickets"])


def test_non_monday_week_end_is_rejected():
    try:
        build_manifest(date(2026, 9, 8))
    except ValueError as exc:
        assert "Monday" in str(exc)
    else:
        raise AssertionError("non-Monday week_end must fail")


def test_validator_rejects_metric_publish_and_reference_tampering():
    manifest = build_manifest()
    tampered = deepcopy(manifest)
    tampered["entities"]["answer_snapshots"][0]["simulated"] = False
    tampered["entities"]["publishing_channels"][0]["enabled"] = True
    tampered["entities"]["channel_variants"][0]["adapt_meta"]["publishable"] = True
    tampered["entities"]["content_tasks"][0]["prompt_key"] = (
        "g-snipers-geo-demo-v1:prompt:missing"
    )
    errors = validate_manifest(tampered)
    assert any("not forced simulated" in error for error in errors)
    assert "publishing channels must be disabled" in errors
    assert "every variant must be explicitly non-publishable" in errors
    assert any("unresolved logical reference" in error for error in errors)
