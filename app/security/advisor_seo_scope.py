"""SEO compatibility around the SEM-owned identity predicate.

Keep the legacy raw settings exclusion consistent with the approved backfill;
the upstream parity request is recorded in handoff-request.md (COMMON-3).
"""
from app.security.advisor_scope import is_advisor


def is_advisor_role(role) -> bool:
    if not is_advisor(role):
        return False
    raw = role.permissions if isinstance(role.permissions, dict) else {}
    return not any(isinstance(key, str) and key.startswith('settings.') and value == 'edit'
                   for key, value in raw.items())
