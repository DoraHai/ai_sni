"""Phase 2 website/docs webhook connector."""

from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from app.geo.content.connectors.webhook import (
    WebhookConnectorError,
    build_webhook_payload,
    extract_remote_url,
    normalize_webhook_credentials,
    post_webhook,
)


class WebhookConnectorTests(unittest.IsolatedAsyncioTestCase):
    def test_normalize_requires_https(self):
        with self.assertRaises(WebhookConnectorError):
            normalize_webhook_credentials({"webhook_url": "http://example.com/hook"})

    def test_normalize_defaults(self):
        creds = normalize_webhook_credentials(
            {
                "webhook_url": "https://cms.example.com/hooks/geo",
                "headers": {"Authorization": "Bearer x", "Host": "evil"},
                "secret": "s3cret",
            }
        )
        self.assertEqual(creds["method"], "POST")
        self.assertNotIn("Host", creds["headers"])
        self.assertEqual(creds["headers"]["Authorization"], "Bearer x")
        self.assertEqual(creds["secret"], "s3cret")

    def test_extract_remote_url(self):
        self.assertEqual(
            extract_remote_url({"data": {"permalink": "https://site.com/p/1"}}),
            "https://site.com/p/1",
        )
        self.assertIsNone(extract_remote_url({"ok": True}))

    def test_build_payload(self):
        payload = build_webhook_payload(
            action="draft",
            tenant_id=1,
            task_id=9,
            channel="website",
            channel_type="docs",
            title="T",
            body_markdown="B",
            export_format="markdown",
            base_url="https://docs.example.com",
        )
        self.assertEqual(payload["action"], "draft")
        self.assertEqual(payload["channel_type"], "docs")

    async def test_post_webhook_success(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.method, "POST")
            self.assertIn("X-GEO-Signature", request.headers)
            body = json.loads(request.content.decode("utf-8"))
            self.assertEqual(body["action"], "publish")
            return httpx.Response(200, json={"url": "https://site.com/published"})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            with patch(
                "app.geo.content.connectors.webhook._ensure_public_host",
                new=AsyncMock(return_value=None),
            ):
                result = await post_webhook(
                    {
                        "webhook_url": "https://cms.example.com/hook",
                        "secret": "abc",
                    },
                    {"action": "publish", "task_id": 1},
                    client=client,
                )
        self.assertEqual(result["http_status"], 200)
        self.assertEqual(result["remote_url"], "https://site.com/published")

    async def test_post_webhook_non_2xx(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            with patch(
                "app.geo.content.connectors.webhook._ensure_public_host",
                new=AsyncMock(return_value=None),
            ):
                with self.assertRaises(WebhookConnectorError):
                    await post_webhook(
                        {"webhook_url": "https://cms.example.com/hook"},
                        {"action": "draft"},
                        client=client,
                    )


if __name__ == "__main__":
    unittest.main()
