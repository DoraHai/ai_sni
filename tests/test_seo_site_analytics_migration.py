"""The analytics migration remains additive and unapplied until reviewed."""
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).parents[1]


def test_analytics_migration_is_new_single_head():
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert script.get_heads() == ["0103_seo_tdk_review"]
    assert script.get_revision("0101_seo_site_analytics").down_revision == "0100_seo_page_captures"
    text = (ROOT / "migrations/versions/20261004_0101_seo_site_analytics.py").read_text(encoding="utf-8")
    assert "未在任何环境执行；生产执行前须单独审核" in text
    for table in ("seo_site_analytics_sources", "seo_site_analytics_monthly", "seo_site_export_templates"):
        assert f'op.create_table("{table}"' in text
    for field in ("secret_ciphertext", "last_error_code", "last_error_message", "last_attempt_at"):
        assert f'sa.Column("{field}"' in text
