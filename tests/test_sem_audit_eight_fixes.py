"""Offline regressions for the SEM audit; no external API or production database."""
import ast
import asyncio
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import Column, JSON, MetaData, Table, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB, asyncpg
from sqlalchemy.orm import Session

for key, value in {
    "DATABASE_URL": "postgresql+asyncpg://test:test@localhost/test",
    "BAIDU_APP_ID": "test-app", "BAIDU_SECRET_KEY": "1234567890abcdef",
    "BAIDU_DEFAULT_USERNAME": "test-user", "BAIDU_DEFAULT_UCID": "1",
    "BAIDU_SELF_ACCESS_TOKEN": "test-token",
    "BAIDU_SELF_TOKEN_EXPIRES_AT": "2099-01-01T00:00:00",
    "CRYPTO_MASTER_KEY_B64": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "ADMIN_API_KEY": "test-admin-key",
}.items():
    os.environ.setdefault(key, value)

from app.api import assistant, roles, users, writeback as queue_api
from app.baidu import client, oauth, writeback
from app.models import BidWriteback, WritebackAction
from app.rules import engine as rules
from app.rules.base import AlertDraft
from app.security.auth import AuthContext, require_admin, require_auth
from app.suggestions import engine as suggestions


def auth(permissions, tenant_id=10):
    return AuthContext(1, "operator", "custom", tenant_id, permissions)


def test_global_admin_rejects_bound_account_even_with_edit_permission():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_admin(auth({"settings.accounts": "edit"})))
    assert exc.value.status_code == 403
    global_admin = auth({"settings.accounts": "edit"}, None)
    assert asyncio.run(require_admin(global_admin)) is global_admin
    with pytest.raises(HTTPException):
        asyncio.run(require_admin(auth({"settings.accounts": "view"}, None)))


@pytest.mark.parametrize("method,path,payload", [
    ("GET", "/api/v1/users", None),
    ("POST", "/api/v1/users", {"username": "intruder", "password": "not-a-real-password", "role_id": 1}),
    ("PATCH", "/api/v1/users/1", {"clear_tenant": True, "role_id": 1}),
    ("GET", "/api/v1/roles", None),
    ("POST", "/api/v1/roles", {"name": "intruder", "permissions": {"settings.accounts": "edit"}}),
    ("PATCH", "/api/v1/roles/1", {"permissions": {"settings.accounts": "edit"}}),
    ("DELETE", "/api/v1/roles/1", None),
])
def test_bound_admin_is_blocked_at_actual_global_routes(method, path, payload):
    app = FastAPI()
    app.include_router(users.router)
    app.include_router(roles.router)
    app.dependency_overrides[require_auth] = lambda: auth({"settings.accounts": "edit"})
    database = Mock(side_effect=AssertionError("must not reach the database"))
    def no_database():
        return database()
    app.dependency_overrides[users.get_session] = no_database
    with TestClient(app) as http:
        assert http.request(method, path, json=payload).status_code == 403
    database.assert_not_called()


@pytest.mark.parametrize("action,permission", [
    ("pause", "optimize.keywords"), ("adjust_bid", "optimize.keywords"),
    ("negative", "optimize.negatives"), ("set_budget", "manage.account"),
])
def test_assistant_adopt_requires_action_edit(monkeypatch, action, permission):
    execute = AsyncMock(return_value={"status": "dry_run"})
    monkeypatch.setattr(assistant, "adopt_action", execute)
    req = assistant.AdoptRequest(tenant_id=10, type=action, keywords=["test"], budget=100)
    for permissions in ({"assistant": "view"}, {"assistant": "edit", permission: "view"}):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(assistant.adopt(req, auth(permissions), object()))
        assert exc.value.status_code == 403
    execute.assert_not_awaited()
    editor = auth({"assistant": "view", permission: "edit"})
    assert asyncio.run(assistant.adopt(req, editor, object())) == {"status": "dry_run"}
    execute.assert_awaited_once()
    with pytest.raises(HTTPException):
        asyncio.run(assistant.adopt(req, auth({permission: "edit"}, 20), object()))
    assert execute.await_count == 1


