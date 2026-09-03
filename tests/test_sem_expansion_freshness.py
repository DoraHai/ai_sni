"""Offline provenance contracts: no production DB, model or Baidu requests."""
import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine, event, literal_column, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, make_transient_to_detached
from sqlalchemy.orm.attributes import get_history, set_committed_value

from tests.test_sem_expansion_business_profile import tenant
from app.ai import expansion_eval as ev
from app.api import expansion as api
from app.models import KeywordCandidate


def candidate(fingerprint=None, **kwargs):
    values = dict(id=1, tenant_id=3, word="同行涂料官网", source="planner", status="pending",
                  ai_relevance="relevant", ai_recommend="watch", ai_reason="同行，需人工确认价值",
                  ai_evaluated_at=datetime(2026, 9, 3), ai_suggested_bid=3, preset_price=2,
                  recommend_price_pc=4,
                  raw={"word": "同行涂料官网"})
    if fingerprint:
        values["raw"][ev.EVALUATION_META_KEY] = {"context_hash": fingerprint}
    values.update(kwargs)
    return KeywordCandidate(**values)


@pytest.mark.parametrize("field,value", [
    ("id", 4), ("name", "另一个客户"), ("industry", "机械"),
    ("business_desc", "不投竞品词"), ("brand_terms", ["另一品牌"]),
])
def test_context_changes_are_detected_without_editing_profile_routes(field, value):
    customer = tenant()
    old = ev.context_fingerprint(customer)
    row = candidate(old)
    assert ev.evaluation_freshness(row, old) == "current"
    setattr(customer, field, value)
    assert ev.evaluation_freshness(row, ev.context_fingerprint(customer)) == "stale"
    assert row.ai_reason == "同行，需人工确认价值"  # read-only classification


def test_summary_is_not_context_but_prompt_policy_is(monkeypatch):
    customer = tenant()
    before = ev.context_fingerprint(customer)
    customer.profile_summary = "模型猜测的新业务"
    assert ev.context_fingerprint(customer) == before
    monkeypatch.setattr(ev, "SYSTEM_PROMPT", ev.SYSTEM_PROMPT + "新评估规则")
    assert ev.context_fingerprint(customer) != before


@pytest.mark.parametrize("raw", [None, [], "external", {}, {ev.EVALUATION_META_KEY: []},
                                  {ev.EVALUATION_META_KEY: {"context_hash": 10}},
                                  {ev.EVALUATION_META_KEY: {"context_hash": "x" * 64}}])
def test_missing_legacy_or_replaced_metadata_is_unverified(raw):
    assert ev.evaluation_freshness(candidate(raw=raw), ev.context_fingerprint(tenant())) == "unverified"


def test_missing_profile_and_never_evaluated_are_distinct():
    row = candidate(ev.context_fingerprint(tenant()))
    empty = tenant(industry=None, business_desc=None)
    assert ev.context_fingerprint(empty) is None
    assert ev.evaluation_freshness(row, None) == "stale"
    row.ai_evaluated_at = None
    assert ev.evaluation_freshness(row, None) == "not_evaluated"


@pytest.mark.parametrize("state", ["unverified", "stale", "current"])
def test_payload_preserves_verdict_and_presets_but_masks_old_ai_price(state):
    fingerprint = ev.context_fingerprint(tenant())
    row = candidate(None if state == "unverified" else "a" * 64 if state == "stale" else fingerprint)
    payload = api._candidate_payload(row, fingerprint)
    assert payload["ai_freshness"] == state
    assert payload["ai_suggested_bid"] == (3.0 if state == "current" else None)
    assert payload["preset_price"] == 2 and payload["ai_reason"] == row.ai_reason
    assert row.ai_suggested_bid == 3 and row.status == "pending"


