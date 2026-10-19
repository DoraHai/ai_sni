"""Unmounted SEO AI visibility policy draft; no database or provider access.

The integration is intentionally deferred pending the environment-contract
decision documented in docs/SEO_AI_VISIBILITY_PLAN.md. Callers must persist
the ledger under the tenant-module UPDATE lock and recheck live authorization
before committing or calling any provider. This module does neither.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.geo.ai_sampling import build_neutral_questions, clean_questions

KEY = "seo_ai_visibility_quota_v1"
LIMIT = 10
BEIJING = ZoneInfo("Asia/Shanghai")


def deny(status: int, code: str):
    raise HTTPException(status, {"code": code})


@dataclass(frozen=True)
class VisibilityScope:
    """Server-derived authority snapshot, never a request body schema.

    Integration must obtain selected_tenant_id/granted_tenant_ids from the live
    grant-bound auth context and assigned_site_ids from live SEO assignments.
    An HTTP caller must never be able to supply this object.
    """
    user_id: int | None
    selected_tenant_id: int | None
    granted_tenant_ids: frozenset[int]
    assigned_site_ids: frozenset[int]
    role: Literal["advisor", "superadmin", "customer"]
    can_view: bool
    can_edit: bool


def authorize(scope: VisibilityScope, *, tenant_id: int, site_id: int,
              write: bool = False, configuration: bool = False) -> None:
    # Tenant/site ownership and active SEO entitlement must also be checked by
    # the integration; IDs in this policy are already verified server-side.
    if configuration and scope.role != "superadmin":
        deny(403, "AI_VISIBILITY_SUPERADMIN_REQUIRED")
    if scope.role == "superadmin":
        return
    if (tenant_id != scope.selected_tenant_id
            or tenant_id not in scope.granted_tenant_ids):
        deny(403, "AI_VISIBILITY_SELECTED_TENANT_REQUIRED")
    if not scope.can_view or write and not scope.can_edit:
        deny(403, "AI_VISIBILITY_PERMISSION_REQUIRED")
    if scope.role == "advisor" and (scope.user_id is None
            or site_id not in scope.assigned_site_ids):
        deny(403, "AI_VISIBILITY_ASSIGNMENT_REQUIRED")


@dataclass(frozen=True)
class Reservation:
    tenant_id: int
    advisor_id: int
    day: str
    request_id: str


def _day(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise ValueError("timezone-aware time required")
    return value.astimezone(BEIJING).date().isoformat()


def used(settings: dict | None, tenant_id: int, advisor_id: int,
         *, now: datetime | None = None) -> int:
    ledger = (settings or {}).get(KEY) or {}
    if ledger.get("day") != _day(now) or ledger.get("tenant_id") != tenant_id:
        return 0
    attempts = ledger.get("actors", {}).get(str(advisor_id), {})
    return sum(row["state"] in {"reserved", "consumed"} for row in attempts.values())


def reserve_quota(settings: dict | None, *, tenant_id: int, advisor_id: int,
                  request_id: str, fingerprint: str,
                  now: datetime | None = None) -> tuple[dict, Reservation]:
    """Pure transition, requiring a database row lock in the future adapter.

    A refunded request ID stays terminal. A fresh attempt needs a new ID. A
    durable operation row must additionally prevent cross-day request replay.
    """
    if (type(tenant_id) is not int or tenant_id <= 0
            or type(advisor_id) is not int or advisor_id <= 0
            or not isinstance(request_id, str) or not 1 <= len(request_id) <= 64
            or not isinstance(fingerprint, str) or len(fingerprint) != 64):
        raise ValueError("invalid reservation identity")
    result = deepcopy(settings or {})
    day = _day(now)
    ledger = result.get(KEY) or {}
    if ledger and ledger.get("tenant_id") != tenant_id:
        deny(403, "AI_VISIBILITY_LEDGER_TENANT_MISMATCH")
    if ledger.get("day") != day:
        ledger = {"day": day, "tenant_id": tenant_id, "actors": {}}
    attempts = ledger["actors"].setdefault(str(advisor_id), {})
    prior = attempts.get(request_id)
    if prior:
        if prior["fingerprint"] != fingerprint:
            deny(409, "AI_VISIBILITY_REQUEST_CONFLICT")
        if prior["state"] == "refunded":
            deny(409, "AI_VISIBILITY_ATTEMPT_REFUNDED")
    else:
        if sum(row["state"] in {"reserved", "consumed"} for row in attempts.values()) >= LIMIT:
            deny(429, "AI_VISIBILITY_DAILY_LIMIT")
        attempts[request_id] = {"fingerprint": fingerprint, "state": "reserved"}
    result[KEY] = ledger
    return result, Reservation(tenant_id, advisor_id, day, request_id)


def settle_quota(settings: dict, reservation: Reservation, *, has_result: bool) -> dict:
    """reserved -> consumed/refunded only; partial results consume immediately.

    The future adapter must commit the first result and consumed state together
    before trying another engine. Refund cleanup may only change this exact
    unused reservation and may never mutate business results or authorization.
    """
    if type(has_result) is not bool:
        raise ValueError("result evidence must be a boolean")
    result = deepcopy(settings)
    ledger = result.get(KEY) or {}
    if (ledger.get("day"), ledger.get("tenant_id")) != (reservation.day, reservation.tenant_id):
        return result
    row = ledger.get("actors", {}).get(str(reservation.advisor_id), {}).get(reservation.request_id)
    if row is not None and row["state"] == "reserved":
        row["state"] = "consumed" if has_result else "refunded"
    return result


def questions_for_site(*, industry: str, products: list[str], audience: list[str],
                       brand_terms: list[str]) -> list[str]:
    """Reuse GEO's neutral-question builder; never include the observed brand."""
    return clean_questions(build_neutral_questions(
        industry=industry, core_products=products,
        audience_segments=audience, brand_terms=brand_terms,
    ), brand_terms)
