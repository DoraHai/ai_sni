import asyncio
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.sql.dml import Insert

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "test-secret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00+00:00")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.seo_demo_fixture_loader import (
    REQUIRED_REVISION,
    TABLE_ORDER,
    SeoFixtureBundle,
    SeoFixtureError,
    _verify_app_readonly,
    load_fixture_transaction,
    manifest_digest,
    run_fixture_load,
    validate_target_url,
)


def minimum_rows():
    timestamp = "2026-09-09T00:00:00+00:00"
    return {
        "tenants": [{"id": 901, "name": "Tiger demo", "created_at": timestamp}],
        "tenant_modules": [{
            "id": 902, "tenant_id": 901, "module_code": "seo", "status": "active",
            "opened_at": timestamp, "created_at": timestamp, "updated_at": timestamp,
        }],
        "seo_sites": [{
            "id": 903, "tenant_id": 901, "tenant_module_id": 902,
            "name": "Tiger", "domain": "tiger.example", "canonical_domain": "tiger.example",
            "status": "active", "created_at": timestamp, "updated_at": timestamp,
            "site_settings": {
                "fixture_marker": "seo-tiger-demo", "dataset_version": "tiger-20260909-v1",
                "synthetic": True, "scheduler_excluded": True,
                "external_actions_disabled": True,
            },
        }],
    }


def write_bundle(root: Path, *, rows=None, mutate_manifest=None):
    rows = rows or minimum_rows()
    tables = {}
    for table, values in rows.items():
        path = f"tables/{table}.jsonl"
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = b"".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True).encode() + b"\n"
            for row in values
        )
        target.write_bytes(payload)
        tables[table] = {
            "path": path,
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "row_count": len(values),
        }
    manifest = {
        "schema_version": 1,
        "module": "seo",
        "target_revision": REQUIRED_REVISION,
        "target_database": "gsnipers_demo",
        "dataset_key": "seo-tiger-demo",
        "dataset_version": "tiger-20260909-v1",
        "demo_tenant_id": 901,
        "generated_at": "2026-09-09T00:00:00+00:00",
        "loader_version": "test-v1",
        "app_readonly_role": "seo_demo_reader",
        "sites": [{"site_id": 903, "canonical_domain": "tiger.example"}],
        "sources": [{"url": "https://tiger.example/", "collected_at": "2026-09-09T00:00:00+00:00", "content_sha256": "0" * 64}],
        "tables": tables,
        "bundle_sha256": "0" * 64,
    }
    if mutate_manifest:
        mutate_manifest(manifest)
    manifest["bundle_sha256"] = manifest_digest(manifest)
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def test_minimum_bundle_is_offline_valid(tmp_path):
    manifest = write_bundle(tmp_path)
    bundle = SeoFixtureBundle.open(tmp_path)
    assert bundle.digest == manifest["bundle_sha256"]
    assert bundle.demo_tenant_id == 901
    assert set(bundle.rows) == {"tenants", "tenant_modules", "seo_sites"}


def test_rejects_sem_prod_and_non_0098(tmp_path):
    write_bundle(tmp_path, mutate_manifest=lambda value: value.update(target_database="sem_prod"))
    with pytest.raises(SeoFixtureError, match="gsnipers_demo"):
        SeoFixtureBundle.open(tmp_path)
    write_bundle(tmp_path, mutate_manifest=lambda value: value.update(target_revision="0097_demo_tenant_bindings"))
    with pytest.raises(SeoFixtureError, match="0098"):
        SeoFixtureBundle.open(tmp_path)


def test_target_url_rejects_sem_prod_or_unapproved_host(tmp_path):
    write_bundle(tmp_path)
    bundle = SeoFixtureBundle.open(tmp_path)
    with pytest.raises(SeoFixtureError, match="target"):
        validate_target_url("postgresql+asyncpg://u:p@demo-db/sem_prod", bundle, {"demo-db"})
    with pytest.raises(SeoFixtureError, match="host"):
        validate_target_url("postgresql+asyncpg://u:p@primary-db/gsnipers_demo", bundle, {"demo-db"})


def test_hash_path_and_undeclared_file_are_rejected(tmp_path):
    write_bundle(tmp_path)
    (tmp_path / "tables/tenants.jsonl").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(SeoFixtureError, match="hash or size"):
        SeoFixtureBundle.open(tmp_path)


