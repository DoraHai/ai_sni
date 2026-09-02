import os
import re
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
from app.models import WRITEBACK_ACTION_LABELS  # noqa: E402


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
        baidu_response="must-not-be-exposed",
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
    assert "baidu_response" not in result


def test_action_api_exposes_live_execution_context():
    row = SimpleNamespace(
        id=42,
        baidu_account_id=8,
        action_type="set_adgroup_bid",
        word="测试单元",
        match_mode=None,
        price=None,
        old_value=None,
        new_value=3.5,
        campaign_name="测试计划",
        adgroup_id=19,
        adgroup_name="测试单元",
        dry_run=False,
        status="success",
        error_msg=None,
        operator_name="operator",
        created_at=datetime(2026, 9, 1, 21, 0),
    )

    result = _action_dict(row)

    assert result["old_value"] is None
    assert result["new_value"] == 3.5
    assert result["execution_mode"] == "live"
    assert result["execution_mode_label"] == "真实执行"


def test_frontend_action_filters_cover_every_backend_action_type():
    source = (ROOT / "frontend/src/utils/actionLedger.js").read_text(encoding="utf-8")
    frontend_codes = set(re.findall(r"\{ code: '([^']+)'", source))

    assert frontend_codes == set(WRITEBACK_ACTION_LABELS)