@pytest.mark.parametrize("http_status", [400, 429, 500, 502, 503, 504])
def test_http_failure_requires_reconciliation(monkeypatch, http_status):
    http = SimpleNamespace(post=AsyncMock(return_value=httpx.Response(http_status, text="gateway error")))

    @asynccontextmanager
    async def transport(**kwargs):
        yield http

    monkeypatch.setattr(client.httpx, "AsyncClient", transport)
    monkeypatch.setattr(client, "get_settings", lambda: SimpleNamespace(
        baidu_api_base_url="https://example.invalid", baidu_legacy_split_confirmation_enabled=False,
        baidu_live_write_allowed=lambda *args: True,
    ))
    monkeypatch.setattr(client, "resolve_baidu_write_dry_run", lambda *args: False)
    with pytest.raises(client.BaiduHTTPError) as exc:
        asyncio.run(client.BaiduAPIClient("dummy", "dummy").call("KeywordService", "updateWord", {}))
    for model in (BidWriteback, WritebackAction):
        record = model()
        writeback._record_writeback_exception(record, exc.value, dry_run=False)
        assert record.status == "reconcile"
        assert "需人工对账" in record.error_msg
        writeback._record_writeback_exception(record, exc.value, dry_run=True)
        assert record.status == "failed"


def test_explicit_rejection_is_still_failed():
    for error in (client.BaiduAPIError(9011519, "invalid field"), client.BaiduLiveWriteBlockedError("blocked")):
        record = BidWriteback()
        writeback._record_writeback_exception(record, error, dry_run=False)
        assert record.status == "failed"


def test_body_rejection_is_not_misclassified_as_transport(monkeypatch):
    @asynccontextmanager
    async def transport(**kwargs):
        yield SimpleNamespace(post=AsyncMock(return_value=httpx.Response(200, json={
            "header": {"status": 1, "failures": [{"code": 9011519, "message": "invalid field"}]},
        })))
    monkeypatch.setattr(client.httpx, "AsyncClient", transport)
    with pytest.raises(client.BaiduAPIError) as exc:
        asyncio.run(client.BaiduAPIClient("dummy", "dummy").call("KeywordService", "getWord", {}))
    assert not isinstance(exc.value, client.BaiduHTTPError)
    record = BidWriteback()
    writeback._record_writeback_exception(record, exc.value, dry_run=False)
    assert record.status == "failed"


def test_sem_lifespan_only_starts_sem_scheduler():
    source = Path("app/main.py").read_text(encoding="utf-8")
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.AsyncFunctionDef) and n.name == "lifespan")
    start, stop, guard = Mock(), Mock(), Mock()
    namespace = dict(asynccontextmanager=asynccontextmanager, FastAPI=object,
                     enforce_production_secrets=guard, start_scheduler=start, shutdown_scheduler=stop,
                     settings=SimpleNamespace(app_env="test", app_base_url="https://example.invalid", baidu_default_username="dummy"),
                     logger=Mock())
    # Execute the actual lifecycle function, not a copied implementation.
    assert "app.geo" not in ast.unparse(node)
    exec(compile(ast.Module(body=[node], type_ignores=[]), "lifespan", "exec"), namespace)

    async def run():
        async with namespace["lifespan"](None):
            start.assert_called_once()
            stop.assert_not_called()
    asyncio.run(run())
    guard.assert_called_once_with(namespace["settings"], hard_fail=True)
    stop.assert_called_once()


@pytest.mark.parametrize("module,runner,worker", [
    (rules, "run_rules_for_all_tenants", "run_rules_for_tenant"),
    (suggestions, "run_suggestions_for_all_tenants", "run_suggestions_for_tenant"),
])
@pytest.mark.parametrize("cleanup_failure", [False, True])
def test_one_tenant_failure_cannot_poison_next(monkeypatch, module, runner, worker, cleanup_failure):
    tenants = [SimpleNamespace(id=1, name="first"), SimpleNamespace(id=2, name="second")]
    monkeypatch.setattr(module, "list_active_module_tenants", AsyncMock(return_value=tenants))
    sessions, closed = [], []

    @asynccontextmanager
    async def factory():
        session = SimpleNamespace(get=AsyncMock(side_effect=lambda model, id: tenants[id-1]), poisoned=False)
        sessions.append(session)
        try:
            yield session
        finally:
            closed.append(session)
            if session.poisoned and cleanup_failure:
                raise RuntimeError("cleanup failed")

    async def evaluate(session, tenant, *args):
        assert not session.poisoned
        if tenant.id == 1:
            session.poisoned = True
            raise RuntimeError("aborted transaction")
        return 7

    monkeypatch.setattr(module, "async_session_factory", factory)
    monkeypatch.setattr(module, worker, evaluate)
    args = [object(), date(2026, 9, 5)] if module is rules else [object()]
    assert asyncio.run(getattr(module, runner)(*args)) == {"first": -1, "second": 7}
    assert len(sessions) == len(closed) == 2
    assert sessions[0] is not sessions[1]