def test_competitor_is_not_forced_to_adopt_and_drop_never_gets_ai_bid(monkeypatch):
    assert "相关性与投放价值必须分别判断" in ev.SYSTEM_PROMPT
    assert "业务语义相关，不代表值得投放" in ev.SYSTEM_PROMPT
    assert "虽相关但没有投放价值" in ev.SYSTEM_PROMPT
    assert "relevant/drop" in ev.SYSTEM_PROMPT
    assert "不要自动采纳竞品词" in ev.SYSTEM_PROMPT
    monkeypatch.setattr(ev, "chat_json", AsyncMock(return_value={"items": [{
        "word": "同行涂料官网", "relevance": "relevant", "recommend": "drop",
        "reason": "同行但导航意图，建议忽略", "suggested_bid": 4, "bid_reason": "错误出价",
    }]}))
    verdict = asyncio.run(ev._evaluate_batch(tenant(), [{"word": "同行涂料官网", "recommend_price_pc": 4}]))["同行涂料官网"]
    assert verdict["relevance"] == "relevant" and verdict["recommend"] == "drop"
    assert verdict["suggested_bid"] is None and verdict["bid_reason"] is None
    fp = ev.context_fingerprint(tenant())
    assert api._candidate_payload(candidate(fp, ai_recommend="drop"), fp)["ai_suggested_bid"] is None


def test_stamp_patches_current_database_raw_instead_of_overwriting_source_fields():
    statement = update(KeywordCandidate).where(KeywordCandidate.id == 1).values(
        raw=ev.evaluation_stamp_expression("a" * 64))
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "THEN jsonb_set(keyword_candidates.raw" in str(compiled)
    assert "ELSE keyword_candidates.raw END" in str(compiled)
    assert {"context_hash": "a" * 64} in compiled.params.values()
    assert [ev.EVALUATION_META_KEY] in compiled.params.values()


def test_profile_change_during_model_call_does_not_stamp_new_context(monkeypatch):
    customer = tenant()
    before = ev.context_fingerprint(customer)
    row = candidate()
    async def verdict(*args):
        customer.business_desc = "画像在等待模型时被修改"
        return {row.word: dict(relevance="relevant", recommend="watch", reason="旧画像结果",
                               suggested_bid=None, bid_reason=None)}
    monkeypatch.setattr(ev, "is_enabled", lambda: True)
    monkeypatch.setattr(ev, "_evaluate_batch", verdict)
    session = SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [row])),
                              commit=AsyncMock())
    asyncio.run(ev.evaluate_candidates_for_tenant(session, customer, force=True, limit=20))
    params = row.raw.compile(dialect=postgresql.dialect()).params
    assert {"context_hash": before} in params.values()
    assert {"context_hash": ev.context_fingerprint(customer)} not in params.values()


def test_list_reports_unfiltered_tenant_scoped_freshness_without_writes():
    customer = tenant()
    fp = ev.context_fingerprint(customer)
    row = candidate(fp)
    results = [ [("planner", 8)], [("pending", 8)], [("relevant", 8)],
                [(fp, 1), ("a" * 64, 2), (None, 3), (int("1" * 64), 1), ({}, 1)] ]
    session = SimpleNamespace(
        get=AsyncMock(return_value=customer), scalar=AsyncMock(side_effect=[1, None, None]),
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [row])),
        execute=AsyncMock(side_effect=[SimpleNamespace(all=lambda r=r: r) for r in results]),
        commit=AsyncMock(),
    )
    data = asyncio.run(api.list_candidates(
        tenant_id=3, source="planner", status="pending", suggested_category=None,
        min_score=None, q="官网", ai_relevance="relevant", page=1, page_size=20, session=session))
    assert data["ai_freshness_counts"] == {"current": 1, "stale": 2, "unverified": 5}
    assert data["candidates"][0]["ai_freshness"] == "current"
    query = session.execute.await_args_list[-1].args[0].compile(dialect=postgresql.dialect())
    assert 3 in query.params.values() and "pending" in query.params.values()
    assert "ai_evaluated_at IS NOT NULL" in str(query)
    assert "jsonb_extract_path" in str(query) and "->>" not in str(query)
    assert "官网" not in query.params.values() and "LIMIT" not in str(query)
    session.commit.assert_not_awaited()


