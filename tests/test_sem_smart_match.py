import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "test-secret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault(
    "CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
)
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.baidu.writeback import (
    WritebackError,
    _ensure_add_word_not_duplicate,
    _MATCH_BY_MODE,
    apply_add_word_writeback,
)
from app.api.expansion import AddToPlanRequest


class _Session:
    def __init__(self) -> None:
        self.record = None

    async def scalar(self, _statement):
        return SimpleNamespace(
            baidu_account_id=7,
            campaign_id=101,
            adgroup_id=202,
            adgroup_name="智能匹配测试单元",
        )

    async def scalars(self, _statement):
        return SimpleNamespace(all=lambda: [])

    def add(self, record) -> None:
        self.record = record

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def refresh(self, _record) -> None:
        return None


def test_add_word_smart_match_uses_baidu_smart_combo() -> None:
    assert _MATCH_BY_MODE["smart"] == (2, 3)

    service = SimpleNamespace(add_word=AsyncMock(return_value={"header": {"status": 0}}))
    session = _Session()

    async def run():
        with (
            patch("app.baidu.writeback.get_settings", return_value=SimpleNamespace(baidu_write_dry_run=True)),
            patch("app.baidu.writeback._active_account", new=AsyncMock(return_value=SimpleNamespace(id=7))),
            patch("app.baidu.writeback._account_client", return_value=object()),
            patch("app.baidu.writeback.KeywordService", return_value=service),
        ):
            return await apply_add_word_writeback(
                session,
                tenant_id=3,
                word="工业泵",
                adgroup_id=202,
                price=3.6,
                match_mode="smart",
                operator_user_id=9,
                operator_name="operator",
            )

    record = asyncio.run(run())

    service.add_word.assert_awaited_once_with(202, "工业泵", 2, 3, 3.6)
    assert record.match_mode == "smart"
    assert record.status == "dry_run"


def test_add_to_plan_request_accepts_only_supported_match_modes() -> None:
    request = AddToPlanRequest(
        tenant_id=3,
        adgroup_id=202,
        price=3.6,
        match_mode="smart",
    )
    assert request.match_mode == "smart"

    with pytest.raises(ValidationError):
        AddToPlanRequest(
            tenant_id=3,
            adgroup_id=202,
            price=3.6,
            match_mode="broad",
        )


def test_add_word_rejects_unknown_match_mode_before_database_access() -> None:
    with pytest.raises(WritebackError, match="exact / phrase / smart"):
        asyncio.run(
            apply_add_word_writeback(
                _Session(),
                tenant_id=3,
                word="工业泵",
                adgroup_id=202,
                price=3.6,
                match_mode="broad",
                operator_user_id=9,
                operator_name="operator",
            )
        )


@pytest.mark.parametrize("price", [float("nan"), float("inf"), float("-inf")])
def test_add_word_rejects_non_finite_price_before_database_access(price: float) -> None:
    with pytest.raises(WritebackError, match="有限数值"):
        asyncio.run(
            apply_add_word_writeback(
                _Session(),
                tenant_id=3,
                word="工业泵",
                adgroup_id=202,
                price=price,
                match_mode="exact",
                operator_user_id=9,
                operator_name="operator",
            )
        )


@pytest.mark.parametrize(
    ("dimension_words", "recent_writes", "message"),
    [
        (["  工业泵  "], [], "目标单元已存在同名关键词"),
        ([], ["工业泵"], "已有待确认、演练或近期成功的加入记录"),
    ],
)
def test_add_word_blocks_dimension_and_recent_ledger_duplicates(
    dimension_words: list[str], recent_writes: list[str], message: str
) -> None:
    class DuplicateSession(_Session):
        def __init__(self) -> None:
            super().__init__()
            self.results = [dimension_words, recent_writes]

        async def scalars(self, _statement):
            return SimpleNamespace(all=lambda: self.results.pop(0))

    service = SimpleNamespace(add_word=AsyncMock())

    async def run():
        with (
            patch(
                "app.baidu.writeback._active_account",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ),
            patch("app.baidu.writeback._account_client", return_value=object()),
            patch("app.baidu.writeback.KeywordService", return_value=service),
        ):
            return await apply_add_word_writeback(
                DuplicateSession(),
                tenant_id=3,
                word="工业泵",
                adgroup_id=202,
                price=3.6,
                match_mode="exact",
                operator_user_id=9,
                operator_name="operator",
            )

    with pytest.raises(WritebackError, match=message):
        asyncio.run(run())
    service.add_word.assert_not_awaited()


def test_add_word_duplicate_guard_includes_recent_dry_run_records() -> None:
    class QueryCaptureSession:
        def __init__(self) -> None:
            self.statements = []

        async def scalars(self, statement):
            self.statements.append(statement)
            return SimpleNamespace(all=lambda: [])

    session = QueryCaptureSession()
    asyncio.run(
        _ensure_add_word_not_duplicate(
            session,
            tenant_id=3,
            adgroup_id=202,
            word="工业泵",
        )
    )

    assert len(session.statements) == 2
    ledger_params = session.statements[1].compile().params
    status_sets = {
        frozenset(value)
        for value in ledger_params.values()
        if isinstance(value, (list, tuple, set))
    }
    assert frozenset({"success", "dry_run"}) in status_sets
