"""Offline safety checks; no DB credential file or database is accessed."""
import importlib.util
import asyncio
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

spec = importlib.util.spec_from_file_location("local_acceptance", Path(__file__).parents[1] / "scripts/seo_local_acceptance.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def fields():
    return dict(PGHOST="127.0.0.1", PGPORT="55432", PGDATABASE="seo_workflow_test", PGUSER="seo_workflow_tester", PGPASSWORD="fake-test-only")


@pytest.mark.parametrize("key,value", [("PGHOST", "localhost"), ("PGPORT", "5432"),
    ("PGDATABASE", "production"), ("PGUSER", "postgres"), ("PGPASSWORD", "")])
def test_target_requires_exact_dedicated_instance_and_ordinary_role(key, value):
    config = fields()
    config[key] = value
    with pytest.raises(ValueError): runner.validate_target(config)


def test_application_url_is_never_a_fallback():
    with pytest.raises(ValueError): runner.validate_target({"DATABASE_URL": "postgresql://bad"})
    assert runner.validate_target(fields()).database == "seo_workflow_test"


@pytest.mark.parametrize("method,path", [("POST", "/api/v1/seo/content-ai/assist"),
    ("POST", "/api/v1/seo/site/crawl"), ("POST", "/api/v1/seo/content-distribution/publications"),
    ("POST", "/api/v1/auth/tenants"), ("POST", "/api/v1/seo/content-distribution/publications/1/retry"),
    ("DELETE", "/api/v1/seo/sites/1")])
def test_external_and_unreviewed_mutations_are_disabled(method, path):
    assert not runner.allowed_request(method, path)


@pytest.mark.parametrize("method,path", [("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/seo/workbench/content-assets/1/confirmations"),
    ("PUT", "/api/v1/seo/workbench/service-plan"), ("GET", "/api/v1/seo/workbench/executions")])
def test_local_business_actions_can_reach_real_auth_dependencies(method, path):
    assert runner.allowed_request(method, path)


@pytest.mark.parametrize("method,path", [
    ("POST", "/api/v1/seo/qa/facts"),
    ("POST", "/api/v1/seo/keywords"),
    ("PATCH", "/api/v1/seo/qa/facts/1"),
    ("PATCH", "/api/v1/seo/keywords/1"),
])
def test_ui13_maintenance_reaches_real_auth(method, path):
    assert runner.allowed_request(method, path)


@pytest.mark.parametrize("method,path", [
    ("POST", "/api/v1/seo/keywords/1"), ("POST", "/api/v1/seo/keywords/import"),
    ("POST", "/api/v1/seo/qa/facts/import"), ("POST", "/api/v1/seo/qa/research/file-preview"),
    ("POST", "/api/v1/seo/qa/facts/1"), ("PATCH", "/api/v1/seo/qa/facts"),
    ("DELETE", "/api/v1/seo/qa/facts/1"), ("PATCH", "/api/v1/seo/keywords/1/writeback"),
    ("PATCH", "/api/v1/seo/qa/facts/0"), ("PATCH", "/api/v1/seo/qa/facts/-1"),
    ("PATCH", "/api/v1/seo/keywords/1/extra"),
])
def test_ui13_does_not_expand_to_import_delete_or_adjacent_actions(method, path):
    assert not runner.allowed_request(method, path)


def test_outbound_guard_only_allows_the_database_not_other_local_services():
    runner.network_audit("socket.connect", (None, ("127.0.0.1", 55432)))
    for address in (("127.0.0.1", 8029), ("8.8.8.8", 443), ("::1", 55432)):
        with pytest.raises(PermissionError): runner.network_audit("socket.connect", (None, address))
    with pytest.raises(PermissionError): runner.network_audit("subprocess.Popen", ())
    with pytest.raises(PermissionError): runner.network_audit("socket.getaddrinfo", ("api.deepseek.com",))


def test_config_ignores_inherited_provider_and_database_secrets(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "STATE_DIR", tmp_path)
    (tmp_path / "identities.json").write_text(json.dumps({"jwt_secret": "isolated-signing-key",
        "crypto_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="}), encoding="utf-8")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "must-not-use")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "must-not-use")
    monkeypatch.setenv("DATABASE_URL", "must-not-use")
    from app import config
    original = config.get_settings
    try:
        settings = runner.configure(runner.validate_target(fields()))
        assert settings.deepseek_api_key == settings.dashscope_api_key == ""
        assert not settings.seo_scheduler_enabled and not settings.seo_external_actions_enabled
        assert settings.admin_api_key == "" and not settings.admin_api_key_query_enabled
        assert settings.seo_page_capture_storage_dir == str(tmp_path / "ui14-media")
        assert "must-not-use" not in settings.database_url
    finally:
        config.get_settings = original