def test_failed_rule_rolls_back_savepoint_before_next(monkeypatch):
    state = SimpleNamespace(poisoned=False, rollbacks=0)

    @asynccontextmanager
    async def savepoint():
        try:
            yield
        except Exception:
            state.poisoned = False
            state.rollbacks += 1
            raise

    async def fail(*args):
        state.poisoned = True
        raise RuntimeError("constraint conflict")

    async def succeed(*args):
        assert not state.poisoned
        return [AlertDraft("good", "P2", "title", "message", date(2026, 9, 5), keyword_id=1)]

    monkeypatch.setattr(rules, "ALL_RULES", [SimpleNamespace(code="bad", evaluate=fail), SimpleNamespace(code="good", evaluate=succeed)])
    monkeypatch.setattr(rules, "merge_duplicate_alerts", AsyncMock(return_value=0))
    session = SimpleNamespace(begin_nested=savepoint, execute=AsyncMock(), commit=AsyncMock())
    assert asyncio.run(rules.run_rules_for_tenant(session, SimpleNamespace(id=1), date(2026, 9, 5))) == 1
    assert state.rollbacks == 1
    session.execute.assert_awaited_once()


@pytest.mark.parametrize("cleanup_failure", [False, True])
def test_oauth_refresh_uses_ids_and_isolated_sessions(monkeypatch, cleanup_failure):
    listing = SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [1, 2])))
    visited, closed = [], []

    @asynccontextmanager
    async def factory():
        grant = SimpleNamespace(id=None, status="active")
        async def get(model, id):
            grant.id = id
            return grant
        try:
            yield SimpleNamespace(get=get)
        finally:
            closed.append(grant.id)
            grant.__dict__.clear()  # no ORM attributes may be read after cleanup
            if len(closed) == 1 and cleanup_failure:
                raise RuntimeError("rollback failure")

    async def refresh(session, grant):
        visited.append(grant.id)
        if grant.id == 1:
            raise RuntimeError("database failure")
        return True
    monkeypatch.setattr(oauth, "async_session_factory", factory)
    monkeypatch.setattr(oauth, "refresh_grant", refresh)
    assert asyncio.run(oauth.refresh_expiring_oauth_grants(listing)) == {"checked": 2, "failed": 1, "refreshed": 1}
    assert visited == closed == [1, 2]
    assert list(listing.scalars.call_args.args[0].selected_columns.keys()) == ["id"]


@pytest.mark.parametrize("upsert,keyword", [(rules._upsert_keyword_alerts, True), (rules._upsert_entity_alerts, False)])
def test_alert_upserts_respect_asyncpg_parameter_limit(upsert, keyword):
    rows = [rules._alert_record(SimpleNamespace(id=1), AlertDraft(
        "test", "P2", "title", "message", date(2026, 9, 5),
        keyword_id=i if keyword else None, entity_ref=None if keyword else str(i),
    )) for i in range(2600)]
    session = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock())
    asyncio.run(upsert(session, rows))
    sizes = []
    for call in session.execute.call_args_list:
        compiled = call.args[0].compile(dialect=asyncpg.dialect())
        assert len(compiled.params) < 32767
        sizes.append(sum(key.startswith("tenant_id_m") for key in compiled.params))
        assert "priority = excluded.priority" in str(compiled)
        assert "status = excluded.status" in str(compiled)
    assert sum(sizes) == 2600 and len(sizes) > 1
    session.commit.assert_not_awaited()  # caller owns the whole transaction


