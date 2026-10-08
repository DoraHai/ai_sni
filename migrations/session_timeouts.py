"""Optional per-invocation asyncpg timeouts; no settings files or connections."""
import logging
import re
from collections.abc import Mapping

from sqlalchemy import text

NAMES = {"lock_timeout": ("ALEMBIC_LOCK_TIMEOUT_MS", 10000),
         "statement_timeout": ("ALEMBIC_STATEMENT_TIMEOUT_MS", 300000)}
logger = logging.getLogger("alembic.runtime.migration")


def session_timeouts(environ: Mapping[str, str]) -> dict[str, str] | None:
    present = [name in environ for name, _ in NAMES.values()]
    if not any(present):
        return None  # Preserve the existing driver/server defaults exactly.
    if not all(present):
        raise ValueError("Set both ALEMBIC_LOCK_TIMEOUT_MS and ALEMBIC_STATEMENT_TIMEOUT_MS")
    result = {}
    for setting, (name, maximum) in NAMES.items():
        value = environ[name].strip()
        if not re.fullmatch(r"[0-9]{1,6}", value) or not 1 <= int(value) <= maximum:
            raise ValueError(f"{name} must be an integer in 1..{maximum} milliseconds")
        result[setting] = f"{int(value)}ms"
    return result


def verify_session_timeouts(connection, expected: dict[str, str]) -> None:
    """Called inside Alembic's transaction, before run_migrations can issue DDL."""
    found = {row["name"]: (row["setting"], row["unit"]) for row in connection.execute(text(
        "SELECT name, setting, unit FROM pg_catalog.pg_settings "
        "WHERE name IN ('lock_timeout', 'statement_timeout')"
    )).mappings()}
    wanted = {name: (value.removesuffix("ms"), "ms") for name, value in expected.items()}
    if found != wanted:
        raise RuntimeError("Alembic migration session timeout verification failed; DDL not started")
    logger.info("Migration session verified: lock_timeout_ms=%s statement_timeout_ms=%s",
                found["lock_timeout"][0], found["statement_timeout"][0])
