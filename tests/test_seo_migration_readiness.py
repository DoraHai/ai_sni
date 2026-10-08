"""Offline release checks only; no credentials, DB, migration or business calls."""
import re
import socket
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import seo_confirmation_message_readiness as readiness


def test_inventory_reuses_both_canonical_migrations_without_a_connection(monkeypatch):
    def denied(*args, **kwargs): raise AssertionError("Network/DB must not be used by generator")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(sa, "create_engine", denied)
    inv = readiness.inventory(2)
    assert len(inv.tables) == 5 and len(inv.indexes) == 11
    assert len(readiness.sequence_names(inv)) == 4
    assert sum(len(t.foreign_key_constraints) for t in inv.tables.values()) == 14
    assert sum(isinstance(c,sa.CheckConstraint) for t in inv.tables.values() for c in t.constraints) == 6
    assert sum(isinstance(c,sa.UniqueConstraint) for t in inv.tables.values() for c in t.constraints) == 3
    assert len(inv.sql) == 3


@pytest.mark.parametrize("revision", readiness.REVISIONS)
def test_generated_sql_is_read_only_and_fails_closed(revision):
    sql = readiness.render(revision,"sample_db","sample_runtime","sample_migrator")
    assert "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY" in sql
    assert "\\set ON_ERROR_STOP on" in sql
    assert "COALESCE((" in sql and "SELECT 1/0 AS readiness_failed" in sql
    # Lexical exclusion of write/DDL commands outside SQL literals/comments.
    unquoted = re.sub(r"'(?:''|[^'])*'", "''", sql)
    unquoted = re.sub(r"--[^\n]*", "", unquoted)
    assert not re.search(r"\b(CREATE|ALTER|DROP|INSERT|UPDATE|DELETE|TRUNCATE|GRANT|REVOKE|DO|CALL|COPY)\b",unquoted,re.I)
    assert "nextval(" not in sql and "setval(" not in sql and "FOR UPDATE" not in sql
    assert "single_expected_revision" in sql and "public_search_path" in sql
    assert "migration_timeouts_bounded" in sql
    assert "sites_with_any_new_opt_in" in sql


def test_preflight_detects_every_future_object_and_postflight_checks_runtime_locks():
    before = readiness.render(readiness.REVISIONS[0],"sample_db","sample_runtime","sample_migrator")
    after = readiness.render(readiness.REVISIONS[2],"sample_db","sample_runtime","sample_migrator")
    for table in readiness.inventory(2).tables:
        assert "absent_future_"+table in before
        assert "column_count_"+table in after
    assert "future_function_absent" in before
    assert "message_trigger_function" in after and "tgtype=27" in after and "tgtype=34" in after
    assert "runtime_update_seo_content_conversations.id" in after
    assert "runtime_lock_users" in after and "runtime_lock_seo_content_assets" in after
    assert "runtime_append_only_seo_content_messages" in after
    assert "runtime_update_seo_conversation_participants.last_read_message_id" in after
    assert "confdeltype='r'" in after and "confdeltype='c'" in after and "confdeltype='n'" in after


def test_role_input_is_quoted_and_generated_files_cannot_overwrite_receipts(tmp_path, monkeypatch):
    sql = readiness.render(readiness.REVISIONS[0],"sample_db","runtime'; DROP TABLE users; --","migration")
    assert "'runtime''; DROP TABLE users; --'" in sql
    target = tmp_path / "existing.sql"
    target.write_text("original evidence", encoding="utf-8")
    monkeypatch.setattr(sys,"argv",["readiness","--revision",readiness.REVISIONS[0],"--database","sample_db",
        "--runtime-role","runtime","--migration-role","migration","--output",str(target)])
    with pytest.raises(FileExistsError): readiness.main()
    assert target.read_text(encoding="utf-8") == "original evidence"


def test_unknown_revision_cannot_generate_a_false_approval():
    with pytest.raises(ValueError): readiness.render("9999_unknown","db","runtime","migration")
