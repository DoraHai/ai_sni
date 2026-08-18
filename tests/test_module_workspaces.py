import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "1234567890abcdefsecret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from fastapi import HTTPException

from app.api.customer_modules import _canonical_domain
from app.api.auth import _MODULE_PERMISSION_KEYS
from app.models import GeoProject, SeoSite, TenantModule
from app.module_scope import normalize_module_code
from app.permissions import CLIENT_PERMS, OPERATOR_PERMS
from app.security.auth import AuthContext, _required


class ModuleWorkspaceTests(unittest.TestCase):
    def test_models_have_independent_subject_tables(self):
        self.assertEqual(TenantModule.__tablename__, "tenant_modules")
        self.assertEqual(SeoSite.__tablename__, "seo_sites")
        self.assertEqual(GeoProject.__tablename__, "geo_projects")

    def test_default_customer_can_edit_own_module_assets_only(self):
        self.assertEqual(CLIENT_PERMS["sem.assets"], "edit")
        self.assertEqual(CLIENT_PERMS["seo.assets"], "edit")
        self.assertEqual(CLIENT_PERMS["geo.assets"], "edit")
        self.assertNotIn("settings.customers", CLIENT_PERMS)
        self.assertNotIn("settings.customers", OPERATOR_PERMS)

    def test_asset_routes_require_their_own_module_permission(self):
        self.assertEqual(_required("/api/v1/sem/assets/accounts", "GET"), ({"sem.assets"}, False))
        self.assertEqual(_required("/api/v1/seo/sites", "POST"), ({"seo.assets"}, True))
        self.assertEqual(_required("/api/v1/geo/projects", "PATCH"), ({"geo.assets"}, True))
        self.assertIn("sem.assets", _MODULE_PERMISSION_KEYS["sem"])
        self.assertIn("seo.assets", _MODULE_PERMISSION_KEYS["seo"])
        self.assertIn("geo.assets", _MODULE_PERMISSION_KEYS["geo"])

    def test_bound_customer_cannot_switch_tenant(self):
        ctx = AuthContext(1, "client", "client", 7, {"seo.assets": "edit"})
        ctx.ensure_tenant(7)
        with self.assertRaises(HTTPException):
            ctx.ensure_tenant(8)

    def test_domain_normalization(self):
        self.assertEqual(_canonical_domain("https://www.Example.com/path")[0], "example.com")
        self.assertEqual(normalize_module_code("SEO"), "seo")
        with self.assertRaises(HTTPException):
            normalize_module_code("diagnosis")


if __name__ == "__main__":
    unittest.main()
