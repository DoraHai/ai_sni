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
    EMPTY_GUARD_TABLES,
    RECEIPT_REGISTRY_TABLE,
    REQUIRED_REVISION,
    TABLE_ORDER,
    SeoFixtureBundle,
    SeoFixtureError,
    _verify_app_readonly,
    _verify_loader_role,
    _verify_receipt_registry,
    load_fixture_transaction,
    manifest_digest,
    recover_committed_receipt,
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
        "text_policy": {"synthetic": True, "redacted": True, "policy_version": "seo-fixture-text-v1"},
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
    rows = minimum_rows(); rows["seo_tasks"] = [{"id": 1, "tenant_id": 901, "site_id": 903, "module": "seo", "status": "in_progress", "created_by": "fixture:synthetic"}]
    cases.append((rows, "runnable"))
    rows = minimum_rows(); rows["seo_distribution_connections"] = [{"id": 1, "tenant_id": 901, "credentials_encrypted": "cipher", "has_credentials": True, "enabled": True, "status": "active"}]
    cases.append((rows, "allowlist|credential"))
    rows = minimum_rows(); rows["seo_image_verifications"] = [{"id": 1, "tenant_id": 901, "site_id": 903, "status": "checking"}]
    cases.append((rows, "runnable"))
    rows = minimum_rows(); rows["seo_sites"][0]["site_settings"]["note"] = "Authorization: Bearer abc.def"
    cases.append((rows, "credential"))
    for index, (candidate, message) in enumerate(cases):
        root = tmp_path / str(index); root.mkdir()
        write_bundle(root, rows=candidate)
        with pytest.raises(SeoFixtureError, match=message):
            SeoFixtureBundle.open(root)


def test_scheduler_query_states_remain_covered_by_loader_guard():
    root = Path(__file__).parents[1]
    checks = {
        "seo_image_verifications": ("app/seo_image_verification.py", {"pending", "checking"}),
        "seo_qa_batches": ("app/seo_qa_batches.py", {"queued", "running"}),
        "seo_automation_runs": ("app/seo_automation_runs.py", {"queued", "running"}),
        "seo_ai_operations": ("app/seo_ai_operations.py", {"running"}),
    }
    from app.seo_demo_fixture_loader import RUNNABLE_STATES
    for table, (relative, queried_states) in checks.items():
        source = (root / relative).read_text(encoding="utf-8")
        assert table.split("seo_", 1)[1].split("_", 1)[0] in source.lower()
        assert all(f"'{state}'" in source or f'"{state}"' in source for state in queried_states)
        assert queried_states <= RUNNABLE_STATES[table]


def test_cross_site_parent_reference_is_rejected(tmp_path):
    rows = minimum_rows()
    timestamp = "2026-09-09T00:00:00+00:00"
    rows["seo_sites"].append({
        **rows["seo_sites"][0], "id": 904, "name": "Second", "domain": "second.example",
        "canonical_domain": "second.example",
    })
    rows["seo_site_pages"] = [
        {"id": 905, "tenant_id": 901, "site_id": 904, "url": "https://second.example/a", "status": "healthy", "created_at": timestamp, "updated_at": timestamp}
    ]
    rows["seo_image_alt_reviews"] = [
        {"id": 906, "tenant_id": 901, "site_id": 903, "page_id": 905, "position": 1, "source_url": "https://second.example/a.png", "review_status": "pending", "actor_id": 0, "actor_name": "Synthetic Fixture"}
    ]
    write_bundle(tmp_path, rows=rows, mutate_manifest=lambda value: value["sites"].append(
        {"site_id": 904, "canonical_domain": "second.example"}
    ))
    with pytest.raises(SeoFixtureError, match="crosses site boundaries"):
        SeoFixtureBundle.open(tmp_path)


@pytest.mark.parametrize("unsafe", [
    "person@example.com", "13800138000", "11010519491231002X",
    "姓名：张三", "联系地址：上海市静安区测试路1号", "座机：021-12345678",
    "apiKey: abcdefghijklmnop", "client_secret=abcdefghijklmnop", "oauth: ya29.abcdefghijk",
])
def test_scalar_pii_is_rejected_anywhere_in_bundle_rows(tmp_path, unsafe):
    rows = minimum_rows()
    rows["seo_sites"][0]["site_settings"]["note"] = unsafe
    write_bundle(tmp_path, rows=rows)
    with pytest.raises(SeoFixtureError, match="credential material"):
        SeoFixtureBundle.open(tmp_path)