def test_queue_sql_and_python_stage_classification_agree():
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    # Only columns touched by the SQL projection are needed for this matrix.
    cases = [(status, dry) for status in ("failed", "pending", "reconcile", "success", "dry_run", "new_state", None)
             for dry in (False, True, None)]
    for model in (BidWriteback, WritebackAction):
        columns = [Column(c.name, c.type) for c in model.__table__.columns
                   if c.name in {"id", "tenant_id", "created_at", "status", "dry_run"}]
        Table(model.__tablename__, metadata, *columns)
    metadata.create_all(engine)
    with engine.begin() as conn:
        for table in metadata.tables.values():
            conn.execute(table.insert(), [dict(id=i, tenant_id=10, status=status, dry_run=dry)
                                          for i, (status, dry) in enumerate(cases)])
        queue = queue_api._queue_rows_query(10)
        for row in conn.execute(select(queue)):
            assert row.stage == queue_api._queue_stage(*cases[row.id])
    engine.dispose()


def test_queue_filters_history_before_paging_and_isolates_tenant(monkeypatch):
    # Actual SQL query execution against disposable in-memory tables; no migration.
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    tables = {}
    for model in (BidWriteback, WritebackAction):
        tables[model] = Table(model.__tablename__, metadata, *[
            Column(c.name, JSON() if isinstance(c.type, JSONB) else c.type, primary_key=c.primary_key)
            for c in model.__table__.columns
        ])
    metadata.create_all(engine)
    old = datetime(2026, 1, 1)
    with Session(engine) as sync:
        for model, table in tables.items():
            values = []
            for id in range(1, 605):
                values.append(dict(id=id, tenant_id=10 if id < 604 else 20,
                                   created_at=old + timedelta(minutes=id),
                                   status="reconcile" if id <= 3 or id == 604 else "success", dry_run=False,
                                   **({"new_bid": 1} if model is BidWriteback else {})))
            sync.execute(table.insert(), values)
        sync.commit()
        session = SimpleNamespace(execute=AsyncMock(side_effect=sync.execute), scalars=AsyncMock(side_effect=sync.scalars))
        monkeypatch.setattr(queue_api, "get_writeback_mode", AsyncMock(return_value={
            "writeback_enabled": False, "mode": "dry_run", "live_scopes": [],
        }))
        def page(offset, stage="reconciliation_required"):
            return asyncio.run(queue_api.list_writeback_queue(10, 2, auth({}), session, stage, offset))
        first, second, third = page(0), page(2), page(4)
        assert first["total"] == 6
        assert first["counts"] == {"pending_writeback": 0, "reconciliation_required": 6, "executed": 1200, "failed": 0}
        assert first["has_more"] and not third["has_more"]
        keys = [row["key"] for result in (first, second, third) for row in result["items"]]
        assert keys == ["bid:3", "action:3", "bid:2", "action:2", "bid:1", "action:1"]
        assert page(0, None)["total"] == 1206
        with pytest.raises(HTTPException):
            asyncio.run(queue_api.list_writeback_queue(20, 2, auth({}), session, None, 0))
    engine.dispose()


def _suggestion_records(count):
    return [dict(tenant_id=10, rule_code="test", suggestion_type="lower",
                 priority="P2", confidence="high", current_bid=1, suggested_bid=0.99,
                 change_pct=-1, reason="test", signals={}, report_date=date(2026, 9, 5),
                 keyword_id=i, keyword="test", campaign_id=1, campaign_name="test", adgroup_id=1)
            for i in range(1, count + 1)]


@pytest.mark.parametrize("count", [0, 1, 1000, 1001, 2100])
def test_suggestion_batches_bound_parameters_preserve_human_state(count):
    records = _suggestion_records(count)
    session = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock(), rollback=AsyncMock())
    asyncio.run(suggestions._persist_suggestions(session, 10, date(2026, 9, 5), records))
    if not count:
        session.execute.assert_not_awaited()
        session.commit.assert_not_awaited()
        return
    seen = []
    for call in session.execute.call_args_list[:-1]:
        compiled = call.args[0].compile(dialect=asyncpg.dialect())
        assert len(compiled.params) < 32767
        seen.extend(value for key, value in compiled.params.items() if key.startswith("keyword_id_m"))
        conflict = str(compiled).split("DO UPDATE SET", 1)[1]
        assert "status = CASE WHEN (suggestions.status =" in conflict
        assert "ELSE suggestions.status END" in conflict
        for column in ("adopted_at", "handling_status", "assignee_id", "due_at",
                       "workflow_updated_by", "workflow_updated_at"):
            assert column not in conflict
    assert seen == list(range(1, count + 1))
    cleanup = session.execute.call_args.args[0].compile(dialect=asyncpg.dialect())
    assert cleanup.params["keyword_ids"] == seen  # all batches participate in ONE exclusion
    assert "!= ALL" in str(cleanup)
    assert "pending" in cleanup.params.values() and "expired" in cleanup.params.values()
    assert "suggestions.tenant_id =" in str(cleanup)
    assert "suggestions.report_date !=" in str(cleanup)
    assert len(cleanup.params) < 10
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


