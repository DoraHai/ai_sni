"""Alembic revision identifiers must fit the project's PostgreSQL schema."""

import ast
from pathlib import Path


MIGRATIONS_DIR = Path(__file__).parents[1] / "migrations" / "versions"


def _revision_id(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "revision" for target in node.targets)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    raise AssertionError(f"No revision id found in {path.name}")


def test_0049_revision_id_fits_alembic_version_column():
    revision = _revision_id(
        MIGRATIONS_DIR / "20260804_0049_clean_legacy_geo_demo_statements.py"
    )
    assert len(revision) <= 32


def test_0050_revision_id_fits_alembic_version_column():
    revision = _revision_id(MIGRATIONS_DIR / "20260805_0050_geo_expand_runs.py")
    assert len(revision) <= 32
    assert revision == "0050_geo_expand_runs"


def test_0051_revision_id_fits_alembic_version_column():
    revision = _revision_id(MIGRATIONS_DIR / "20260805_0051_geo_engine_sample.py")
    assert len(revision) <= 32
    assert revision == "0051_geo_engine_sample"