def test_distribution_connection_config_has_exact_inert_schema(tmp_path):
    rows = minimum_rows()
    rows["seo_distribution_connections"] = [{
        "id": 907, "tenant_id": 901, "platform_code": "zhihu", "name": "demo",
        "mode": "assisted", "config": {"browser": "demo"}, "capabilities": [],
        "has_credentials": False, "enabled": False, "status": "disabled",
    }]
    write_bundle(tmp_path, rows=rows)
    with pytest.raises(SeoFixtureError, match="inert and credential-free"):
        SeoFixtureBundle.open(tmp_path)


def test_supported_not_null_actor_rows_use_auditable_synthetic_contract(tmp_path):
    rows = minimum_rows()
    timestamp = "2026-09-09T00:00:00+00:00"
    rows.update({
        "seo_ai_operations": [{
            "id": "op-1", "tenant_id": 901, "site_id": 903, "request_key": "r1",
            "request_hash": "0" * 64, "actor": "fixture:synthetic", "kind": "draft",
            "charged_on": "2026-09-09", "status": "succeeded", "expires_at": timestamp,
        }],
        "seo_qa_batches": [{
            "id": 910, "tenant_id": 901, "site_id": 903, "actor": "fixture:synthetic",
            "request_key": "q1", "request_hash": "1" * 64, "status": "done", "items": [],
        }],
        "seo_tasks": [{
            "id": 911, "tenant_id": 901, "site_id": 903, "module": "seo",
            "action_type": "review", "title": "Synthetic review", "status": "done",
            "created_by": "fixture:synthetic", "assignee_role": "reviewer",
        }],
        "seo_crawl_runs": [{"id": 912, "tenant_id": 901, "site_id": 903, "status": "completed"}],
        "seo_site_pages": [{"id": 913, "tenant_id": 901, "site_id": 903, "url": "https://tiger.example/a"}],
        "seo_page_snapshots": [{
            "id": 914, "tenant_id": 901, "site_id": 903, "crawl_run_id": 912,
            "url": "https://tiger.example/a", "fetched_at": timestamp,
        }],
        "seo_image_alt_reviews": [{
            "id": 915, "tenant_id": 901, "site_id": 903, "page_id": 913,
            "snapshot_id": 914, "position": 1, "observed_alt_state": "missing",
            "decision": "approved", "actor_id": 0, "actor_name": "Synthetic Fixture",
        }],
        "seo_page_index_reviews": [{
            "id": 916, "tenant_id": 901, "site_id": 903, "page_id": 913,
            "intent": "allow", "reason": "Synthetic fixture evidence", "evidence": {},
            "actor_id": 0, "actor_name": "Synthetic Fixture",
        }],
    })
    write_bundle(tmp_path, rows=rows)
    bundle = SeoFixtureBundle.open(tmp_path)
    assert len(bundle.rows["seo_tasks"]) == 1


def test_site_tenant_module_parent_must_be_in_bundle(tmp_path):
    rows = minimum_rows()
    rows["seo_sites"][0]["tenant_module_id"] = 999999
    write_bundle(tmp_path, rows=rows)
    with pytest.raises(SeoFixtureError, match="tenant_module_id does not reference a bundled parent"):
        SeoFixtureBundle.open(tmp_path)


class Result:
    def __init__(self, value):
        self.value = value

    def one(self):
        return self.value

    def one_or_none(self):
        return self.value

    def scalar_one(self):
        return self.value

    def scalars(self):
        return iter(self.value)

    def all(self):
        return self.value


