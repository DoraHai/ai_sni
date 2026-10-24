"""Exercise real account routes and SQL contracts without DB writes or tokens."""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from tests import sem_cockpit_fixtures  # isolated dummy application settings
from app.api import users
from app.database import get_session
from app.models import Role, User
from app.security.auth import AuthContext, require_auth


OLD = datetime(2026, 10, 1, tzinfo=timezone.utc)


@pytest.fixture
def account(monkeypatch):
    user = User(id=7, username="synthetic-advisor", role_id=3, tenant_id=10,
                is_active=True, display_name="Synthetic")
    role = Role(id=3, name="顾问", is_system=False,
                permissions={"seo.site": "edit", "seo.content": "edit"})
    grants = [
        dict(id=1, user_id=7, tenant_id=10, revoked_at=None, revoked_by=None, revoke_reason=None),
        dict(id=2, user_id=7, tenant_id=20, revoked_at=None, revoked_by=None, revoke_reason=None),
        dict(id=3, user_id=7, tenant_id=30, revoked_at=OLD, revoked_by=9, revoke_reason="admin_uncheck"),
        dict(id=4, user_id=8, tenant_id=10, revoked_at=None, revoked_by=None, revoke_reason=None),
    ]
    assignments = [
        dict(id=1, advisor_user_id=7, active=True, assigned_by=9, updated_at=OLD),
        dict(id=2, advisor_user_id=7, active=False, assigned_by=9, updated_at=OLD),
        dict(id=3, advisor_user_id=8, active=True, assigned_by=9, updated_at=OLD),
    ]
    statements = []

    async def get(model, ident, **kwargs):
        return user if model is User else role

    async def execute(statement, parameters=None):
        compiled = statement.compile(dialect=postgresql.dialect())
        sql, params = str(compiled), parameters or compiled.params
        statements.append((sql, params))
        if "UPDATE advisor_tenant_grants" in sql:
            # Assert the actual emitted columns, ownership and history guards.
            assert "advisor_tenant_grants.user_id =" in sql
            assert "advisor_tenant_grants.revoked_at IS NULL" in sql
            changed = sql.split(" SET ")[1].split(" WHERE ")[0]
            assert {part.split("=")[0] for part in changed.split(", ")} == {
                "revoked_at", "revoked_by", "revoke_reason"}
            for grant in grants:
                if grant["user_id"] == params["user_id_1"] and grant["revoked_at"] is None:
                    grant.update({key: params[key] for key in ("revoked_at", "revoked_by", "revoke_reason")})
        else:
            assert "UPDATE seo_site_advisor_assignments" in sql
            assert "WHERE advisor_user_id =" in sql and "AND active = true" in sql
            assert "SET active = false, assigned_by =" in sql
            assert ", updated_at =" in sql
            for assignment in assignments:
                if assignment["advisor_user_id"] == params["user_id"] and assignment["active"]:
                    assignment.update(active=False, assigned_by=params["actor_id"], updated_at=params["now"])

    session = SimpleNamespace(get=AsyncMock(side_effect=get), execute=AsyncMock(side_effect=execute),
                              commit=AsyncMock(), flush=AsyncMock())
    audit = AsyncMock()
    monkeypatch.setattr(users, "audit_business", audit)

    async def projection(session, user, role, names, rows=None):
        assert rows is None  # never project a pre-revocation cached grant list
        return {"is_active": user.is_active,
                "tenant_ids": [g["tenant_id"] for g in grants
                               if g["user_id"] == user.id and g["revoked_at"] is None]}

    monkeypatch.setattr(users, "_account_payload", projection)
    ctx = AuthContext(1, "synthetic-admin", "admin", None,
                      {"settings.accounts": "edit", "settings.customers": "edit"})
    app = FastAPI()
    app.include_router(users.router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[require_auth] = lambda: ctx
    with TestClient(app, raise_server_exceptions=False) as client:
        yield SimpleNamespace(client=client, session=session, user=user, role=role, grants=grants,
                              assignments=assignments, statements=statements, ctx=ctx, audit=audit)


def deactivate(account, method):
    if method == "PATCH":
        return account.client.patch("/api/v1/users/7", json={"is_active": False})
    return account.client.delete("/api/v1/users/7")


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
def test_deactivation_revokes_only_current_grants_and_active_assignments(account, method):
    before = deepcopy((account.grants, account.assignments))
    assert deactivate(account, method).status_code == 200
    assert account.user.is_active is False
    for grant in account.grants[:2]:
        assert grant["revoked_at"] > OLD and grant["revoked_by"] == 1
        assert grant["revoke_reason"] == "account_deactivated"
    assert account.grants[0]["revoked_at"] == account.grants[1]["revoked_at"]
    assert account.grants[2:] == before[0][2:]
    assert not account.assignments[0]["active"] and account.assignments[0]["assigned_by"] == 1
    assert account.assignments[0]["updated_at"] == account.grants[0]["revoked_at"].replace(tzinfo=None)
    assert account.assignments[1:] == before[1][1:]
    # No DELETE/INSERT or independent commit; both updates precede the route's audit/commit.
    assert len(account.statements) == 2
    account.session.commit.assert_awaited_once()
    account.audit.assert_awaited_once()
    assert account.session.get.await_args_list[0].kwargs["with_for_update"] is True

    revoked = deepcopy((account.grants, account.assignments))
    assert deactivate(account, method).status_code == 200
    assert len(account.statements) == 2  # already inactive: no history repair
    assert (account.grants, account.assignments) == revoked
    assert account.client.patch("/api/v1/users/7", json={"is_active": True}).status_code == 200
    assert account.user.is_active is True
    assert (account.grants, account.assignments) == revoked


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
def test_non_advisor_deactivation_never_touches_grants_or_assignments(account, method):
    account.role.permissions = {"sem.keywords": "edit"}
    before = deepcopy((account.grants, account.assignments))
    assert deactivate(account, method).status_code == 200
    assert account.user.is_active is False
    account.session.execute.assert_not_awaited()
    assert (account.grants, account.assignments) == before


def test_unrelated_edit_does_not_revoke(account):
    assert account.client.patch("/api/v1/users/7", json={"display_name": "Edited"}).status_code == 200
    assert account.user.is_active is True
    account.session.execute.assert_not_awaited()


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
def test_failure_in_assignment_revocation_cannot_commit_account_or_grants(account, method):
    original = account.session.execute.side_effect

    async def fail_second(statement, parameters=None):
        if "seo_site_advisor_assignments" in str(statement):
            raise RuntimeError("synthetic assignment failure")
        return await original(statement, parameters)

    account.session.execute.side_effect = fail_second
    assert deactivate(account, method).status_code == 500
    # Real get_session owns rollback on context exit; no helper may commit.
    account.session.commit.assert_not_awaited()
    assert account.user.is_active is True
    account.audit.assert_not_awaited()


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
def test_unnamed_actor_cannot_create_unauditable_revocations(account, method):
    account.ctx.user_id = None
    assert deactivate(account, method).status_code == 403
    account.session.execute.assert_not_awaited()
    account.session.commit.assert_not_awaited()


def test_simultaneous_customer_edit_and_deactivation_revokes_new_grants(account, monkeypatch):
    monkeypatch.setattr(users, "_require_multi_tenant", lambda: None)
    monkeypatch.setattr(users, "lock_named_admin", AsyncMock(return_value=account.user))
    monkeypatch.setattr(users, "read_grants", AsyncMock(return_value=[]))
    monkeypatch.setattr(users, "grants_version", lambda *args: "version")
    monkeypatch.setattr(users, "validate_tenants", AsyncMock(return_value=[10, 40]))

    async def save(*args):
        account.grants.append(dict(id=5, user_id=7, tenant_id=40, revoked_at=None,
                                   revoked_by=None, revoke_reason=None))
        return [SimpleNamespace(**g) for g in account.grants if g["user_id"] == 7]

    monkeypatch.setattr(users, "save_grants", save)
    response = account.client.patch("/api/v1/users/7", json={"is_active": False,
        "tenant_ids": [10, 40], "default_tenant_id": 10, "expected_grants_version": "version"})
    assert response.status_code == 200 and response.json()["tenant_ids"] == []
    assert all(g["revoked_at"] is not None for g in account.grants if g["user_id"] == 7)
    account.session.flush.assert_awaited_once()
    account.session.commit.assert_awaited_once()
