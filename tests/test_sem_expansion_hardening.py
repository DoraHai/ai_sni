import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
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

from app.api.expansion import (
    AddToPlanRequest,
    BatchNegativeRequest,
    BatchSetPresetRequest,
    _candidate_payload,
    add_candidate_to_plan,
    batch_add_negative,
    batch_set_preset,
    router as expansion_router,
)
from app.api.negatives import NegativeRequest, add_negative
from app.api.search_terms import ExpandRequest, expand_to_keyword
from app.baidu.writeback import apply_negative_batch_writeback
from app.models.keyword_candidate import KeywordCandidate
from app.models.writeback_action import MATCH_MODE_LABELS
from app.security.auth import AuthContext


def _ctx(tenant_id: int = 3) -> AuthContext:
    return AuthContext(
        user_id=9,
        username="operator",
        role_name="运营",
        tenant_id=tenant_id,
    )


class _ScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _BatchSession:
    def __init__(self, rows):
        self.rows = rows
        self.commits = 0

    async def scalars(self, _statement):
        return _ScalarRows(self.rows)

    async def commit(self):
        self.commits += 1


class _CandidateSession:
    def __init__(self, candidate):
        self.candidate = candidate
        self.commits = 0

    async def get(self, _model, _candidate_id):
        return self.candidate

    async def commit(self):
        self.commits += 1


def test_expansion_batch_routes_are_registered() -> None:
    paths = {route.path for route in expansion_router.routes}
    assert {
        "/api/v1/expansion/candidates/batch-set-preset",
        "/api/v1/expansion/candidates/batch-set-category",
        "/api/v1/expansion/candidates/batch-status",
        "/api/v1/expansion/candidates/batch-negative",
    }.issubset(paths)


def test_smart_match_is_available_in_presets_and_ledger_labels() -> None:
    request = BatchSetPresetRequest(
        tenant_id=3,
        candidate_ids=[11],
        preset_match_mode="smart",
    )
    assert request.preset_match_mode == "smart"
    assert MATCH_MODE_LABELS["smart"] == "智能匹配"

    with pytest.raises(ValidationError):
        BatchSetPresetRequest(
            tenant_id=3,
            candidate_ids=[11],
            preset_match_mode="broad",
        )

    assert ExpandRequest(
        tenant_id=3,
        word="工业泵",
        adgroup_id=202,
        price=3.6,
        match_mode="smart",
    ).match_mode == "smart"

    with pytest.raises(ValidationError):
        NegativeRequest(
            tenant_id=3,
            word="工业泵",
            adgroup_id=202,
            match_mode="smart",
        )


def test_candidate_payload_includes_existing_preset_columns() -> None:
    candidate = KeywordCandidate(
        id=11,
        tenant_id=3,
        word="工业泵",
        source="planner",
        status="pending",
        preset_price=3.6,
        preset_match_mode="smart",
    )
    payload = _candidate_payload(candidate)
    assert payload["preset_price"] == 3.6
    assert payload["preset_match_mode"] == "smart"


def test_batch_set_preset_updates_smart_match() -> None:
    candidate = SimpleNamespace(
        id=11,
        preset_price=None,
        preset_match_mode=None,
    )
    session = _BatchSession([candidate])
    request = BatchSetPresetRequest(
        tenant_id=3,
        candidate_ids=[11],
        preset_price=3.6,
        preset_match_mode="smart",
    )

    result = asyncio.run(batch_set_preset(request, _ctx(), session))

    assert result == {"status": "ok", "updated": 1}
    assert candidate.preset_price == 3.6
    assert candidate.preset_match_mode == "smart"
    assert session.commits == 1


def test_batch_negative_route_calls_one_bulk_writeback() -> None:
    candidates = [
        SimpleNamespace(id=11, word="工业泵", status="pending", status_updated_at=None),
        SimpleNamespace(id=12, word="免费", status="pending", status_updated_at=None),
    ]
    records = [
        SimpleNamespace(status="success", error_msg=None, no_op=False),
        SimpleNamespace(status="failed", error_msg="写回失败", no_op=False),
    ]
    session = _BatchSession(candidates)
    request = BatchNegativeRequest(
        tenant_id=3,
        candidate_ids=[11, 12],
        adgroup_id=202,
        match_mode="phrase",
    )

    async def run():
        with patch(
            "app.api.expansion.apply_negative_batch_writeback",
            new=AsyncMock(return_value=records),
        ) as bulk_writeback:
            result = await batch_add_negative(request, _ctx(), session)
            bulk_writeback.assert_awaited_once()
            assert bulk_writeback.await_args.args[2] == ["工业泵", "免费"]
            return result

    result = asyncio.run(run())

    assert [item["status"] for item in result["results"]] == ["success", "failed"]
    assert result["results"][1]["error"] == "写回失败"
    assert candidates[0].status == "ignored"
    assert candidates[1].status == "pending"
    assert session.commits == 1


