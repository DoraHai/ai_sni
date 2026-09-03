import ast
import asyncio
import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


ROOT = Path(__file__).parents[1]
GEO_REPAIR = ROOT / "migrations/versions/20260819_0073_geo_schema_repair.py"
MERGE_REVISION = ROOT / "migrations/versions/20260822_0074_merge_geo_seo_heads.py"
SEM_SEO_MERGE_REVISION = ROOT / "migrations/versions/20260829_0077_merge_sem_seo_heads.py"
SITE_DATA_REPAIR_REVISION = ROOT / "migrations/versions/20260829_0078_seo_site_data_repairs.py"
CONTENT_REVIEW_REVISION = ROOT / "migrations/versions/20260829_0079_seo_content_review_workflow.py"
CONTENT_REVIEW_HISTORY_REVISION = ROOT / "migrations/versions/20260831_0080_seo_content_review_history.py"
SEO_MONITOR_CASCADE_REVISION = ROOT / "migrations/versions/20260831_0081_seo_monitor_tenant_cascade.py"
SEO_AUTOMATION_RUNS_REVISION = ROOT / "migrations/versions/20260901_0082_seo_automation_runs.py"
SEO_MANUAL_RERUN_REVISION = ROOT / "migrations/versions/20260901_0083_seo_manual_rerun.py"
SEO_CRAWL_QUEUED_REVISION = ROOT / "migrations/versions/20260901_0084_seo_crawl_queued_status.py"
EXPECTED_GEO_REPAIR_SHA256 = "4e785eefd6bcc7a6f1158ff38b19769cb5ee2ffafa433e9f616f30c85ac533ba"
CANONICAL_SEM_MIGRATION_SHA256 = {
    "20260822_0074_suggestion_workflow.py": "c082bfbab80ad2db03e11d00c0855bdbd2167ee3418259433b2caddc9d18addc",
    "20260822_0075_sem_asset_sync_state.py": "cd54e173d6d09ee3ac6d7a081297a5e38658206daa3eafdfa2e5b8d57a9490e1",
    "20260825_0076_oauth_rebind_intent.py": "3fc37d229ce841e7c3192ecd923edd257a7e810d8561aa66def5d7f1f06154d9",
}


def _config() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return config


def test_geo_repair_is_preserved_across_platform_line_endings() -> None:
    normalized = GEO_REPAIR.read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(normalized).hexdigest() == EXPECTED_GEO_REPAIR_SHA256
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "/migrations/versions/20260819_0073_geo_schema_repair.py text eol=lf" in attributes


def test_imported_sem_migrations_match_the_canonical_production_history() -> None:
    versions = ROOT / "migrations/versions"
    for filename, expected in CANONICAL_SEM_MIGRATION_SHA256.items():
        normalized = (versions / filename).read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(normalized).hexdigest() == expected


