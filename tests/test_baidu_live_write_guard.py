import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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

from app.baidu.client import BaiduAPIClient, BaiduLiveWriteBlockedError
from app.config import parse_positive_id_csv


def _settings(*, dry_run: bool, tenants: set[int], accounts: set[int]):
    return SimpleNamespace(
        baidu_api_base_url="https://api.baidu.test",
        baidu_write_dry_run=dry_run,
        baidu_live_write_allowed=lambda tenant_id, account_id: (
            tenant_id in tenants and account_id in accounts
        ),
    )


class BaiduLiveWriteGuardTests(unittest.TestCase):
    def test_allowlist_parser_rejects_ambiguous_or_non_positive_ids(self):
        self.assertEqual(parse_positive_id_csv("7, 9,7", label="TEST"), {7, 9})
        for value in ("0", "-1", "7.0", "7,abc", "７"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_positive_id_csv(value, label="TEST")

    def test_dry_run_blocks_write_before_live_allowlist(self):
        settings = _settings(dry_run=True, tenants=set(), accounts=set())
        with patch("app.baidu.client.get_settings", return_value=settings):
            client = BaiduAPIClient("user", "token")
            result = asyncio.run(
                client.call("KeywordService", "updateWord", {}, is_write=True)
            )
        self.assertTrue(result["_dry_run"])

    def test_live_write_rejects_missing_or_mismatched_scope(self):
        settings = _settings(dry_run=False, tenants={3}, accounts={17})
        with patch("app.baidu.client.get_settings", return_value=settings):
            for tenant_id, account_id in ((None, None), (3, 18), (4, 17)):
                with self.subTest(tenant_id=tenant_id, account_id=account_id):
                    client = BaiduAPIClient(
                        "user",
                        "token",
                        tenant_id=tenant_id,
                        baidu_account_id=account_id,
                    )
                    with self.assertRaises(BaiduLiveWriteBlockedError):
                        asyncio.run(
                            client.call(
                                "KeywordService", "updateWord", {}, is_write=True
                            )
                        )

    def test_live_write_reaches_http_only_for_exact_scope(self):
        settings = _settings(dry_run=False, tenants={3}, accounts={17})
        response = SimpleNamespace(
            status_code=200,
            json=lambda: {"header": {"status": 0}, "body": {"ok": True}},
        )
        http = AsyncMock()
        http.post.return_value = response
        context = AsyncMock()
        context.__aenter__.return_value = http
        context.__aexit__.return_value = False
        with (
            patch("app.baidu.client.get_settings", return_value=settings),
            patch("app.baidu.client.httpx.AsyncClient", return_value=context),
        ):
            client = BaiduAPIClient(
                "user", "token", tenant_id=3, baidu_account_id=17
            )
            result = asyncio.run(
                client.call("KeywordService", "updateWord", {}, is_write=True)
            )
        self.assertEqual(result, {"ok": True})
        http.post.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
