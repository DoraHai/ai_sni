"""Fail-closed runtime policy for the isolated SEO demonstration service."""

from __future__ import annotations

from dataclasses import dataclass


SAFE_HTTP_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# These POST routes only parse or evaluate supplied/stored data.  They do not
# commit, enqueue work, call a provider, crawl a URL, generate with AI, or
# publish.  Keep this exact-path list short and require a code review to add to
# it.  Login is routed by the independent auth service in the target topology,
# but remains explicit here so the policy is reusable at the combined gateway.
DEMO_SAFE_POST_PATHS = frozenset(
    {
        "/api/v1/auth/login",
        "/api/v1/seo/content-distribution/preflight",
        "/api/v1/seo/qa/questions/import/preview",
        "/api/v1/seo/qa/research/file-preview",
    }
)


@dataclass(frozen=True)
class SeoDemoRuntimePolicy:
    demo_mode: bool
    scheduler_enabled: bool
    external_actions_enabled: bool


def _is_demo_environment(settings: object) -> bool:
    return str(getattr(settings, "app_env", "")).strip().lower() == "demo"


def validate_seo_demo_runtime_settings(settings: object) -> SeoDemoRuntimePolicy:
    """Reject partial or contradictory demo configuration at startup."""
    demo_mode = bool(getattr(settings, "seo_demo_mode", False))
    scheduler_enabled = bool(getattr(settings, "seo_scheduler_enabled", True))
    external_actions_enabled = bool(
        getattr(settings, "seo_external_actions_enabled", True)
    )
    environment_is_demo = _is_demo_environment(settings)
    if demo_mode and not environment_is_demo:
        raise RuntimeError("SEO_DEMO_MODE=true requires APP_ENV=demo")
    if environment_is_demo:
        problems: list[str] = []
        if not demo_mode:
            problems.append("SEO_DEMO_MODE must be true")
        if scheduler_enabled:
            problems.append("SEO_SCHEDULER_ENABLED must be false")
        if external_actions_enabled:
            problems.append("SEO_EXTERNAL_ACTIONS_ENABLED must be false")
        if problems:
            raise RuntimeError("Unsafe SEO demo runtime configuration: " + "; ".join(problems))
    return SeoDemoRuntimePolicy(
        demo_mode=demo_mode,
        scheduler_enabled=scheduler_enabled,
        external_actions_enabled=external_actions_enabled,
    )


def seo_scheduler_may_start(settings: object) -> bool:
    """Return false for demo even if a caller bypasses startup validation."""
    return (
        not _is_demo_environment(settings)
        and not bool(getattr(settings, "seo_demo_mode", False))
        and bool(getattr(settings, "seo_scheduler_enabled", True))
    )


def demo_request_is_allowed(settings: object, method: str, path: str) -> bool:
    """Permit reads, login and reviewed local previews; reject every other write."""
    if not bool(getattr(settings, "seo_demo_mode", False)):
        return True
    normalized_method = str(method or "").strip().upper()
    normalized_path = (str(path or "").strip().rstrip("/") or "/")
    if normalized_method in SAFE_HTTP_METHODS:
        return True
    return normalized_method == "POST" and normalized_path in DEMO_SAFE_POST_PATHS
