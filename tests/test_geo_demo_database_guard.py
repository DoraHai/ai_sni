from copy import deepcopy

import pytest

from app.geo.demo_database_guard import (
    DEMO_CONFIRMATION,
    DemoDatabaseGuardError,
    REQUIRED_RUNTIME_FLAGS,
    validate_demo_database_target,
    validate_demo_loader_environment,
)


def valid_env():
    return {
        **REQUIRED_RUNTIME_FLAGS,
        "APP_ENV": "demo",
        "DATABASE_URL": "postgresql+asyncpg://gsnipers_demo_loader:secret@geo-demo-db.internal:5432/gsnipers_demo?sslmode=require",
        "GEO_DEMO_DB_HOST": "geo-demo-db.internal",
        "GEO_DEMO_DB_NAME": "gsnipers_demo",
        "GEO_DEMO_DB_USER": "gsnipers_demo_loader",
        "GEO_DEMO_LOADER_CONFIRM": DEMO_CONFIRMATION,
    }


def test_exact_demo_target_is_accepted_without_exposing_password():
    target = validate_demo_loader_environment(valid_env())
    assert target.hostname == "geo-demo-db.internal"
    assert target.database == "gsnipers_demo"
    assert target.username == "gsnipers_demo_loader"
    assert not hasattr(target, "password")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("APP_ENV", "production", "APP_ENV must be demo"),
        ("GEO_DEMO_LOADER_CONFIRM", "yes", "confirmation mismatch"),
        ("GEO_DEMO_DB_HOST", "primary-db.internal", "hostname must contain demo"),
        ("GEO_DEMO_DB_NAME", "production", "database name must contain demo"),
        ("GEO_DEMO_DB_USER", "platform", "username must be demo-only"),
        ("GEO_SCHEDULER_ENABLED", "true", "must be false"),
        ("GEO_PUBLISHING_ENABLED", "true", "must be false"),
        ("GEO_OPENAI_API_KEY", "live-key", "external credentials must be empty"),
    ],
)
def test_environment_mismatch_fails_closed(field, value, message):
    env = valid_env()
    env[field] = value
    with pytest.raises(DemoDatabaseGuardError, match=message):
        validate_demo_loader_environment(env)


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+asyncpg://gsnipers_demo_loader:secret@production-db.internal/gsnipers_demo",
        "postgresql+asyncpg://gsnipers_demo_loader:secret@geo-demo-db.internal/production",
        "postgresql+asyncpg://platform:secret@geo-demo-db.internal/gsnipers_demo",
        "sqlite:///gsnipers_demo.db",
        "postgresql+asyncpg://gsnipers_demo_loader:secret@geo-demo-db.internal/gsnipers_demo?host=production-db",
    ],
)
def test_url_mismatch_and_target_override_fail_closed(database_url):
    env = valid_env()
    env["DATABASE_URL"] = database_url
    with pytest.raises(DemoDatabaseGuardError):
        validate_demo_loader_environment(env)


def test_missing_disable_flag_fails_closed():
    env = deepcopy(valid_env())
    del env["GEO_ASYNC_WORKER_ENABLED"]
    with pytest.raises(DemoDatabaseGuardError, match="GEO_ASYNC_WORKER_ENABLED must be false"):
        validate_demo_loader_environment(env)


def test_guard_module_has_no_apply_side_effect():
    env = valid_env()
    before = deepcopy(env)
    validate_demo_database_target(
        env["DATABASE_URL"],
        app_env=env["APP_ENV"],
        expected_hostname=env["GEO_DEMO_DB_HOST"],
        expected_database=env["GEO_DEMO_DB_NAME"],
        expected_username=env["GEO_DEMO_DB_USER"],
        confirmation=env["GEO_DEMO_LOADER_CONFIRM"],
    )
    assert env == before
