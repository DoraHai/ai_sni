"""SEM release regressions against disposable localhost PostgreSQL, never production."""
import asyncio
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import ForeignKeyConstraint, MetaData, func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

# Configure dummy application credentials before importing app code.
from test_sem_audit_eight_fixes import auth, _suggestion_records
from app.api import writeback as queue_api
from app.models import Alert, BidWriteback, Suggestion, WritebackAction
from app.rules import engine as rules
from app.suggestions import engine as suggestions


def test_ci_runs_native_sem_regressions_with_disposable_database():
    import yaml
    config = yaml.load(Path(".github/workflows/ci.yml").read_text(encoding="utf-8"),
                       Loader=yaml.BaseLoader)
    job = config["jobs"]["pytest"]
    service = job["services"]["sem-test-postgres"]
    assert service["image"] == "postgres:16"
    assert service["env"]["POSTGRES_DB"] == "sem_writeback_test"
    step = next(step for step in job["steps"] if step.get("name") == "Run tests")
    url = make_url(step["env"]["SEM_ALERT_TEST_DATABASE_URL"])
    assert url.host == "127.0.0.1" and url.database == "sem_writeback_test"
    assert url.username == service["env"]["POSTGRES_USER"]
    assert url.password == service["env"]["POSTGRES_PASSWORD"]
    assert "${{" not in step["env"]["SEM_ALERT_TEST_DATABASE_URL"]
    assert step["run"] == "python -m pytest -q tests"


@asynccontextmanager
async def local_session(*models):
    url = os.environ.get("SEM_ALERT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires disposable SEM_ALERT_TEST_DATABASE_URL")
    parsed = make_url(url)
    assert parsed.drivername == "postgresql+asyncpg"
    assert parsed.host in {"localhost", "127.0.0.1"}
    assert parsed.database == "sem_writeback_test"
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            for model in models:
                table = model.__table__.to_metadata(MetaData())
                table._prefixes = ["TEMPORARY"]
                for constraint in list(table.constraints):
                    if isinstance(constraint, ForeignKeyConstraint):
                        table.constraints.remove(constraint)
                await conn.run_sync(lambda sync, t=table: t.create(sync))
            await conn.commit()
            async with AsyncSession(bind=conn, expire_on_commit=False) as session:
                yield session
    finally:
        await engine.dispose()


@pytest.mark.parametrize("identity", ["keyword", "entity"])
def test_rehit_alert_clears_resolution_timestamp_and_refreshes_priority(identity):
    async def run():
        async with local_session(Alert) as session:
            record = dict(tenant_id=10, rule_code="postrelease", priority="P2",
                          title="initial", message="test", report_date=date(2026, 9, 5),
                          keyword_id=1 if identity == "keyword" else None,
                          entity_ref="campaign:1" if identity == "entity" else None,
                          status="open")
            upsert = rules._upsert_keyword_alerts if identity == "keyword" else rules._upsert_entity_alerts
            await upsert(session, [record])
            original_id = await session.scalar(select(Alert.id))
            for old_status in ("resolved", "merged"):
                await session.execute(update(Alert).values(
                    status=old_status, resolved_at=datetime(2026, 9, 5, 9)))
                await upsert(session, [dict(record, priority="P0", title="rehit")])
                session.expire_all()
                row = await session.scalar(select(Alert))
                assert row.id == original_id
                assert row.status == "open" and row.priority == "P0"
                assert row.resolved_at is None
                assert await session.scalar(select(func.count()).select_from(Alert)) == 1
    asyncio.run(run())


