"""Offline small-batch contracts: mock all AI/Baidu/database boundaries."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Reuse the existing offline fixture environment (no .env / real services).
from tests.test_sem_expansion_business_profile import tenant
from app.ai import expansion_eval as evaluator
from app.api import expansion
from app.database import get_session
from app.models import KeywordCandidate
from app import sem_expansion_sample as sampler
from app.security.auth import AuthContext, require_scoped_auth, require_auth


def rows_result(rows):
    return SimpleNamespace(all=lambda: rows)


def candidate(i, word=None):
    return KeywordCandidate(id=i, tenant_id=3, word=word or f"粉末涂料{i}",
                            source="planner", status="pending", preset_price=2)


@pytest.mark.parametrize("force", [False, True])
def test_evaluation_caps_distinct_words_and_keeps_remaining(monkeypatch, force):
    monkeypatch.setattr(evaluator, "is_enabled", lambda: True)
    rows = [candidate(i) for i in range(1, 26)] + [candidate(26, "粉末涂料1")]
    async def verdict(_tenant, words):
        return {w["word"]: dict(relevance="relevant", recommend="watch", reason="相关",
                              suggested_bid=None, bid_reason=None) for w in words}
    call = AsyncMock(side_effect=verdict)
    monkeypatch.setattr(evaluator, "_evaluate_batch", call)
    session = SimpleNamespace(scalars=AsyncMock(return_value=rows_result(rows)), commit=AsyncMock())
    result = asyncio.run(evaluator.evaluate_candidates_for_tenant(session, tenant(), force=force, limit=20))
    assert len(call.await_args.args[1]) == 20
    assert result["successful_words"] == 20 and result["evaluated"] == 21
    assert result["remaining"] == 5 and result["failed_words"] == 0
    assert all(r.ai_evaluated_at is None for r in rows[20:25])
    assert all(r.status == "pending" and r.preset_price == 2 for r in rows)
    query = session.scalars.await_args.args[0].compile()
    assert "ORDER BY keyword_candidates.id ASC" in str(query)
    assert ("ai_evaluated_at IS NULL" in str(query).split("ORDER BY")[0]) is not force
    assert 3 in query.params.values() and "pending" in query.params.values()


@pytest.mark.parametrize("failure", ["batch", "missing"])
def test_failures_are_counted_as_remaining_and_keep_old_results(monkeypatch, failure):
    monkeypatch.setattr(evaluator, "is_enabled", lambda: True)
    call = AsyncMock(side_effect=evaluator.DeepSeekError("offline")) if failure == "batch" else AsyncMock(return_value={})
    monkeypatch.setattr(evaluator, "_evaluate_batch", call)
    rows = [candidate(i) for i in range(1, 26)]
    for row in rows:
        row.ai_reason = "旧结果"
    session = SimpleNamespace(scalars=AsyncMock(return_value=rows_result(rows)), commit=AsyncMock())
    result = asyncio.run(evaluator.evaluate_candidates_for_tenant(session, tenant(), force=True, limit=20))
    assert result["remaining"] == 25 and result["failed_words"] == 20
    assert result["deferred"] == 5 and result["evaluated"] == 0
    assert all(r.ai_reason == "旧结果" for r in rows)


def setup_sampler(monkeypatch, returned):
    service = SimpleNamespace(get_words_by_seed=AsyncMock(return_value=returned))
    monkeypatch.setattr(sampler, "KeywordPlannerService", lambda _: service)
    monkeypatch.setattr(sampler, "_account_client", lambda _: object())
    monkeypatch.setattr(sampler, "_tenant_brand_terms", AsyncMock(return_value=["老虎"]))
    monkeypatch.setattr(sampler, "_existing_keyword_texts", AsyncMock(return_value={"已有词"}))
    write = AsyncMock()
    monkeypatch.setattr(sampler, "_upsert_candidates", write)
    return service, write


def test_sampling_enforces_local_cap_even_if_baidu_ignores_limit(monkeypatch):
    words = [{"word": "已有词"}, {"word": ""}] + [{"word": f"粉末涂料{i}"} for i in range(40)]
    service, write = setup_sampler(monkeypatch, words)
    account = SimpleNamespace(id=5, tenant_id=3)
    count = asyncio.run(sampler.sample_planner_candidates(object(), account, "粉末涂料", 20))
    assert count == 20
    service.get_words_by_seed.assert_awaited_once_with("粉末涂料", 20)
    records = write.await_args.args[1]
    assert len(records) == 20
    assert all(r["tenant_id"] == 3 and r["baidu_account_id"] == 5 for r in records)
    assert all("status" not in r and "ai_relevance" not in r for r in records)


def test_sampling_deduplicates_and_does_not_write_empty_results(monkeypatch):
    _, write = setup_sampler(monkeypatch, [{"word": "已有词"}, {"word": ""}])
    assert asyncio.run(sampler.sample_planner_candidates(object(), SimpleNamespace(id=5, tenant_id=3), "粉末", 20)) == 0
    write.assert_not_awaited()
    _, write = setup_sampler(monkeypatch, [{"word": "ABC"}, {"word": "abc"}, {"word": "abc"}])
    assert asyncio.run(sampler.sample_planner_candidates(object(), SimpleNamespace(id=5, tenant_id=3), "粉末", 20)) == 1


def api_client(session):
    app = FastAPI()
    app.include_router(expansion.router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[require_scoped_auth] = lambda: AuthContext(user_id=9, username="tester", role_name="管理员", tenant_id=3)
    return TestClient(app)


def test_evaluate_http_defaults_and_rejects_out_of_bounds(monkeypatch):
    call = AsyncMock(return_value={"enabled": True, "evaluated": 0})
    monkeypatch.setattr(expansion, "evaluate_candidates_for_tenant", call)
    client = api_client(SimpleNamespace(get=AsyncMock(return_value=tenant())))
    assert client.post('/api/v1/expansion/evaluate?tenant_id=3').status_code == 200
    assert call.await_args.kwargs["limit"] == 20
    for invalid in [0, -1, 21, 1000, "null", "", "1.5"]:
        call.reset_mock()
        assert client.post(f'/api/v1/expansion/evaluate?tenant_id=3&limit={invalid}').status_code == 422
        call.assert_not_awaited()


@pytest.mark.parametrize("accounts", [[], [SimpleNamespace(id=1), SimpleNamespace(id=2)]])
def test_sample_rejects_ambiguous_account_without_external_calls(monkeypatch, accounts):
    call = AsyncMock()
    monkeypatch.setattr(expansion, "sample_planner_candidates", call)
    session = SimpleNamespace(get=AsyncMock(return_value=tenant()), scalars=AsyncMock(return_value=rows_result(accounts)))
    client = api_client(session)
    assert client.post('/api/v1/expansion/sample', params={"tenant_id": 3, "seed": "粉末"}).status_code == 409
    call.assert_not_awaited()
    sql = session.scalars.await_args.args[0].compile()
    assert "baidu_accounts.tenant_id =" in str(sql) and 3 in sql.params.values()


def test_sample_http_is_bounded_and_never_auto_evaluates(monkeypatch):
    sample = AsyncMock(return_value=10)
    ai = AsyncMock()
    monkeypatch.setattr(expansion, "sample_planner_candidates", sample)
    monkeypatch.setattr(expansion, "evaluate_candidates_for_tenant", ai)
    account = SimpleNamespace(id=5)
    session = SimpleNamespace(get=AsyncMock(return_value=tenant()), scalars=AsyncMock(return_value=rows_result([account])))
    client = api_client(session)
    result = client.post('/api/v1/expansion/sample', params={"tenant_id": 3, "seed": "粉末"})
    assert result.status_code == 200 and result.json()["ai_evaluated"] is False
    sample.assert_awaited_once_with(session, account, "粉末", 20)
    ai.assert_not_awaited()
    for seed, limit in [("a,b", 20), ("a，b", 20), (" \n", 20), ("粉末", 21), ("粉末", 0)]:
        sample.reset_mock()
        assert client.post('/api/v1/expansion/sample', params={"tenant_id": 3, "seed": seed, "limit": limit}).status_code == 422
        sample.assert_not_awaited()


def test_sample_has_no_bulk_sync_ai_or_baidu_write_path():
    source = (Path(__file__).resolve().parents[1] / "app/sem_expansion_sample.py").read_text(encoding="utf-8")
    for forbidden in ["get_account_recommend_words", "sync_query", "evaluate_candidates", "apply_", "add_words"]:
        assert forbidden not in source


@pytest.mark.parametrize("path", ["sample", "evaluate"])
@pytest.mark.parametrize("tenant_id,permission", [(4, "edit"), (3, "view")])
def test_real_auth_dependency_blocks_cross_tenant_and_readonly(monkeypatch, path, tenant_id, permission):
    app = FastAPI()
    app.include_router(expansion.router)
    session = SimpleNamespace(get=AsyncMock(), scalars=AsyncMock())
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[require_auth] = lambda: AuthContext(
        user_id=9, username="tester", role_name="运营", tenant_id=3,
        permissions={"optimize.expand": permission},
    )
    call = AsyncMock()
    monkeypatch.setattr(expansion, "sample_planner_candidates", call)
    monkeypatch.setattr(expansion, "evaluate_candidates_for_tenant", call)
    response = TestClient(app).post(f'/api/v1/expansion/{path}', params={"tenant_id": tenant_id, "seed": "粉末"})
    assert response.status_code == 403
    call.assert_not_awaited()
    session.get.assert_not_awaited()


@pytest.mark.parametrize("force", [False, True])
@pytest.mark.parametrize("failure", ["batch", "missing"])
def test_failed_first_batch_does_not_block_next_batch_or_retry(monkeypatch, force, failure):
    monkeypatch.setattr(evaluator, "is_enabled", lambda: True)
    rows = [candidate(i) for i in range(1, 26)]
    attempted = []
    should_fail = True
    async def query(_stmt):
        return rows_result([r for r in rows if force or r.ai_evaluated_at is None])
    async def verdict(_tenant, words):
        attempted.append([w["word"] for w in words])
        if should_fail:
            if failure == "batch":
                raise evaluator.DeepSeekError("offline rejection")
            return {}
        return {w["word"]: dict(relevance="relevant", recommend="watch", reason="相关",
                              suggested_bid=None, bid_reason=None) for w in words}
    monkeypatch.setattr(evaluator, "_evaluate_batch", verdict)
    session = SimpleNamespace(scalars=query, commit=AsyncMock())
    async def run():
        nonlocal should_fail
        first = await evaluator.evaluate_candidates_for_tenant(session, tenant(), force=force, limit=20)
        assert first["next_after_id"] == 20 and first["failed_candidate_ids"] == list(range(1, 21))
        should_fail = False
        second = await evaluator.evaluate_candidates_for_tenant(session, tenant(), force=force, limit=20, after_id=first["next_after_id"])
        assert second["successful_words"] == 5 and second["next_after_id"] is None
        assert attempted[1] == [r.word for r in rows[20:]]
        retry = await evaluator.evaluate_candidates_for_tenant(session, tenant(), force=force, limit=20, retry_ids=first["failed_candidate_ids"])
        assert retry["successful_words"] == 20 and retry["failed_candidate_ids"] == []
        assert set(attempted[1]).isdisjoint(attempted[2])
        assert all(r.status == "pending" for r in rows)
    asyncio.run(run())


def test_cursor_and_retry_keep_multisource_words_together(monkeypatch):
    monkeypatch.setattr(evaluator, "is_enabled", lambda: True)
    rows = [candidate(1, "粉末"), candidate(2, "涂料"), candidate(99, "粉末")]
    call = AsyncMock(return_value={})
    monkeypatch.setattr(evaluator, "_evaluate_batch", call)
    session = SimpleNamespace(scalars=AsyncMock(return_value=rows_result(rows)), commit=AsyncMock())
    result = asyncio.run(evaluator.evaluate_candidates_for_tenant(session, tenant(), limit=1))
    assert result["next_after_id"] == 1
    asyncio.run(evaluator.evaluate_candidates_for_tenant(session, tenant(), limit=1, after_id=1))
    assert call.await_args.args[1][0]["word"] == "涂料"
    asyncio.run(evaluator.evaluate_candidates_for_tenant(session, tenant(), limit=1, retry_ids=[99]))
    assert call.await_args.args[1][0]["word"] == "粉末"
    call.reset_mock()
    result = asyncio.run(evaluator.evaluate_candidates_for_tenant(session, tenant(), limit=20, retry_ids=[123456]))
    assert result["evaluated"] == 0 and result["next_after_id"] is None
    call.assert_not_awaited()


def test_retry_api_bounds_and_cursor_forwarding(monkeypatch):
    call = AsyncMock(return_value={"enabled": True, "evaluated": 0})
    monkeypatch.setattr(expansion, "evaluate_candidates_for_tenant", call)
    client = api_client(SimpleNamespace(get=AsyncMock(return_value=tenant())))
    url = '/api/v1/expansion/evaluate?tenant_id=3'
    assert client.post(url + '&after_id=20').status_code == 200
    assert call.await_args.kwargs["after_id"] == 20
    assert client.post(url, json={"retry_ids": [1, 2]}).status_code == 200
    assert call.await_args.kwargs["retry_ids"] == [1, 2]
    for suffix, body in [('&after_id=-1', None), ('&after_id=20', {"retry_ids": [1]}),
                         ('&limit=1', {"retry_ids": [1, 2]}), ('', {"retry_ids": []}),
                         ('', {"retry_ids": [-1]}), ('', {"retry_ids": list(range(1, 22))})]:
        call.reset_mock()
        assert client.post(url + suffix, json=body).status_code == 422
        call.assert_not_awaited()


def test_successful_force_round_finishes_without_repeating_words(monkeypatch):
    monkeypatch.setattr(evaluator, "is_enabled", lambda: True)
    rows = [candidate(i) for i in range(1, 46)]
    seen = []
    async def verdict(_tenant, words):
        seen.extend(w["word"] for w in words)
        return {w["word"]: dict(relevance="relevant", recommend="watch", reason="相关",
                              suggested_bid=None, bid_reason=None) for w in words}
    monkeypatch.setattr(evaluator, "_evaluate_batch", verdict)
    session = SimpleNamespace(scalars=AsyncMock(return_value=rows_result(rows)), commit=AsyncMock())
    async def run():
        cursor = 0
        sizes = []
        for _ in range(3):
            result = await evaluator.evaluate_candidates_for_tenant(session, tenant(), force=True, limit=20, after_id=cursor)
            sizes.append(result["successful_words"])
            cursor = result["next_after_id"]
        assert sizes == [20, 20, 5] and cursor is None
        assert len(seen) == len(set(seen)) == 45
    asyncio.run(run())