@pytest.mark.parametrize("fail_at", [2, 4])
def test_suggestion_late_batch_or_cleanup_failure_rolls_back_every_batch(fail_at):
    calls = 0
    async def execute(stmt):
        nonlocal calls
        calls += 1
        if calls == fail_at:
            raise RuntimeError("simulated transaction failure")
    session = SimpleNamespace(execute=execute, commit=AsyncMock(), rollback=AsyncMock())
    with pytest.raises(RuntimeError, match="simulated"):
        asyncio.run(suggestions._persist_suggestions(session, 10, date(2026, 9, 5), _suggestion_records(2100)))
    assert calls == fail_at
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()


def test_suggestion_large_id_lists_use_one_array_bind():
    records = _suggestion_records(33000)
    session = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock(), rollback=AsyncMock())
    asyncio.run(suggestions._persist_suggestions(session, 10, date(2026, 9, 5), records))
    compiled = session.execute.call_args.args[0].compile(dialect=asyncpg.dialect())
    assert len(compiled.params) < 10
    assert len(compiled.params["keyword_ids"]) == 33000

    # Exercise the actual keyword read before rule/AI processing.
    metric_rows = [(i, "test", 1, 1, 10, 0, 1) for i in range(1, 33001)]
    reader = SimpleNamespace(
        scalar=AsyncMock(return_value=date(2026, 9, 5)),
        execute=AsyncMock(return_value=SimpleNamespace(all=lambda: metric_rows)),
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [])),
    )
    assert asyncio.run(suggestions.run_suggestions_for_tenant(reader, SimpleNamespace(id=10))) == 0
    query = reader.scalars.call_args.args[0].compile(dialect=asyncpg.dialect())
    assert "= ANY" in str(query) and len(query.params) < 10
    assert len(query.params["keyword_ids"]) == 33000


def test_suggestion_engine_routes_full_result_through_atomic_batches(monkeypatch):
    records = _suggestion_records(2100)
    drafts = {r["keyword_id"]: SimpleNamespace(**r) for r in records}
    metrics = [(i, "test", 1, 1, 10, 0, 1) for i in drafts]
    keywords = [SimpleNamespace(keyword_id=i, keyword="test", campaign_id=1, adgroup_id=1,
                                category="brand", price=1, quality=1, left_price_guide=None,
                                m_price_guide=None) for i in drafts]
    monkeypatch.setattr(suggestions, "ALL_RULES", [lambda profile, ctx: drafts[profile.keyword_id]])
    monkeypatch.setattr(suggestions, "apply_guardrails", lambda draft, profile: draft)
    monkeypatch.setattr("app.ai.customer_profile.build_customer_brief", AsyncMock(return_value="test"))
    monkeypatch.setattr("app.ai.judge.enhance_draft", AsyncMock(side_effect=lambda profile, draft, brief: draft))
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=date(2026, 9, 5)),
        execute=AsyncMock(return_value=SimpleNamespace(all=lambda: metrics)),
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: keywords)),
        commit=AsyncMock(), rollback=AsyncMock(),
    )
    assert asyncio.run(suggestions.run_suggestions_for_tenant(session, SimpleNamespace(id=10))) == 2100
    assert session.execute.await_count == 5  # metrics + three upserts + one cleanup
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


