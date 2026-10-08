from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_ai_tdk_is_unapplied_additive_head():
    root = Path(__file__).parents[1]
    script = ScriptDirectory.from_config(Config(str(root / "alembic.ini")))
    assert script.get_heads() == ["0106_seo_content_messages"]
    assert script.get_revision("0104_seo_page_ai_tdk").down_revision == "0103_seo_tdk_review"
    source = (root / "migrations/versions/20261005_0104_seo_page_ai_tdk.py").read_text(encoding="utf8")
    assert "未在任何环境执行；生产执行前须单独审核" in source
    assert 'op.create_table("seo_page_ai_tdk_suggestions"' in source
