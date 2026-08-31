import ast
import asyncio
import hashlib
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine


ROOT = Path(__file__).parents[1]
GEO_REPAIR = ROOT / "migrations/versions/20260819_0073_geo_schema_repair.py"
MERGE_REVISION = ROOT / "migrations/versions/20260822_0074_merge_geo_seo_heads.py"
SEM_SEO_MERGE_REVISION = ROOT / "migrations/versions/20260829_0077_merge_sem_seo_heads.py"
SITE_DATA_REPAIR_REVISION = ROOT / "migrations/versions/20260829_0078_seo_site_data_repairs.py"
CONTENT_REVIEW_REVISION = ROOT / "migrations/versions/20260829_0079_seo_content_review_workflow.py"
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
    assert script.get_heads() == ["0079_seo_content_review_workflow"]
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


def test_upgrade_plan_from_production_sem_head_runs_only_seo_branch() -> None:
    script = ScriptDirectory.from_config(_config())
    steps = script._upgrade_revs("head", "0076_oauth_rebind_intent")
    revisions = [step.revision.revision for step in steps]
    assert revisions == [
        "0075_seo_content_source_page",
        "0077_merge_sem_seo_heads",
        "0078_seo_site_data_repairs",
        "0079_seo_content_review_workflow",
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
                assert "seo_distribution_variants" in inspector.get_table_names()
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

    assert after == "0079_seo_content_review_workflow"
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
