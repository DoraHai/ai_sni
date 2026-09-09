"""Pure fail-closed target validation for a future demo-only loader.

There is intentionally no connection, migration, apply, seed, or cleanup code here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
from urllib.parse import parse_qs, unquote, urlsplit


DEMO_CONFIRMATION = "LOAD_GEO_DEMO_ONLY"

# Shared loader/runtime contract. app.geo_main validates these switches before
# starting the isolated demo service; a future loader must validate the same set.
REQUIRED_RUNTIME_FLAGS = {
    "GEO_DEMO_RUNTIME": "true",
    "GEO_SCHEDULER_ENABLED": "false",
    "GEO_FOLLOWUP_SCHEDULER_ENABLED": "false",
    "GEO_STALE_RECONCILIATION_ENABLED": "false",
    "GEO_STARTUP_RECOVERY_ENABLED": "false",
    "GEO_ASYNC_WORKER_ENABLED": "false",
    "GEO_PATROL_EXECUTION_ENABLED": "false",
    "GEO_MODEL_EXECUTION_ENABLED": "false",
    "GEO_CONTENT_GENERATION_ENABLED": "false",
    "GEO_PUBLISHING_ENABLED": "false",
    "GEO_OAUTH_ENABLED": "false",
    "BAIDU_WRITE_DRY_RUN": "true",
    "CHINAZ_API_ENABLED": "false",
    "SEO_RANK_SCHEDULER_ENABLED": "false",
}

EXTERNAL_CREDENTIAL_KEYS = (
    "DASHSCOPE_API_KEY",
    "DEEPSEEK_API_KEY",
    "GEO_OPENAI_API_KEY",
    "GEO_DEEPSEEK_API_KEY",
    "GEO_QWEN_API_KEY",
    "GEO_DOUBAO_API_KEY",
    "GEO_HUNYUAN_API_KEY",
    "GEO_QIANFAN_API_KEY",
    "GEO_KIMI_API_KEY",
    "GEO_PERPLEXITY_API_KEY",
    "GEO_TENCENT_WSA_API_KEY",
    "CHINAZ_API_KEY",
    "CHINAZ_BAIDU_INDEX_API_KEY",
    "CHINAZ_BAIDU_PC_KEYWORDS_API_KEY",
    "CHINAZ_BAIDU_MOBILE_KEYWORDS_API_KEY",
    "CHINAZ_BAIDU_PC_TOP50_API_KEY",
    "CHINAZ_BAIDU_MOBILE_TOP50_API_KEY",
    "CHINAZ_WEIGHT_ALL_API_KEY",
    "CHINAZ_WHOIS_API_KEY",
    "PAGESPEED_API_KEY",
)


class DemoDatabaseGuardError(ValueError):
    """Raised without echoing the database URL or credentials."""


@dataclass(frozen=True)
class DemoDatabaseTarget:
    driver: str
    hostname: str
    port: int
    database: str
    username: str


def _required(env: Mapping[str, str], key: str) -> str:
    value = str(env.get(key) or "").strip()
    if not value:
        raise DemoDatabaseGuardError(f"missing required demo setting: {key}")
    return value


def validate_demo_database_target(
    database_url: str,
    *,
    app_env: str,
    expected_hostname: str,
    expected_database: str,
    expected_username: str,
    confirmation: str,
) -> DemoDatabaseTarget:
    """Validate one exact demo PostgreSQL target and return redacted metadata."""
    errors = []
    expected_hostname = expected_hostname.strip().lower().rstrip(".")
    expected_database = expected_database.strip()
    expected_username = expected_username.strip()
    if app_env.strip().lower() != "demo":
        errors.append("APP_ENV must be demo")
    if confirmation != DEMO_CONFIRMATION:
        errors.append("demo loader confirmation mismatch")
    if "demo" not in expected_hostname:
        errors.append("expected hostname must contain demo")
    if "demo" not in expected_database.lower():
        errors.append("expected database name must contain demo")
    if "demo" not in expected_username.lower():
        errors.append("expected username must be demo-only")
    try:
        parsed = urlsplit(database_url)
        driver = parsed.scheme.lower()
        hostname = (parsed.hostname or "").lower().rstrip(".")
        database = unquote(parsed.path.lstrip("/"))
        username = unquote(parsed.username or "")
        port = parsed.port or 5432
        query = parse_qs(parsed.query, keep_blank_values=True)
    except (TypeError, ValueError):
        errors.append("DATABASE_URL is not a valid URL")
        driver, hostname, database, username, port, query = "", "", "", "", 0, {}
    if driver not in {"postgresql", "postgresql+asyncpg"}:
        errors.append("demo loader requires PostgreSQL")
    if hostname != expected_hostname:
        errors.append("database hostname does not match the approved demo host")
    if database != expected_database or not database or "/" in database:
        errors.append("database name does not match the approved demo database")
    if username != expected_username:
        errors.append("database username does not match the approved demo account")
    unexpected_query = set(query) - {"ssl", "sslmode"}
    if unexpected_query:
        errors.append("DATABASE_URL contains unsupported or target-changing query options")
    if errors:
        raise DemoDatabaseGuardError("; ".join(dict.fromkeys(errors)))
    return DemoDatabaseTarget(
        driver=driver,
        hostname=hostname,
        port=port,
        database=database,
        username=username,
    )


def validate_demo_loader_environment(env: Mapping[str, str]) -> DemoDatabaseTarget:
    """Validate the proposed loader environment without opening a connection."""
    errors = []
    for key, required_value in REQUIRED_RUNTIME_FLAGS.items():
        if str(env.get(key) or "").strip().lower() != required_value:
            errors.append(f"{key} must be {required_value}")
    populated_credentials = [key for key in EXTERNAL_CREDENTIAL_KEYS if str(env.get(key) or "").strip()]
    if populated_credentials:
        errors.append("external credentials must be empty: " + ", ".join(populated_credentials))
    if errors:
        raise DemoDatabaseGuardError("; ".join(errors))
    return validate_demo_database_target(
        _required(env, "DATABASE_URL"),
        app_env=_required(env, "APP_ENV"),
        expected_hostname=_required(env, "GEO_DEMO_DB_HOST"),
        expected_database=_required(env, "GEO_DEMO_DB_NAME"),
        expected_username=_required(env, "GEO_DEMO_DB_USER"),
        confirmation=_required(env, "GEO_DEMO_LOADER_CONFIRM"),
    )
