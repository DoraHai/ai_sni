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
EXPECTED_GEO_REPAIR_SHA256 = "4e785eefd6bcc7a6f1158ff38b19769cb5ee2ffafa433e9f616f30c85ac533ba"


def _config() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return config


def test_geo_repair_is_preserved_byte_for_byte() -> None:
    assert hashlib.sha256(GEO_REPAIR.read_bytes()).hexdigest() == EXPECTED_GEO_REPAIR_SHA256


def test_merge_revision_is_noop_and_only_head() -> None:
    source = MERGE_REVISION.read_text(encoding="utf-8")
    tree = ast.parse(source)
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

    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == ["0074_merge_geo_seo_heads"]
    merge = script.get_revision("0074_merge_geo_seo_heads")
    assert set(merge._normalized_down_revisions) == {
        "0073_geo_schema_repair",
        "0073_seo_distribution_variants",
    }


def test_upgrade_plan_from_production_geo_head_skips_geo_and_runs_seo() -> None:
    script = ScriptDirectory.from_config(_config())
    steps = script._upgrade_revs("head", "0073_geo_schema_repair")
    revisions = [step.revision.revision for step in steps]
    assert "0073_geo_schema_repair" not in revisions
    assert revisions == [
        "0073_seo_distribution_variants",
        "0074_merge_geo_seo_heads",
    ]


@pytest.mark.skipif(
    not os.getenv("SEO_MIGRATION_TEST_DATABASE_URL"),
    reason="requires an isolated PostgreSQL migration database",
)
def test_postgres_upgrade_from_geo_head_creates_seo_variant_schema(monkeypatch) -> None:
    async_url = os.environ["SEO_MIGRATION_TEST_DATABASE_URL"]
    monkeypatch.setenv("DATABASE_URL", async_url)
    from app.config import get_settings

    get_settings.cache_clear()
    config = _config()
    command.upgrade(config, "0073_geo_schema_repair")

    async def version() -> str:
        engine = create_async_engine(async_url)
        async with engine.connect() as connection:
            value = await connection.execute(text("SELECT version_num FROM alembic_version"))
            current = value.scalar_one()
        await engine.dispose()
        return current

    before = asyncio.run(version())
    assert before == "0073_geo_schema_repair"

    command.upgrade(config, "head")

    async def schema_snapshot() -> tuple[str, set[str], set[str]]:
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
                return variant_indexes, publication_indexes

            variant_indexes, publication_indexes = await connection.run_sync(inspect_schema)
        await engine.dispose()
        return current, variant_indexes, publication_indexes

    after, variant_indexes, publication_indexes = asyncio.run(schema_snapshot())
    get_settings.cache_clear()

    assert after == "0074_merge_geo_seo_heads"
    assert {
        "ix_seo_distribution_variants_tenant_id",
        "ix_seo_distribution_variants_content_asset_id",
        "ix_seo_distribution_variants_connection_id",
        "ix_seo_distribution_variant_latest",
        "ix_seo_distribution_variant_status",
    }.issubset(variant_indexes)
    assert "ix_seo_content_publications_variant_id" in publication_indexes