def test_cleanup_plan_does_not_drop_database_schema_extensions_or_cascade():
    objects = {"foreign_keys": [{"table_name": "child", "name": "fk_child"}],
        "relations": [{"name": "child", "kind": "r"}, {"name": "child_id_seq", "kind": "S"}],
        "functions": [], "types": []}
    sql = runner.cleanup_sql(objects)
    statements = [line for line in sql.splitlines() if not line.startswith("--")]
    assert all("CASCADE" not in line and "DROP SCHEMA" not in line and "DROP DATABASE" not in line for line in statements)
    assert sql.index("DROP CONSTRAINT") < sql.index("DROP TABLE")
    assert "RESTRICT" in sql and "current_database()" in sql


def test_real_alembic_graph_has_expected_head_without_running_env():
    assert runner.graph() == {"head": runner.MESSAGE_HEAD, "parent": runner.HEAD, "revisions": 123}


@pytest.mark.parametrize("method,suffix,allowed", [
    ("POST", "messages", True), ("POST", "read", True),
    ("DELETE", "messages", False), ("PATCH", "messages/1", False),
    ("POST", "messages/1", False), ("POST", "publish", False),
])
def test_ui15_write_allowlist_is_narrow(method, suffix, allowed):
    assert runner.allowed_request(method, "/api/v1/seo/workbench/content-assets/64/conversation/" + suffix) is allowed


def test_ui14_fixture_plan_is_bounded_and_has_confirmation_cases_on_every_page(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "scripts"))
    import seo_local_ui14_seed as seed
    plan = seed.plans()
    assert len(plan["contents"]) == 60
    assert len(plan["tasks"]) == len(plan["keywords"]) == 45
    assert "done" not in {item["status"] for item in plan["tasks"]}
    for offset in (0, 20, 40):
        assert {"pending", "approved", "rejected", "stale"} <= {
            item["kind"] for item in plan["contents"][offset:offset + 20]}


def test_ui14_tasks_cannot_be_advanced_but_existing_workflow_is_not_blocked():
    path = "/api/v1/seo/workbench/content-workflows/5/advance"
    assert runner.fixture_execution_blocked("POST", path, {5, 6})
    assert not runner.fixture_execution_blocked("GET", path, {5, 6})
    assert not runner.fixture_execution_blocked("POST", path, {6})
    assert not runner.fixture_execution_blocked("POST", "/api/v1/seo/workbench/content-workflows/1/advance", {5, 6})


@pytest.mark.parametrize("permitted,expired,expected", [(True, False, True), (False, False, False), (True, True, False)])
def test_local_catalog_requires_both_real_role_permissions_and_module_availability(tmp_path, monkeypatch, permitted, expired, expected):
    monkeypatch.setattr(runner, "STATE_DIR", tmp_path)
    (tmp_path / "identities.json").write_text(json.dumps({"jwt_secret": "isolated-signing-key",
        "crypto_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="}), encoding="utf-8")
    from app import config
    original = config.get_settings
    try:
        runner.configure(runner.validate_target(fields()))
        monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "scripts"))
        import seo_local_auth
        from app.security.auth import AuthContext
        ctx = AuthContext(1, "isolated", "customer", 1, {"seo.content": "view"} if permitted else {})
        row = SimpleNamespace(module_code="seo", status="active", expires_at=date.today()-timedelta(days=1) if expired else None)
        session = SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [row])))
        response = asyncio.run(seo_local_auth.modules(ctx, session))
        assert response["tenant_id"] == 1
        assert next(item for item in response["modules"] if item["module_code"] == "seo")["available"] is expected
        assert not next(item for item in response["modules"] if item["module_code"] == "sem")["available"]
    finally:
        config.get_settings = original
