import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "1234567890abcdefsecret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault(
    "CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
)
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.api.customer_modules import (
    SEM_IDENTITY_REPAIR_TABLES,
    _normalized_customer_name,
    _sem_duplicate_candidate_groups,
    _sem_identity_account_select,
    _sem_identity_candidate_tenant_ids,
    _sem_identity_repair_preview_payload,
    list_sem_identity_repair_candidates,
    preview_sem_identity_repair,
    router as customer_modules_router,
)
from app.database import Base


ROOT = Path(__file__).resolve().parents[1]


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


def _tenant(tenant_id, name, baidu_ucid=None):
    return SimpleNamespace(
        id=tenant_id,
        name=name,
        baidu_ucid=baidu_ucid,
        created_at=datetime(2026, 8, 1, 9, tenant_id),
    )


def _account(
    account_id,
    tenant_id,
    ucid,
    *,
    status="active",
    username="SEM account",
):
    return SimpleNamespace(
        id=account_id,
        tenant_id=tenant_id,
        baidu_ucid=ucid,
        baidu_username=username,
        status=status,
        auth_mode="oauth",
        access_token_encrypted="must-not-leak",
        refresh_token_encrypted="must-not-leak",
    )


class TestSemIdentityRepairPreview(IsolatedAsyncioTestCase):
    def test_name_matching_is_conservative_and_unicode_normalized(self):
        self.assertEqual(_normalized_customer_name("  ＮＩＬＦＩＳＫ  02 "), "nilfisk 02")

        groups = _sem_duplicate_candidate_groups(
            [
                _tenant(1, "ＮＩＬＦＩＳＫ  02"),
                _tenant(2, "nilfisk 02"),
                _tenant(3, "Nilfisk-02"),
            ],
            [],
        )

        self.assertEqual(len(groups), 1)
        self.assertEqual([row["tenant_id"] for row in groups[0]["customers"]], [1, 2])

    async def test_candidate_endpoint_is_read_only_and_does_not_leak_credentials(self):
        tenants = [_tenant(1, "诺德"), _tenant(2, " 诺德 ")]
        account = _account(10, 2, 80243027)
        sem_module = SimpleNamespace(
            id=1,
            tenant_id=1,
            module_code="sem",
            status="active",
            expires_at=None,
        )
        session = SimpleNamespace(
            scalars=AsyncMock(
                side_effect=[
                    _Rows(tenants),
                    _Rows([sem_module]),
                    _Rows([account]),
                    _Rows([]),
                ]
            ),
            commit=AsyncMock(),
            flush=AsyncMock(),
            delete=AsyncMock(),
        )

        result = await list_sem_identity_repair_candidates(session=session)

        self.assertEqual(result["summary"]["candidate_groups"], 1)
        self.assertEqual(result["safety"]["writes_performed"], 0)
        self.assertFalse(result["safety"]["execution_endpoint_available"])
        self.assertNotIn("token", str(result).lower())
        account_query = str(session.scalars.await_args_list[2].args[0]).lower()
        self.assertNotIn("access_token_encrypted", account_query)
        self.assertNotIn("refresh_token_encrypted", account_query)
        session.commit.assert_not_awaited()
        session.flush.assert_not_awaited()
        session.delete.assert_not_awaited()

    def test_candidate_filter_excludes_non_sem_same_name_customers(self):
        tenants = [
            _tenant(1, "SEO 客户"),
            _tenant(2, "SEO 客户"),
            _tenant(3, "SEM 客户"),
            _tenant(4, "SEM 客户"),
        ]
        modules = [
            SimpleNamespace(
                tenant_id=1,
                module_code="seo",
                status="active",
                expires_at=None,
            ),
            SimpleNamespace(
                tenant_id=3,
                module_code="sem",
                status="active",
                expires_at=None,
            ),
        ]
        accounts = [_account(10, 4, 80243027)]

        eligible = _sem_identity_candidate_tenant_ids(
            tenants, modules, accounts, set()
        )
        groups = _sem_duplicate_candidate_groups(
            [tenant for tenant in tenants if tenant.id in eligible],
            accounts,
        )

        self.assertEqual(eligible, {3, 4})
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["normalized_name"], "sem 客户")

    def test_account_identity_query_does_not_select_encrypted_credentials(self):
        query = str(_sem_identity_account_select()).lower()

        self.assertIn("baidu_accounts.baidu_ucid", query)
        self.assertIn("baidu_accounts.auth_mode", query)
        self.assertNotIn("access_token_encrypted", query)
        self.assertNotIn("refresh_token_encrypted", query)

    async def test_preview_endpoint_rejects_customer_without_sem_evidence(self):
        source = _tenant(1, "同名客户")
        target = _tenant(2, "同名客户")
        sem_module = SimpleNamespace(
            tenant_id=1,
            module_code="sem",
            status="active",
            expires_at=None,
        )
        session = SimpleNamespace(
            get=AsyncMock(side_effect=[source, target]),
            scalars=AsyncMock(
                side_effect=[_Rows([sem_module]), _Rows([]), _Rows([])]
            ),
            execute=AsyncMock(),
        )

        with self.assertRaises(HTTPException) as caught:
            await preview_sem_identity_repair(1, 2, session=session)

        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("SEM", caught.exception.detail)
        session.execute.assert_not_awaited()

    async def test_preview_endpoint_accepts_two_sem_evidence_customers_read_only(self):
        source = _tenant(1, "同名客户")
        target = _tenant(2, "同名客户")
        sem_module = SimpleNamespace(
            tenant_id=1,
            module_code="sem",
            status="active",
            expires_at=None,
        )
        target_account = _account(20, 2, 80243027)
        session = SimpleNamespace(
            get=AsyncMock(side_effect=[source, target]),
            scalars=AsyncMock(
                side_effect=[
                    _Rows([sem_module]),
                    _Rows([target_account]),
                    _Rows([]),
                ]
            ),
            commit=AsyncMock(),
            flush=AsyncMock(),
            delete=AsyncMock(),
        )

        with patch(
            "app.api.customer_modules._sem_identity_repair_row_counts",
            new=AsyncMock(return_value={1: {}, 2: {"baidu_accounts": 1}}),
        ):
            result = await preview_sem_identity_repair(1, 2, session=session)

        self.assertTrue(result["safety"]["read_only"])
        account_query = str(session.scalars.await_args_list[1].args[0]).lower()
        self.assertNotIn("access_token_encrypted", account_query)
        self.assertNotIn("refresh_token_encrypted", account_query)
        session.commit.assert_not_awaited()
        session.flush.assert_not_awaited()
        session.delete.assert_not_awaited()

    def test_preview_blocks_conflicting_ucid_and_two_sided_history(self):
        source = _tenant(1, "老虎新材料", 1001)
        target = _tenant(2, " 老虎新材料 ", 2002)
        accounts = [_account(10, 1, 1001), _account(20, 2, 2002)]
        row_counts = {
            1: {"keywords": 8, "baidu_accounts": 1},
            2: {"campaigns": 2, "baidu_accounts": 1},
        }

        result = _sem_identity_repair_preview_payload(
            source, target, accounts, row_counts
        )

        blocker_codes = {item["code"] for item in result["blockers"]}
        self.assertIn("ucid_evidence_conflict", blocker_codes)
        self.assertIn("both_customers_have_sem_history", blocker_codes)
        self.assertTrue(result["safety"]["read_only"])
        self.assertEqual(result["safety"]["writes_performed"], 0)
        self.assertEqual(result["safety"]["migration"], "not-run")
        self.assertNotIn("must-not-leak", str(result))

    def test_preview_blocks_active_account_against_other_customer_primary_ucid(self):
        source = _tenant(1, "诺德", None)
        target = _tenant(2, "诺德", 2002)
        accounts = [_account(10, 1, 1001)]

        result = _sem_identity_repair_preview_payload(
            source, target, accounts, {1: {}, 2: {}}
        )

        self.assertIn(
            "ucid_evidence_conflict",
            {item["code"] for item in result["blockers"]},
        )

    def test_preview_blocks_duplicate_active_account_bindings(self):
        source = _tenant(1, "诺德", 1001)
        target = _tenant(2, "诺德", 1001)
        accounts = [_account(10, 1, 1001), _account(20, 2, 1001)]
        row_counts = {
            1: {"baidu_accounts": 1},
            2: {"baidu_accounts": 1},
        }

        result = _sem_identity_repair_preview_payload(
            source, target, accounts, row_counts
        )

        self.assertIn(
            "duplicate_active_account_bindings",
            {item["code"] for item in result["blockers"]},
        )
        self.assertIn(
            "source_customer_has_identity_only",
            {item["code"] for item in result["warnings"]},
        )
        self.assertNotIn(
            "source_customer_has_no_sem_history",
            {item["code"] for item in result["warnings"]},
        )
        account_operation = next(
            item for item in result["proposed_operations"]
            if item["table"] == "baidu_accounts"
        )
        self.assertEqual(
            account_operation["proposed_action"],
            "manual_identity_resolution_required",
        )

    def test_preview_blocks_duplicate_active_accounts_within_source(self):
        source = _tenant(1, "诺德", 1001)
        target = _tenant(2, "诺德", None)
        accounts = [_account(10, 1, 1001), _account(11, 1, 1001)]

        result = _sem_identity_repair_preview_payload(
            source,
            target,
            accounts,
            {1: {"baidu_accounts": 2}, 2: {}},
        )

        self.assertIn(
            "duplicate_active_accounts_within_customer",
            {item["code"] for item in result["blockers"]},
        )

    def test_preview_blocks_two_sided_oauth_grants(self):
        source = _tenant(1, "诺德", None)
        target = _tenant(2, "诺德", None)
        row_counts = {
            1: {"baidu_oauth_grants": 1},
            2: {"baidu_oauth_grants": 1},
        }

        result = _sem_identity_repair_preview_payload(source, target, [], row_counts)

        self.assertIn(
            "both_customers_have_oauth_grants",
            {item["code"] for item in result["blockers"]},
        )
        grant_operation = next(
            item for item in result["proposed_operations"]
            if item["table"] == "baidu_oauth_grants"
        )
        self.assertEqual(
            grant_operation["proposed_action"],
            "manual_identity_resolution_required",
        )

    def test_preview_blocks_and_preserves_writeback_audit_provenance(self):
        source = _tenant(1, "诺德", None)
        target = _tenant(2, "诺德", None)
        row_counts = {
            1: {"bid_writebacks": 2, "writeback_approvals": 1},
            2: {},
        }

        result = _sem_identity_repair_preview_payload(source, target, [], row_counts)

        self.assertIn(
            "source_has_writeback_audit_history",
            {item["code"] for item in result["blockers"]},
        )
        audit_operations = [
            item for item in result["proposed_operations"]
            if item["category"] == "writeback_audit"
        ]
        self.assertTrue(audit_operations)
        self.assertTrue(
            all(
                item["proposed_action"]
                == "preserve_audit_provenance_manual_review"
                for item in audit_operations
            )
        )

    def test_empty_source_is_only_a_warning_not_an_automatic_merge_decision(self):
        source = _tenant(1, "诺德", None)
        target = _tenant(2, "诺德", 80243027)
        row_counts = {1: {}, 2: {"keywords": 10}}

        result = _sem_identity_repair_preview_payload(source, target, [], row_counts)

        self.assertIn(
            "source_customer_has_no_sem_history",
            {item["code"] for item in result["warnings"]},
        )
        self.assertFalse(result["safety"]["execution_endpoint_available"])
        self.assertIn("separate_database_change_approval", result["required_reviews"])

    def test_table_allowlist_is_sem_only_and_every_table_exists(self):
        table_names = {name for name, _category in SEM_IDENTITY_REPAIR_TABLES}
        tenant_scoped_tables = {
            name for name, table in Base.metadata.tables.items() if "tenant_id" in table.c
        }
        explicitly_non_sem = {
            name
            for name in tenant_scoped_tables
            if name.startswith(("seo_", "geo_"))
            or name in {"tenant_modules", "users", "api_audit_logs"}
        }

        self.assertTrue(table_names)
        self.assertTrue(table_names.issubset(Base.metadata.tables.keys()))
        self.assertNotIn("tenant_modules", table_names)
        self.assertNotIn("users", table_names)
        self.assertNotIn("api_audit_logs", table_names)
        self.assertFalse(any(name.startswith(("seo_", "geo_")) for name in table_names))
        self.assertEqual(tenant_scoped_tables, table_names | explicitly_non_sem)

    def test_frontend_contract_exposes_only_read_only_get_calls(self):
        api_source = (ROOT / "frontend/src/api/moduleAssets.js").read_text(
            encoding="utf-8"
        )
        view_source = (
            ROOT / "frontend/src/views/settings/CustomerModulesView.vue"
        ).read_text(encoding="utf-8")

        repair_lines = [line for line in api_source.splitlines() if "identity-repair" in line]
        self.assertEqual(len(repair_lines), 2)
        self.assertTrue(all("client.get(" in line for line in repair_lines))
        self.assertNotIn("executeSemIdentityRepair", api_source)
        self.assertIn("不会合并客户、迁移记录、删除数据或执行数据库迁移", view_source)
        self.assertIn("execution_endpoint", view_source)
        self.assertIn("repairPreview.source.accounts", view_source)
        self.assertIn("repairPreview.target.accounts", view_source)
        self.assertIn("manual_identity_resolution_required", view_source)
        self.assertIn("禁止直接迁移身份记录", view_source)
        self.assertIn("preserve_audit_provenance_manual_review", view_source)
        self.assertIn("保留原始审计归属", view_source)
        self.assertIn('v-for="row in repairCandidateCustomers"', view_source)
        self.assertIn('v-for="row in repairTargetCustomers"', view_source)
        self.assertNotIn('v-for="row in customers"', view_source)
        self.assertIn("repairTargetCustomers.value.some", view_source)

    def test_backend_exposes_no_identity_repair_mutation_route(self):
        repair_routes = [
            route
            for route in customer_modules_router.routes
            if "/sem-identity-repair/" in route.path
        ]

        self.assertEqual(len(repair_routes), 2)
        self.assertTrue(all(route.methods == {"GET"} for route in repair_routes))