@pytest.mark.parametrize("scenario", [
    "ai_rejects_all", "rules_return_none", "guardrails_reject_all",
    "rule_failure", "partial_rule_failure", "ai_failure", "profile_failure",
    "no_report_date", "no_metrics", "no_assets", "no_rules",
])
def test_empty_suggestion_result_requires_complete_evaluation(monkeypatch, scenario):
    drafts = {r["keyword_id"]: SimpleNamespace(**r) for r in _suggestion_records(2)}
    metrics = [(i, "test", 1, 1, 10, 0, 1) for i in drafts]
    keywords = [SimpleNamespace(keyword_id=i, keyword="test", campaign_id=1, adgroup_id=1,
                                category="normal", price=1, quality=1, left_price_guide=None,
                                m_price_guide=None) for i in drafts]
    def rule(profile, ctx):
        if scenario == "rule_failure" or (scenario == "partial_rule_failure" and profile.keyword_id == 2):
            raise RuntimeError("rule failure")
        return None if scenario == "rules_return_none" else drafts[profile.keyword_id]
    monkeypatch.setattr(suggestions, "ALL_RULES", [] if scenario == "no_rules" else [rule])
    monkeypatch.setattr(suggestions, "apply_guardrails", lambda d, p: None if scenario == "guardrails_reject_all" else d)
    monkeypatch.setattr("app.ai.customer_profile.build_customer_brief", AsyncMock(
        side_effect=RuntimeError("profile failure") if scenario == "profile_failure" else None,
        return_value="test",
    ))
    monkeypatch.setattr("app.ai.judge.enhance_draft", AsyncMock(
        side_effect=RuntimeError("AI failure") if scenario == "ai_failure" else None,
        return_value=None,
    ))
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=None if scenario == "no_report_date" else date(2026, 9, 5)),
        execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [] if scenario == "no_metrics" else metrics)),
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [] if scenario == "no_assets" else keywords)),
        commit=AsyncMock(), rollback=AsyncMock(),
    )
    call = suggestions.run_suggestions_for_tenant(session, SimpleNamespace(id=10))
    if scenario in {"rule_failure", "partial_rule_failure", "ai_failure", "profile_failure"}:
        with pytest.raises(RuntimeError):
            asyncio.run(call)
    else:
        assert asyncio.run(call) == 0
    updates = [c.args[0] for c in session.execute.call_args_list if getattr(c.args[0], "is_update", False)]
    if scenario in {"ai_rejects_all", "rules_return_none", "guardrails_reject_all"}:
        assert len(updates) == 1
        compiled = updates[0].compile(dialect=asyncpg.dialect())
        assert compiled.params["keyword_ids"] == []
        assert compiled.params["evaluated_keyword_ids"] == [1, 2]
        assert "pending" in compiled.params.values()
        assert "suggestions.report_date <=" in str(compiled)
        session.commit.assert_awaited_once()
    else:
        assert updates == []
        session.commit.assert_not_awaited()


def test_empty_cleanup_is_scoped_and_preserves_human_and_newer_results():
    """Run the cleanup predicate locally, translating only PostgreSQL array operators."""
    from sqlalchemy import Integer, String, Date, update
    from sqlalchemy.sql import visitors, operators
    from sqlalchemy.sql.elements import BinaryExpression, CollectionAggregate
    from app.models import Suggestion

    session = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock(), rollback=AsyncMock())
    asyncio.run(suggestions._persist_suggestions(
        session, 10, date(2026, 9, 5), [], evaluated_keyword_ids=[1, 2]
    ))
    statement = session.execute.call_args.args[0]
    def portable(expr):
        if isinstance(expr, BinaryExpression) and isinstance(expr.right, CollectionAggregate):
            values = expr.right.element.element.value
            if expr.right.operator is operators.any_op:
                return expr.left.in_(values)
            if expr.right.operator is operators.all_op:
                return expr.left.notin_(values)
        return None
    predicate = visitors.replacement_traverse(statement.whereclause, {}, portable)
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    table = Table("suggestions", metadata, Column("id", Integer, primary_key=True),
                  Column("tenant_id", Integer), Column("keyword_id", Integer),
                  Column("status", String), Column("report_date", Date))
    metadata.create_all(engine)
    rows = [
        dict(id=1, tenant_id=10, keyword_id=1, status="pending", report_date=date(2026, 9, 5)),
        dict(id=2, tenant_id=10, keyword_id=2, status="pending", report_date=date(2026, 9, 4)),
        dict(id=3, tenant_id=10, keyword_id=1, status="adopted", report_date=date(2026, 9, 4)),
        dict(id=4, tenant_id=10, keyword_id=1, status="ignored", report_date=date(2026, 9, 4)),
        dict(id=5, tenant_id=20, keyword_id=1, status="pending", report_date=date(2026, 9, 4)),
        dict(id=6, tenant_id=10, keyword_id=3, status="pending", report_date=date(2026, 9, 4)),
        dict(id=7, tenant_id=10, keyword_id=1, status="pending", report_date=date(2026, 9, 6)),
    ]
    with engine.begin() as conn:
        conn.execute(table.insert(), rows)
        conn.execute(update(Suggestion).where(predicate).values(status="expired"))
        states = dict(conn.execute(select(table.c.id, table.c.status)).all())
    assert states == {1: "expired", 2: "expired", 3: "adopted", 4: "ignored",
                      5: "pending", 6: "pending", 7: "pending"}
    engine.dispose()


