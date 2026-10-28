"""Read-only local authorization adapter, never connected to production.

The identity resolver is supplied by a trusted session layer, never raw headers or
JSON. Table/field semantics follow advisor_tenant_grants, users, tenant_modules
and baidu_accounts. This slice only exercises a synthetic SQLite snapshot.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Protocol

from fastapi import Depends

from app.sem_phase0.store import AdvisorPrincipal, ScopeDenied


@dataclass(frozen=True)
class SessionIdentity:
    user_id: int
    role: str
    tenant_id: int | None
    grant_id: int | None = None


class PrincipalAdapter(Protocol):
    def resolve(self, identity: SessionIdentity) -> AdvisorPrincipal: ...


class LocalGrantPrincipalAdapter:
    def __init__(self, path: Path, clock=lambda: datetime.now(timezone.utc)):
        self.path, self.clock = Path(path).resolve(), clock

    def resolve(self, identity):
        if not isinstance(identity, SessionIdentity) or identity.role not in {"advisor", "customer"}:
            raise ScopeDenied("身份未获准")
        now = self.clock()
        if not isinstance(now, datetime) or now.utcoffset() is None:
            raise ScopeDenied("授权时钟必须带时区")
        if identity.tenant_id is None:
            raise ScopeDenied("须选择已授权客户")
        try:
            # mode=ro forbids writes and creating a missing database; no cache across requests.
            with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as db:
                db.execute("PRAGMA query_only=ON")
                user = db.execute("SELECT is_active,locked_until,tenant_id,role FROM users WHERE id=?",
                                  (identity.user_id,)).fetchone()
                if not user or user[0] != 1 or user[3] != identity.role:
                    raise ScopeDenied("身份停用")
                if user[1]:
                    until = datetime.fromisoformat(user[1])
                    if until.tzinfo is None:
                        until = until.replace(tzinfo=timezone.utc)
                    if until > now:
                        raise ScopeDenied("身份已锁定")
                if user[2] is not None and user[2] != identity.tenant_id:
                    raise ScopeDenied("身份限定客户不符")
                if identity.role == "advisor":
                    grant = db.execute("SELECT id FROM advisor_tenant_grants WHERE user_id=? AND tenant_id=? "
                                       "AND id=? AND revoked_at IS NULL",
                                       (identity.user_id, identity.tenant_id, identity.grant_id)).fetchone()
                    if not grant:
                        raise ScopeDenied("当前会话客户未获授权")
                elif user[2] != identity.tenant_id:
                    raise ScopeDenied("客户身份跨租户")
                if not db.execute("SELECT id FROM tenants WHERE id=?", (identity.tenant_id,)).fetchone():
                    raise ScopeDenied("客户记录不存在")
                module = db.execute("SELECT status,expires_at FROM tenant_modules WHERE tenant_id=? "
                                    "AND module_code='sem'", (identity.tenant_id,)).fetchone()
                if (not module or module[0] not in {"active", "trial"}
                        or (module[1] and date.fromisoformat(module[1]) < now.date())):
                    raise ScopeDenied("SEM暂停、关闭、未开通或过期")
                accounts = frozenset((identity.tenant_id, r[0]) for r in db.execute(
                    "SELECT a.id FROM baidu_accounts a JOIN sem_phase1a_account_grants g ON g.account_id=a.id "
                    "AND g.tenant_id=a.tenant_id WHERE a.tenant_id=? AND a.status='active' "
                    "AND g.user_id=? AND g.revoked_at IS NULL "
                    "AND ((?='advisor' AND g.advisor_grant_id=?) OR (?='customer' AND g.advisor_grant_id IS NULL))",
                    (identity.tenant_id, identity.user_id, identity.role, identity.grant_id, identity.role)))
        except (sqlite3.Error, ValueError, TypeError):
            raise ScopeDenied("授权数据不可用") from None
        return AdvisorPrincipal(str(identity.user_id), identity.role,
                                accounts if identity.role == "advisor" else frozenset(), accounts)


def principal_dependency(adapter: PrincipalAdapter, resolve_identity):
    """Unattached FastAPI dependency; trusted session resolution must be supplied."""
    def resolve_principal(identity: SessionIdentity = Depends(resolve_identity)):
        from fastapi import HTTPException

        try:
            return adapter.resolve(identity)
        except ScopeDenied:
            raise HTTPException(403, {"code": "SCOPE_DENIED", "message": "身份或SEM授权不可用"}) from None
    return resolve_principal