def test_csv_marks_old_result_as_unverified():
    row = candidate()
    session = SimpleNamespace(get=AsyncMock(return_value=tenant()),
                              scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [row])))
    response = asyncio.run(api.export_candidates(
        tenant_id=3, source=None, status=None, suggested_category=None,
        min_score=None, q=None, ai_relevance=None, session=session))
    assert "AI结果有效性" in response.body.decode("utf-8-sig")
    assert "历史结果未核验" in response.body.decode("utf-8-sig")


def test_even_unchanged_verdict_fields_are_written_together_with_stamp(monkeypatch):
    """A concurrent writer may have changed a value equal to our old snapshot."""
    row = candidate()
    fields = ("ai_relevance", "ai_recommend", "ai_reason", "ai_suggested_bid", "ai_bid_reason")
    for field in fields:
        set_committed_value(row, field, getattr(row, field))
    monkeypatch.setattr(ev, "is_enabled", lambda: True)
    monkeypatch.setattr(ev, "_evaluate_batch", AsyncMock(return_value={row.word: {
        "relevance": row.ai_relevance, "recommend": row.ai_recommend,
        "reason": row.ai_reason, "suggested_bid": row.ai_suggested_bid,
        "bid_reason": row.ai_bid_reason,
    }}))
    session = SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [row])),
                              commit=AsyncMock())
    asyncio.run(ev.evaluate_candidates_for_tenant(session, tenant(), force=True, limit=20))
    assert all(get_history(row, field).has_changes() for field in fields)
    assert not get_history(row, "status").deleted


def test_stamp_does_not_replace_non_object_source_data():
    compiled = ev.evaluation_stamp_expression("a" * 64).compile(dialect=postgresql.dialect())
    assert "ELSE keyword_candidates.raw END" in str(compiled)


def test_orm_flush_emits_one_complete_verdict_without_manual_fields(monkeypatch):
    """Inspect real ORM UPDATE emission using an in-memory connection, no DB files.

    Only substitute the PostgreSQL JSON expression (compiled separately above).
    Stop before SQL execution: this test checks ORM dirty tracking, not PG semantics.
    """
    row = candidate()
    for column in KeywordCandidate.__table__.columns:
        set_committed_value(row, column.key, getattr(row, column.key))
    make_transient_to_detached(row)
    engine = create_engine("sqlite://")
    statements = []

    class CapturedUpdate(Exception):
        pass

    @event.listens_for(engine, "before_cursor_execute")
    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)
        raise CapturedUpdate()

    monkeypatch.setattr(ev, "is_enabled", lambda: True)
    monkeypatch.setattr(ev, "evaluation_stamp_expression", lambda _: literal_column("'{}'"))
    monkeypatch.setattr(ev, "_evaluate_batch", AsyncMock(return_value={row.word: {
        "relevance": row.ai_relevance, "recommend": row.ai_recommend,
        "reason": row.ai_reason, "suggested_bid": row.ai_suggested_bid,
        "bid_reason": row.ai_bid_reason,
    }}))
    try:
        with Session(engine, expire_on_commit=False) as orm:
            orm.add(row)
            async def flush():
                orm.flush()
            session = SimpleNamespace(
                scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [row])), commit=flush,
            )
            with pytest.raises(CapturedUpdate):
                asyncio.run(ev.evaluate_candidates_for_tenant(session, tenant(), force=True, limit=20))
    finally:
        engine.dispose()
    assert len(statements) == 1
    sql = statements[0]
    assert sql.startswith("UPDATE keyword_candidates SET ")
    for field in ("ai_relevance", "ai_recommend", "ai_reason", "ai_suggested_bid",
                  "ai_bid_reason", "ai_evaluated_at", "raw"):
        assert f"{field}=" in sql
    for field in ("status", "preset_price", "suggested_category", "synced_at"):
        assert f"{field}=" not in sql


