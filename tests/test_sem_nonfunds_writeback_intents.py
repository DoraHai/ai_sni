import ast
import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "1234567890abcdefsecret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.baidu.writeback import (
    WritebackError,
    _relock_action_intent,
    apply_adgroup_landing_url_writeback,
    apply_adgroup_pause_writeback,
    apply_campaign_pause_writeback,
    apply_match_type_writeback,
    apply_pause_writeback,
)


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


@pytest.fixture(autouse=True)
def _configured_live_policy(monkeypatch):
    async def resolve(*_args, **_kwargs):
        return SimpleNamespace(dry_run=False)

    monkeypatch.setattr("app.baidu.writeback.resolve_live_write_decision", resolve)


def test_disabled_account_cannot_overwrite_reconciled_action() -> None:
    asset = SimpleNamespace(baidu_account_id=88)
    account = SimpleNamespace(id=88, status="active")
    record = SimpleNamespace(
        id=15,
        status="pending",
        reconciliation_result=None,
        error_msg=None,
        executed_at=None,
    )

    async def refresh(row, **_kwargs):
        if row is account:
            account.status = "disabled"
        elif row is record:
            record.status = "success"
            record.reconciliation_result = "confirmed_executed"
            record.error_msg = "manual reconciliation preserved"

    session = SimpleNamespace(refresh=AsyncMock(side_effect=refresh), commit=AsyncMock())
    with pytest.raises(WritebackError, match="已被处理为 success"):
        asyncio.run(
            _relock_action_intent(
                session, record, asset=asset, account=account
            )
        )

    assert record.status == "success"
    assert record.reconciliation_result == "confirmed_executed"
    assert record.error_msg == "manual reconciliation preserved"
    session.commit.assert_not_awaited()


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
    assert (record.old_value, record.new_value) == (0, 1)


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


def test_intent_reconciled_during_commit_gap_never_calls_remote() -> None:
    campaign = SimpleNamespace(
        baidu_account_id=88,
        campaign_id=12,
        campaign_name="品牌计划",
        pause=False,
    )
    account = SimpleNamespace(id=88, status="active")
    captured = []

    async def refresh(row, **_kwargs):
        if row in captured:
            row.id = 901
            row.status = "failed"
            row.reconciliation_result = "confirmed_not_executed"

    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[campaign, None]),
        add=lambda record: captured.append(record),
        flush=AsyncMock(),
        refresh=AsyncMock(side_effect=refresh),
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
        assert "#901" in str(exc)
        assert "failed" in str(exc)
    else:
        raise AssertionError("a reconciled intent must not resume")

    remote.assert_not_awaited()
    assert captured[0].status == "failed"
    assert captured[0].reconciliation_result == "confirmed_not_executed"


def _adgroup() -> SimpleNamespace:
    return SimpleNamespace(
        baidu_account_id=88,
        campaign_id=12,
        adgroup_id=44,
        adgroup_name="测试单元",
        pause=False,
        pc_final_url="https://old.example/pc",
        mobile_final_url="https://old.example/mobile",
        pc_track_param=None,
        mobile_track_param=None,
        pc_track_template=None,
        mobile_track_template=None,
    )


def _live_settings() -> SimpleNamespace:
    return SimpleNamespace(
        baidu_write_dry_run=False,
        baidu_write_is_dry_run=lambda tenant_id, account_id, scope: False,
    )


def test_live_adgroup_pause_reaches_remote_and_finishes_successfully() -> None:
    adgroup = _adgroup()
    account = SimpleNamespace(id=88, status="active")
    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[adgroup, None]),
        add=Mock(),
        flush=AsyncMock(),
        refresh=AsyncMock(),
        commit=AsyncMock(),
    )
    remote = AsyncMock(return_value={"data": []})

    async def run():
        with (
            patch("app.baidu.writeback._active_account", new=AsyncMock(return_value=account)),
            patch("app.baidu.writeback._account_client", return_value=object()),
            patch("app.baidu.writeback.AdgroupService.update_adgroup_fields", remote),
            patch("app.baidu.writeback.get_settings", return_value=_live_settings()),
        ):
            return await apply_adgroup_pause_writeback(
                session, 7, 44, True, operator_user_id=3, operator_name="tester"
            )

    record = asyncio.run(run())
    remote.assert_awaited_once_with(44, pause=True)
    assert record.status == "success"
    assert adgroup.pause is True
    assert (record.old_value, record.new_value) == (0, 1)
    assert session.commit.await_count == 2


def test_landing_url_snapshot_change_after_intent_commit_blocks_remote() -> None:
    adgroup = _adgroup()
    account = SimpleNamespace(id=88, status="active")
    captured = []

    async def refresh(row, **_kwargs):
        if row is adgroup:
            adgroup.pc_final_url = "https://synced.example/pc"

    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[adgroup, None]),
        add=lambda record: captured.append(record),
        flush=AsyncMock(),
        refresh=AsyncMock(side_effect=refresh),
        commit=AsyncMock(),
    )
    remote = AsyncMock()

    async def run():
        with (
            patch("app.baidu.writeback._active_account", new=AsyncMock(return_value=account)),
            patch("app.baidu.writeback.AdgroupService.update_adgroup_fields", remote),
            patch("app.baidu.writeback.get_settings", return_value=_live_settings()),
        ):
            return await apply_adgroup_landing_url_writeback(
                session,
                7,
                44,
                pc_final_url="https://new.example/pc",
                mobile_final_url="https://new.example/mobile",
                pc_track_param=None,
                mobile_track_param=None,
                pc_track_template=None,
                mobile_track_template=None,
                operator_user_id=3,
                operator_name="tester",
            )

    try:
        asyncio.run(run())
    except Exception as exc:
        assert "落地页设置已变化" in str(exc)
    else:
        raise AssertionError("a changed landing snapshot must block the remote write")

    remote.assert_not_awaited()
    assert captured[0].status == "failed"
    assert session.commit.await_count == 2


