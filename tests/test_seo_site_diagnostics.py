import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.api.seo_site_diagnostics import (
    IndexReviewCreate, create_index_review, list_diagnostics, list_index_reviews,
)
from app.models.seo import SeoPageIndexReview, SeoSitePage
from app.security.auth import AuthContext, _required
from app.seo_site_diagnostics import FATAL_CODES, assessed_condition, diagnostic_payload


def page(**values):
    defaults = dict(id=231, tenant_id=1, site_id=1, url="https://example.com/privacy",
                    title="Privacy", http_status=200, status="needs_fix", last_error=None,
                    issue_codes=[], indexable=True, audit_score=90,
                    last_checked_at=datetime(2026, 9, 3, 6, 0))
    return SimpleNamespace(**(defaults | values))


def context(**values):
    return AuthContext(**(dict(user_id=7, username="operator", role_name="editor", tenant_id=1,
                              permissions={"seo.site": "edit"}) | values))


def request(**values):
    return IndexReviewCreate(**(dict(tenant_id=1, site_id=1, page_id=231,
                                    expected_review_id=None, intent="noindex", reason="客户确认用途") | values))


@pytest.mark.parametrize("changes", [
    {"http_status": 404}, {"http_status": 503}, {"http_status": 302}, {"http_status": None},
    {"status": "error"}, {"last_error": "timeout"}, {"status": "pending"},
    *[{"issue_codes": [code]} for code in sorted(FATAL_CODES)],
])
def test_failed_pages_never_receive_a_health_score(changes):
    result = diagnostic_payload(page(**changes))
    assert result["audit_score"] is None
    assert result["assessment_state"] == "unavailable"
    assert result["search_engine_indexed"] is None


def test_unchecked_has_no_score_even_with_legacy_values():
    result = diagnostic_payload(page(last_checked_at=None))
    assert result["audit_score"] is None
    assert result["assessment_state"] == "not_checked"
    assert result["index_control"] == "unknown"


def test_noindex_needs_human_intent_even_on_a_privacy_page():
    result = diagnostic_payload(page(issue_codes=["noindex"], indexable=False))
    assert result["review_outcome"] == "needs_review"
    assert result["index_intent"] == "undecided"
    assert result["guidance_source"] == "rules" and result["ai_used"] is False


@pytest.mark.parametrize("indexable,intent,expected", [
    (True, "index", "matches_intent"), (False, "noindex", "matches_intent"),
    (False, "index", "conflict"), (True, "noindex", "conflict"),
    (None, "index", "unverifiable"),
])
def test_review_outcome_uses_observations_and_intent(indexable, intent, expected):
    result = diagnostic_payload(page(indexable=indexable), intent)
    assert result["review_outcome"] == expected
    assert result["search_engine_indexed"] is None


def test_robots_block_is_not_proof_of_noindex_and_ai_is_separate():
    result = diagnostic_payload(page(issue_codes=["robots_blocked"], indexable=False), "noindex")
    assert result["review_outcome"] == "unverifiable"
    assert result["index_control"] == "crawl_blocked"
    result = diagnostic_payload(page(issue_codes=["ai_crawlers", "llms"]), "index")
    assert result["review_outcome"] == "matches_intent"
    assert result["index_evidence_codes"] == []
    assert result["ai_crawler_codes"] == ["ai_crawlers", "llms"]


def test_times_are_explicit_and_scores_have_shared_sql_filter():
    result = diagnostic_payload(page())
    assert result["checked_at"] == "2026-09-03T06:00:00+00:00"
    clause = str(assessed_condition(SeoSitePage).compile(dialect=postgresql.dialect()))
    assert "http_status >=" in clause and "http_status <" in clause
    assert "last_checked_at IS NOT NULL" in clause
    assert clause.count("@>") == len(FATAL_CODES)


@pytest.mark.parametrize("values", [{"reason": "  "}, {"reason": "a" * 2001}, {"intent": "auto"}, {"site_id": 0}])
def test_review_rejects_invalid_input(values):
    with pytest.raises(ValidationError):
        request(**values)


def test_review_requires_concurrency_token():
    values = request().model_dump()
    del values["expected_review_id"]
    with pytest.raises(ValidationError):
        IndexReviewCreate(**values)


def test_save_appends_evidence_without_mutating_page_and_history_survives():
    row = page(indexable=False, issue_codes=["noindex"])
    before = dict(vars(row))
    db = AsyncMock()
    db.scalar.side_effect = [1, row, None]
    db.add = MagicMock()
    result = asyncio.run(create_index_review(request(), context(), db))
    saved = db.add.call_args.args[0]
    assert isinstance(saved, SeoPageIndexReview)
    assert (saved.tenant_id, saved.site_id, saved.page_id) == (1, 1, 231)
    assert saved.actor_id == 7 and saved.actor_name == "operator"
    assert saved.created_at.tzinfo == timezone.utc
    assert saved.evidence["review_outcome"] == "matches_intent"
    assert result["review"]["reason"] == "客户确认用途"
    assert vars(row) == before
    assert db.scalar.call_args_list[1].args[0]._for_update_arg is not None
    db.commit.assert_awaited_once()
    # Read history through a separate request/session, from stored events.
    saved.id = 8
    reader = AsyncMock()
    reader.scalar.side_effect = [1, 231]
    reader.scalars.return_value = [saved]
    loaded = asyncio.run(list_index_reviews(1, 1, 231, None, 20, context(), reader))
    assert loaded["items"][0]["id"] == 8
    assert loaded["items"][0]["evidence"] == saved.evidence


