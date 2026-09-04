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
    ImageAltReviewCopy, ImageAltReviewUpdate, IndexReviewCreate, copy_image_remediation,
    create_index_review, get_image_remediation, list_diagnostics,
    list_image_remediation_history, list_index_reviews, get_image_evidence,
    save_image_remediation,
)
from app.models.seo import SeoImageAltReview, SeoPageIndexReview, SeoSitePage
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
    for suffix, method in [("diagnostics", "GET"), ("index-reviews", "POST"), ("index-reviews", "GET"), ("image-evidence", "GET"), ("image-remediation", "GET"), ("image-remediation", "PUT"), ("image-remediation-history", "GET"), ("image-remediation/copy", "POST")]:
        path = f"/api/v1/seo/site-pages/{suffix}"
        assert _required(path, method) == ({"seo.site"}, method in {"POST", "PUT"})
        route = next(r for r in router.routes if r.path == path and method in r.methods)
        assert require_seo_module_access in [d.call for d in route.dependant.dependencies]


def test_model_constraints_and_timezone():
    table = SeoPageIndexReview.__table__
    assert table.c.created_at.type.timezone is True
    for name in ("tenant_id", "site_id", "page_id"):
        assert next(iter(table.c[name].foreign_keys)).ondelete == "CASCADE"
    assert {"ck_seo_index_review_reason", "ck_seo_index_review_intent"} <= {c.name for c in table.constraints}


@pytest.mark.parametrize("evidence,error", [(None, None), (None, "timeout"), ({"items": [], "candidate_count": 0}, None)])
def test_image_evidence_reads_latest_scoped_snapshot_without_network_or_writes(evidence, error):
    db = AsyncMock()
    db.scalar.side_effect = [1, page(), SimpleNamespace(id=9, fetched_at=datetime(2026, 9, 3, 18, 0),
                            status_code=200, error_type=error, images_missing_alt_count=26, image_alt_evidence=evidence)]
    result = asyncio.run(get_image_evidence(1, 1, 231, context(), db))
    assert result["evidence"] == evidence
    assert result["fetch_error"] == error
    assert result["fetched_at"] == "2026-09-03T18:00:00+08:00"
    query = db.scalar.call_args_list[2].args[0]
    sql = str(query.compile(dialect=postgresql.dialect()))
    for column in ("tenant_id", "site_id", "url"):
        assert f"seo_page_snapshots.{column} =" in sql
    assert "fetched_at DESC" in sql and "id DESC" in sql
    assert query._limit_clause.value == 1
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("ctx,values,expected", [
    (context(tenant_id=2), [], 403), (context(permissions={}), [], 403),
    (context(), [None], 404), (context(), [1, None], 404),
])
def test_image_evidence_rejects_cross_scope_and_missing_page(ctx, values, expected):
    db = AsyncMock(); db.scalar.side_effect = values
    with pytest.raises(HTTPException) as error:
        asyncio.run(get_image_evidence(1, 1, 231, ctx, db))
    assert error.value.status_code == expected


def test_image_evidence_no_snapshot_is_unknown():
    db = AsyncMock(); db.scalar.side_effect = [1, page(), None]
    result = asyncio.run(get_image_evidence(1, 1, 231, context(), db))
    assert result["evidence"] is None and result["snapshot_id"] is None
    assert result["legacy_candidate_count"] is None


def test_image_evidence_explicit_unknown_snapshot_is_404():
    db = AsyncMock(); db.scalar.side_effect = [1, page(), None]
    with pytest.raises(HTTPException) as error:
        asyncio.run(get_image_evidence(1, 1, 231, context(), db, snapshot_id=99))
    assert error.value.status_code == 404


def image_snapshot(snapshot_id=12, fetched_at=None, items=None):
    candidates = items or [{
        "position": 2, "source_url": "https://cdn.example/a.webp", "source_attribute": "src",
        "srcset": None, "section": "main", "element_id": None, "in_link": False,
        "role": None, "alt_state": "empty",
    }]
    return SimpleNamespace(
        id=snapshot_id, error_type=None,
        fetched_at=fetched_at or datetime(2026, 9, 4, 3, 0),
        image_alt_evidence={"candidate_count": len(candidates), "items": candidates},
    )


def image_review_request(**values):
    return ImageAltReviewUpdate(**(dict(
        tenant_id=1, site_id=1, page_id=231, expected_snapshot_id=12, position=2,
        expected_review_id=None,
        decision="informative", alt_suggestion="NORDBLOC.1 伞齿轮减速电机", note="产品主图",
        review_status="approved",
    ) | values))


