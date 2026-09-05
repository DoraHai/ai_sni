"""Offline contract checks. No production credentials, database or network required."""
import asyncio
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

# Reuse the repository's test-only environment bootstrap.
import test_writeback_approval  # noqa: F401
from app.api import sem_metrics as api
from app.baidu import writeback_approval as approvals
from app.baidu.writeback import _claim_funds_approval, WritebackError
from app.security.auth import AuthContext
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from pydantic import ValidationError


def context(tenant_id=3, permissions=None):
    return AuthContext(user_id=9, username="test", role_name="operator", tenant_id=tenant_id,
                       permissions=permissions if permissions is not None else {
                           "monitor.dashboard": "view", "verify.adjustments": "view"})


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 9, 5, 12, tzinfo=tz)


def session(rows=(), budget=100):
    return SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(monthly_budget=Decimal(budget) if budget is not None else None)),
        scalar=AsyncMock(side_effect=[2, 3]),
        execute=AsyncMock(return_value=SimpleNamespace(all=lambda: rows)),
        commit=AsyncMock(), flush=AsyncMock(), add=Mock(),
    )


def run_snapshot(db, ctx=None, blocked=False):
    with patch.object(api, "datetime", Clock), patch.object(api, "ensure_module_access", AsyncMock()), \
         patch.object(api, "load_sem_identity_states", AsyncMock(return_value={3: {"status": "blocked" if blocked else "ok"}})):
        result = asyncio.run(api.snapshot(tenant_id=3, ctx=ctx or context(), session=db))
    db.commit.assert_not_awaited()
    db.flush.assert_not_awaited()
    db.add.assert_not_called()
    return {item["metric_key"]: item for item in result["items"]}


def test_metrics_observed_month_total_and_same_metric_trend():
    db = session([(date(2026, 9, 1), Decimal("10.25"), 2, 2),
                  (date(2026, 9, 4), Decimal("20.25"), 2, 2)])
    items = run_snapshot(db)
    spend = items["sem.spend.month_to_date_cny"]
    assert spend["value"] == 30.5
    assert spend["as_of"] == "2026-09-04T00:00:00+08:00"
    assert spend["trend_7d"] is None
    assert items["sem.spend.budget_utilization_pct"]["value"] == 30.5
    assert items["sem.accounts.active_count"]["value"] == 2
    assert items["sem.approvals.pending_count"]["value"] == 3
    assert items["sem.identity.conflict_tenant_count"]["value"] == 0
    for item in items.values():
        assert item["definition"]
        assert {"metric_key", "value", "unit", "as_of", "trend_7d"} <= item.keys()
    assert items["sem.approvals.pending_count"]["trend_7d"] is None
    for call in db.scalar.await_args_list + db.execute.await_args_list:
        stmt = call.args[0]
        assert "tenant_id" in str(stmt)
        assert 3 in stmt.compile().params.values()


@pytest.mark.parametrize("budget", [None, 0, -1])
def test_no_positive_budget_is_not_zero_utilization(budget):
    items = run_snapshot(session([(date(2026, 9, 4), Decimal(0), 1, 1)], budget))
    assert items["sem.spend.month_to_date_cny"]["value"] == 0
    assert items["sem.spend.budget_utilization_pct"]["value"] is None
    assert items["sem.spend.budget_utilization_pct"]["data_status"] == "no_budget"


@pytest.mark.parametrize("rows,expected", [([], "no_reports"),
    ([(date(2026, 9, 4), Decimal(100), 2, 1)], "unattributed_reports")])
def test_missing_or_ambiguous_reports_fail_closed(rows, expected):
    items = run_snapshot(session(rows))
    assert items["sem.spend.month_to_date_cny"]["value"] is None
    assert items["sem.spend.month_to_date_cny"]["data_status"] == expected


def test_identity_block_does_not_read_or_expose_spend_or_approvals():
    db = session()
    items = run_snapshot(db, blocked=True)
    assert items["sem.identity.conflict_tenant_count"]["value"] == 1
    assert all(item["value"] is None for key, item in items.items() if "identity" not in key)
    db.scalar.assert_not_awaited()
    db.execute.assert_not_awaited()


@pytest.mark.parametrize("ctx", [context(4), context(permissions={}),
    context(permissions={"monitor.dashboard": "view"}),
    context(permissions={"verify.adjustments": "view"})])