def test_stale_save_is_409_not_last_write_wins():
    db = AsyncMock()
    db.add = MagicMock()
    db.scalar.side_effect = [1, page(), SimpleNamespace(id=9)]
    with pytest.raises(HTTPException) as error:
        asyncio.run(create_index_review(request(expected_review_id=8), context(), db))
    assert error.value.status_code == 409
    db.commit.assert_not_awaited()
    db.add.assert_not_called()


@pytest.mark.parametrize("ctx,scalars,expected", [
    (context(tenant_id=2), [], 403),
    (context(permissions={"seo.site": "view"}), [], 403),
    (context(user_id=None, is_superadmin=True), [1], 403),
    (context(), [None], 404), (context(), [1, None], 404),
])
def test_write_scope_permission_and_real_actor(ctx, scalars, expected):
    db = AsyncMock()
    db.scalar.side_effect = scalars
    with pytest.raises(HTTPException) as error:
        asyncio.run(create_index_review(request(), ctx, db))
    assert error.value.status_code == expected
    db.commit.assert_not_awaited()


def test_listing_is_scoped_paged_and_keeps_latest_human_intent():
    db = AsyncMock()
    db.scalar.side_effect = [1, 1]
    events = MagicMock()
    events.all.return_value = [(page(indexable=False), SimpleNamespace(
        id=9, intent="noindex", reason="客户确认", actor_id=7, actor_name="operator",
        created_at=datetime.now(timezone.utc), evidence={}))]
    coverage = MagicMock()
    coverage.one.return_value = (3, 1, 1, datetime(2026, 9, 3))
    db.execute.side_effect = [events, coverage]
    result = asyncio.run(list_diagnostics(1, 1, "", "all", 1, 25, context(), db))
    assert result["coverage"]["unavailable"] == 1
    assert result["items"][0]["diagnostic"]["review_outcome"] == "matches_intent"
    query = db.execute.call_args_list[0].args[0]
    compiled = query.compile(dialect=postgresql.dialect())
    assert "seo_site_pages.tenant_id =" in str(compiled)
    assert "seo_site_pages.site_id =" in str(compiled)
    assert "max(seo_page_index_reviews.id)" in str(compiled)
    assert query._limit_clause.value == 25


def test_routes_use_seo_site_permissions_and_parent_subscription_guard():
    from app.api.seo import router, require_seo_module_access
    for suffix, method in [("diagnostics", "GET"), ("index-reviews", "POST"), ("index-reviews", "GET")]:
        path = f"/api/v1/seo/site-pages/{suffix}"
        assert _required(path, method) == ({"seo.site"}, method == "POST")
        route = next(r for r in router.routes if r.path == path and method in r.methods)
        assert require_seo_module_access in [d.call for d in route.dependant.dependencies]


def test_model_constraints_and_timezone():
    table = SeoPageIndexReview.__table__
    assert table.c.created_at.type.timezone is True
    for name in ("tenant_id", "site_id", "page_id"):
        assert next(iter(table.c[name].foreign_keys)).ondelete == "CASCADE"
    assert {"ck_seo_index_review_reason", "ck_seo_index_review_intent"} <= {c.name for c in table.constraints}


def test_frontend_marks_sources_and_prevents_stale_scope_and_duplicate_save():
    source = (Path(__file__).parents[1] / "frontend/src/views/seo/SeoSiteDiagnosticsPanel.vue").read_text(encoding="utf-8")
    for marker in ["程序检测", "规则建议", "人工确认", "不调用 AI", "expected_review_id",
                   "token !== generation", "token !== dialogGeneration", "if (saving.value",
                   "flush: 'sync'", "未发现索引限制 ≠ 已收录", "未修改客户网站"]:
        assert marker in source


def test_migration_renders_postgresql_ddl_without_connecting_to_database():
    import importlib.util
    import io
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).parents[1] / "migrations/versions/20260903_0085_seo_page_index_reviews.py"
    spec = importlib.util.spec_from_file_location("index_review_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    output = io.StringIO()
    ctx = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(ctx):
        migration.upgrade()
    sql = output.getvalue()
    assert "CREATE TABLE seo_page_index_reviews" in sql
    assert "TIMESTAMP WITH TIME ZONE" in sql and "JSONB NOT NULL" in sql
    assert sql.count("ON DELETE CASCADE") == 3
    assert "ck_seo_index_review_reason" in sql