def _assert_noop_revision(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert set(functions) == {"upgrade", "downgrade"}
    assert all(
        len(functions[name].body) == 1 and isinstance(functions[name].body[0], ast.Pass)
        for name in ("upgrade", "downgrade")
    )


def test_merge_revisions_are_noop_and_sem_seo_merge_is_only_head() -> None:
    _assert_noop_revision(MERGE_REVISION)
    _assert_noop_revision(SEM_SEO_MERGE_REVISION)

    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == ["0087_seo_image_alt_evidence"]
    merge = script.get_revision("0074_merge_geo_seo_heads")
    assert set(merge._normalized_down_revisions) == {
        "0073_geo_schema_repair",
        "0073_seo_distribution_variants",
    }
    source_page = script.get_revision("0075_seo_content_source_page")
    assert source_page.down_revision == "0074_merge_geo_seo_heads"
    sem_seo_merge = script.get_revision("0077_merge_sem_seo_heads")
    assert set(sem_seo_merge._normalized_down_revisions) == {
        "0076_oauth_rebind_intent",
        "0075_seo_content_source_page",
    }
    site_data_repair = script.get_revision("0078_seo_site_data_repairs")
    assert site_data_repair.down_revision == "0077_merge_sem_seo_heads"
    content_review = script.get_revision("0079_seo_content_review_workflow")
    assert content_review.down_revision == "0078_seo_site_data_repairs"
    content_review_history = script.get_revision("0080_seo_content_review_history")
    assert content_review_history.down_revision == "0079_seo_content_review_workflow"
    monitor_cascade = script.get_revision("0081_seo_monitor_cascade")
    assert monitor_cascade.down_revision == "0080_seo_content_review_history"
    automation_runs = script.get_revision("0082_seo_automation_runs")
    assert automation_runs.down_revision == "0081_seo_monitor_cascade"
    manual_rerun = script.get_revision("0083_seo_manual_rerun")
    assert manual_rerun.down_revision == "0082_seo_automation_runs"
    crawl_queued = script.get_revision("0084_seo_crawl_queued_status")
    assert crawl_queued.down_revision == "0083_seo_manual_rerun"


def test_seo_health_required_revision_matches_alembic_head() -> None:
    source = (ROOT / "app/seo_main.py").read_text(encoding="utf-8")
    match = re.search(r'SEO_REQUIRED_SCHEMA_REVISION = "([^"]+)"', source)
    assert match is not None
    assert ScriptDirectory.from_config(_config()).get_heads() == [match.group(1)]


def test_crawl_status_migration_allows_queued_and_has_safe_downgrade() -> None:
    source = SEO_CRAWL_QUEUED_REVISION.read_text(encoding="utf-8")
    assert "status IN ('queued','running','completed','partial','failed')" in source
    assert "WHERE status = 'queued'" in source
    assert "SET status = 'failed'" in source


def test_upgrade_plan_from_production_sem_head_runs_only_seo_branch() -> None:
    script = ScriptDirectory.from_config(_config())
    steps = script._upgrade_revs("head", "0076_oauth_rebind_intent")
    revisions = [step.revision.revision for step in steps]
    assert revisions == [
        "0075_seo_content_source_page",
        "0077_merge_sem_seo_heads",
        "0078_seo_site_data_repairs",
        "0079_seo_content_review_workflow",
        "0080_seo_content_review_history",
        "0085_seo_page_index_reviews",
        "0081_seo_monitor_cascade",
        "0082_seo_automation_runs",
        "0083_seo_manual_rerun",
        "0084_seo_crawl_queued_status",
        "0086_seo_index_review_merge",
        "0087_seo_image_alt_evidence",
    ]


def test_index_review_promotion_preserves_both_histories_and_upgrades_only_new_table():
    script = ScriptDirectory.from_config(_config())
    assert script.get_revision("0085_seo_page_index_reviews").down_revision == "0080_seo_content_review_history"
    assert set(script.get_revision("0086_seo_index_review_merge").down_revision) == {
        "0084_seo_crawl_queued_status", "0085_seo_page_index_reviews",
    }
    steps = script._upgrade_revs("head", "0084_seo_crawl_queued_status")
    assert [step.revision.revision for step in steps] == [
        "0085_seo_page_index_reviews", "0086_seo_index_review_merge",
        "0087_seo_image_alt_evidence",
    ]
    assert script.get_revision("0087_seo_image_alt_evidence").down_revision == "0086_seo_index_review_merge"
    assert [step.revision.revision for step in script._upgrade_revs("head", "0086_seo_index_review_merge")] == [
        "0087_seo_image_alt_evidence",
    ]


def test_site_data_repair_is_tenant_scoped_and_page_231_is_fail_closed() -> None:
    source = SITE_DATA_REPAIR_REVISION.read_text(encoding="utf-8")
    assert source.count("snapshot.tenant_id = keyword.tenant_id") == 1
    assert source.count("result.tenant_id = keyword.tenant_id") == 1
    assert source.count("site.tenant_id = keyword.tenant_id") == 2
    assert "content.id = 3" in source
    assert "content.tenant_id = 1" in source
    assert "content.site_id = 1" in source
    assert "content.status = 'drafting'" in source
    assert "page.id = 231" in source
    assert "page.tenant_id = content.tenant_id" in source
    assert "page.site_id = content.site_id" in source
    assert "linked.source_page_id = 231" in source
    assert "NORDAC NORDCON BU0000" in source


@pytest.mark.skipif(
    not os.getenv("SEO_MIGRATION_TEST_DATABASE_URL"),
    reason="requires an isolated PostgreSQL migration database",
)
def test_postgres_upgrade_from_sem_head_applies_only_pending_seo_branch(monkeypatch) -> None:
    async_url = os.environ["SEO_MIGRATION_TEST_DATABASE_URL"]
    monkeypatch.setenv("DATABASE_URL", async_url)
    from app.config import get_settings

    get_settings.cache_clear()
    config = _config()
    command.upgrade(config, "0076_oauth_rebind_intent")

    async def version() -> str:
        engine = create_async_engine(async_url)
        async with engine.connect() as connection:
            value = await connection.execute(text("SELECT version_num FROM alembic_version"))
            current = value.scalar_one()
        await engine.dispose()
        return current

    before = asyncio.run(version())
    assert before == "0076_oauth_rebind_intent"

    command.upgrade(config, "head")

    async def schema_snapshot() -> tuple[str, set[str], set[str], set[str], set[str]]:
        engine = create_async_engine(async_url)
        async with engine.connect() as connection:
            value = await connection.execute(text("SELECT version_num FROM alembic_version"))
            current = value.scalar_one()

            def inspect_schema(sync_connection) -> tuple[set[str], set[str]]:
                inspector = inspect(sync_connection)
                image_column = next(column for column in inspector.get_columns("seo_page_snapshots")
                                    if column["name"] == "image_alt_evidence")
                assert image_column["nullable"] is True
                assert str(image_column["type"]) == "JSONB"
                assert "seo_distribution_variants" in inspector.get_table_names()
                assert "seo_content_review_events" in inspector.get_table_names()
                assert "seo_automation_runs" in inspector.get_table_names()
                automation_columns = {
                    column["name"]
                    for column in inspector.get_columns("seo_automation_runs")
                }
                assert {
                    "tenant_id",
                    "site_id",
                    "job_type",
                    "trigger_type",
                    "status",
                    "planned_count",
                    "success_count",
                    "failed_count",
                    "skipped_count",
                    "error_summary",
                    "requested_by",
                    "started_at",
                    "completed_at",
                }.issubset(automation_columns)
                automation_indexes = {
                    index["name"]
                    for index in inspector.get_indexes("seo_automation_runs")
                }
                assert "ix_seo_automation_runs_tenant_job_started" in automation_indexes
                assert "ix_seo_automation_runs_requested_by" in automation_indexes
                crawl_checks = inspector.get_check_constraints("seo_crawl_runs")
                crawl_status_check = next(
                    constraint
                    for constraint in crawl_checks
                    if constraint["name"] == "ck_seo_crawl_run_status"
                )
                assert "queued" in crawl_status_check["sqltext"]
                automation_foreign_keys = inspector.get_foreign_keys(
                    "seo_automation_runs"
                )
                assert any(
                    foreign_key["constrained_columns"] == ["requested_by"]
                    and foreign_key["referred_table"] == "users"
                    and foreign_key["options"].get("ondelete") == "SET NULL"
                    for foreign_key in automation_foreign_keys
                )
                review_event_columns = {
                    column["name"]
                    for column in inspector.get_columns("seo_content_review_events")
                }
                assert {
                    "tenant_id",
                    "site_id",
                    "content_asset_id",
                    "action",
                    "from_status",
                    "to_status",
                    "note",
                    "actor_id",
                    "created_at",
                }.issubset(review_event_columns)
                review_event_indexes = {
                    index["name"]
                    for index in inspector.get_indexes("seo_content_review_events")
                }
                assert "ix_seo_content_review_events_tenant_asset_created" in review_event_indexes
                publication_columns = {
                    column["name"]
                    for column in inspector.get_columns("seo_content_publications")
                }
                assert "variant_id" in publication_columns
                variant_indexes = {
                    index["name"]
                    for index in inspector.get_indexes("seo_distribution_variants")
                }
                publication_indexes = {
                    index["name"]
                    for index in inspector.get_indexes("seo_content_publications")
                }
                content_columns = {
                    column["name"]
                    for column in inspector.get_columns("seo_content_assets")
                }
                assert "source_page_id" in content_columns
                assert {
                    "review_submitted_by",
                    "review_submitted_at",
                    "review_note",
                    "reviewed_by",
                    "reviewed_at",
                }.issubset(content_columns)
                content_indexes = {
                    index["name"]
                    for index in inspector.get_indexes("seo_content_assets")
                }
                content_unique_constraints = {
                    constraint["name"]
                    for constraint in inspector.get_unique_constraints(
                        "seo_content_assets"
                    )
                }
                return (
                    variant_indexes,
                    publication_indexes,
                    content_indexes,
                    content_unique_constraints,
                )

            (
                variant_indexes,
                publication_indexes,
                content_indexes,
                content_unique_constraints,
            ) = await connection.run_sync(inspect_schema)
            # Exercise the application writer against the migrated PostgreSQL
            # CHECK constraints, not just ORM metadata. Temp copies preserve
            # constraints/defaults without needing unrelated tenant fixtures.
            from app.models.seo import SeoCrawlRun, SeoPageSnapshot, SeoSitePage
            from app.seo_page_audit import save_page_snapshot

            for table in ('seo_crawl_runs', 'seo_site_pages', 'seo_page_snapshots'):
                await connection.execute(text(
                    f'CREATE TEMP TABLE {table} (LIKE public.{table} INCLUDING ALL) ON COMMIT DROP'))
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                page = SeoSitePage(tenant_id=1, site_id=1, url='https://example.com/audit', status='approved',
                                   title_suggestion='Keep approved title')
                session.add(page)
                await session.flush()
                for failed in (False, True):
                    values = dict(url=page.url, discovery_source='single_page', click_depth=0,
                                  status_code=None if failed else 200, issue_codes=['timeout'] if failed else [],
                                  error_type='timeout' if failed else None,
                                  image_alt_evidence=None if failed else {'candidate_count': 1, 'items': []})
                    await save_page_snapshot(session, page, values, None, datetime.now(timezone.utc).replace(tzinfo=None))
                    await session.flush()
                runs = list(await session.scalars(select(SeoCrawlRun).order_by(SeoCrawlRun.id)))
                assert [run.status for run in runs] == ['completed', 'failed']
                assert all(run.max_urls == 1 for run in runs)
                snapshots = list(await session.scalars(select(SeoPageSnapshot).order_by(SeoPageSnapshot.id)))
                assert len(snapshots) == 2
                assert all(row.discovery_source == 'single_page' for row in snapshots)
                assert snapshots[0].image_alt_evidence['candidate_count'] == 1
                assert snapshots[1].image_alt_evidence is None
                assert page.title_suggestion == 'Keep approved title'
        await engine.dispose()
        return (
            current,
            variant_indexes,
            publication_indexes,
            content_indexes,
            content_unique_constraints,
        )

    (
        after,
        variant_indexes,
        publication_indexes,
        content_indexes,
        content_unique_constraints,
    ) = asyncio.run(schema_snapshot())
    get_settings.cache_clear()

    assert after == "0087_seo_image_alt_evidence"
    assert {
        "ix_seo_distribution_variants_tenant_id",
        "ix_seo_distribution_variants_content_asset_id",
        "ix_seo_distribution_variants_connection_id",
        "ix_seo_distribution_variant_latest",
        "ix_seo_distribution_variant_status",
    }.issubset(variant_indexes)
    assert "ix_seo_content_publications_variant_id" in publication_indexes
    assert "ix_seo_content_assets_source_page_id" in content_indexes
    assert "ix_seo_content_assets_tenant_review" in content_indexes
    assert "uq_seo_content_asset_source_page" in content_unique_constraints
