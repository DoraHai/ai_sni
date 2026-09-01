"""Production secret / config guards for productization must-do.

When APP_ENV is prod/production, refuse known demo defaults so a mis-copied
``.env`` cannot go live with repository keys.
"""

from __future__ import annotations

import base64
import logging
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from app.config import parse_positive_id_csv

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)

CANONICAL_APP_HOST = "gsnipers.snipers.com.cn"
LEGACY_APP_HOST = "sem.snipers.com.cn"

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


def _public_https_origin_issue(
    label: str,
    value: str | None,
    *,
    allowed_hosts: set[str],
) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return f"{label} must be set to an approved public HTTPS origin"
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        return f"{label} is not a valid URL"
    if parsed.scheme.lower() != "https":
        return f"{label} must use HTTPS"
    if parsed.username or parsed.password:
        return f"{label} must not contain URL credentials"
    host = (parsed.hostname or "").lower().rstrip(".")
    if host not in allowed_hosts:
        expected = ", ".join(sorted(allowed_hosts))
        return f"{label} host must be one of: {expected}"
    if port not in (None, 443):
        return f"{label} must use the default HTTPS port"
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        return f"{label} must be an origin without path, query, or fragment"
    return None


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

    base_issue = _public_https_origin_issue(
        "APP_BASE_URL",
        getattr(settings, "app_base_url", None),
        allowed_hosts={CANONICAL_APP_HOST},
    )
    if base_issue:
        issues.append(base_issue)
    if bool(getattr(settings, "admin_api_key_query_enabled", False)):
        issues.append(
            "ADMIN_API_KEY_QUERY_ENABLED must be false in production; use X-API-Key header"
        )
    cors_origins = str(
        getattr(settings, "cors_allowed_origins", "https://gsnipers.snipers.com.cn") or ""
    )
    if "*" in {item.strip() for item in cors_origins.split(",")}:
        issues.append("CORS_ALLOWED_ORIGINS must not contain * in production")
    else:
        for index, origin in enumerate(cors_origins.split(","), start=1):
            if not origin.strip():
                continue
            cors_issue = _public_https_origin_issue(
                f"CORS_ALLOWED_ORIGINS entry {index}",
                origin,
                allowed_hosts={CANONICAL_APP_HOST, LEGACY_APP_HOST},
            )
            if cors_issue:
                issues.append(cors_issue)

    callback_url = str(getattr(settings, "baidu_oauth_callback_url", "") or "").strip()
    if callback_url:
        try:
            parsed_callback = urlsplit(callback_url)
        except ValueError:
            issues.append("BAIDU_OAUTH_CALLBACK_URL is not a valid URL")
        else:
            callback_origin = f"{parsed_callback.scheme}://{parsed_callback.netloc}"
            callback_issue = _public_https_origin_issue(
                "BAIDU_OAUTH_CALLBACK_URL origin",
                callback_origin,
                allowed_hosts={CANONICAL_APP_HOST, LEGACY_APP_HOST},
            )
            if callback_issue:
                issues.append(callback_issue)
            if parsed_callback.path != "/api/oauth/baidu/callback":
                issues.append(
                    "BAIDU_OAUTH_CALLBACK_URL path must be /api/oauth/baidu/callback"
                )
            if parsed_callback.query or parsed_callback.fragment:
                issues.append("BAIDU_OAUTH_CALLBACK_URL must not contain query or fragment")
    if bool(getattr(settings, "geo_allow_self_review", False)):
        issues.append(
            "GEO_ALLOW_SELF_REVIEW is true — self-approve of content is a delivery risk"
        )

    if not bool(getattr(settings, "baidu_write_dry_run", True)):
        for attr, label in (
            ("baidu_live_write_tenant_ids", "BAIDU_LIVE_WRITE_TENANT_IDS"),
            ("baidu_live_write_account_ids", "BAIDU_LIVE_WRITE_ACCOUNT_IDS"),
        ):
            try:
                allowed_ids = parse_positive_id_csv(
                    str(getattr(settings, attr, "") or ""),
                    label=label,
                )
            except ValueError as exc:
                issues.append(str(exc))
            else:
                if not allowed_ids:
                    issues.append(
                        f"{label} must contain at least one ID when BAIDU_WRITE_DRY_RUN=false"
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
