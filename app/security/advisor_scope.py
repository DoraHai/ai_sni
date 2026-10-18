"""Pure advisor identity predicate. Tenant/default/activation are access gates."""
from app.permissions import normalize_permissions


def is_advisor_role(role) -> bool:
    if role is None or (role.is_system and role.name == "管理员"):
        return False
    permissions = normalize_permissions(role.permissions or {})
    raw = role.permissions if isinstance(role.permissions, dict) else {}
    # Preserve the legacy exclusion for *any* settings edit, including dirty
    # unregistered keys, matching the reviewed SQL backfill predicate.
    if any(isinstance(key, str) and key.startswith("settings.") and value == "edit"
           for key, value in raw.items()):
        return False
    return (
        not any(key.startswith("settings.") and level == "edit"
                for key, level in permissions.items())
        and ((permissions.get("seo.site") == "edit" and permissions.get("seo.content") == "edit")
             or (permissions.get("geo.assets") == "edit" and permissions.get("geo.content") == "edit"))
    )
