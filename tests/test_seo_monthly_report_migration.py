"""The optional monthly report template migration is additive and review gated."""
from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory


def test_monthly_report_migration_is_new_head():
    root = Path(__file__).parents[1]
    script = ScriptDirectory.from_config(Config(str(root / "alembic.ini")))
    assert script.get_heads() == ["0102_seo_monthly_report_template"]
    assert script.get_revision("0102_seo_monthly_report_template").down_revision == "0101_seo_site_analytics"
    text = (root / "migrations/versions/20261005_0102_seo_monthly_report_template.py").read_text(encoding="utf-8")
    assert "未在任何环境执行；生产执行前须单独审核" in text
    assert 'op.create_table("seo_site_report_templates"' in text
    assert 'sa.Column("sections", JSONB(), nullable=False)' in text
