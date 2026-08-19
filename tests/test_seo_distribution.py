from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.api.seo import DistributionPreflightRequest, DistributionPublishRequest
from app.models.seo import (
    SeoContentPublication,
    SeoDistributionConnection,
    SeoPublishAttempt,
)
from app import seo_distribution as distribution


def test_platform_catalog_distinguishes_api_assisted_and_planned_channels() -> None:
    catalog = {item["code"]: item for item in distribution.platform_catalog()}

    assert catalog["wordpress"]["mode"] == "api"
    assert catalog["wordpress"]["available"] is True
    assert {"draft", "publish"} <= set(catalog["wordpress"]["capabilities"])
    assert catalog["zhihu"]["mode"] == "assisted"
    assert catalog["zhihu"]["credential_fields"] == []
    assert catalog["wechat_official"]["available"] is True
    assert catalog["wechat_official"]["base_url_required"] is False
    assert "async_status" in catalog["wechat_official"]["capabilities"]


@pytest.mark.parametrize(
    "value",
    [
        "http://example.com",
        "https://localhost",
        "https://127.0.0.1",
        "https://10.0.0.2",
        "https://user:password@example.com",
        "https://example.com?token=secret",
    ],
)
def test_api_connection_base_url_rejects_unsafe_targets(value: str) -> None:
    with pytest.raises(distribution.SeoDistributionError):
        distribution.normalize_base_url(value)


def test_credentials_are_platform_bounded_and_content_is_prepared_safely() -> None:
    credentials = distribution.normalize_credentials(
        "wordpress",
        {"username": "writer", "application_password": "secret", "ignored": "no"},
    )
    prepared = distribution.prepare_content("  SEO   指南  ", "第一段\n<script>alert(1)</script>", "wordpress")

    assert credentials == {"username": "writer", "application_password": "secret"}
    assert prepared["title"] == "SEO 指南"
    assert "&lt;script&gt;" in prepared["content_html"]
    assert "<script>" not in prepared["content_html"]

    rich = distribution.prepare_content(
        "富文本",
        '<h2 onclick="steal()">章节</h2><p>正文<script>alert(1)</script><a href="javascript:steal()">链接</a></p>',
        "wordpress",
    )
    assert "script" not in rich["content_html"].lower()
    assert "onclick" not in rich["content_html"].lower()
    assert "javascript:" not in rich["content_html"].lower()
    assert rich["excerpt"] == "章节 正文 链接"

    svg = distribution.prepare_content(
        "富文本",
        '<p>正文</p><svg><animate attributeName="href" /></svg>',
        "wordpress",
    )
    assert "svg" not in svg["content_html"].lower()


def test_publication_idempotency_is_stable_and_action_specific() -> None:
    first = distribution.publication_idempotency_key(1, 2, 3, 4, "draft")
    repeat = distribution.publication_idempotency_key(1, 2, 3, 4, "draft")
    published = distribution.publication_idempotency_key(1, 2, 3, 4, "publish")

    assert first == repeat
    assert first != published
    assert len(first) == 64


def test_assisted_publish_returns_handoff_without_platform_credentials() -> None:
    result = asyncio.run(
        distribution.publish_content(
            "zhihu",
            None,
            {},
            distribution.prepare_content("标题", "正文", "zhihu"),
            "draft",
        )
    )

    assert result.status == "manual_required"
    assert result.response_summary["handoff_url"].startswith("https://")


def test_wordpress_adapter_uses_official_post_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    class FakeResponse:
        status_code = 201
        content = b"{}"

        def json(self) -> dict:
            return {"id": 88, "link": "https://blog.example.com/seo-guide"}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, **kwargs):
            calls.append({"url": url, **kwargs})
            return FakeResponse()

    async def public_endpoint(value: str) -> str:
        return value

    monkeypatch.setattr(distribution, "ensure_public_endpoint", public_endpoint)
    monkeypatch.setattr(distribution.httpx, "AsyncClient", lambda **_kwargs: FakeClient())

    result = asyncio.run(
        distribution.publish_content(
            "wordpress",
            "https://blog.example.com",
            {"username": "writer", "application_password": "app-pass"},
            distribution.prepare_content("SEO 指南", "正文内容", "wordpress"),
            "draft",
        )
    )

    assert result.status == "draft_created"
    assert result.external_id == "88"
    assert calls[0]["url"] == "https://blog.example.com/wp-json/wp/v2/posts"
    assert calls[0]["json"]["status"] == "draft"
    assert calls[0]["auth"] == ("writer", "app-pass")