class FakeConnection:
    def __init__(self, *, revisions=None, initial=None, unsafe_table=None, unsafe_schema=False, writable_sequences=0, fail_insert=None, lock=True, registry=True, session_role="seo_fixture_loader", loader_memberships=(0, 0), production_connect=False, trigger_rows=None):
        self.revisions = revisions or [REQUIRED_REVISION]
        self.counts = {table: 0 for table in (*EMPTY_GUARD_TABLES, RECEIPT_REGISTRY_TABLE)}
        self.counts.update(initial or {})
        self.unsafe_table = unsafe_table
        self.unsafe_schema = unsafe_schema
        self.writable_sequences = writable_sequences
        self.fail_insert = fail_insert
        self.lock = lock
        self.registry = registry
        self.session_role = session_role
        self.loader_memberships = loader_memberships
        self.production_connect = production_connect
        self.trigger_rows = trigger_rows
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
        if sql.lstrip().startswith(f"INSERT INTO public.{RECEIPT_REGISTRY_TABLE}"):
            self.counts[RECEIPT_REGISTRY_TABLE] += 1
            self.inserted.append(RECEIPT_REGISTRY_TABLE)
            return Result(None)
        if "current_database()" in sql and "transaction_isolation" in sql:
            if "rolsuper" in sql:
                return Result(("gsnipers_demo", "192.0.2.10", "seo_fixture_loader", self.session_role, "serializable", False, False, False, False, False))
            return Result(("gsnipers_demo", "192.0.2.10", "seo_fixture_loader", self.session_role, "serializable"))
        if "FROM alembic_version" in sql:
            return Result(self.revisions)
        if "pg_try_advisory_xact_lock" in sql:
            return Result(self.lock)
        if "to_regclass" in sql:
            return Result(RECEIPT_REGISTRY_TABLE if self.registry else None)
        if "information_schema.columns" in sql:
            return Result([
                "manifest_sha256", "dataset_key", "dataset_version", "demo_tenant_id",
                "target_revision", "target_database", "server_address", "loader_role",
                "loader_version", "row_counts", "committed_at",
            ])
        if "FROM information_schema.triggers" in sql:
            return Result(self.trigger_rows if self.trigger_rows is not None else [
                (event, "BEFORE", "EXECUTE FUNCTION public.reject_seo_fixture_receipt_mutation()")
                for event in ("UPDATE", "DELETE", "TRUNCATE")
            ])
        if f"FROM public.{RECEIPT_REGISTRY_TABLE} WHERE manifest_sha256" in sql:
            return Result((
                "seo-tiger-demo", "tiger-20260909-v1", 901, REQUIRED_REVISION,
                "gsnipers_demo", "192.0.2.10", "seo_fixture_loader", "test-v1",
                {"tenants": 1, "tenant_modules": 1, "seo_sites": 1},
                "2026-09-09T00:00:00+00:00",
            ))
        if "SELECT count(*) FROM public." in sql:
            table = sql.split("public.", 1)[1].strip().split()[0]
            return Result(self.counts[table])
        if "count(*)=1" in sql and "FROM pg_roles" in sql:
            return Result((True, False, False, False, False, False, True, True))
        if "SELECT (SELECT count(*) FROM pg_auth_members" in sql:
            return Result(self.loader_memberships)
        if "pg_database WHERE datname='sem_prod'" in sql:
            if self.production_connect == "error":
                raise RuntimeError("catalog lookup failed")
            return Result(self.production_connect)
        if "has_table_privilege" in sql:
            if self.unsafe_table and f"public.{self.unsafe_table}" in sql:
                return Result((True, True, False, False, False))
            role = (parameters or {}).get("role")
            if role == "seo_fixture_loader":
                table = sql.split("public.", 1)[1].split("'", 1)[0]
                return Result((True, table in TABLE_ORDER or table == RECEIPT_REGISTRY_TABLE, False, False, False))
            if f"public.{RECEIPT_REGISTRY_TABLE}" in sql:
                return Result((False, False, False, False, False))
            return Result((True, False, False, False, False))
        if "has_schema_privilege" in sql:
            return Result((True, self.unsafe_schema, True, False, False))
        if "has_sequence_privilege" in sql:
            return Result(self.writable_sequences)
        raise AssertionError(sql)


