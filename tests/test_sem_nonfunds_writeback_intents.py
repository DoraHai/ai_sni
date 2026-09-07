import ast
import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "1234567890abcdefsecret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.baidu.writeback import apply_campaign_pause_writeback


ROOT = Path(__file__).resolve().parents[1]
NON_FUNDS_ACTIONS = {
    "apply_negative_writeback",
    "apply_negative_batch_writeback",
    "apply_negative_writeback_campaign",
    "apply_add_word_writeback",
    "apply_pause_writeback",
    "apply_match_type_writeback",
    "apply_remove_negative_writeback",
    "apply_campaign_pause_writeback",
    "apply_campaign_schedule_writeback",
    "apply_campaign_region_writeback",
    "apply_adgroup_pause_writeback",
    "apply_adgroup_landing_url_writeback",
}


def test_every_nonfunds_action_persists_live_intent_and_classifies_uncertain_errors() -> None:
    source = (ROOT / "app/baidu/writeback.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    for name in NON_FUNDS_ACTIONS:
        calls = {
            node.func.id
            for node in ast.walk(functions[name])
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        if name == "apply_negative_batch_writeback":
            assert "_ensure_no_unresolved_funds_writeback" in calls, name
            assert "_record_writeback_exception" in calls, name
            assert any(
                isinstance(node, ast.Await)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr == "commit"
                for node in ast.walk(functions[name])
            ), name
        else:
            assert "_persist_action_intent" in calls, name
            assert "_record_writeback_exception" in calls, name


def test_live_nonfunds_timeout_keeps_durable_reconciliation_record() -> None:
    events: list[str] = []
    campaign = SimpleNamespace(
        baidu_account_id=88,
        campaign_id=12,
        campaign_name="品牌计划",
        pause=False,
    )
    account = SimpleNamespace(id=88, status="active")
    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[campaign, None]),
        add=Mock(),
        flush=AsyncMock(),
        refresh=AsyncMock(),
    )

    async def commit() -> None:
        events.append("commit")

    session.commit = AsyncMock(side_effect=commit)

    async def timeout(*_args, **_kwargs):
        events.append("remote")
        raise TimeoutError("upstream timeout")

    service = SimpleNamespace(update_campaign_pause=AsyncMock(side_effect=timeout))

    async def run():
        with (
            patch("app.baidu.writeback._active_account", new=AsyncMock(return_value=account)),
            patch("app.baidu.writeback._account_client", return_value=object()),
            patch("app.baidu.writeback.CampaignService", return_value=service),
            patch(
                "app.baidu.writeback.get_settings",
                return_value=SimpleNamespace(
                    baidu_write_dry_run=False,
                    baidu_write_is_dry_run=lambda tenant_id, account_id, scope: False,
                ),
            ),
        ):
            return await apply_campaign_pause_writeback(
                session,
                7,
                12,
                True,
                operator_user_id=3,
                operator_name="tester",
            )

    record = asyncio.run(run())

    assert events == ["commit", "remote", "commit"]
    assert record.status == "reconcile"
    assert record.error_msg.startswith("执行结果未知，需人工对账：")
    assert campaign.pause is False


def test_unresolved_live_nonfunds_action_blocks_remote_call() -> None:
    campaign = SimpleNamespace(
        baidu_account_id=88,
        campaign_id=12,
        campaign_name="品牌计划",
        pause=False,
    )
    account = SimpleNamespace(id=88, status="active")
    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[campaign, 321]),
        add=Mock(),
        flush=AsyncMock(),
        refresh=AsyncMock(),
        commit=AsyncMock(),
    )
    remote = AsyncMock()

    async def run():
        with (
            patch("app.baidu.writeback._active_account", new=AsyncMock(return_value=account)),
            patch("app.baidu.writeback.CampaignService.update_campaign_pause", remote),
            patch(
                "app.baidu.writeback.get_settings",
                return_value=SimpleNamespace(
                    baidu_write_dry_run=False,
                    baidu_write_is_dry_run=lambda tenant_id, account_id, scope: False,
                ),
            ),
        ):
            return await apply_campaign_pause_writeback(
                session,
                7,
                12,
                True,
                operator_user_id=3,
                operator_name="tester",
            )

    try:
        asyncio.run(run())
    except Exception as exc:
        assert "#321" in str(exc)
    else:
        raise AssertionError("unresolved writeback should block a second live action")

    remote.assert_not_awaited()
    session.commit.assert_not_awaited()