def test_wechat_adapter_creates_draft_submits_publish_and_syncs_status(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []
    responses = [
        {"access_token": "token", "expires_in": 7200},
        {"media_id": "draft-media"},
        {"publish_id": "publish-job"},
        {
            "publish_status": 0,
            "article_id": "article-id",
            "article_detail": {"item": [{"article_url": "https://mp.weixin.qq.com/s/example"}]},
        },
    ]

    class FakeResponse:
        status_code = 200
        content = b"{}"

        def __init__(self, body):
            self.body = body

        def json(self):
            return self.body

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, **kwargs):
            calls.append({"method": "GET", "url": url, **kwargs})
            return FakeResponse(responses.pop(0))

        async def post(self, url, **kwargs):
            calls.append({"method": "POST", "url": url, **kwargs})
            return FakeResponse(responses.pop(0))

    monkeypatch.setattr(distribution.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    distribution._WECHAT_TOKEN_CACHE.clear()
    credentials = {"app_id": "appid", "app_secret": "secret", "thumb_media_id": "cover"}
    published = asyncio.run(
        distribution.publish_content(
            "wechat_official",
            None,
            credentials,
            distribution.prepare_content("微信公众号 SEO 标题", "正文", "wechat_official"),
            "publish",
        )
    )
    synced = asyncio.run(
        distribution.sync_publish_status("wechat_official", credentials, published.external_id)
    )

    assert published.status == "publishing"
    assert published.external_id == "publish-job"
    assert calls[0]["url"].endswith("/cgi-bin/stable_token")
    assert calls[0]["json"]["force_refresh"] is False
    assert calls[1]["url"].endswith("/cgi-bin/draft/add")
    assert calls[1]["json"]["articles"][0]["thumb_media_id"] == "cover"
    assert calls[2]["url"].endswith("/cgi-bin/freepublish/submit")
    assert calls[3]["url"].endswith("/cgi-bin/freepublish/get")
    assert synced.status == "published"
    assert synced.page_url == "https://mp.weixin.qq.com/s/example"


def test_wechat_body_images_are_uploaded_deduplicated_and_replaced(monkeypatch: pytest.MonkeyPatch) -> None:
    uploads: list[dict] = []

    class FakeResponse:
        status_code = 200
        content = b"{}"

        def json(self):
            return {"url": "https://mmbiz.qpic.cn/material/image"}

    class FakeClient:
        async def post(self, url, **kwargs):
            uploads.append({"url": url, **kwargs})
            return FakeResponse()

    async def fake_download(value: str, position: int):
        assert value == "https://cdn.example.com/article.png"
        return f"article-{position}.png", b"\x89PNG\r\n\x1a\ncontent", "image/png"

    monkeypatch.setattr(distribution, "_download_wechat_image", fake_download)
    rewritten, count = asyncio.run(
        distribution._rewrite_wechat_images(
            FakeClient(),
            "access-token",
            '<p><img src="https://cdn.example.com/article.png"><img data-src="https://cdn.example.com/article.png"></p>',
        )
    )

    assert count == 2
    assert len(uploads) == 1
    assert uploads[0]["url"].endswith("/cgi-bin/media/uploadimg")
    assert uploads[0]["params"] == {"access_token": "access-token"}
    assert uploads[0]["files"]["media"][2] == "image/png"
    assert rewritten.count('src="https://mmbiz.qpic.cn/material/image"') == 2
    assert "data-src" not in rewritten


def test_wechat_body_images_reject_private_targets_and_excessive_count() -> None:
    with pytest.raises(distribution.SeoDistributionError, match="内网"):
        asyncio.run(distribution._ensure_public_image_url("http://127.0.0.1/private.png"))

    content = "<p>" + "".join(
        f'<img src="https://cdn.example.com/{index}.png">' for index in range(21)
    ) + "</p>"
    with pytest.raises(distribution.SeoDistributionError, match="最多自动处理"):
        asyncio.run(distribution._rewrite_wechat_images(object(), "token", content))


def test_wechat_image_download_stream_checks_actual_format_and_size(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeStreamResponse:
        status_code = 200
        headers = {"content-length": "12"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def aiter_bytes(self):
            yield b"not-an-image"

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def stream(self, *_args, **_kwargs):
            return FakeStreamResponse()

    async def public_url(value: str) -> str:
        return value

    monkeypatch.setattr(distribution, "_ensure_public_image_url", public_url)
    monkeypatch.setattr(distribution.httpx, "AsyncClient", lambda **_kwargs: FakeClient())

    with pytest.raises(distribution.SeoDistributionError, match="JPG/PNG"):
        asyncio.run(distribution._download_wechat_image("https://cdn.example.com/fake.jpg", 1))

    FakeStreamResponse.headers = {"content-length": str(distribution._WECHAT_IMAGE_MAX_BYTES + 1)}
    with pytest.raises(distribution.SeoDistributionError, match="1MB"):
        asyncio.run(distribution._download_wechat_image("https://cdn.example.com/large.jpg", 1))


def test_distribution_models_are_tenant_scoped_and_keep_credentials_private() -> None:
    assert SeoDistributionConnection.__tablename__ == "seo_distribution_connections"
    assert SeoContentPublication.__tablename__ == "seo_content_publications"
    assert SeoPublishAttempt.__tablename__ == "seo_publish_attempts"
    assert "tenant_id" in SeoDistributionConnection.__table__.columns
    assert "credentials_encrypted" in SeoDistributionConnection.__table__.columns
    assert "page_url" in SeoContentPublication.__table__.columns
    assert "request_summary" in SeoPublishAttempt.__table__.columns


def test_publish_requests_bound_batch_size_and_require_explicit_confirmation_field() -> None:
    request = DistributionPreflightRequest(
        tenant_id=1,
        content_ids=[1, 2],
        connection_ids=[3],
        action="draft",
    )
    publish = DistributionPublishRequest(
        tenant_id=1,
        content_id=1,
        connection_id=3,
        action="publish",
    )

    assert request.content_ids == [1, 2]
    assert publish.confirm is False
    with pytest.raises(Exception):
        DistributionPreflightRequest(
            tenant_id=1,
            content_ids=list(range(1, 22)),
            connection_ids=[3],
        )


def test_distribution_migration_backfills_legacy_links_and_is_linear() -> None:
    root = Path(__file__).parents[1]
    migration = (root / "migrations/versions/20260819_0071_seo_distribution_publishing.py").read_text(encoding="utf-8")

    assert 'revision: str = "0071_seo_distribution"' in migration
    assert 'down_revision: Union[str, None] = "0070_seo_content_keywords"' in migration
    assert "INSERT INTO seo_content_publications" in migration
    assert "WHERE page_url IS NOT NULL" in migration
    assert migration.index('op.drop_table("seo_publish_attempts")') < migration.index('op.drop_table("seo_content_publications")')


def test_distribution_frontend_exposes_guided_publish_flow() -> None:
    root = Path(__file__).parents[1]
    view = (root / "frontend/src/views/seo/SeoDistributionView.vue").read_text(encoding="utf-8")
    api = (root / "frontend/src/api/seo.js").read_text(encoding="utf-8")

    for label in ("平台连接", "发布预检", "优先创建草稿", "复制并打开编辑器", "同一文章可保留多个平台链接", "正在转存"):
        assert label in view
    for function_name in (
        "fetchSeoDistributionConnections",
        "preflightSeoDistribution",
        "publishSeoDistribution",
        "completeSeoManualPublication",
        "syncSeoContentPublication",
    ):
        assert function_name in api
    credential_keys = {
        field["key"].lower()
        for platform in distribution.platform_catalog()
        for field in platform.get("credential_fields", [])
    }
    assert "cookie" not in credential_keys