@pytest.mark.parametrize("bid", [float("nan"), float("inf"), -1, 0, True, 1000000])
def test_invalid_model_price_never_becomes_a_current_suggestion(monkeypatch, bid):
    monkeypatch.setattr(ev, "chat_json", AsyncMock(return_value={"items": [{
        "word": "同行涂料官网", "relevance": "relevant", "recommend": "watch",
        "suggested_bid": bid, "bid_reason": "模型价格",
    }]}))
    verdict = asyncio.run(ev._evaluate_batch(tenant(), [{"word": "同行涂料官网", "recommend_price_pc": 4}]))["同行涂料官网"]
    assert verdict["suggested_bid"] is None and verdict["bid_reason"] is None
    fp = ev.context_fingerprint(tenant())
    payload = api._candidate_payload(candidate(fp, ai_suggested_bid=bid), fp)
    assert payload["ai_suggested_bid"] is None and payload["ai_bid_reason"] is None


@pytest.mark.parametrize("value,expected", [("3.28", 3.28), (0.01, 0.01), (999.99, 999.99),
                                           (1.234, 1.23), (None, None), ("bad", None)])
def test_suggestion_price_valid_boundaries(value, expected):
    assert ev.validated_suggested_bid(value) == expected


@pytest.mark.parametrize("relevance,recommend,pc,mobile,expected", [
    ("relevant", "watch", None, None, None),
    ("generic", "watch", 3, None, None),
    ("irrelevant", "adopt", 3, None, None),
    ("relevant", "drop", 3, None, None),
    ("relevant", "watch", 0, -1, None),
    ("relevant", "watch", float("nan"), True, None),
    ("relevant", "adopt", 3, None, 2.5),
    ("relevant", "watch", None, 3, 2.5),
])
def test_price_requires_clear_relevance_and_real_guide_at_write_and_read(
    monkeypatch, relevance, recommend, pc, mobile, expected,
):
    word = "涂料采购"
    words = [{"word": word, "recommend_price_pc": pc, "recommend_price_mobile": mobile}]
    monkeypatch.setattr(ev, "chat_json", AsyncMock(return_value={"items": [{
        "word": word, "relevance": relevance, "recommend": recommend,
        "suggested_bid": 2.5, "bid_reason": "参考指导价",
        "recommend_price_pc": 10,  # Model-invented guide is never provider evidence.
    }]}))
    result = asyncio.run(ev._evaluate_batch(tenant(), words))[word]
    assert result["suggested_bid"] == expected
    assert result["bid_reason"] == ("参考指导价" if expected else None)
    fp = ev.context_fingerprint(tenant())
    row = candidate(fp, word=word, ai_relevance=relevance, ai_recommend=recommend,
                    ai_suggested_bid=2.5, ai_bid_reason="参考指导价",
                    recommend_price_pc=pc, recommend_price_mobile=mobile)
    payload = api._candidate_payload(row, fp)
    assert payload["ai_suggested_bid"] == expected
    assert payload["ai_bid_reason"] == ("参考指导价" if expected else None)
    assert row.preset_price == 2 and row.ai_suggested_bid == 2.5


@pytest.mark.parametrize("field", ["relevance", "recommend"])
@pytest.mark.parametrize("invalid", [[], {}, True, 1, None, "unknown"])
def test_invalid_verdict_entry_does_not_abort_valid_entries(monkeypatch, field, invalid):
    bad = {"word": "坏词", "relevance": "relevant", "recommend": "watch", field: invalid}
    good = {"word": "好词", "relevance": "relevant", "recommend": "watch"}
    monkeypatch.setattr(ev, "chat_json", AsyncMock(return_value={"items": [bad, good]}))
    result = asyncio.run(ev._evaluate_batch(tenant(), [{"word": "坏词"}, {"word": "好词"}]))
    assert set(result) == {"好词"}


@pytest.mark.parametrize("response", [None, [], True, 1, "invalid", {}, {"items": {}}, {"items": None}])
def test_invalid_response_shape_uses_controlled_batch_failure(monkeypatch, response):
    monkeypatch.setattr(ev, "chat_json", AsyncMock(return_value=response))
    with pytest.raises(ev.DeepSeekError):
        asyncio.run(ev._evaluate_batch(tenant(), [{"word": "涂料"}]))