def test_queue_real_postgres_old_records_pagination_and_tenant_scope(monkeypatch):
    monkeypatch.setattr(queue_api, "get_writeback_mode", AsyncMock(return_value={
        "writeback_enabled": False, "mode": "dry_run", "live_scopes": [],
    }))
    async def run():
        async with local_session(BidWriteback, WritebackAction) as session:
            when = datetime(2026, 9, 5, 12)
            session.add_all([BidWriteback(id=i, tenant_id=10, keyword_id=i, new_bid=1,
                dry_run=False, status="success", created_at=when) for i in range(1, 1201)])
            for model in (BidWriteback, WritebackAction):
                for i in range(1201, 1204):
                    fields = dict(id=i, tenant_id=10, dry_run=False, status="reconcile",
                                  created_at=when-timedelta(days=10))
                    fields.update(dict(keyword_id=i, new_bid=1) if model is BidWriteback
                                  else dict(action_type="set_account_budget", word="test"))
                    session.add(model(**fields))
            session.add(BidWriteback(id=1300, tenant_id=20, keyword_id=1300, new_bid=1,
                                    dry_run=False, status="reconcile", created_at=when))
            await session.flush()
            keys = []
            for offset in (0, 2, 4):
                page = await queue_api.list_writeback_queue(
                    10, 2, auth({}), session, "reconciliation_required", offset)
                assert page["counts"] == {"pending_writeback": 0, "executed": 1200,
                                          "failed": 0, "reconciliation_required": 6}
                assert page["total"] == 6 and page["has_more"] == (offset < 4)
                keys.extend(item["key"] for item in page["items"])
            assert keys == ["bid:1203", "bid:1202", "bid:1201",
                            "action:1203", "action:1202", "action:1201"]
            with pytest.raises(HTTPException) as error:
                await queue_api.list_writeback_queue(20, 2, auth({}), session, None, 0)
            assert error.value.status_code == 403
    asyncio.run(run())


def test_suggestion_postgres_batches_human_state_and_atomic_rollback():
    async def run():
        async with local_session(Suggestion) as session:
            records = _suggestion_records(2100)
            await suggestions._persist_suggestions(session, 10, date(2026, 9, 5), records)
            assert await session.scalar(select(func.count()).select_from(Suggestion)) == 2100
            handled_at = datetime(2026, 9, 5, 9)
            for keyword_id, status in ((1, "adopted"), (2, "ignored"), (3, "expired")):
                await session.execute(update(Suggestion).where(Suggestion.keyword_id == keyword_id)
                    .values(status=status, adopted_at=handled_at, handling_status="completed"))
            await session.commit()
            revised = [dict(row, suggested_bid=1.1) for row in records]
            await suggestions._persist_suggestions(session, 10, date(2026, 9, 5), revised)
            rows = (await session.execute(select(Suggestion.keyword_id, Suggestion.status,
                    Suggestion.adopted_at, Suggestion.handling_status)
                    .where(Suggestion.keyword_id.in_([1, 2, 3])))).all()
            assert {row.keyword_id: row.status for row in rows} == {1: "adopted", 2: "ignored", 3: "pending"}
            assert all(row.adopted_at == handled_at and row.handling_status == "completed" for row in rows)
            # A genuine PostgreSQL NOT NULL violation in a later batch undoes earlier batches.
            invalid = [dict(row, suggested_bid=1.2) for row in records]
            invalid[-1]["reason"] = None
            from sqlalchemy.exc import IntegrityError
            with pytest.raises(IntegrityError):
                await suggestions._persist_suggestions(session, 10, date(2026, 9, 5), invalid)
            assert set((await session.scalars(select(Suggestion.suggested_bid))).all()) == {Decimal("1.1")}
            # Array cleanup is scoped even when all evaluated results are rejected.
            await suggestions._persist_suggestions(session, 10, date(2026, 9, 5), [], evaluated_keyword_ids=[1, 2, 3])
            states = dict((await session.execute(select(Suggestion.keyword_id, Suggestion.status))).all())
            assert states[1] == "adopted" and states[2] == "ignored" and states[3] == "expired"
            assert states[4] == "pending"
    asyncio.run(run())


def test_rule_savepoint_survives_real_database_error(monkeypatch):
    class BrokenRule:
        code = "broken"
        async def evaluate(self, session, tenant, target_date):
            await session.execute(text("SELECT 1 / 0"))

    class HealthyRule:
        code = "healthy"
        async def evaluate(self, session, tenant, target_date):
            assert await session.scalar(text("SELECT 42")) == 42
            from app.rules.base import AlertDraft
            return [AlertDraft(rule_code=self.code, priority="P2", title="healthy",
                               message="test", report_date=target_date, keyword_id=1)]

    monkeypatch.setattr(rules, "ALL_RULES", [BrokenRule(), HealthyRule()])
    async def run():
        async with local_session(Alert) as session:
            assert await rules.run_rules_for_tenant(session, SimpleNamespace(id=10), date(2026, 9, 5)) == 1
            assert await session.scalar(select(Alert.rule_code)) == "healthy"
    asyncio.run(run())
