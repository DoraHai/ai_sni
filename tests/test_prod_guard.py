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
            app_base_url="https://sem.example.com",
        )
        self.assertEqual(collect_production_issues(s), [])

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