@pytest.mark.parametrize("initial_status", ["pending", "expired", "adopted", "ignored", "unknown"])
@pytest.mark.parametrize("fail_cleanup", [False, True])
def test_suggestion_reactivation_lifecycle_preserves_human_state_and_rolls_back(monkeypatch, initial_status, fail_cleanup):
    """Execute actual persistence with SQLite adapters for PG-only syntax, offline."""
    from sqlalchemy import Integer, UniqueConstraint
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from sqlalchemy.sql import visitors, operators
    from sqlalchemy.sql.elements import BinaryExpression, CollectionAggregate
    from app.models import Suggestion

    class PortableInsert:
        def __init__(self, model):
            self.stmt = sqlite_insert(model)
        def values(self, records):
            self.stmt = self.stmt.values(records)
            return self
        @property
        def excluded(self):
            return self.stmt.excluded
        def on_conflict_do_update(self, *, constraint, set_):
            assert constraint == "uq_suggestions_tenant_kw_date"
            return self.stmt.on_conflict_do_update(
                index_elements=["tenant_id", "keyword_id", "report_date"], set_=set_
            )

    def portable(expr):
        if isinstance(expr, BinaryExpression) and isinstance(expr.right, CollectionAggregate):
            values = expr.right.element.element.value
            if expr.right.operator is operators.any_op:
                return expr.left.in_(values)
            if expr.right.operator is operators.all_op:
                return expr.left.notin_(values)
        return None

    monkeypatch.setattr(suggestions, "pg_insert", PortableInsert)
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    table = Table("suggestions", metadata, *[
        Column(c.name, Integer() if c.primary_key else JSON() if isinstance(c.type, JSONB) else c.type,
               primary_key=c.primary_key, server_default=c.server_default)
        for c in Suggestion.__table__.columns
    ], UniqueConstraint("tenant_id", "keyword_id", "report_date"))
    metadata.create_all(engine)
    when = datetime(2026, 9, 5, 10)
    record = _suggestion_records(1)[0]
    human = dict(handling_status="completed", assignee_id=7, due_at=when,
                 workflow_updated_by=7, workflow_updated_at=when,
                 adopted_at=when if initial_status == "adopted" else None)
    with engine.connect() as conn:
        conn.execute(table.insert().values(**record, id=1, status=initial_status, **human))
        conn.commit()
        fail = False
        async def execute(stmt):
            if fail and getattr(stmt, "is_update", False):
                raise RuntimeError("cleanup failure after upsert")
            return conn.execute(visitors.replacement_traverse(stmt, {}, portable))
        async def commit():
            conn.commit()
        async def rollback():
            conn.rollback()
        session = SimpleNamespace(execute=execute, commit=commit, rollback=rollback)
        def persist(records):
            return asyncio.run(suggestions._persist_suggestions(
                session, 10, date(2026, 9, 5), records, evaluated_keyword_ids=[1]
            ))

        # First successful assessment rejects this keyword; only pending expires.
        persist([])
        expired_status = "expired" if initial_status == "pending" else initial_status
        assert conn.scalar(select(table.c.status)) == expired_status
        # Same report date re-hits: only system-expired status becomes pending.
        revised = dict(record, suggested_bid=1.1, reason="new confirmed recommendation")
        fail = fail_cleanup
        if fail_cleanup:
            with pytest.raises(RuntimeError, match="cleanup failure"):
                persist([revised])
            row = conn.execute(select(table)).mappings().one()
            assert row["status"] == expired_status
            assert float(row["suggested_bid"]) == 0.99
            fail = False
        persist([revised])
        persist([revised])  # repeated same-date run does not duplicate the row
        row = conn.execute(select(table)).mappings().one()
        assert row["status"] == ("pending" if expired_status == "expired" else initial_status)
        assert float(row["suggested_bid"]) == 1.1
        assert row["reason"] == revised["reason"]
        assert row["id"] == 1
        for key, value in human.items():
            assert row[key] == value
    engine.dispose()
