"""Actual Alembic rehearsal, opt-in dedicated loopback DB only. No production."""
import asyncio
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).parents[1]
RUNNER = ROOT / "ops/sem-task-migration/bundle.py"
spec = importlib.util.spec_from_file_location("sem_bundle_review", RUNNER)
bundle_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle_module)


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    # Actual Alembic loading/execution is explicitly opt-in, not an addition to
    # ordinary shallow-checkout CI or application deployment jobs.
    url = os.environ.get("SEM_TASK_MIGRATION_TEST_DATABASE_URL")
    if not url:
        pytest.skip("local Alembic rehearsal not explicitly enabled")
    bundle_module.validate_local_url(url, "sem_migration_test_" + "a" * 32)
    path = tmp_path_factory.mktemp("sem-migration") / "bundle"
    result = subprocess.run([sys.executable, "-I", "-B", str(RUNNER), "build", str(path)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return path


def test_source_bundle_and_real_alembic_graph(bundle):
    manifest = bundle_module.verify(bundle)
    assert manifest["source_commit"] == "4e83611aabc8c3d9bb6ecee1a6aff37a2fbfbe21"
    assert len(manifest["files"]) == 118
    result = subprocess.run([sys.executable, "-I", "-B", str(RUNNER), "plan", str(bundle)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "0094_seo_qa_batches -> 0095_sem_tasks (one revision" in result.stdout


def test_bundle_tamper_and_extra_file_refused(bundle):
    path = bundle / "migrations/versions/20260906_0095_sem_tasks.py"
    original = path.read_bytes()
    try:
        path.write_bytes(original + b"\n# tampered\n")
        with pytest.raises(ValueError, match="content mismatch"):
            bundle_module.verify(bundle)
    finally:
        path.write_bytes(original)
    extra = bundle / "unexpected.py"
    try:
        extra.write_text("raise RuntimeError('must not execute')")
        with pytest.raises(ValueError, match="Unexpected"):
            bundle_module.verify(bundle)
    finally:
        extra.unlink()


@pytest.mark.parametrize("url", [
    "postgresql+asyncpg://test@db.example/sem_tasks_migration_test",
    "postgresql+asyncpg://test@127.0.0.1:55449/sem_prod",
    "postgresql+asyncpg://test@127.0.0.1:55449/sem_tasks_migration_test?host=db.example",
    "postgresql://test@127.0.0.1:55449/sem_tasks_migration_test",
])
def test_nonlocal_or_alternate_connection_refused(url):
    with pytest.raises(ValueError):
        bundle_module.validate_local_url(url, "sem_migration_test_" + "a" * 32)


@pytest.mark.parametrize("scenario", ["success", "after_create_failure", "existing_table",
    "existing_sequence", "existing_index", "wrong_revision", "multiple_revisions", "empty_revision", "repeat"])
def test_real_local_upgrade_and_rollback(bundle, scenario):
    url = os.environ.get("SEM_TASK_MIGRATION_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires explicit dedicated local migration test database")
    schema = "sem_migration_test_" + uuid.uuid4().hex
    parsed = bundle_module.validate_local_url(url, schema)

    async def run():
        engine = create_async_engine(parsed, poolclass=NullPool, hide_parameters=True)
        created = False
        try:
            async with engine.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
                created = True
                await conn.execute(text("SELECT set_config('search_path', :s, true)"), {"s": schema})
                # Explicit local baseline fixture, not production history replay,
                # not an Alembic stamp and not full SEO schema reconstruction.
                await conn.execute(text("CREATE TABLE tenants(id BIGINT PRIMARY KEY, name TEXT NOT NULL)"))
                await conn.execute(text("INSERT INTO tenants VALUES (9007199254740993, 'preserve customer')"))
                await conn.execute(text("CREATE TABLE seo_sentinel(id BIGINT PRIMARY KEY, evidence TEXT NOT NULL)"))
                await conn.execute(text("INSERT INTO seo_sentinel VALUES (1, 'preserve SEO evidence')"))
                await conn.execute(text("CREATE TABLE alembic_version(version_num VARCHAR(32) PRIMARY KEY)"))
                if scenario != "empty_revision":
                    revision = "0093_seo_qa" if scenario == "wrong_revision" else "0094_seo_qa_batches"
                    await conn.execute(text("INSERT INTO alembic_version VALUES (:r)"), {"r": revision})
                if scenario == "multiple_revisions":
                    await conn.execute(text("INSERT INTO alembic_version VALUES ('unexpected_branch')"))
                if scenario == "existing_table":
                    await conn.execute(text("CREATE TABLE sem_tasks (marker TEXT)"))
                if scenario == "existing_sequence":
                    await conn.execute(text("CREATE SEQUENCE sem_tasks_id_seq"))
                if scenario == "existing_index":
                    await conn.execute(text("CREATE INDEX ix_sem_tasks_queue ON seo_sentinel(id)"))

            env = dict(os.environ, SEM_TASK_MIGRATION_TEST_DATABASE_URL=url)
            if scenario == "after_create_failure":
                code = ("import runpy,asyncio,os,sys; n=runpy.run_path(sys.argv[1]); "
                        "\ntry: asyncio.run(n['rehearse'](sys.argv[2], os.environ['SEM_TASK_MIGRATION_TEST_DATABASE_URL'], sys.argv[3], inject_after_create=True))"
                        "\nexcept Exception as e: print('injected-after-create' if str(e) == 'Injected failure after table creation' else type(e).__name__); sys.exit(1)")
                cmd = [sys.executable, "-I", "-B", "-c", code, str(RUNNER), str(bundle), schema]
            else:
                cmd = [sys.executable, "-I", "-B", str(RUNNER), "local-upgrade", str(bundle), "--schema", schema]
            result = await asyncio.to_thread(subprocess.run, cmd, env=env, capture_output=True, text=True)
            success = scenario in {"success", "repeat"}
            assert (result.returncode == 0) == success, result.stdout + result.stderr
            if scenario == "after_create_failure":
                assert result.stdout.strip() == "injected-after-create"
            if scenario == "repeat":
                second = await asyncio.to_thread(subprocess.run, cmd, env=env, capture_output=True, text=True)
                assert second.returncode != 0
            async with engine.begin() as conn:
                await conn.execute(text("SELECT set_config('search_path', :s, true)"), {"s": schema})
                versions = set((await conn.execute(text("SELECT version_num FROM alembic_version"))).scalars())
                expected = ({"0095_sem_tasks"} if success else {"0093_seo_qa"} if scenario == "wrong_revision"
                            else set() if scenario == "empty_revision" else {"0094_seo_qa_batches"})
                if scenario == "multiple_revisions": expected.add("unexpected_branch")
                assert versions == expected
                assert await conn.scalar(text("SELECT evidence FROM seo_sentinel WHERE id=1")) == "preserve SEO evidence"
                assert await conn.scalar(text("SELECT name FROM tenants WHERE id=9007199254740993")) == "preserve customer"
                exists = await conn.scalar(text("SELECT to_regclass(:n)"), {"n": schema + ".sem_tasks"})
                assert bool(exists) == (success or scenario == "existing_table")
                if scenario == "after_create_failure":
                    for name in ("sem_tasks_id_seq", "ix_sem_tasks_action", "ix_sem_tasks_queue"):
                        assert await conn.scalar(text("SELECT to_regclass(:n)"), {"n": schema + "." + name}) is None
                if success:
                    assert await conn.scalar(text("SELECT count(*) FROM sem_tasks")) == 0
                    assert await conn.scalar(text("SELECT count(*) FROM pg_indexes WHERE schemaname=:s AND tablename='sem_tasks'"), {"s": schema}) == 3
        finally:
            if created:
                async with engine.begin() as conn:
                    await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await engine.dispose()
    asyncio.run(run())