def test_match_combo_change_after_intent_commit_blocks_remote() -> None:
    keyword = SimpleNamespace(
        baidu_account_id=88,
        keyword_id=55,
        keyword="工业泵",
        campaign_id=12,
        adgroup_id=44,
        match_type=1,
        phrase_type=1,
    )
    account = SimpleNamespace(id=88, status="active")
    captured = []

    async def refresh(row, **_kwargs):
        if row is keyword:
            keyword.match_type = 2
            keyword.phrase_type = 1

    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[keyword, None]),
        add=lambda record: captured.append(record),
        flush=AsyncMock(),
        refresh=AsyncMock(side_effect=refresh),
        commit=AsyncMock(),
    )
    remote = AsyncMock()

    async def run():
        with (
            patch("app.baidu.writeback._active_account", new=AsyncMock(return_value=account)),
            patch("app.baidu.writeback.KeywordService.update_word_match_type", remote),
            patch("app.baidu.writeback.get_settings", return_value=_live_settings()),
        ):
            return await apply_match_type_writeback(
                session,
                7,
                55,
                2,
                3,
                operator_user_id=3,
                operator_name="tester",
            )

    with pytest.raises(WritebackError, match="关键词匹配模式已变化"):
        asyncio.run(run())

    remote.assert_not_awaited()
    assert captured[0].status == "failed"
    assert captured[0].old_value == 1
    assert json.loads(captured[0].baidu_response) == {
        "schema": "sem.match_change",
        "version": 1,
        "old": {"matchType": 1, "phraseType": 1},
        "new": {"matchType": 2, "phraseType": 3},
    }
    assert keyword.match_type == 2
    assert keyword.phrase_type == 1


def test_large_non_json_match_response_keeps_valid_audit_json() -> None:
    keyword = SimpleNamespace(
        baidu_account_id=88,
        keyword_id=55,
        keyword="工业泵",
        campaign_id=12,
        adgroup_id=44,
        match_type=2,
        phrase_type=1,
    )
    account = SimpleNamespace(id=88, status="active")
    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[keyword, None]),
        add=Mock(),
        flush=AsyncMock(),
        refresh=AsyncMock(),
        commit=AsyncMock(),
    )

    class LargeResponse:
        def __str__(self):
            return "百度响应内容" * 800

    remote = AsyncMock(return_value=LargeResponse())

    async def run():
        with (
            patch("app.baidu.writeback._active_account", new=AsyncMock(return_value=account)),
            patch("app.baidu.writeback._account_client", return_value=object()),
            patch("app.baidu.writeback.KeywordService.update_word_match_type", remote),
            patch("app.baidu.writeback.get_settings", return_value=_live_settings()),
        ):
            return await apply_match_type_writeback(
                session, 7, 55, 2, 3, operator_user_id=3, operator_name="tester"
            )

    record = asyncio.run(run())
    payload = json.loads(record.baidu_response)
    assert payload["schema"] == "sem.match_change"
    assert payload["version"] == 1
    assert payload["old"] == {"matchType": 2, "phraseType": 1}
    assert payload["new"] == {"matchType": 2, "phraseType": 3}
    assert payload["baidu"]["truncated"] is True
    assert "百度响应内容" in payload["baidu"]["preview"]
    assert len(record.baidu_response) < 2000


@pytest.mark.parametrize(
    ("apply", "asset", "remote_path", "args", "message"),
    [
        (
            apply_pause_writeback,
            SimpleNamespace(
                baidu_account_id=88, keyword_id=55, keyword="工业泵",
                campaign_id=12, adgroup_id=44, pause=False,
            ),
            "app.baidu.writeback.KeywordService.update_word_pause",
            (7, 55, True),
            "关键词启停状态已变化",
        ),
        (
            apply_campaign_pause_writeback,
            SimpleNamespace(
                baidu_account_id=88, campaign_id=12, campaign_name="品牌计划", pause=False,
            ),
            "app.baidu.writeback.CampaignService.update_campaign_pause",
            (7, 12, True),
            "计划启停状态已变化",
        ),
        (
            apply_adgroup_pause_writeback,
            _adgroup(),
            "app.baidu.writeback.AdgroupService.update_adgroup_fields",
            (7, 44, True),
            "单元启停状态已变化",
        ),
    ],
)
def test_pause_snapshot_change_after_intent_commit_blocks_remote(
    apply, asset, remote_path, args, message
) -> None:
    account = SimpleNamespace(id=88, status="active")
    captured = []

    async def refresh(row, **_kwargs):
        if row is asset:
            asset.pause = True

    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[asset, None]),
        add=lambda record: captured.append(record),
        flush=AsyncMock(),
        refresh=AsyncMock(side_effect=refresh),
        commit=AsyncMock(),
    )
    remote = AsyncMock()

    async def run():
        with (
            patch("app.baidu.writeback._active_account", new=AsyncMock(return_value=account)),
            patch(remote_path, remote),
            patch("app.baidu.writeback.get_settings", return_value=_live_settings()),
        ):
            return await apply(
                session, *args, operator_user_id=3, operator_name="tester"
            )

    with pytest.raises(WritebackError, match=message):
        asyncio.run(run())

    remote.assert_not_awaited()
    assert captured[0].status == "failed"
    assert (captured[0].old_value, captured[0].new_value) == (0, 1)