def test_permissions_fail_before_data_queries(ctx):
    db = session()
    with pytest.raises(HTTPException) as error:
        run_snapshot(db, ctx)
    assert error.value.status_code == 403
    db.get.assert_not_awaited()


def test_module_entitlement_is_required():
    db = session()
    with patch.object(api, "ensure_module_access", AsyncMock(side_effect=HTTPException(403, "disabled"))):
        with pytest.raises(HTTPException):
            asyncio.run(api.snapshot(tenant_id=3, ctx=context(), session=db))
    db.get.assert_not_awaited()


def test_http_contract_read_only_and_requires_authentication():
    app = FastAPI()
    app.include_router(api.router)
    async def forbidden_db():
        yield session()
    app.dependency_overrides[api.get_session] = forbidden_db
    with TestClient(app) as client:
        assert client.get("/api/v1/sem/metrics/snapshot?tenant_id=3").status_code == 401
        assert client.post("/api/v1/sem/metrics/snapshot?tenant_id=3").status_code == 405


def arguments(key=None):
    return dict(tenant_id=3, action_type=approvals.ACTION_KEYWORD_BID,
                payload={"keyword_id": 7, "new_bid": 1.23}, operator_user_id=9,
                confirmation=approvals.WRITEBACK_CONFIRMATION, idempotency_key=key)


@pytest.mark.parametrize("key", [None, "", "short", "x" * 129, "含中文" * 10])
def test_one_click_invalid_key_rejected_before_any_database_work(key):
    with pytest.raises(approvals.WritebackApprovalError):
        asyncio.run(approvals.create_self_approved_approval(SimpleNamespace(), **arguments(key)))


def test_dry_run_still_needs_no_key_and_live_fails_closed():
    assert asyncio.run(_claim_funds_approval(SimpleNamespace(), approval_id=None,
                       dry_run=True, **arguments())) is None
    with pytest.raises(WritebackError, match="idempotency_key"):
        asyncio.run(_claim_funds_approval(SimpleNamespace(), approval_id=None,
                    dry_run=False, **arguments()))


def test_replayed_key_reuses_consumed_row_and_cannot_consume_again():
    payload, fingerprint = approvals.payload_fingerprint(approvals.ACTION_KEYWORD_BID,
                                                        arguments()["payload"])
    existing = SimpleNamespace(id=41, tenant_id=3, status="consumed",
                               action_type=approvals.ACTION_KEYWORD_BID,
                               payload=payload, payload_hash=fingerprint)
    db = SimpleNamespace(execute=AsyncMock(), scalar=AsyncMock(return_value=existing),
                         add=Mock(), flush=AsyncMock())
    async def replay():
        row = await approvals.create_self_approved_approval(db, **arguments("sem-contract-request-0001"))
        assert row is existing
        with pytest.raises(approvals.WritebackApprovalError, match="已经使用"):
            await approvals.claim_approval(db, approval_id=row.id, tenant_id=3,
                  action_type=row.action_type, payload=payload, operator_user_id=9)
    asyncio.run(replay())
    db.add.assert_not_called()
    db.flush.assert_not_awaited()


def test_real_sql_multiple_accounts_and_tenants_never_mix():
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE baidu_accounts (id INTEGER, tenant_id INTEGER, status TEXT)"))
            conn.execute(text("CREATE TABLE writeback_approvals (id INTEGER, tenant_id INTEGER, status TEXT)"))
            conn.execute(text("CREATE TABLE kw_report_snapshots (tenant_id INTEGER, baidu_account_id INTEGER, report_date DATE, cost NUMERIC)"))
            conn.execute(text("INSERT INTO baidu_accounts VALUES (1,3,'active'),(2,3,'active'),(3,4,'active')"))
            conn.execute(text("INSERT INTO writeback_approvals VALUES (1,3,'pending'),(2,3,'consumed'),(3,4,'pending')"))
            conn.execute(text("INSERT INTO kw_report_snapshots VALUES (3,1,'2026-09-04',10),(3,2,'2026-09-04',20),(4,3,'2026-09-04',900)"))
            db = session()
            async def scalar(stmt):
                return conn.scalar(stmt)
            async def execute(stmt):
                return conn.execute(stmt)
            db.scalar = AsyncMock(side_effect=scalar)
            db.execute = AsyncMock(side_effect=execute)
            items = run_snapshot(db)
            assert items["sem.spend.month_to_date_cny"]["value"] == 30
            assert items["sem.approvals.pending_count"]["value"] == 1
            # A report claiming this tenant but pointing at another tenant's account
            # must invalidate the spend, not add 900 or silently discard it.
            conn.execute(text("INSERT INTO kw_report_snapshots VALUES (3,3,'2026-09-04',900)"))
            items = run_snapshot(db)
            assert items["sem.spend.month_to_date_cny"]["value"] is None
            assert items["sem.spend.month_to_date_cny"]["data_status"] == "unattributed_reports"
    finally:
        engine.dispose()


