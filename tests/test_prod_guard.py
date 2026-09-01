"""Production secret guard + nginx inject detector."""

from __future__ import annotations

import base64
import unittest
from types import SimpleNamespace

from app.security.prod_guard import (
    collect_production_issues,
    enforce_production_secrets,
    is_production_env,
    nginx_injects_api_key,
)


class ProdGuardTests(unittest.TestCase):
    def test_env_detect(self):
        self.assertTrue(is_production_env("prod"))
        self.assertTrue(is_production_env("Production"))
        self.assertFalse(is_production_env("dev"))

    def test_demo_key_blocked(self):
        s = SimpleNamespace(
            app_env="prod",
            admin_api_key="geo-demo-local-key",
            jwt_secret="only-jwt",
            crypto_master_key_b64=base64.b64encode(b"0" * 32).decode(),
            app_base_url="https://sem.example.com",
        )
        issues = collect_production_issues(s)
        self.assertTrue(any("ADMIN_API_KEY" in i for i in issues))

    def test_jwt_must_differ(self):
        key = base64.b64encode(b"1" * 32).decode()
        s = SimpleNamespace(
            app_env="production",
            admin_api_key="real-admin-key-long-enough",
            jwt_secret="real-admin-key-long-enough",
            crypto_master_key_b64=key,
            app_base_url="https://sem.example.com",
        )
        issues = collect_production_issues(s)
        self.assertTrue(any("JWT_SECRET" in i for i in issues))

    def test_ok_production(self):
        key = base64.b64encode(b"2" * 32).decode()
        s = SimpleNamespace(
            app_env="prod",
            admin_api_key="real-admin-key-long-enough",
            jwt_secret="other-jwt-secret-long-enough",
            crypto_master_key_b64=key,
            app_base_url="https://gsnipers.snipers.com.cn",
        )
        self.assertEqual(collect_production_issues(s), [])

    def test_production_rejects_noncanonical_or_insecure_app_base_url(self):
        key = base64.b64encode(b"3" * 32).decode()
        common = dict(
            app_env="prod",
            admin_api_key="real-admin-key-long-enough",
            jwt_secret="other-jwt-secret-long-enough",
            crypto_master_key_b64=key,
        )
        for app_base_url in (
            "http://gsnipers.snipers.com.cn",
            "https://gsniper.snipers.com.cn",
            "https://sem.snipers.com.cn",
            "https://gsnipers.snipers.com.cn/unexpected",
        ):
            with self.subTest(app_base_url=app_base_url):
                issues = collect_production_issues(
                    SimpleNamespace(**common, app_base_url=app_base_url)
                )
                self.assertTrue(any("APP_BASE_URL" in issue for issue in issues))

    def test_production_validates_cors_origins_and_oauth_callback(self):
        key = base64.b64encode(b"4" * 32).decode()
        common = dict(
            app_env="prod",
            admin_api_key="real-admin-key-long-enough",
            jwt_secret="other-jwt-secret-long-enough",
            crypto_master_key_b64=key,
            app_base_url="https://gsnipers.snipers.com.cn",
        )
        ok = SimpleNamespace(
            **common,
            cors_allowed_origins=(
                "https://gsnipers.snipers.com.cn,https://sem.snipers.com.cn"
            ),
            baidu_oauth_callback_url=(
                "https://gsnipers.snipers.com.cn/api/oauth/baidu/callback"
            ),
        )
        self.assertEqual(collect_production_issues(ok), [])

        bad = SimpleNamespace(
            **common,
            cors_allowed_origins="http://evil.example",
            baidu_oauth_callback_url="https://evil.example/callback?next=1",
        )
        issues = collect_production_issues(bad)
        self.assertTrue(any("CORS_ALLOWED_ORIGINS" in issue for issue in issues))
        self.assertTrue(any("BAIDU_OAUTH_CALLBACK_URL" in issue for issue in issues))

        malformed = SimpleNamespace(
            **common,
            baidu_oauth_callback_url="https://[invalid/callback",
        )
        malformed_issues = collect_production_issues(malformed)
        self.assertIn(
            "BAIDU_OAUTH_CALLBACK_URL is not a valid URL",
            malformed_issues,
        )

    def test_api_key_query_guard_reports_once(self):
        key = base64.b64encode(b"5" * 32).decode()
        issues = collect_production_issues(
            SimpleNamespace(
                app_env="prod",
                admin_api_key="real-admin-key-long-enough",
                jwt_secret="other-jwt-secret-long-enough",
                crypto_master_key_b64=key,
                app_base_url="https://gsnipers.snipers.com.cn",
                admin_api_key_query_enabled=True,
            )
        )
        matches = [issue for issue in issues if "ADMIN_API_KEY_QUERY_ENABLED" in issue]
        self.assertEqual(len(matches), 1)

    def test_live_baidu_write_requires_nonempty_valid_double_allowlist(self):
        key = base64.b64encode(b"6" * 32).decode()
        common = dict(
            app_env="prod",
            admin_api_key="real-admin-key-long-enough",
            jwt_secret="other-jwt-secret-long-enough",
            crypto_master_key_b64=key,
            app_base_url="https://gsnipers.snipers.com.cn",
            baidu_write_dry_run=False,
        )
        issues = collect_production_issues(SimpleNamespace(**common))
        self.assertTrue(any("BAIDU_LIVE_WRITE_TENANT_IDS" in item for item in issues))
        self.assertTrue(any("BAIDU_LIVE_WRITE_ACCOUNT_IDS" in item for item in issues))

        invalid = collect_production_issues(
            SimpleNamespace(
                **common,
                baidu_live_write_tenant_ids="3,not-an-id",
                baidu_live_write_account_ids="17",
            )
        )
        self.assertTrue(any("positive integers" in item for item in invalid))

        allowed = collect_production_issues(
            SimpleNamespace(
                **common,
                baidu_live_write_tenant_ids="3",
                baidu_live_write_account_ids="17",
            )
        )
        self.assertEqual(allowed, [])

    def test_dev_skips(self):
        s = SimpleNamespace(
            app_env="dev",
            admin_api_key="geo-demo-local-key",
            jwt_secret="",
            crypto_master_key_b64="x",
            app_base_url="http://127.0.0.1:8000",
        )
        self.assertEqual(collect_production_issues(s), [])

    def test_hard_fail(self):
        s = SimpleNamespace(
            app_env="prod",
            admin_api_key="geo-demo-local-key",
            jwt_secret="",
            crypto_master_key_b64="CHANGE_ME",
            app_base_url="http://127.0.0.1:8000",
        )
        with self.assertRaises(RuntimeError):
            enforce_production_secrets(s, hard_fail=True)

    def test_nginx_inject_detect(self):
        bad = "proxy_set_header X-API-Key $geo_key;"
        good = "proxy_set_header Host $host;\n# proxy_set_header X-API-Key never"
        self.assertTrue(nginx_injects_api_key(bad))
        self.assertFalse(nginx_injects_api_key(good))


if __name__ == "__main__":
    unittest.main()