def test_revision_0098_unconditionally_rejects_before_database_access(tmp_path):
    write_bundle(tmp_path)
    bundle = SeoFixtureBundle.open(tmp_path)

    class MustNotExecute:
        async def execute(self, *_args, **_kwargs):
            raise AssertionError("0098 guard queried the database")

    with pytest.raises(SeoFixtureError, match="0098 cannot load"):
        asyncio.run(load_fixture_transaction(
            MustNotExecute(), bundle, expected_server_addresses={"192.0.2.10"}
        ))


def test_loader_role_membership_is_rejected_directly():
    with pytest.raises(SeoFixtureError, match="memberships"):
        asyncio.run(_verify_loader_role(
            FakeConnection(loader_memberships=(1, 0)), "seo_fixture_loader"
        ))


@pytest.mark.parametrize("unsafe", [True, None, "error"])
def test_demo_roles_must_prove_no_sem_prod_connect(unsafe):
    with pytest.raises((SeoFixtureError, RuntimeError), match="CONNECT|catalog"):
        asyncio.run(_verify_loader_role(
            FakeConnection(production_connect=unsafe), "seo_fixture_loader"
        ))


def test_receipt_registry_requires_exact_event_function_contract():
    asyncio.run(_verify_receipt_registry(FakeConnection()))
    wrong = [("UPDATE", "BEFORE", "EXECUTE FUNCTION public.other_function()")]
    with pytest.raises(SeoFixtureError, match="immutable triggers"):
        asyncio.run(_verify_receipt_registry(FakeConnection(trigger_rows=wrong)))


def test_app_role_contract_rejects_write_privilege():
    with pytest.raises(SeoFixtureError, match="privileges"):
        asyncio.run(_verify_app_readonly(FakeConnection(unsafe_table="seo_sites"), "seo_demo_reader"))
    with pytest.raises(SeoFixtureError, match="schema"):
        asyncio.run(_verify_app_readonly(FakeConnection(unsafe_schema=True), "seo_demo_reader"))
    with pytest.raises(SeoFixtureError, match="sequence"):
        asyncio.run(_verify_app_readonly(FakeConnection(writable_sequences=1), "seo_demo_reader"))


def test_revision_0098_unconditionally_rejects_receipt_recovery(tmp_path):
    write_bundle(tmp_path)
    bundle = SeoFixtureBundle.open(tmp_path)
    with pytest.raises(SeoFixtureError, match="0098 cannot recover"):
        asyncio.run(recover_committed_receipt(
            "postgresql+asyncpg://u:p@demo-db/gsnipers_demo", bundle,
            allowed_hosts={"demo-db"}, expected_server_addresses={"192.0.2.10"},
            engine=FakeEngine(FakeConnection()),
        ))


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


def test_run_fixture_load_0098_refuses_before_transaction_or_inserts(tmp_path):
    write_bundle(tmp_path)
    bundle = SeoFixtureBundle.open(tmp_path)
    connection = FakeConnection()
    engine = FakeEngine(connection)
    with pytest.raises(SeoFixtureError, match="0098 cannot load"):
        asyncio.run(run_fixture_load(
            "postgresql+asyncpg://u:p@demo-db/gsnipers_demo", bundle,
            allowed_hosts={"demo-db"}, expected_server_addresses={"192.0.2.10"}, engine=engine,
        ))
    assert engine.context.rolled_back is False
    assert engine.context.committed is False
    assert connection.inserted == []


def test_cli_0098_refuses_without_writing_receipt(tmp_path, monkeypatch):
    import scripts.load_seo_demo_fixture as command

    bundle_root = tmp_path / "bundle"; bundle_root.mkdir()
    write_bundle(bundle_root)
    receipt = tmp_path / "receipt.json"
    monkeypatch.setenv("SEO_FIXTURE_DATABASE_URL", "postgresql+asyncpg://u:p@demo-db/gsnipers_demo")
    monkeypatch.setattr("sys.argv", [
        "load_seo_demo_fixture.py", str(bundle_root), "--allow-host", "demo-db",
        "--allow-server-address", "192.0.2.10", "--receipt", str(receipt),
    ])
    with pytest.raises(SeoFixtureError, match="0098 cannot load"):
        command.main()
    assert not receipt.exists()