def test_bulk_negative_writeback_is_idempotent_across_candidate_sources() -> None:
    adgroup = SimpleNamespace(
        baidu_account_id=17,
        campaign_id=101,
        adgroup_name="泵业务单元",
        negative_words=["已有词"],
        exact_negative_words=[],
    )
    account = SimpleNamespace(id=17)
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=adgroup),
        add=lambda _record: None,
        flush=AsyncMock(),
        commit=AsyncMock(),
    )
    update_negative_words = AsyncMock(return_value={"header": {"status": 0}})
    service = SimpleNamespace(update_negative_words=update_negative_words)

    async def run():
        with (
            patch(
                "app.baidu.writeback._active_account",
                new=AsyncMock(return_value=account),
            ),
            patch("app.baidu.writeback._account_client", return_value=object()),
            patch("app.baidu.writeback.AdgroupService", return_value=service),
            patch(
                "app.baidu.writeback.get_settings",
                return_value=SimpleNamespace(
                    baidu_write_dry_run=False,
                    baidu_write_is_dry_run=lambda tenant_id, account_id, scope: False,
                ),
            ),
        ):
            return await apply_negative_batch_writeback(
                session,
                3,
        ["新词一", "新词二", "新词一", "已有词"],
                202,
                match_mode="phrase",
                operator_user_id=9,
                operator_name="operator",
            )

    records = asyncio.run(run())

    update_negative_words.assert_awaited_once_with(
        202,
        negative_words=["已有词", "新词一", "新词二"],
    )
    assert [result.status for result in records] == [
        "success",
        "success",
        "success",
        "success",
    ]
    assert records[0] is records[2]
    assert records[3].no_op is True
    assert records[3].record is None
    assert len({id(result.record) for result in records if result.record is not None}) == 2
    assert adgroup.negative_words == ["已有词", "新词一", "新词二"]
    session.commit.assert_not_awaited()


def test_add_to_plan_returns_error_when_writeback_failed() -> None:
    candidate = SimpleNamespace(id=11, tenant_id=3, word="工业泵", status="pending")
    session = _CandidateSession(candidate)
    request = AddToPlanRequest(
        tenant_id=3,
        adgroup_id=202,
        price=3.6,
        match_mode="smart",
    )
    failed_record = SimpleNamespace(status="failed", dry_run=False)

    async def run():
        with patch(
            "app.api.expansion.apply_add_word_writeback",
            new=AsyncMock(return_value=failed_record),
        ):
            return await add_candidate_to_plan(11, request, _ctx(), session)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(run())

    assert exc.value.status_code == 502
    assert candidate.status == "pending"
    assert session.commits == 0


def test_other_keyword_and_negative_routes_do_not_report_failed_writeback_as_ok() -> None:
    failed_record = SimpleNamespace(status="failed", dry_run=False)
    session = SimpleNamespace()

    async def run_keyword():
        with patch(
            "app.api.search_terms.apply_add_word_writeback",
            new=AsyncMock(return_value=failed_record),
        ):
            return await expand_to_keyword(
                ExpandRequest(
                    tenant_id=3,
                    word="工业泵",
                    adgroup_id=202,
                    price=3.6,
                    match_mode="smart",
                ),
                _ctx(),
                session,
            )

    async def run_negative():
        with patch(
            "app.api.negatives.apply_negative_writeback",
            new=AsyncMock(return_value=failed_record),
        ):
            return await add_negative(
                NegativeRequest(
                    tenant_id=3,
                    word="免费",
                    adgroup_id=202,
                    match_mode="exact",
                ),
                _ctx(),
                session,
            )

    for operation in (run_keyword, run_negative):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(operation())
        assert exc.value.status_code == 502
