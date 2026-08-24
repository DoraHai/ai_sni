import os
from datetime import datetime
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from fastapi import HTTPException

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "1234567890abcdefsecret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.api.auth import _sem_account_payload, list_tenants
from app.api.customer_modules import (
    CustomerUpdate,
    SemAccountArchive,
    _sem_identity_check,
    archive_sem_account,
    update_customer,
)
from app.main import init_self_auth_account
from app.security.sem_identity import (
    SEM_IDENTITY_BLOCKED_CODE,
    ensure_sem_identity_access,
    evaluate_sem_identity_states,
    filter_identity_safe_active_accounts,
)


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class TestSemTenantAccountIdentity(IsolatedAsyncioTestCase):
    def test_account_context_payload_is_sanitized(self):
        account = SimpleNamespace(
            id=8,
            baidu_username="苏尔寿化工",
            baidu_ucid=80243027,
            auth_mode="oauth",
            status="active",
            sync_status="success",
            last_synced_at=datetime(2026, 8, 22, 13, 15),
            access_token_encrypted="must-not-leak",
        )

        payload = _sem_account_payload(account)

        self.assertEqual(payload["username"], "苏尔寿化工")
        self.assertEqual(payload["ucid"], "80243027")
        self.assertEqual(payload["last_synced_at"], "2026-08-22T13:15:00")
        self.assertNotIn("access_token_encrypted", payload)

    async def test_tenant_switcher_returns_scoped_sem_account_context(self):
        tenant = SimpleNamespace(id=7, name="诺德")
        account = SimpleNamespace(
            id=8,
            tenant_id=7,
            baidu_username="苏尔寿化工",
            baidu_ucid=80243027,
            auth_mode="oauth",
            status="active",
            sync_status="success",
            last_synced_at=datetime(2026, 8, 22, 13, 15),
        )
        session = SimpleNamespace(
            scalars=AsyncMock(
                side_effect=[_Rows([tenant]), _Rows([account]), _Rows([account])]
            )
        )
        ctx = SimpleNamespace(tenant_id=7)

        result = await list_tenants(module=None, ctx=ctx, session=session)

        self.assertEqual(result["tenants"][0]["name"], "诺德")
        self.assertEqual(
            result["tenants"][0]["sem_accounts"][0]["username"],
            "苏尔寿化工",
        )
        self.assertEqual(result["tenants"][0]["sem_identity"]["status"], "ok")
        first_query = str(session.scalars.await_args_list[0].args[0])
        second_query = str(session.scalars.await_args_list[1].args[0])
        self.assertIn("tenants.id", first_query)
        self.assertIn("baidu_accounts.tenant_id", second_query)

    async def test_tenant_switcher_hides_account_context_when_ucid_conflicts(self):
        tenant = SimpleNamespace(id=7, name="诺德")
        local = SimpleNamespace(
            id=8,
            tenant_id=7,
            baidu_username="苏尔寿化工",
            baidu_ucid=80243027,
            auth_mode="oauth",
            status="active",
            sync_status="success",
            last_synced_at=datetime(2026, 8, 22, 13, 15),
        )
        rightful = SimpleNamespace(
            id=9,
            tenant_id=9,
            baidu_username="苏尔寿化工",
            baidu_ucid=80243027,
            status="active",
        )
        session = SimpleNamespace(
            scalars=AsyncMock(
                side_effect=[_Rows([tenant]), _Rows([local]), _Rows([local, rightful])]
            )
        )

        result = await list_tenants(
            module=None, ctx=SimpleNamespace(tenant_id=7), session=session
        )

        payload = result["tenants"][0]
        self.assertEqual(
            payload["sem_identity"],
            {
                "status": "blocked",
                "code": SEM_IDENTITY_BLOCKED_CODE,
                "message": "推广账户归属冲突，已暂停展示该客户的 SEM 数据，请联系超级管理员处理",
            },
        )
        self.assertEqual(payload["sem_accounts"], [])

    def test_quarantined_wrong_bindings_stay_blocked_while_owner_recovers(self):
        wrong = SimpleNamespace(
            id=8, tenant_id=7, baidu_ucid=80243027, status="identity_conflict"
        )
        rightful = SimpleNamespace(
            id=9, tenant_id=9, baidu_ucid=80243027, status="active"
        )

        states = evaluate_sem_identity_states(
            [7, 9], [wrong, rightful], [rightful]
        )

        self.assertEqual(states[7]["status"], "blocked")
        self.assertEqual(states[9]["status"], "ok")

    async def test_conflicted_tenant_data_access_fails_closed(self):
        local = SimpleNamespace(
            id=8, tenant_id=7, baidu_ucid=80243027, status="active"
        )
        other = SimpleNamespace(
            id=9, tenant_id=9, baidu_ucid=80243027, status="active"
        )
        session = SimpleNamespace(
            scalars=AsyncMock(side_effect=[_Rows([local]), _Rows([local, other])])
        )

        with self.assertRaises(HTTPException) as cm:
            await ensure_sem_identity_access(session, 7)

        self.assertEqual(cm.exception.status_code, 409)
        self.assertEqual(
            cm.exception.detail,
            {
                "code": SEM_IDENTITY_BLOCKED_CODE,
                "msg": "推广账户归属冲突，已暂停展示该客户的 SEM 数据，请联系超级管理员处理",
            },
        )

    def test_scheduler_excludes_every_active_row_for_cross_tenant_ucid(self):
        conflicted_a = SimpleNamespace(
            id=8, tenant_id=7, baidu_ucid=80243027, status="active"
        )
        conflicted_b = SimpleNamespace(
            id=9, tenant_id=9, baidu_ucid=80243027, status="active"
        )
        safe = SimpleNamespace(
            id=10, tenant_id=11, baidu_ucid=90001, status="active"
        )
        inactive = SimpleNamespace(
            id=11, tenant_id=12, baidu_ucid=90002, status="identity_conflict"
        )

        result = filter_identity_safe_active_accounts(
            [conflicted_a, conflicted_b, safe, inactive]
        )

        self.assertEqual([account.id for account in result], [10])

    def test_identity_check_reports_cross_tenant_and_duplicate_rows_once(self):
        tenants = [
            SimpleNamespace(id=1, baidu_ucid=80243027),
            SimpleNamespace(id=2, baidu_ucid=80243027),
        ]
        accounts = [
            SimpleNamespace(id=10, tenant_id=1, baidu_ucid=80243027, auth_mode="self"),
            SimpleNamespace(id=11, tenant_id=1, baidu_ucid=80243027, auth_mode="oauth"),
            SimpleNamespace(id=12, tenant_id=2, baidu_ucid=80243027, auth_mode="oauth"),
        ]

        result = _sem_identity_check(tenants, accounts)

        self.assertEqual(result["summary"]["errors"], 1)
        self.assertEqual(result["summary"]["warnings"], 1)
        self.assertFalse(result["summary"]["healthy"])
        self.assertIn("ucid_cross_tenant", {i["code"] for i in result["issues_by_tenant"][1]})
        self.assertIn("ucid_cross_tenant", {i["code"] for i in result["issues_by_tenant"][2]})
        self.assertIn("duplicate_account_rows", {i["code"] for i in result["issues_by_tenant"][1]})

    def test_identity_check_reports_missing_primary_ucid(self):
        tenant = SimpleNamespace(id=3, baidu_ucid=99)

        result = _sem_identity_check([tenant], [])

        self.assertEqual(result["summary"]["warnings"], 1)
        self.assertEqual(result["issues_by_tenant"][3][0]["code"], "primary_ucid_missing")

    def test_identity_check_treats_quarantined_binding_as_resolved_warning(self):
        tenants = [
            SimpleNamespace(id=7, baidu_ucid=None),
            SimpleNamespace(id=9, baidu_ucid=80243027),
        ]
        accounts = [
            SimpleNamespace(
                id=8,
                tenant_id=7,
                baidu_ucid=80243027,
                auth_mode="oauth",
                status="identity_conflict",
            ),
            SimpleNamespace(
                id=9,
                tenant_id=9,
                baidu_ucid=80243027,
                auth_mode="oauth",
                status="active",
            ),
        ]

        result = _sem_identity_check(tenants, accounts)

        self.assertEqual(result["summary"]["errors"], 0)
        self.assertEqual(result["summary"]["warnings"], 1)
        self.assertEqual(
            result["issues_by_tenant"][7][0]["code"],
            "quarantined_account_binding",
        )

    async def test_bound_customer_name_change_requires_confirmation_and_reason(self):
        tenant = SimpleNamespace(id=7, name="苏尔寿", industry=None, business_desc=None)
        account = SimpleNamespace(id=88, baidu_ucid=1)
        session = SimpleNamespace(
            get=AsyncMock(return_value=tenant),
            scalars=AsyncMock(return_value=_Rows([account])),
            commit=AsyncMock(),
        )

        with self.assertRaises(HTTPException) as cm:
            await update_customer(
                7,
                CustomerUpdate(name="诺德"),
                SimpleNamespace(user_id=5, username="admin"),
                session,
            )

        self.assertEqual(cm.exception.status_code, 409)
        self.assertEqual(tenant.name, "苏尔寿")
        session.commit.assert_not_awaited()

    async def test_bound_customer_name_can_change_with_audited_confirmation(self):
        tenant = SimpleNamespace(id=7, name="旧品牌", industry=None, business_desc=None)
        account = SimpleNamespace(id=88, baidu_ucid=1)
        session = SimpleNamespace(
            get=AsyncMock(return_value=tenant),
            scalars=AsyncMock(return_value=_Rows([account])),
            commit=AsyncMock(),
        )
        ctx = SimpleNamespace(user_id=5, username="admin")

        result = await update_customer(
            7,
            CustomerUpdate(
                name="新品牌",
                confirm_bound_name_change=True,
                name_change_reason="客户完成品牌更名",
            ),
            ctx,
            session,
        )

        self.assertEqual(result, {"status": "ok"})
        self.assertEqual(tenant.name, "新品牌")
        session.commit.assert_awaited_once()

    async def test_unbound_customer_name_can_be_changed(self):
        tenant = SimpleNamespace(id=7, name="旧名称", industry=None, business_desc=None)
        session = SimpleNamespace(
            get=AsyncMock(return_value=tenant),
            scalars=AsyncMock(return_value=_Rows([])),
            commit=AsyncMock(),
        )

        result = await update_customer(
            7,
            CustomerUpdate(name="新名称"),
            SimpleNamespace(user_id=5, username="admin"),
            session,
        )

        self.assertEqual(result, {"status": "ok"})
        self.assertEqual(tenant.name, "新名称")
        session.commit.assert_awaited_once()

    async def test_archive_sem_account_soft_deletes_and_audits(self):
        account = SimpleNamespace(id=4, tenant_id=4, baidu_ucid=80243027, status="identity_conflict")
        session = SimpleNamespace(
            scalar=AsyncMock(return_value=account),
            commit=AsyncMock(),
        )
        ctx = SimpleNamespace(user_id=5, username="admin")

        result = await archive_sem_account(
            4, 4, SemAccountArchive(reason="账户归属核实为其他客户"), ctx, session,
        )

        self.assertEqual(result, {"status": "ok"})
        self.assertEqual(account.status, "archived")
        session.commit.assert_awaited_once()

    async def test_archive_sem_account_rejects_wrong_tenant(self):
        account = SimpleNamespace(id=4, tenant_id=4, baidu_ucid=80243027, status="active")
        session = SimpleNamespace(scalar=AsyncMock(return_value=account), commit=AsyncMock())
        ctx = SimpleNamespace(user_id=5, username="admin")

        with self.assertRaises(HTTPException) as cm:
            await archive_sem_account(
                1, 4, SemAccountArchive(reason="账户归属核实为其他客户"), ctx, session,
            )

        self.assertEqual(cm.exception.status_code, 404)
        self.assertEqual(account.status, "active")
        session.commit.assert_not_awaited()

    async def test_archive_sem_account_rejects_already_archived(self):
        account = SimpleNamespace(id=4, tenant_id=4, baidu_ucid=80243027, status="archived")
        session = SimpleNamespace(scalar=AsyncMock(return_value=account), commit=AsyncMock())
        ctx = SimpleNamespace(user_id=5, username="admin")

        with self.assertRaises(HTTPException) as cm:
            await archive_sem_account(
                4, 4, SemAccountArchive(reason="账户归属核实为其他客户"), ctx, session,
            )

        self.assertEqual(cm.exception.status_code, 409)
        session.commit.assert_not_awaited()

    async def test_self_auth_account_cannot_be_initialized_under_another_customer(self):
        account = SimpleNamespace(tenant_id=3)
        tenant = SimpleNamespace(id=3, name="苏尔寿", baidu_ucid=1)
        session = SimpleNamespace(
            scalars=AsyncMock(return_value=_Rows([account])),
            get=AsyncMock(return_value=tenant),
        )

        with self.assertRaises(HTTPException) as cm:
            await init_self_auth_account(tenant_name="诺德", monthly_budget=None, session=session)

        self.assertEqual(cm.exception.status_code, 409)
        self.assertIn("已绑定客户", cm.exception.detail)

    async def test_self_auth_stops_when_ucid_has_cross_customer_history(self):
        session = SimpleNamespace(
            scalars=AsyncMock(
                return_value=_Rows(
                    [SimpleNamespace(tenant_id=3), SimpleNamespace(tenant_id=9)]
                )
            ),
        )

        with self.assertRaises(HTTPException) as cm:
            await init_self_auth_account(tenant_name="苏尔寿", monthly_budget=None, session=session)

        self.assertEqual(cm.exception.status_code, 409)
        self.assertIn("跨客户历史绑定", cm.exception.detail)
