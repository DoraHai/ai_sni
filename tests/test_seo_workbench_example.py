import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.seo_workbench_adapter import WorkbenchPayloadError


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "seo_phase1_workbench.json"
SPEC = importlib.util.spec_from_file_location(
    "render_seo_workbench_example", ROOT / "scripts" / "render_seo_workbench_example.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def by_id(result, scenario_id):
    return next(row for row in result["items"] if row["scenario_id"] == scenario_id)


def message(item, kind):
    return next(row["text"] for row in item["customer_messages"] if row["kind"] == kind)


def test_end_to_end_example_renders_all_eight_scenarios_from_raw():
    document = fixture()
    # Prove that expected_workbench is test metadata, not consumer input.
    for scenario in document["scenarios"]:
        scenario["expected_workbench"] = {"must_not_be_read": object()}
    result = MODULE.render_document(document, "test-request")
    assert result["item_count"] == 8
    assert {row["scenario_id"] for row in result["items"]} == {
        "approved_unpublished",
        "multi_platform_mixed",
        "missing_url",
        "unmapped_url",
        "ambiguous_url",
        "matched_not_checked",
        "latest_failed_old_success",
        "historical_self_review",
    }


def test_customer_messages_keep_review_publication_check_and_clicks_separate():
    result = MODULE.render_document(fixture(), "test-request")
    approved = by_id(result, "approved_unpublished")
    assert approved["view"]["content"]["label"] == "已审核待发布"
    assert message(approved, "review") == "审核通过"
    assert message(approved, "publication") == "尚无分平台发布记录。"
    assert "未知" in message(approved, "page_check")
    assert "不可用" in message(approved, "search_performance")
    assert approved["view"]["search_performance"]["article_clicks"] is None

    mixed = by_id(result, "multi_platform_mixed")
    assert "成功 1 条，失败 1 条" in message(mixed, "publication")
    assert mixed["view"]["page_evidence"]["passed"] is None


@pytest.mark.parametrize(
    ("scenario_id", "mapping_state", "message_fragment"),
    [
        ("missing_url", "missing_url", "没有发布地址"),
        ("unmapped_url", "unmapped", "尚未关联"),
        ("ambiguous_url", "ambiguous", "多个候选页面"),
        ("matched_not_checked", "source_page_only", "不能当作实际发布页面"),
        ("latest_failed_old_success", "source_page_only", "不能当作实际发布页面"),
    ],
)
def test_page_mapping_messages_do_not_overstate_evidence(
    scenario_id, mapping_state, message_fragment
):
    item = by_id(MODULE.render_document(fixture(), "test-request"), scenario_id)
    assert item["view"]["page_evidence"]["mapping_state"] == mapping_state
    assert item["view"]["page_evidence"]["passed"] is None
    assert message_fragment in message(item, "page_check")


def test_historical_self_review_is_explained():
    item = by_id(
        MODULE.render_document(fixture(), "test-request"), "historical_self_review"
    )
    assert item["view"]["review"]["independent"] is False
    assert message(item, "review") == "历史审核，独立性未确认"


@pytest.mark.parametrize(
    "change",
    [
        {"synthetic": False},
        {"production_data": True},
        {"executable_urls": True},
    ],
)
def test_example_entry_refuses_non_synthetic_or_executable_documents(change):
    document = fixture()
    document.update(change)
    with pytest.raises(WorkbenchPayloadError):
        MODULE.render_document(document, "test-request")


def test_consumer_input_keeps_candidate_scope_checks():
    document = fixture()
    scenario = next(row for row in document["scenarios"] if row["id"] == "ambiguous_url")
    scenario["consumer_input"]["page_candidates"][0]["tenant_id"] = 1
    with pytest.raises(WorkbenchPayloadError):
        MODULE.render_document(document, "test-request")


def test_committed_customer_example_matches_renderer():
    expected = MODULE.render_document(fixture(), "offline-example")
    committed = json.loads(
        (ROOT / "docs" / "examples" / "seo_workbench_customer_example.json").read_text(
            encoding="utf-8"
        )
    )
    assert committed == expected


def test_json_roundtrip_preserves_latest_publication_attempt():
    document = fixture()
    scenario = next(row for row in document["scenarios"] if row["id"] == "missing_url")
    scenario["consumer_input"] = {
        "attempts_by_publication": {
            92001: [
                {
                    "id": 95001,
                    "action": "sync",
                    "status": "failed",
                    "error": "虚构同步失败",
                    "started_at": "2026-09-06T08:00:00Z",
                    "completed_at": "2026-09-06T08:01:00Z",
                }
            ]
        }
    }
    # JSON changes the integer mapping key to a string, as real fixture input does.
    roundtripped = json.loads(json.dumps(document, ensure_ascii=False))
    item = by_id(MODULE.render_document(roundtripped, "test-request"), "missing_url")
    assert item["view"]["publications"][0]["latest_attempt"] == {
        "id": 95001,
        "action": "sync",
        "status": "failed",
        "error": "虚构同步失败",
        "started_at": "2026-09-06T08:00:00Z",
        "completed_at": "2026-09-06T08:01:00Z",
    }


@pytest.mark.parametrize("key", ["0", "-1", "1.5", "publication", True])
def test_attempt_publication_key_must_be_a_strict_positive_integer(key):
    with pytest.raises(WorkbenchPayloadError):
        MODULE.normalize_attempts_by_publication({key: []})


def test_attempt_publication_keys_cannot_collide_after_normalization():
    with pytest.raises(WorkbenchPayloadError):
        MODULE.normalize_attempts_by_publication({1: [], "01": []})
