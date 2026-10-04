"""The additive TDK review migration is the reviewed, unapplied head."""
from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory


def test_tdk_review_migration_is_new_head():
    root = Path(__file__).parents[1]
    script = ScriptDirectory.from_config(Config(str(root / "alembic.ini")))
    assert script.get_heads() == ["0103_seo_tdk_review"]
    assert script.get_revision("0103_seo_tdk_review").down_revision == "0102_seo_monthly_report_template"
    source = (root / "migrations/versions/20261005_0103_seo_tdk_review.py").read_text(encoding="utf-8")
    assert "未在任何环境执行；生产执行前须单独审核" in source
    assert 'op.create_table("seo_tdk_review_batches"' in source
    assert 'op.create_table("seo_site_tdk_review_templates"' in source
