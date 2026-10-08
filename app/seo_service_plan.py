"""Small, shared policy helpers for the site-level SEO service plan."""

from sqlalchemy import func

from app.models.module_workspace import SeoSite


def service_plan_is_paused(site: SeoSite) -> bool:
    raw_settings = getattr(site, "site_settings", None)
    settings = raw_settings if isinstance(raw_settings, dict) else {}
    plan = settings.get("seo_service_plan")
    return isinstance(plan, dict) and plan.get("status") == "paused"


def automation_site_not_paused_clause():
    return func.coalesce(
        SeoSite.site_settings["seo_service_plan"]["status"].astext,
        "active",
    ) != "paused"
