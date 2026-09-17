import asyncio
import hashlib
import json
import os
from pathlib import Path
import pytest
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
    "gh" + "p_abcdefghijklmnopqrstuvwxyz123456",
    "github_" + "pat_abcdefghijklmnopqrstuvwxyz123456",
    "xo" + "xb-1234567890-abcdefghijklmnop",
    "AI" + "zaSyAabcdefghijklmnopqrstuvwxyz123",
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


def test_revision_0098_unconditionally_rejects_before_database_access(tmp_path):
    write_bundle(tmp_path)
    bundle = SeoFixtureBundle.open(tmp_path)

    class MustNotExecute:
        async def execute(self, *_args, **_kwargs):
            raise AssertionError("0098 guard queried the database")

    with pytest.raises(SeoFixtureError, match="0098 cannot"):
        asyncio.run(load_fixture_transaction(
            MustNotExecute(), bundle, expected_server_addresses={"192.0.2.10"}
        ))


def test_revision_0098_unconditionally_rejects_receipt_recovery(tmp_path):
    write_bundle(tmp_path)
    bundle = SeoFixtureBundle.open(tmp_path)
    with pytest.raises(SeoFixtureError, match="0098 cannot"):
        asyncio.run(recover_committed_receipt(
            "postgresql+asyncpg://u:p@demo-db/gsnipers_demo", bundle,
            allowed_hosts={"demo-db"}, expected_server_addresses={"192.0.2.10"},
            engine=MustNotBegin(),
        ))


class MustNotBegin:
    def begin(self):
        raise AssertionError("0098 guard opened a transaction")


def test_run_fixture_load_0098_refuses_before_transaction_or_inserts(tmp_path):
    write_bundle(tmp_path)
    bundle = SeoFixtureBundle.open(tmp_path)
    with pytest.raises(SeoFixtureError, match="0098 cannot"):
        asyncio.run(run_fixture_load(
            "postgresql+asyncpg://u:p@demo-db/gsnipers_demo", bundle,
            allowed_hosts={"demo-db"}, expected_server_addresses={"192.0.2.10"}, engine=MustNotBegin(),
        ))


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
    with pytest.raises(SeoFixtureError, match="0098 cannot"):
        command.main()
    assert not receipt.exists()