def test_duplicate_json_key_is_rejected(tmp_path):
    write_bundle(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    raw = manifest_path.read_text(encoding="utf-8")
    manifest_path.write_text(raw.replace('{"schema_version": 1,', '{"schema_version": 1, "schema_version": 1,'), encoding="utf-8")
    with pytest.raises(SeoFixtureError, match="duplicate JSON key"):
        SeoFixtureBundle.open(tmp_path)
    write_bundle(tmp_path, mutate_manifest=lambda value: value["tables"]["tenants"].update(path="../tenants.jsonl"))
    with pytest.raises(SeoFixtureError, match="escapes"):
        SeoFixtureBundle.open(tmp_path)
    write_bundle(tmp_path, mutate_manifest=lambda value: value["tables"]["tenants"].update(path="tables//tenants.jsonl"))
    with pytest.raises(SeoFixtureError, match="escapes"):
        SeoFixtureBundle.open(tmp_path)
    write_bundle(tmp_path)
    (tmp_path / "extra.txt").write_text("extra", encoding="utf-8")
    with pytest.raises(SeoFixtureError, match="undeclared"):
        SeoFixtureBundle.open(tmp_path)


def test_symlink_is_rejected(tmp_path):
    write_bundle(tmp_path)
    original = tmp_path / "tables/tenants.jsonl"
    payload = original.read_bytes()
    original.unlink()
    target = tmp_path / "tables/tenant-target.jsonl"
    target.write_bytes(payload)
    try:
        original.symlink_to(target)
    except OSError as exc:
        pytest.fail(f"test environment cannot create required symlink fixture: {exc}")
    with pytest.raises(SeoFixtureError, match="regular file|symlink"):
        SeoFixtureBundle.open(tmp_path)


def test_non_seo_table_cross_tenant_runnable_state_and_credentials_are_rejected(tmp_path):
    cases = []
    rows = minimum_rows(); rows["sem_tasks"] = []
    cases.append((rows, "allowlist"))
    rows = minimum_rows(); rows["seo_sites"][0]["tenant_id"] = 902
    cases.append((rows, "tenant boundary"))
    rows = minimum_rows(); rows["seo_sites"][0]["id"] = 904
    cases.append((rows, "sites do not match"))
    rows = minimum_rows(); rows["seo_tasks"] = [{"id": 1, "tenant_id": 901, "site_id": 903, "module": "seo", "status": "in_progress"}]
    cases.append((rows, "runnable"))
    rows = minimum_rows(); rows["seo_distribution_connections"] = [{"id": 1, "tenant_id": 901, "credentials_encrypted": "cipher", "has_credentials": True, "enabled": True, "status": "active"}]
    cases.append((rows, "credential"))
    for index, (candidate, message) in enumerate(cases):
        root = tmp_path / str(index); root.mkdir()
        write_bundle(root, rows=candidate)
        with pytest.raises(SeoFixtureError, match=message):
            SeoFixtureBundle.open(root)


class Result:
    def __init__(self, value):
        self.value = value

    def one(self):
        return self.value

    def scalar_one(self):
        return self.value

    def scalars(self):
        return iter(self.value)


class FakeConnection:
    def __init__(self, *, revisions=None, initial=None, unsafe_table=None, unsafe_schema=False, writable_sequences=0, fail_insert=None, lock=True):
        self.revisions = revisions or [REQUIRED_REVISION]
        self.counts = {table: 0 for table in (*TABLE_ORDER, "demo_tenant_bindings", "demo_tenant_binding_history")}
        self.counts.update(initial or {})
        self.unsafe_table = unsafe_table
        self.unsafe_schema = unsafe_schema
        self.writable_sequences = writable_sequences
        self.fail_insert = fail_insert
        self.lock = lock
        self.inserted = []

    async def execute(self, statement, parameters=None):
        sql = str(statement)
        if isinstance(statement, Insert):
            if statement.table.name == self.fail_insert:
                raise RuntimeError("injected insert failure")
            values = parameters if isinstance(parameters, list) else [parameters]
            self.counts[statement.table.name] += len(values)
            self.inserted.append(statement.table.name)
            return Result(None)
        if "current_database()" in sql and "transaction_isolation" in sql:
            return Result(("gsnipers_demo", "192.0.2.10", "seo_fixture_loader", "serializable", False, False, False, False, False))
        if "FROM alembic_version" in sql:
            return Result(self.revisions)
        if "pg_try_advisory_xact_lock" in sql:
            return Result(self.lock)
        if "SELECT count(*) FROM public." in sql:
            table = sql.split("public.", 1)[1].strip().split()[0]
            return Result(self.counts[table])
        if "count(*)=1" in sql and "FROM pg_roles" in sql:
            return Result((True, False, False, False, False, False, True))
        if "has_table_privilege" in sql:
            if self.unsafe_table and f"public.{self.unsafe_table}" in sql:
                return Result((True, True, False, False, False))
            return Result((True, False, False, False, False))
        if "has_schema_privilege" in sql:
            return Result((True, self.unsafe_schema, False, False))
        if "has_sequence_privilege" in sql:
            return Result(self.writable_sequences)
        raise AssertionError(sql)


def test_nonempty_target_and_repeat_load_are_rejected(tmp_path):
    write_bundle(tmp_path)
    bundle = SeoFixtureBundle.open(tmp_path)
    connection = FakeConnection(initial={"seo_sites": 1})
    with pytest.raises(SeoFixtureError, match="not empty"):
        asyncio.run(load_fixture_transaction(connection, bundle, expected_server_addresses={"192.0.2.10"}))


def test_second_load_is_rejected_after_one_success(tmp_path):
    write_bundle(tmp_path)
    bundle = SeoFixtureBundle.open(tmp_path)
    connection = FakeConnection()
    asyncio.run(load_fixture_transaction(connection, bundle, expected_server_addresses={"192.0.2.10"}))
    with pytest.raises(SeoFixtureError, match="not empty"):
        asyncio.run(load_fixture_transaction(connection, bundle, expected_server_addresses={"192.0.2.10"}))


def test_database_revision_must_be_exact_0098(tmp_path):
    write_bundle(tmp_path)
    bundle = SeoFixtureBundle.open(tmp_path)
    with pytest.raises(SeoFixtureError, match="0098"):
        asyncio.run(load_fixture_transaction(FakeConnection(revisions=["0097_demo_tenant_bindings"]), bundle, expected_server_addresses={"192.0.2.10"}))


def test_concurrent_dataset_loader_is_rejected(tmp_path):
    write_bundle(tmp_path)
    bundle = SeoFixtureBundle.open(tmp_path)
    with pytest.raises(SeoFixtureError, match="advisory lock"):
        asyncio.run(load_fixture_transaction(FakeConnection(lock=False), bundle, expected_server_addresses={"192.0.2.10"}))


def test_app_role_contract_rejects_write_privilege():
    with pytest.raises(SeoFixtureError, match="privileges"):
        asyncio.run(_verify_app_readonly(FakeConnection(unsafe_table="seo_sites"), "seo_demo_reader"))
    with pytest.raises(SeoFixtureError, match="schema"):
        asyncio.run(_verify_app_readonly(FakeConnection(unsafe_schema=True), "seo_demo_reader"))
    with pytest.raises(SeoFixtureError, match="sequence"):
        asyncio.run(_verify_app_readonly(FakeConnection(writable_sequences=1), "seo_demo_reader"))


def test_successful_single_load_returns_manifest_bound_receipt(tmp_path):
    write_bundle(tmp_path)
    bundle = SeoFixtureBundle.open(tmp_path)
    connection = FakeConnection()
    receipt = asyncio.run(load_fixture_transaction(connection, bundle, expected_server_addresses={"192.0.2.10"}))
    assert receipt["manifest_sha256"] == bundle.digest
    assert receipt["row_counts"] == {"tenants": 1, "tenant_modules": 1, "seo_sites": 1}
    assert connection.inserted == ["tenants", "tenant_modules", "seo_sites"]


class BeginContext:
    def __init__(self, connection):
        self.connection = connection
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, *_args):
        self.rolled_back = exc_type is not None
        self.committed = exc_type is None


