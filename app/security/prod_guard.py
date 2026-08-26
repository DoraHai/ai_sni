"""Production secret / config guards for productization must-do.

When APP_ENV is prod/production, refuse known demo defaults so a mis-copied
``.env`` cannot go live with repository keys.
"""

from __future__ import annotations

import base64
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)

# Never allow these as ADMIN_API_KEY / JWT in production.
DEMO_API_KEYS = frozenset(
    {
        "",
        "CHANGE_ME",
        "geo-demo-local-key",
        "dev",
        "test",
        "secret",
        "admin",
    }
)


def is_production_env(app_env: str | None) -> bool:
    return str(app_env or "").strip().lower() in {"prod", "production"}


def _looks_like_placeholder(value: str | None) -> bool:
    v = (value or "").strip()
    if not v:
        return True
    if v in DEMO_API_KEYS:
        return True
    if v.upper() in {"CHANGE_ME", "TODO", "REPLACE_ME"}:
        return True
    return False


def _crypto_key_issues(crypto_master_key_b64: str | None) -> list[str]:
    raw = (crypto_master_key_b64 or "").strip()
    if _looks_like_placeholder(raw):
        return ["CRYPTO_MASTER_KEY_B64 is missing or still a placeholder"]
    try:
        decoded = base64.b64decode(raw, validate=True)
    except Exception:  # noqa: BLE001
        return ["CRYPTO_MASTER_KEY_B64 is not valid base64"]
    if len(decoded) != 32:
        return [f"CRYPTO_MASTER_KEY_B64 must decode to 32 bytes (got {len(decoded)})"]
    return []


def collect_production_issues(settings: "Settings") -> list[str]:
    """Return human-readable issues; empty when ok or not production."""
    if not is_production_env(getattr(settings, "app_env", None)):
        return []

    issues: list[str] = []
    admin = (getattr(settings, "admin_api_key", None) or "").strip()
    jwt_secret = (getattr(settings, "jwt_secret", None) or "").strip()

    if _looks_like_placeholder(admin):
        issues.append("ADMIN_API_KEY is missing, placeholder, or a known demo key")
    if not jwt_secret:
        issues.append("JWT_SECRET must be set independently in production (not empty)")
    elif jwt_secret == admin:
        issues.append("JWT_SECRET must not equal ADMIN_API_KEY in production")
    elif _looks_like_placeholder(jwt_secret):
        issues.append("JWT_SECRET is a placeholder or known demo value")

    issues.extend(_crypto_key_issues(getattr(settings, "crypto_master_key_b64", None)))

    base = (getattr(settings, "app_base_url", None) or "").strip().lower()
    if "127.0.0.1" in base or "localhost" in base:
        issues.append("APP_BASE_URL still points at localhost; set public production URL")
    if bool(getattr(settings, "admin_api_key_query_enabled", False)):
        issues.append(
            "ADMIN_API_KEY_QUERY_ENABLED must be false in production; use X-API-Key header"
        )
    cors_origins = str(
        getattr(settings, "cors_allowed_origins", "https://sem.snipers.com.cn") or ""
    )
    if "*" in {item.strip() for item in cors_origins.split(",")}:
        issues.append("CORS_ALLOWED_ORIGINS must not contain * in production")

    if bool(getattr(settings, "admin_api_key_query_enabled", False)):
        issues.append(
            "ADMIN_API_KEY_QUERY_ENABLED must be false in production "
            "(API keys in URL leak via logs/Referer)"
        )
    if bool(getattr(settings, "geo_allow_self_review", False)):
        issues.append(
            "GEO_ALLOW_SELF_REVIEW is true — self-approve of content is a delivery risk"
        )

    return issues


def enforce_production_secrets(settings: "Settings", *, hard_fail: bool = True) -> list[str]:
    """Log and optionally abort startup when production secrets are unsafe."""
    issues = collect_production_issues(settings)
    if not issues:
        if is_production_env(getattr(settings, "app_env", None)):
            logger.info("[prod_guard] production secret checks passed")
        return []
    for item in issues:
        logger.critical("[prod_guard] %s", item)
    msg = "Production secret checks failed:\n- " + "\n- ".join(issues)
    if hard_fail:
        raise RuntimeError(msg)
    return issues


def nginx_injects_api_key(nginx_conf_text: str) -> bool:
    """True if conf injects X-API-Key (forbidden — bypasses RBAC)."""
    text = nginx_conf_text or ""
    # proxy_set_header X-API-Key ...
    for line in text.splitlines():
        stripped = line.strip().lower()
        if stripped.startswith("#"):
            continue
        if "proxy_set_header" in stripped and "x-api-key" in stripped:
            return True
        if "add_header" in stripped and "x-api-key" in stripped:
            return True
    return False