def test_image_remediation_is_scoped_to_latest_snapshot():
    saved = SimpleNamespace(id=4, snapshot_id=12, position=2, source_url="https://cdn.example/a.webp",
                            observed_alt_state="empty", decision="informative", alt_suggestion="product",
                            note=None, review_status="draft", actor_id=7, actor_name="operator",
                            reviewed_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    db = AsyncMock(); db.scalar.side_effect = [1, page(), image_snapshot()]; db.scalars.return_value = [saved]
    result = asyncio.run(get_image_remediation(1, 1, 231, context(), db))
    assert result["snapshot_id"] == 12 and result["items"][0]["position"] == 2
    sql = str(db.scalars.call_args.args[0].compile(dialect=postgresql.dialect()))
    for field in ("tenant_id", "site_id", "page_id", "snapshot_id"):
        assert f"seo_image_alt_reviews.{field} =" in sql
    db.commit.assert_not_awaited()


def test_image_remediation_can_read_an_explicit_historic_snapshot():
    saved = SimpleNamespace(id=4, snapshot_id=11, position=2, source_url="https://cdn.example/a.webp",
                            observed_alt_state="empty", decision="informative", alt_suggestion="product",
                            note="old", review_status="approved", actor_id=7, actor_name="operator",
                            reviewed_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    db = AsyncMock(); db.scalar.side_effect = [1, page(), image_snapshot(11)]; db.scalars.return_value = [saved]
    result = asyncio.run(get_image_remediation(1, 1, 231, context(), db, snapshot_id=11))
    assert result["snapshot_id"] == 11 and result["items"][0]["review_status"] == "approved"
    snapshot_sql = str(db.scalar.call_args_list[2].args[0].compile(dialect=postgresql.dialect()))
    assert "seo_page_snapshots.id =" in snapshot_sql
    for field in ("tenant_id", "site_id", "url"):
        assert f"seo_page_snapshots.{field} =" in snapshot_sql


def test_image_remediation_history_is_scoped_and_summarized():
    current = image_snapshot(12, datetime(2026, 9, 4, 3, 0))
    previous = image_snapshot(11, datetime(2026, 9, 3, 3, 0))
    approved = SimpleNamespace(snapshot_id=11, position=2, review_status="approved")
    draft = SimpleNamespace(snapshot_id=12, position=2, review_status="draft")
    db = AsyncMock(); db.scalar.side_effect = [1, page(), current]
    db.scalars.side_effect = [[current, previous], [draft, approved]]
    result = asyncio.run(list_image_remediation_history(1, 1, 231, None, 20, context(), db))
    assert result["current_snapshot_id"] == 12
    assert result["items"][0] == {
        "snapshot_id": 12, "fetched_at": "2026-09-04T03:00:00+08:00",
        "candidate_count": 1, "saved_count": 1, "approved_count": 0,
        "draft_count": 1, "is_current": True,
    }
    assert result["items"][1]["approved_count"] == 1
    history_sql = str(db.scalars.call_args_list[0].args[0].compile(dialect=postgresql.dialect()))
    for field in ("tenant_id", "site_id", "url"):
        assert f"seo_page_snapshots.{field} =" in history_sql
    review_sql = str(db.scalars.call_args_list[1].args[0].compile(dialect=postgresql.dialect()))
    for field in ("tenant_id", "site_id", "page_id", "snapshot_id"):
        assert f"seo_image_alt_reviews.{field}" in review_sql


def test_copy_image_remediation_matches_unique_evidence_and_resets_to_draft():
    source_items = [{
        "position": 2, "source_url": "https://cdn.example/a.webp", "source_attribute": "src",
        "srcset": None, "section": "main", "element_id": "hero", "in_link": False,
        "role": None, "alt_state": "empty",
    }]
    target_items = [{**source_items[0], "position": 7}]
    source = image_snapshot(11, datetime(2026, 9, 3, 3, 0), source_items)
    target = image_snapshot(12, datetime(2026, 9, 4, 3, 0), target_items)
    approved = SimpleNamespace(position=2, source_url="https://cdn.example/a.webp",
                               observed_alt_state="empty", decision="informative",
                               alt_suggestion="产品主图", note="人工核对", review_status="approved")
    db = AsyncMock(); db.add = MagicMock(); db.scalar.side_effect = [1, page(), target, source]
    db.scalars.side_effect = [[approved], []]
    req = ImageAltReviewCopy(tenant_id=1, site_id=1, page_id=231,
                             expected_snapshot_id=12, source_snapshot_id=11)
    result = asyncio.run(copy_image_remediation(req, context(), db))
    assert result["copied_positions"] == [7] and result["review_status"] == "draft"
    copied = db.add.call_args.args[0]
    assert copied.snapshot_id == 12 and copied.position == 7
    assert copied.decision == "informative" and copied.alt_suggestion == "产品主图"
    assert copied.review_status == "draft" and "复制自快照 #11" in copied.note
    assert copied.actor_id == 7 and copied.actor_name == "operator"
    db.commit.assert_awaited_once()


def test_copy_image_remediation_never_guesses_ambiguous_or_overwrites_existing():
    repeated = {"source_url": "https://cdn.example/shared.webp", "source_attribute": "src",
                "srcset": None, "section": "main", "element_id": None, "in_link": False,
                "role": None, "alt_state": "empty"}
    source = image_snapshot(11, datetime(2026, 9, 3), [{**repeated, "position": 2}, {**repeated, "position": 3}])
    target = image_snapshot(12, datetime(2026, 9, 4), [{**repeated, "position": 4}, {**repeated, "position": 5}])
    approved = SimpleNamespace(position=2, source_url="https://cdn.example/shared.webp",
                               observed_alt_state="empty", decision="decorative",
                               alt_suggestion=None, note=None, review_status="approved")
    existing = SimpleNamespace(position=5)
    db = AsyncMock(); db.add = MagicMock(); db.scalar.side_effect = [1, page(), target, source]
    db.scalars.side_effect = [[approved], [existing]]
    result = asyncio.run(copy_image_remediation(ImageAltReviewCopy(
        tenant_id=1, site_id=1, page_id=231, expected_snapshot_id=12, source_snapshot_id=11,
    ), context(), db))
    assert result["copied"] == 0 and result["skipped_ambiguous"] == 1
    db.add.assert_not_called(); db.commit.assert_not_awaited()


def test_copy_image_remediation_does_not_overwrite_current_draft():
    item = {"position": 2, "source_url": "https://cdn.example/a.webp", "source_attribute": "src",
            "srcset": None, "section": "main", "element_id": "hero", "in_link": False,
            "role": None, "alt_state": "empty"}
    source = image_snapshot(11, datetime(2026, 9, 3), [item])
    target = image_snapshot(12, datetime(2026, 9, 4), [{**item, "position": 7}])
    approved = SimpleNamespace(position=2, source_url=item["source_url"], observed_alt_state="empty",
                               decision="decorative", alt_suggestion=None, note=None)
    db = AsyncMock(); db.add = MagicMock(); db.scalar.side_effect = [1, page(), target, source]
    db.scalars.side_effect = [[approved], [SimpleNamespace(position=7)]]
    result = asyncio.run(copy_image_remediation(ImageAltReviewCopy(
        tenant_id=1, site_id=1, page_id=231, expected_snapshot_id=12, source_snapshot_id=11,
    ), context(), db))
    assert result["copied"] == 0 and result["skipped_existing"] == 1
    db.add.assert_not_called(); db.commit.assert_not_awaited()


@pytest.mark.parametrize("request_values,status", [
    ({"expected_snapshot_id": 11}, 409),
    ({"source_snapshot_id": 12}, 422),
])
def test_copy_image_remediation_rejects_stale_or_current_source(request_values, status):
    db = AsyncMock(); db.scalar.side_effect = [1, page(), image_snapshot(12)]
    values = dict(tenant_id=1, site_id=1, page_id=231,
                  expected_snapshot_id=12, source_snapshot_id=11) | request_values
    with pytest.raises(HTTPException) as error:
        asyncio.run(copy_image_remediation(ImageAltReviewCopy(**values), context(), db))
    assert error.value.status_code == status
    db.commit.assert_not_awaited()


def test_save_image_remediation_validates_evidence_and_real_actor():
    db = AsyncMock(); db.add = MagicMock(); db.scalar.side_effect = [1, page(), image_snapshot(), None]
    result = asyncio.run(save_image_remediation(image_review_request(), context(), db))
    saved = db.add.call_args.args[0]
    assert isinstance(saved, SeoImageAltReview)
    assert (saved.tenant_id, saved.site_id, saved.page_id, saved.snapshot_id, saved.position) == (1, 1, 231, 12, 2)
    assert saved.actor_id == 7 and saved.review_status == "approved"
    assert result["alt_suggestion"] == "NORDBLOC.1 伞齿轮减速电机"
    assert db.scalar.call_args_list[1].args[0]._for_update_arg is not None
    db.commit.assert_awaited_once()


def test_image_remediation_stale_review_is_rejected():
    existing = SimpleNamespace(id=9)
    db = AsyncMock(); db.scalar.side_effect = [1, page(), image_snapshot(), existing]
    with pytest.raises(HTTPException) as error:
        asyncio.run(save_image_remediation(image_review_request(expected_review_id=8), context(), db))
    assert error.value.status_code == 409
    db.commit.assert_not_awaited()


def test_image_remediation_requires_explicit_optimistic_review_token():
    values = image_review_request().model_dump()
    values.pop("expected_review_id")
    with pytest.raises(ValidationError):
        ImageAltReviewUpdate(**values)


def test_decorative_image_clears_alt_suggestion_before_save():
    db = AsyncMock(); db.add = MagicMock(); db.scalar.side_effect = [1, page(), image_snapshot(), None]
    asyncio.run(save_image_remediation(image_review_request(
        decision="decorative", alt_suggestion="不应保存", review_status="approved"), context(), db))
    saved = db.add.call_args.args[0]
    assert saved.alt_suggestion is None


@pytest.mark.parametrize("request_values,status", [
    ({"expected_snapshot_id": 11}, 409),
    ({"position": 3}, 409),
    ({"decision": "undecided", "review_status": "approved"}, 422),
    ({"alt_suggestion": None, "review_status": "approved"}, 422),
    ({}, 409),
])
def test_image_remediation_rejects_stale_or_unreviewable_writes(request_values, status):
    db = AsyncMock(); db.scalar.side_effect = [1, page(), image_snapshot()]
    if not request_values:
        db.scalar.side_effect = [1, page(), SimpleNamespace(
            id=12, error_type=None, image_alt_evidence={"items": [
                {"position": 2, "source_url": "https://cdn.example/a.webp", "alt_state": "unknown"},
            ]})]
    with pytest.raises(HTTPException) as error:
        asyncio.run(save_image_remediation(image_review_request(**request_values), context(), db))
    assert error.value.status_code == status
    db.commit.assert_not_awaited()


def test_image_alt_review_model_constraints():
    table = SeoImageAltReview.__table__
    assert {"ck_seo_image_alt_review_position", "ck_seo_image_alt_review_observed_state",
            "ck_seo_image_alt_review_decision", "ck_seo_image_alt_review_status",
            "ck_seo_image_alt_review_suggestion"} <= {constraint.name for constraint in table.constraints}
    for name in ("tenant_id", "site_id", "page_id", "snapshot_id"):
        assert next(iter(table.c[name].foreign_keys)).ondelete == "CASCADE"


def test_image_alt_review_migration_renders_scoped_timezone_aware_table():
    import importlib.util
    import io
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).parents[1] / "migrations/versions/20260904_0088_seo_image_alt_reviews.py"
    spec = importlib.util.spec_from_file_location("image_alt_review_migration", path)
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    output = io.StringIO()
    migration.op = Operations(MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}))
    migration.upgrade()
    sql = output.getvalue()
    assert "CREATE TABLE seo_image_alt_reviews" in sql
    assert sql.count("ON DELETE CASCADE") == 4
    assert sql.count("TIMESTAMP WITH TIME ZONE") == 2
    assert "uq_seo_image_alt_review_snapshot_position" in sql