class FakeEngine:
    def __init__(self, connection):
        self.context = BeginContext(connection)

    def begin(self):
        return self.context


def test_any_failure_rolls_back_and_emits_no_receipt(tmp_path, monkeypatch):
    write_bundle(tmp_path)
    bundle = SeoFixtureBundle.open(tmp_path)
    engine = FakeEngine(SimpleNamespace())

    async def fail(*_args, **_kwargs):
        raise SeoFixtureError("injected failure")

    monkeypatch.setattr("app.seo_demo_fixture_loader.load_fixture_transaction", fail)
    with pytest.raises(SeoFixtureError, match="injected"):
        asyncio.run(run_fixture_load(
            "postgresql+asyncpg://u:p@demo-db/gsnipers_demo", bundle,
            allowed_hosts={"demo-db"}, expected_server_addresses={"192.0.2.10"}, engine=engine,
        ))
    assert engine.context.rolled_back is True
    assert engine.context.committed is False


def test_insert_failure_rolls_back_the_actual_transaction(tmp_path):
    write_bundle(tmp_path)
    bundle = SeoFixtureBundle.open(tmp_path)
    engine = FakeEngine(FakeConnection(fail_insert="tenant_modules"))
    with pytest.raises(RuntimeError, match="insert failure"):
        asyncio.run(run_fixture_load(
            "postgresql+asyncpg://u:p@demo-db/gsnipers_demo", bundle,
            allowed_hosts={"demo-db"}, expected_server_addresses={"192.0.2.10"}, engine=engine,
        ))
    assert engine.context.rolled_back is True
    assert engine.context.committed is False


def test_cli_writes_new_receipt_atomically_and_refuses_overwrite(tmp_path, monkeypatch):
    import scripts.load_seo_demo_fixture as command

    bundle_root = tmp_path / "bundle"; bundle_root.mkdir()
    write_bundle(bundle_root)
    receipt = tmp_path / "receipt.json"
    expected = {"result": "committed", "manifest_sha256": "a" * 64}

    async def succeed(*_args, **_kwargs):
        return expected

    monkeypatch.setattr(command, "run_fixture_load", succeed)
    monkeypatch.setenv("SEO_FIXTURE_DATABASE_URL", "postgresql+asyncpg://u:p@demo-db/gsnipers_demo")
    monkeypatch.setattr("sys.argv", [
        "load_seo_demo_fixture.py", str(bundle_root), "--allow-host", "demo-db",
        "--allow-server-address", "192.0.2.10", "--receipt", str(receipt),
    ])
    assert command.main() == 0
    assert json.loads(receipt.read_text(encoding="utf-8")) == expected
    with pytest.raises(SystemExit):
        command.main()