def test_concurrent_one_click_requests_consume_once_with_transaction_lock():
    """Exercise orchestration concurrently with a transaction-lock test double.

    This tests the service's lock/reuse/claim sequence, not native PostgreSQL locking.
    """
    async def exercise():
        lock = asyncio.Lock()
        rows = []
        class Session:
            async def execute(self, statement):
                assert "pg_advisory_xact_lock" in str(statement)
                await lock.acquire()
                await asyncio.sleep(0)
            async def scalar(self, statement):
                assert "FOR UPDATE" in str(statement)
                return rows[0] if rows else None
            def add(self, row):
                row.id = 41
                rows.append(row)
            async def flush(self):
                await asyncio.sleep(0)
        async def submit():
            db = Session()
            try:
                row = await approvals.create_self_approved_approval(db, **arguments("sem-concurrent-request-0001"))
                await approvals.claim_approval(db, approval_id=row.id, tenant_id=3,
                    action_type=row.action_type, payload=row.payload, operator_user_id=9)
                return "consumed"
            except approvals.WritebackApprovalError:
                return "rejected"
            finally:
                lock.release()
        settings = SimpleNamespace(baidu_legacy_split_confirmation_enabled=False,
                                   baidu_write_confirmation_ttl_minutes=15)
        with patch.object(approvals, "get_settings", return_value=settings):
            results = await asyncio.gather(submit(), submit())
        assert sorted(results) == ["consumed", "rejected"]
        assert len(rows) == 1
    asyncio.run(exercise())


@pytest.mark.parametrize("today,rows,expected", [
    (Clock(2026, 10, 1, tzinfo=api.TZ), [(date(2026, 9, 30), Decimal(100), 1, 1)], None),
    (Clock(2026, 10, 2, tzinfo=api.TZ), [(date(2026, 9, 30), Decimal(100), 1, 1),
                                      (date(2026, 10, 1), Decimal(5), 1, 1)], 5),
    (Clock(2028, 3, 1, tzinfo=api.TZ), [(date(2028, 2, 29), Decimal(100), 1, 1)], None),
])
def test_month_boundary_does_not_include_previous_month(today, rows, expected):
    with patch.object(Clock, "now", return_value=today):
        items = run_snapshot(session(rows))
    spend = items["sem.spend.month_to_date_cny"]
    assert spend["value"] == expected
    assert spend["trend_7d"] is None


def test_backfilled_report_recomputes_observed_totals_without_claiming_completeness():
    initial = run_snapshot(session([(date(2026, 9, 4), Decimal(10), 1, 1)]))
    backfilled = run_snapshot(session([(date(2026, 9, 1), Decimal(20), 1, 1),
                                     (date(2026, 9, 4), Decimal(10), 1, 1)]))
    assert initial["sem.spend.month_to_date_cny"]["value"] == 10
    spend = backfilled["sem.spend.month_to_date_cny"]
    assert spend["value"] == 30
    assert spend["trend_7d"] is None
    assert spend["data_status"] == "observed_reports"


@pytest.mark.parametrize("change", [
    {"metric_key": "seo.spend.total"}, {"unit": "account"}, {"value": float("nan")},
    {"data_status": "no_reports", "value": 1}, {"as_of": "2026-09-04T00:00:00"},
    {"trend_7d": [{"date": "2026-09-04", "value": 1}] * 2},
    {"definition": ""}, {"unexpected": True},
])
def test_response_schema_rejects_contract_drift(change):
    metric = run_snapshot(session([(date(2026, 9, 4), Decimal(10), 1, 1)]))["sem.spend.month_to_date_cny"]
    with pytest.raises(ValidationError):
        api.MetricSnapshot.model_validate(metric | change)


