"""Offline contract checks; the psql file is never run by ordinary CI."""
from pathlib import Path
import re

ROOT = Path(__file__).parents[1]
SQL = (ROOT / 'ops/sem-task-migration/preflight-readonly.psql').read_text(encoding='utf-8')


def test_readonly_transaction_envelope():
    assert r'\set ON_ERROR_STOP on' in SQL
    assert 'BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;' in SQL
    assert SQL.rstrip().endswith('ROLLBACK;')
    assert "SET LOCAL statement_timeout = '10s';" in SQL


def test_no_mutation_or_customer_rows():
    statements = re.sub(r'--[^\n]*', '', SQL)
    # Strings include privilege names such as CREATE/UPDATE, not operations.
    statements = re.sub(r"'(?:[^']|'')*'", "''", statements)
    assert not re.search(r'\b(CREATE|ALTER|DROP|INSERT|UPDATE|DELETE|GRANT|COPY|COMMIT|VACUUM)\b', statements, re.I)
    assert 'FROM public.alembic_version' in SQL
    assert not re.search(r'\b(?:FROM|JOIN)\s+public\.(?!alembic_version\b)', SQL, re.I)


def test_catalog_and_collision_coverage():
    for name in ('pg_attribute', 'pg_constraint', 'pg_index', 'sem_tasks_pkey',
                 'sem_tasks_id_seq', 'ix_sem_tasks_action', 'ix_sem_tasks_queue',
                 "'tenants_references'", "'version_update'", "'version_tables'"):
        assert name in SQL
    assert "SET LOCAL search_path = pg_catalog;" in SQL


def test_local_runner_is_not_unlocked_for_production():
    runner = (ROOT / 'ops/sem-task-migration/bundle.py').read_text(encoding='utf-8')
    assert 'parsed.host != "127.0.0.1"' in runner
    assert 'parsed.database != "sem_tasks_migration_test"' in runner
    assert 'choices=["build", "verify", "plan", "local-upgrade"]' in runner
