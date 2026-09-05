"""Effect attribution regressions; real SQL against isolated in-memory synthetic data."""
import copy
import hashlib
import json
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import test_writeback_approval  # noqa: F401 -- isolated test settings
from sqlalchemy import Column, JSON, MetaData, Table, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.ai import adjustment_verify as kw
from app.ai import budget_adjustment_verify as budget
from app.ai.effect_verification import effect_window, review_note, REVIEW_PREFIX
from app.api import adjustments_verify as api
from fastapi import HTTPException, FastAPI
from fastapi.testclient import TestClient
from app.models import AdjustmentReview, Alert, Keyword, KwReportSnapshot, OperationRecord, WritebackAction


class AsyncAdapter:
    def __init__(self, session):
        self.session = session

    async def scalar(self, statement):
        return self.session.scalar(statement)

    async def scalars(self, statement):
        return self.session.scalars(statement)

    async def execute(self, statement):
        return self.session.execute(statement)


class EffectIntegrityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        with self.engine.connect() as conn:
            conn.connection.create_function("md5", 1, lambda value: hashlib.md5(value.encode()).hexdigest() if value else None)
        metadata = MetaData()
        # Copy column types only: no production schema creation or migrations.
        # ORM SELECTs use the same column names; SQLite tests exercise predicates.
        self.tables = {}
        for model in (Keyword, KwReportSnapshot, OperationRecord, WritebackAction, AdjustmentReview, Alert):
            self.tables[model] = Table(model.__tablename__, metadata, *[
                Column(c.name, JSON() if isinstance(c.type, JSONB) else c.type,
                       primary_key=c.primary_key, nullable=True)
                for c in model.__table__.columns
            ])
        metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.session = AsyncAdapter(self.db)
        self.tenant = SimpleNamespace(id=1)
        self.now = datetime.utcnow().replace(microsecond=0)
        self.action = self.now - timedelta(days=4)
        self.counter = 0

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def insert(self, model, **values):
        self.counter += 1
        values.setdefault("id", self.counter)
        self.db.execute(self.tables[model].insert().values(**values))
        return values["id"]

    def keyword(self, kid=100, account=10, campaign=20, group=30, tenant=1):
        self.insert(Keyword, tenant_id=tenant, keyword_id=kid, keyword="涂料",
                    baidu_account_id=account, campaign_id=campaign, adgroup_id=group,
                    total_impression=kid * 100)

    def operation(self, key="op", account=10, campaign=20, group=30, **changes):
        values = dict(tenant_id=1, dedup_key=key, baidu_account_id=account,
                      plan_id=campaign, unit_id=group, opt_obj="涂料",
                      opt_time=self.action, opt_level=5, opt_content="bidPriceWord",
                      old_value="10", new_value="9")
        values.update(changes)
        self.insert(OperationRecord, **values)

    def report(self, offset, cost=10, account=10, campaign=20, group=30, kid=100, tenant=1):
        self.insert(KwReportSnapshot, tenant_id=tenant, baidu_account_id=account,
                    campaign_id=campaign, adgroup_id=group, keyword_id=kid,
                    report_date=self.action.date() + timedelta(days=offset),
                    cost=cost, click=2, impression=20, avg_rank=3)

    def writeback(self, status="success", dry_run=False, account=10, action_type="set_account_budget"):
        return self.insert(WritebackAction, tenant_id=1, baidu_account_id=account,
                           campaign_id=20, action_type=action_type, word="预算",
                           created_at=self.action, status=status, dry_run=dry_run,
                           old_value=100, new_value=90)

    async def test_same_name_resolves_exact_account_campaign_group_not_impressions(self):
        self.keyword()
        self.keyword(200, account=11)
        self.keyword(300, campaign=21)
        self.keyword(400, group=31)
        self.operation()
        item = await kw.build_one(self.session, self.tenant, "op")
        self.assertEqual(item["keyword_id"], 100)

    async def test_missing_account_is_unmatched_even_for_one_keyword(self):
        self.keyword()
        self.operation(account=None)
        item = await kw.build_one(self.session, self.tenant, "op")
        self.assertEqual(item["effect"]["sample"]["state"], "unmatched")

    async def test_ambiguous_group_does_not_pick_largest_keyword(self):
        self.keyword()
        self.keyword(200, group=31)
        self.operation(group=None)
        item = await kw.build_one(self.session, self.tenant, "op")
        self.assertIsNone(item["keyword_id"])

    async def test_wrong_plan_and_other_tenant_do_not_match(self):
        self.keyword(campaign=21)
        self.keyword(200, tenant=2)
        self.operation()
        item = await kw.build_one(self.session, self.tenant, "op")
        self.assertIsNone(item["keyword_id"])

    async def test_non_bid_operation_is_not_ai_input(self):
        self.operation(opt_content="shelveWord")
        self.assertIsNone(await kw.build_one(self.session, self.tenant, "op"))

    async def test_keyword_windows_and_latest_date_are_scoped_and_list_matches_detail(self):
        self.keyword()
        self.operation()
        for day in (-1, 1, 2, 3):
            self.report(day)
        # Same ID in mismatching account/plan/group or tenant cannot contaminate.
        for changes in ({"account": 11}, {"campaign": 21}, {"group": 31}, {"tenant": 2}):
            self.report(4, cost=999, **changes)
        item = await kw.build_one(self.session, self.tenant, "op")
        listed = (await kw.list_pending(self.session, self.tenant))[0]
        self.assertEqual(item["effect"], listed["effect"])
        self.assertEqual(item["effect"]["after"]["cost_per_day"], 10)
        self.assertEqual(item["effect"]["after"]["days"], 3)
        self.assertEqual(item["effect"]["sample"]["state"], "ready")
        self.assertEqual(item["effect"]["after_through"],
                         (self.action.date() + timedelta(days=3)).isoformat())

    async def test_budget_list_excludes_dry_runs_failed_pending_and_reconcile(self):
        accepted = self.writeback()
        for status, dry in (("dry_run", True), ("success", True), ("failed", False),
                            ("pending", False), ("reconcile", False)):
            self.writeback(status=status, dry_run=dry)
        items = await budget.list_pending_budget(self.session, self.tenant)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["dedup_key"], budget._budget_dedup_key("account", 10, accepted))
        self.assertFalse(items[0]["dry_run"])

    async def test_account_budget_cost_days_and_latest_exclude_other_account(self):
        self.writeback()
        for day in (-1, 1, 2, 3):
            self.report(day)
        self.report(4, cost=900, account=11)
        self.report(1, cost=900, tenant=2)
        item = (await budget.list_pending_budget(self.session, self.tenant))[0]
        self.assertEqual(item["effect"]["after"]["cost_per_day"], 10)
        self.assertEqual(item["effect"]["after"]["days"], 3)
        self.assertEqual(item["effect"]["after"]["usage_pct"], 11.1)
        self.assertEqual(item["effect"]["sample"]["state"], "ready")
        self.assertEqual(item["effect"]["after_through"],
                         (self.action.date() + timedelta(days=3)).isoformat())

    async def test_campaign_budget_excludes_other_campaign(self):
        self.writeback(action_type="set_campaign_budget")
        self.report(-1)
        self.report(1)
        self.report(3, campaign=21, cost=900)
        item = (await budget.list_pending_budget(self.session, self.tenant))[0]
        self.assertEqual(item["effect"]["after"]["cost_per_day"], 10)
        self.assertEqual(item["effect"]["after"]["days"], 1)
        self.assertEqual(item["effect"]["sample"]["state"], "collecting")

    async def test_missing_report_dates_not_counted_as_zero_spend(self):
        self.report(-1, cost=70)
        value = await budget._daily_cost(self.session, 1, self.action.date() - timedelta(days=7),
                                         self.action.date() - timedelta(days=1), None, 10)
        self.assertEqual(value, 70)

    async def test_missing_before_is_not_ready(self):
        self.writeback()
        for day in (0, 1, 2):
            self.report(day)
        item = (await budget.list_pending_budget(self.session, self.tenant))[0]
        self.assertEqual(item["effect"]["sample"]["state"], "missing_before")
        self.assertIsNone(item["effect"]["before"]["cost_per_day"])

    async def test_unknown_campaign_account_does_not_aggregate_tenant(self):
        self.writeback(account=None, action_type="set_campaign_budget")
        self.report(-1)
        self.report(0)
        item = (await budget.list_pending_budget(self.session, self.tenant))[0]
        self.assertEqual(item["effect"]["sample"]["state"], "unmatched")
        self.assertIsNone(item["effect"]["before"]["cost_per_day"])

    async def test_legacy_ai_conclusion_not_shown_in_list(self):
        self.keyword()
        self.operation()
        self.insert(AdjustmentReview, tenant_id=1, dedup_key="op", status="pending",
                    ai_verdict="achieved", ai_reason="旧数据结论")
        item = (await kw.list_pending(self.session, self.tenant))[0]
        self.assertIsNone(item["ai"]["verdict"])

    async def test_keyword_paging_filters_before_limit_and_has_stable_order(self):
        for i in range(7):
            self.operation(key=f"op{i}")
            if i >= 2:
                self.insert(AdjustmentReview, tenant_id=1, dedup_key=f"op{i}", status="verified")
        page = await kw.list_pending(self.session, self.tenant, status="pending", limit=1, paged=True)
        second = await kw.list_pending(self.session, self.tenant, status="pending", limit=1, offset=1, paged=True)
        self.assertEqual(page["summary"], {"total": 7, "pending": 2, "verified": 5})
        self.assertEqual(page["total"], 2)
        self.assertTrue(page["has_more"])
        self.assertFalse(second["has_more"])
        self.assertEqual([page["items"][0]["dedup_key"], second["items"][0]["dedup_key"]], ["op1", "op0"])

    async def test_budget_paging_and_key_lookup_use_real_hash(self):
        ids = [self.writeback() for _ in range(5)]
        for id_ in ids[1:]:
            self.insert(AdjustmentReview, tenant_id=1,
                        dedup_key=budget._budget_dedup_key("account", 10, id_), status="verified")
        page = await budget.list_pending_budget(self.session, self.tenant, status="pending", limit=1, paged=True)
        self.assertEqual(page["summary"], {"total": 5, "pending": 1, "verified": 4})
        key = budget._budget_dedup_key("account", 10, ids[0])
        self.assertEqual(page["items"][0]["dedup_key"], key)
        found = await budget.list_pending_budget(self.session, self.tenant, dedup_key=key)
        self.assertEqual(len(found), 1)
        self.assertEqual(await budget.list_pending_budget(self.session, SimpleNamespace(id=2), dedup_key=key), [])

    async def test_keyword_next_change_truncates_even_beyond_current_list_page(self):
        self.keyword()
        self.operation(key="first")
        self.operation(key="next", opt_time=self.action + timedelta(days=3))
        for day in (-1, 0, 1, 2, 3, 4):
            self.report(day, cost=900 if day in (0, 3, 4) else 10)
        item = await kw.build_one(self.session, self.tenant, "first")
        self.assertEqual(item["effect"]["after"]["days"], 2)
        self.assertEqual(item["effect"]["after"]["cost_per_day"], 10)
        self.assertEqual(item["effect"]["sample"]["state"], "collecting")

    async def test_same_day_adjustments_have_no_clean_after_window(self):
        self.keyword()
        self.operation(key="first")
        self.operation(key="next", opt_time=self.action + timedelta(minutes=1))
        self.report(-1)
        self.report(1)
        item = await kw.build_one(self.session, self.tenant, "first")
        self.assertIsNone(item["effect"]["after"])
        self.assertIsNone(item["effect"]["after_through"])

    async def test_other_group_adjustment_does_not_truncate(self):
        self.keyword()
        self.operation(key="first")
        self.operation(key="other", group=999, opt_time=self.action + timedelta(days=1))
        for day in (-1, 1, 2, 3):
            self.report(day)
        item = await kw.build_one(self.session, self.tenant, "first")
        self.assertEqual(item["effect"]["sample"]["state"], "ready")

    async def test_budget_next_execution_truncates_but_dry_run_does_not(self):
        id_ = self.writeback()
        self.insert(WritebackAction, tenant_id=1, baidu_account_id=10,
                    action_type="set_account_budget", status="success", dry_run=False,
                    created_at=self.action + timedelta(days=3), old_value=90, new_value=80)
        self.insert(WritebackAction, tenant_id=1, baidu_account_id=10,
                    action_type="set_account_budget", status="dry_run", dry_run=True,
                    created_at=self.action + timedelta(days=1), old_value=90, new_value=80)
        for day in (-1, 0, 1, 2, 3):
            self.report(day, cost=900 if day in (0, 3) else 10)
        item = (await budget.list_pending_budget(self.session, self.tenant,
                dedup_key=budget._budget_dedup_key("account", 10, id_)))[0]
        self.assertEqual(item["effect"]["after"]["days"], 2)
        self.assertEqual(item["effect"]["after"]["cost_per_day"], 10)

    async def test_budget_execution_utc_converts_to_beijing_day(self):
        timestamp = datetime(2026, 9, 1, 20)
        row = SimpleNamespace(executed_at=timestamp, created_at=datetime(2026, 9, 1))
        self.assertEqual(budget._action_time(row), datetime(2026, 9, 2, 4))

    async def test_current_report_day_is_not_a_complete_sample(self):
        today = self.action.date() + timedelta(days=4)
        with patch("app.ai.effect_verification.report_today", return_value=today):
            start, end = effect_window(self.action.date(), today)
        self.assertEqual(start, self.action.date() + timedelta(days=1))
        self.assertEqual(end, today - timedelta(days=1))


class VerificationApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session = AsyncMock()
        self.session.get.return_value = SimpleNamespace(id=1)
        self.session.scalar.return_value = None
        self.item = {"dedup_key": "op", "baidu_account_id": 10, "keyword_id": 100,
                     "effect": {"sample": {"state": "ready"},
                                "before": {"cost_per_day": 10}, "after": {"cost_per_day": 9}}}

    async def call(self, req):
        return await api.mark_verified("op", 1, req, self.session)

    async def test_unknown_source_rejected_without_write(self):
        with patch.object(api, "build_one", new_callable=AsyncMock, return_value=None), patch.object(api, "list_pending_budget", new_callable=AsyncMock, return_value=[]):
            with self.assertRaises(HTTPException) as error:
                await self.call(api.VerifyRequest(verdict="achieved", note="已核对报表"))
        self.assertEqual(error.exception.status_code, 404)
        self.session.execute.assert_not_awaited()

    async def test_no_sample_cannot_mark_achieved(self):
        self.item["effect"]["sample"]["state"] = "collecting"
        with patch.object(api, "build_one", new_callable=AsyncMock, return_value=self.item):
            with self.assertRaises(HTTPException) as error:
                await self.call(api.VerifyRequest(verdict="achieved", note="已核对报表"))
        self.assertEqual(error.exception.status_code, 409)
        self.session.execute.assert_not_awaited()

    async def test_missing_note_cannot_mark_missed(self):
        with patch.object(api, "build_one", new_callable=AsyncMock, return_value=self.item):
            with self.assertRaises(HTTPException) as error:
                await self.call(api.VerifyRequest(verdict="missed", note="  "))
        self.assertEqual(error.exception.status_code, 422)

    async def test_review_saves_server_metrics_with_upsert(self):
        with patch.object(api, "build_one", new_callable=AsyncMock, return_value=self.item):
            result = await self.call(api.VerifyRequest(verdict="achieved", note="报表消费下降"))
        self.assertEqual(result["review_status"], "verified")
        stmt = self.session.execute.call_args.args[0]
        from sqlalchemy.dialects import postgresql
        compiled = stmt.compile(dialect=postgresql.dialect())
        self.assertIn("ON CONFLICT", str(compiled))
        note, evidence = review_note(compiled.params["note"])
        self.assertEqual(note, "报表消费下降")
        self.assertEqual(evidence["effect"], self.item["effect"])
        self.session.commit.assert_awaited_once()

    async def test_observation_stays_pending(self):
        self.item["effect"]["sample"]["state"] = "unmatched"
        with patch.object(api, "build_one", new_callable=AsyncMock, return_value=self.item):
            result = await self.call(api.VerifyRequest(verdict="watch"))
        self.assertEqual(result["review_status"], "pending")

    async def test_reopen_clears_verdict_but_preserves_evidence(self):
        self.session.scalar.return_value = SimpleNamespace(status="verified")
        with patch.object(api, "build_one", new_callable=AsyncMock, return_value=self.item):
            result = await self.call(api.VerifyRequest(reopen=True))
        self.assertEqual(result["review_status"], "pending")
        self.assertIsNone(result["verdict"])
        self.assertNotIn("note", self.session.execute.call_args.args[0].compile().params)

    async def test_budget_source_supported(self):
        with patch.object(api, "build_one", new_callable=AsyncMock, return_value=None), patch.object(api, "list_pending_budget", new_callable=AsyncMock, return_value=[self.item]):
            result = await self.call(api.VerifyRequest(verdict="missed", note="核对后未达成"))
        self.assertEqual(result["review_status"], "verified")

    async def test_budget_route_exists_and_auth_is_not_removed(self):
        self.assertTrue(any(r.path == "/api/v1/adjustment-verify/budget" for r in api.router.routes))
        app = FastAPI()
        app.include_router(api.router)
        with TestClient(app) as client:
            response = client.get("/api/v1/adjustment-verify/budget?tenant_id=1")
        self.assertIn(response.status_code, (401, 403))


