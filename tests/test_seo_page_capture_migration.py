from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


ROOT = Path(__file__).parents[1]


def test_capture_migration_is_single_additive_head():
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert script.get_heads() == ["0106_seo_content_messages"]
    assert script.get_revision("0100_seo_page_captures").down_revision == "0099_geo_review_audit"
    assert script.get_revision("0101_seo_site_analytics").down_revision == "0100_seo_page_captures"
    source = (ROOT / "migrations/versions/20261004_0100_seo_page_captures.py").read_text(encoding="utf-8")
    assert "未在任何环境执行" in source and "生产执行前须单独审核" in source
    assert "op.create_table(" in source and '"seo_page_captures"' in source
    assert 'sa.Column("redirect_chain", JSONB(), nullable=False)' in source
    assert 'sa.Column("warnings", JSONB(), nullable=False)' in source
    assert "status IN ('pending', 'running', 'succeeded', 'failed')" in source
    assert 'sa.Column("source", sa.String(16), server_default="auto", nullable=False)' in source
    assert 'sa.Column("uploaded_by", sa.BigInteger())' in source
    assert 'sa.Column("uploaded_at", sa.DateTime(timezone=True))' in source
    assert 'sa.Column("content_type", sa.String(32), server_default="image/png", nullable=False)' in source
    assert "source IN ('auto', 'manual')" in source
    assert "uploaded_by IS NOT NULL AND uploaded_at IS NOT NULL" in source
    assert '"ix_seo_page_captures_timeline"' in source
