import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace


os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "ci-dummy")
os.environ.setdefault("BAIDU_SECRET_KEY", "ci-dummy-secret1")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "ci-dummy")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "ci-dummy")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00+00:00")
os.environ.setdefault(
    "CRYPTO_MASTER_KEY_B64", "j/QGqbWO8IVw9cCVeAq+u/alTyjLsSQXjROH9uW/3tA="
)
os.environ.setdefault("ADMIN_API_KEY", "ci-admin-key")

from app.api.search_terms import _action_dict  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]


def test_action_api_exposes_budget_change_and_execution_context():
    row = SimpleNamespace(
        id=41,
        baidu_account_id=7,
        action_type="set_campaign_budget",
        word="2026_竞品计划_Mob",
        match_mode=None,
        price=None,
        old_value=50,
        new_value=50,
        campaign_name="2026_竞品计划_Mob",
        adgroup_id=None,
        adgroup_name=None,
        dry_run=True,
        status="dry_run",
        error_msg=None,
        operator_name="superadmin",
        created_at=datetime(2026, 9, 1, 20, 38),
    )

    result = _action_dict(row)

    assert result["baidu_account_id"] == 7
    assert result["old_value"] == 50.0
    assert result["new_value"] == 50.0
    assert result["execution_mode"] == "dry_run"
    assert result["execution_mode_label"] == "演练（未修改百度）"


def test_action_ledger_renders_budget_details_without_exposing_raw_response():
    source = (ROOT / "frontend/src/views/verify/AdjustmentLogView.vue").read_text(
        encoding="utf-8"
    )

    assert "匹配 / 变更" in source
    assert "actionChangeText(row)" in source
    assert "fmtMoney(row.old_value)" in source
    assert "fmtMoney(row.new_value)" in source
    assert "actionAccountLabel(row)" in source
    assert "仅记录台账，未修改百度账户" in source
    assert "row.baidu_response" not in source
