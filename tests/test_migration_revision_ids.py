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
