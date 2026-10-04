from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


ROOT = Path(__file__).parents[1]


def test_capture_migration_is_single_additive_head():
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert script.get_heads() == ["0100_seo_page_captures"]
    assert script.get_revision("0100_seo_page_captures").down_revision == "0099_geo_review_audit"
    source = (ROOT / "migrations/versions/20261004_0100_seo_page_captures.py").read_text(encoding="utf-8")
    assert "未在任何环境执行" in source and "生产执行前须单独审核" in source
    assert "op.create_table(" in source and '"seo_page_captures"' in source
