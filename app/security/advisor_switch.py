"""Legacy #657 credentials are retired in all services before new grants open."""
from fastapi import HTTPException


async def validate_switch_claims(session, payload: dict, target) -> None:
    if "via" in payload:
        raise HTTPException(401, {"code": "LEGACY_ADVISOR_SWITCH_DISABLED"})