def test_response_requires_all_five_metrics_and_http_exposes_schema():
    items = list(run_snapshot(session()).values())
    api.MetricSnapshotResponse.model_validate({"tenant_id": 3, "items": items})
    with pytest.raises(ValidationError):
        api.MetricSnapshotResponse.model_validate({"tenant_id": 3, "items": [items[0]] * 5})
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.require_auth] = lambda: context()
    async def db():
        yield session()
    app.dependency_overrides[api.get_session] = db
    with patch.object(api, "ensure_module_access", AsyncMock()), \
         patch.object(api, "load_sem_identity_states", AsyncMock(return_value={3: {"status": "ok"}})), \
         TestClient(app) as client:
        response = client.get("/api/v1/sem/metrics/snapshot?tenant_id=3")
        assert response.status_code == 200
        assert len(response.json()["items"]) == 5
        assert client.get("/api/v1/sem/metrics/snapshot?tenant_id=0").status_code == 422
    assert "MetricSnapshotResponse" in app.openapi()["components"]["schemas"]


def test_ci_runs_native_tests_in_dedicated_disposable_database():
    from pathlib import Path
    import yaml
    from sqlalchemy.engine import make_url
    config = yaml.load(Path(".github/workflows/ci.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    job = config["jobs"]["sem-foundation-contracts"]
    assert job["permissions"] == {"contents": "read"}
    assert job["services"]["postgres"]["image"] == "postgres:16"
    step = job["steps"][-1]
    url = make_url(step["env"]["SEM_FOUNDATION_TEST_DATABASE_URL"])
    assert url.host == "127.0.0.1" and url.database == "sem_foundation_test"
    assert "tests/test_sem_foundation_postgres.py" in step["run"]
    assert "secrets." not in str(job)
    assert "alembic" not in str(job).lower()


@pytest.mark.parametrize("current,previous,expected", [
    (120, 100, {"direction": "up", "change_pct": 20, "change_abs": 20}),
    (80, 100, {"direction": "down", "change_pct": -20, "change_abs": -20}),
    (100, 100, {"direction": "flat", "change_pct": 0, "change_abs": 0}),
    (10, 0, {"direction": "up", "change_pct": None, "change_abs": 10}),
    (0, 0, {"direction": "flat", "change_pct": None, "change_abs": 0}),
])
def test_shared_trend_direction_and_zero_baseline(current, previous, expected):
    trend = api.compare_seven_days(Decimal(current), Decimal(previous))
    assert trend == expected
    api.MetricTrend.model_validate(trend)


def test_seven_day_comparison_uses_exact_prior_date():
    rows = [(date(2026, 9, day), Decimal(10), 1, 1) for day in range(1, 10)]
    with patch.object(Clock, "now", return_value=Clock(2026, 9, 10, tzinfo=api.TZ)):
        items = run_snapshot(session(rows))
    assert items["sem.spend.month_to_date_cny"]["trend_7d"] == {
        "direction": "up", "change_pct": 350, "change_abs": 70}
    assert items["sem.spend.budget_utilization_pct"]["trend_7d"] is None
    api.MetricSnapshotResponse.model_validate({"tenant_id": 3, "items": list(items.values())})


@pytest.mark.parametrize("missing", [1, 2, 5, 9])
def test_missing_history_never_becomes_zero_change(missing):
    rows = [(date(2026, 9, day), Decimal(10), 1, 1) for day in range(1, 10) if day != missing]
    with patch.object(Clock, "now", return_value=Clock(2026, 9, 10, tzinfo=api.TZ)):
        items = run_snapshot(session(rows))
    assert items["sem.spend.month_to_date_cny"]["trend_7d"] is None


def test_full_zero_history_is_flat_not_unknown():
    rows = [(date(2026, 9, day), Decimal(0), 1, 1) for day in range(1, 10)]
    with patch.object(Clock, "now", return_value=Clock(2026, 9, 10, tzinfo=api.TZ)):
        items = run_snapshot(session(rows))
    assert items["sem.spend.month_to_date_cny"]["trend_7d"] == {
        "direction": "flat", "change_pct": None, "change_abs": 0}