def test_malformed_result_preserves_old_row_and_allows_next_batch(monkeypatch):
    rows = [candidate(id=1, word="坏词"), candidate(id=2, word="好词")]
    old_raw = rows[0].raw.copy()
    old_time = rows[0].ai_evaluated_at
    monkeypatch.setattr(ev, "is_enabled", lambda: True)
    chat = AsyncMock(side_effect=[
        {"items": [{"word": "坏词", "relevance": [], "recommend": "watch"}]},
        {"items": [{"word": "好词", "relevance": "relevant", "recommend": "watch",
                    "reason": "新评估", "suggested_bid": 2.5}]},
    ])
    monkeypatch.setattr(ev, "chat_json", chat)
    session = SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: rows)),
                              commit=AsyncMock())
    result = asyncio.run(ev.evaluate_candidates_for_tenant(
        session, tenant(), force=True, limit=20, batch_size=1,
    ))
    assert result["evaluated"] == 1 and result["successful_words"] == 1
    assert result["failed_words"] == 1 and result["failed_candidate_ids"] == [1]
    assert rows[0].raw == old_raw and rows[0].ai_evaluated_at == old_time
    assert rows[0].ai_reason == "同行，需人工确认价值"
    assert rows[1].ai_reason == "新评估" and rows[1].ai_suggested_bid == 2.5
    assert chat.await_count == 2


@pytest.mark.parametrize("bad", [None, [], 2, "text", {"word": ["好词"]},
                                 {"word": {"word": "好词"}}, {"word": True}])
def test_non_object_items_and_non_string_words_are_ignored(monkeypatch, bad):
    good = {"word": "好词", "relevance": "relevant", "recommend": "watch"}
    monkeypatch.setattr(ev, "chat_json", AsyncMock(return_value={"items": [bad, good]}))
    assert set(asyncio.run(ev._evaluate_batch(tenant(), [{"word": "好词"}]))) == {"好词"}


@pytest.mark.parametrize("field", ["reason", "bid_reason"])
@pytest.mark.parametrize("value", [[], {}, True, 1])
def test_invalid_text_fields_are_failed_not_stringified(monkeypatch, field, value):
    monkeypatch.setattr(ev, "chat_json", AsyncMock(return_value={"items": [{
        "word": "坏词", "relevance": "relevant", "recommend": "watch", field: value,
    }]}))
    assert asyncio.run(ev._evaluate_batch(tenant(), [{"word": "坏词"}])) == {}


def test_duplicate_and_unrequested_verdicts_are_not_cached(monkeypatch):
    first = {"word": "重复词", "relevance": "relevant", "recommend": "adopt"}
    second = {**first, "recommend": "drop"}
    outside = {**first, "word": "未请求词"}
    good = {**first, "word": "正常词"}
    monkeypatch.setattr(ev, "chat_json", AsyncMock(return_value={"items": [first, outside, second, first, good]}))
    result = asyncio.run(ev._evaluate_batch(tenant(), [{"word": "重复词"}, {"word": "正常词"}]))
    assert set(result) == {"正常词"}


def test_invalid_whole_batch_is_counted_and_later_batch_runs(monkeypatch):
    rows = [candidate(id=1, word="首批"), candidate(id=2, word="后批")]
    old_reason = rows[0].ai_reason
    old_raw = rows[0].raw.copy()
    monkeypatch.setattr(ev, "is_enabled", lambda: True)
    monkeypatch.setattr(ev, "chat_json", AsyncMock(side_effect=[[], {"items": [{
        "word": "后批", "relevance": "relevant", "recommend": "watch", "reason": "新结论",
    }]}]))
    session = SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: rows)),
                              commit=AsyncMock())
    result = asyncio.run(ev.evaluate_candidates_for_tenant(session, tenant(), force=True, batch_size=1, limit=20))
    assert result["failed_batches"] == 1 and result["failed_candidate_ids"] == [1]
    assert result["successful_words"] == 1 and result["remaining"] == 1
    assert rows[0].ai_reason == old_reason and rows[0].raw == old_raw
    assert rows[1].ai_reason == "新结论"
