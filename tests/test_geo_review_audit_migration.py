from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.dialects.postgresql import JSONB


ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "migrations/versions/20260913_0099_geo_review_audit.py"


def _migration():
    spec = spec_from_file_location("geo_review_audit_migration", MIGRATION)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_review_audit_is_the_single_head_after_shared_0098():
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert script.get_heads() == ["0099_geo_review_audit"]
    assert script.get_revision("0099_geo_review_audit").down_revision == (
        "0098_demo_binding_no_truncate"
    )


def test_upgrade_adds_only_nullable_jsonb_and_downgrade_refuses(monkeypatch):
    migration = _migration()
    calls = []

    class Operations:
        def add_column(self, table, column):
            calls.append((table, column))

    monkeypatch.setattr(migration, "op", Operations())
    migration.upgrade()
    table, column = calls.pop()
    assert (table, column.name, column.nullable) == (
        "geo_content_tasks",
        "review_audit",
        True,
    )
    assert isinstance(column.type, JSONB)

    with pytest.raises(RuntimeError, match="retain persisted human review evidence"):
        migration.downgrade()
    assert calls == []
