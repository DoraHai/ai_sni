"""Read-only contract for the first SEM controlled-action workflow."""
import os
from datetime import datetime
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "ci-dummy")
os.environ.setdefault("BAIDU_SECRET_KEY", "1234567890abcdef")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "ci-dummy")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "ci-dummy")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00+00:00")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "j/QGqbWO8IVw9cCVeAq+u/alTyjLsSQXjROH9uW/3tA=")
os.environ.setdefault("ADMIN_API_KEY", "ci-admin-key")

from app.api.writeback import _build_action_flow


def row(**overrides):
    values = {
        "id": 71,
        "status": "dry_run",
        "dry_run": True,
        "approval_id": None,
        "baidu_account_id": 17,
        "keyword_id": 701,
        "campaign_id": 702,
        "adgroup_id": 703,
        "match_mode": None,
        "created_at": datetime(2026, 9, 11, 9, 30),
        "executed_at": datetime(2026, 9, 11, 9, 30),
        "error_msg": None,
        "reconciliation_result": None,
        "reconciliation_note": None,
        "action_type": None,
        "keyword": "TIGER粉末涂料",
        "word": "TIGER粉末涂料",
        "old_bid": 8.0,
        "new_bid": 8.6,
        "old_value": None,
        "new_value": None,
        "baidu_response": "must-not-be-exposed",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_keyword_bid_flow_keeps_dry_run_as_record_only():
    flow = _build_action_flow("bid", row(), {"keyword_bid"})

    assert flow["version"] == "sem-controlled-action-v1"
    assert flow["family"] == "keyword_bid"
    assert flow["control"] == {
        "permission": "optimize.keywords",
        "write_scope": "keyword_bid",
        "recorded_mode": "dry_run",
        "account_action_scope_state": "configured",
        "approval_required_for_live": True,
        "approval_id": None,
        "default_behavior": "record_only",
        "existing_gates": [
            "authenticated_identity",
            "tenant_scope",
            "sem_identity",
            "optimize.keywords",
            "account_scope:keyword_bid",
            "one_time_funds_confirmation",
        ],
    }
    assert flow["result"]["stage"] == "pending_writeback"
    assert flow["result"]["readback_status"] == "not_sent"
    assert flow["result"]["confirmed_at"] is None
    assert flow["check_basis"]["before"] == 8.0
    assert flow["check_basis"]["requested"] == 8.6
    assert flow["steps"][1] == {"code": "control", "label": "受控执行", "state": "held"}
    assert "baidu_response" not in str(flow)


def test_keyword_pause_flow_reports_confirmed_live_result_without_new_approval_gate():
    flow = _build_action_flow(
        "action",
        row(action_type="pause", status="success", dry_run=False),
        {"keyword_pause"},
    )

    assert flow["family"] == "keyword_pause"
    assert flow["control"]["permission"] == "optimize.keywords"
    assert flow["control"]["approval_required_for_live"] is False
    assert flow["control"]["account_action_scope_state"] == "configured"
    assert flow["result"]["stage"] == "executed"
    assert flow["result"]["readback_status"] == "platform_success_recorded"
    assert flow["result"]["confirmed_at"] == "2026-09-11T09:30:00"


def test_negative_flow_distinguishes_adgroup_and_campaign_live_scopes():
    adgroup = _build_action_flow(
        "action", row(action_type="negative", keyword_id=None), {"adgroup_negative_words"}
    )
    campaign = _build_action_flow(
        "action",
        row(action_type="negative", keyword_id=None, adgroup_id=None),
        {"adgroup_negative_words"},
    )

    assert adgroup["family"] == campaign["family"] == "negative_word"
    assert adgroup["control"]["write_scope"] == "adgroup_negative_words"
    assert adgroup["control"]["account_action_scope_state"] == "configured"
    assert campaign["control"]["write_scope"] == "campaign_negative_words"
    assert campaign["control"]["account_action_scope_state"] == "scope_disabled"

    unavailable = _build_action_flow(
        "action", row(action_type="negative", keyword_id=None), None
    )
    assert unavailable["control"]["account_action_scope_state"] == "account_unavailable"


def test_uncertain_result_requires_external_basis_and_never_implies_success():
    flow = _build_action_flow(
        "action",
        row(action_type="enable", status="reconcile", dry_run=False, error_msg="timeout"),
        {"keyword_pause"},
    )

    assert flow["result"]["stage"] == "reconciliation_required"
    assert flow["result"]["confirmed_at"] is None
    assert flow["result"]["readback_status"] == "needs_external_confirmation"
    assert flow["check_basis"]["external_confirmation_required"] is True
    assert flow["steps"][2]["state"] == "attention"
    assert flow["steps"][3]["state"] == "attention"
    assert "不要重复提交" in flow["next_action"]


def test_non_priority_action_keeps_legacy_queue_shape():
    assert _build_action_flow("action", row(action_type="set_match_type"), set()) is None