@pytest.mark.parametrize("status", [None, 301, 404, 503])
def test_image_evidence_legacy_http_failure_is_not_a_successful_observation(status):
    db = AsyncMock()
    db.scalar.side_effect = [1, page(), SimpleNamespace(
        id=9, fetched_at=datetime(2026, 9, 3, 10, 0, tzinfo=timezone.utc),
        status_code=status, error_type=None, images_missing_alt_count=1,
        image_alt_evidence={"items": [{"source_url": "https://example.com/error-logo.png"}]})]
    result = asyncio.run(get_image_evidence(1, 1, 231, context(), db))
    assert result["fetch_error"]
    assert result["evidence"] is None
    assert result["fetched_at"] == "2026-09-03T10:00:00+00:00"
    assert db.scalar.await_count == 3  # Never query an older successful snapshot.


def test_image_evidence_migration_is_nullable_and_offline():
    import importlib.util
    import io
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).parents[1] / "migrations/versions/20260903_0087_seo_image_alt_evidence.py"
    spec = importlib.util.spec_from_file_location("image_evidence_migration", path)
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    output = io.StringIO()
    migration.op = Operations(MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}))
    migration.upgrade()
    assert "ADD COLUMN image_alt_evidence JSONB" in output.getvalue()
    assert "NOT NULL" not in output.getvalue() and "UPDATE " not in output.getvalue()


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
