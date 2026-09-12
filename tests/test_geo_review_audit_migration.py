from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.dialects.postgresql import JSONB


ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "migrations/versions/20260913_0100_geo_review_audit.py"


def _migration():
    spec = spec_from_file_location("geo_review_audit_migration", MIGRATION)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_review_audit_is_single_canonical_head_after_shared_0099():
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert script.get_heads() == ["0100_geo_review_audit"]
    assert script.get_revision("0100_geo_review_audit").down_revision == (
        "0099_demo_fixture_registry"
    )
    revisions = {
        revision.revision
        for revision in script.iterate_revisions("0100_geo_review_audit", "base")
    }
    assert {
        "0095_adopt_geo_ticket",
        "0098_demo_binding_no_truncate",
        "0099_demo_fixture_registry",
    } <= revisions
    assert not (
        ROOT / "migrations/versions/20260905_0074_geo_ticket_assignment.py"
    ).exists()


def test_review_audit_upgrade_and_downgrade_touch_only_nullable_jsonb(monkeypatch):
    migration = _migration()
    calls = []

    class Operations:
        def add_column(self, table, column):
            calls.append(("add", table, column))

        def drop_column(self, table, column):
            calls.append(("drop", table, column))

    monkeypatch.setattr(migration, "op", Operations())
    migration.upgrade()
    action, table, column = calls.pop(0)
    assert (action, table, column.name, column.nullable) == (
        "add",
        "geo_content_tasks",
        "review_audit",
        True,
    )
    assert isinstance(column.type, JSONB)

    migration.downgrade()
    assert calls == [("drop", "geo_content_tasks", "review_audit")]