class AiCacheTests(unittest.IsolatedAsyncioTestCase):
    def item(self):
        return dict(dedup_key="op", keyword="涂料", keyword_id=100, baidu_account_id=10,
                    old_value="10", new_value="9", direction="lower", change_pct=-10,
                    effect=dict(before=None, after=None, after_through="2026-09-04",
                                sample={"state": "ready"}))

    def review(self, item):
        return SimpleNamespace(ai_verdict="achieved", ai_reason=kw.AI_CACHE_PREFIX + json.dumps(
            {"fingerprint": kw._effect_fingerprint(item), "reason": "成本下降"}))

    async def test_insufficient_sample_does_not_call_ai_or_database(self):
        item = self.item()
        item["effect"]["sample"]["state"] = "unmatched"
        session = AsyncMock()
        with patch.object(kw, "chat_json", new_callable=AsyncMock) as chat:
            result = await kw.generate_verdict(session, SimpleNamespace(id=1), item, force=True)
        self.assertEqual(result["verdict"], "watch")
        chat.assert_not_awaited()
        session.scalar.assert_not_awaited()

    async def test_cache_requires_same_identity_and_snapshot(self):
        item = self.item()
        review = self.review(item)
        self.assertEqual(kw._cached_ai(review, item)["reason"], "成本下降")
        for field in ("keyword_id", "baidu_account_id", "old_value", "new_value"):
            changed = copy.deepcopy(item)
            changed[field] = 999
            self.assertIsNone(kw._cached_ai(review, changed))
        item["effect"]["after_through"] = "2026-09-05"
        self.assertIsNone(kw._cached_ai(review, item))

    async def test_legacy_or_malformed_cache_is_ignored(self):
        for raw in ("旧结论", kw.AI_CACHE_PREFIX + "oops", kw.AI_CACHE_PREFIX + "[]"):
            self.assertIsNone(kw._cached_ai(SimpleNamespace(ai_verdict="achieved", ai_reason=raw), self.item()))

    async def test_matching_cache_does_not_call_ai(self):
        item = self.item()
        session = AsyncMock()
        session.scalar.return_value = self.review(item)
        with patch.object(kw, "is_enabled", return_value=True), patch.object(kw, "chat_json", new_callable=AsyncMock) as chat:
            result = await kw.generate_verdict(session, SimpleNamespace(id=1), item)
        self.assertEqual(result["reason"], "成本下降")
        chat.assert_not_awaited()

    async def test_new_result_stores_bound_cache_but_returns_plain_reason(self):
        item = self.item()
        session = AsyncMock()
        review = SimpleNamespace(ai_verdict="achieved", ai_reason="legacy")
        session.scalar.return_value = review
        with patch.object(kw, "is_enabled", return_value=True), patch.object(kw, "_build_prompt", return_value="synthetic"), patch.object(kw, "chat_json", new_callable=AsyncMock, return_value={"verdict": "watch", "reason": "继续观察"}):
            result = await kw.generate_verdict(session, SimpleNamespace(id=1), item)
        self.assertEqual(result, {"verdict": "watch", "reason": "继续观察"})
        self.assertEqual(kw._cached_ai(review, item), result)
        session.commit.assert_awaited_once()
