from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.seo import (
    DistributionAdaptRequest,
    DistributionManualComplete,
    DistributionPreflightRequest,
    DistributionPublishRequest,
    DistributionRetryRequest,
    DistributionVariantReviewRequest,
    DistributionVariantSaveRequest,
    _create_distribution_variant_revision,
    _distribution_content,
    _distribution_variant_payload,
    _require_content_ready,
    adapt_content_distribution,
    complete_manual_publication,
    preflight_content_distribution,
    publish_content_distribution,
    review_distribution_variant,
    retry_content_publication,
)
from app.security.auth import AuthContext
from app.models.seo import (
    SeoContentAsset,
    SeoContentPublication,
    SeoDistributionConnection,
    SeoDistributionVariant,
    SeoKeywordAsset,
    SeoPublishAttempt,
)
from app import seo_distribution as distribution


def test_distribution_requires_an_approved_main_content_asset() -> None:
    draft = SeoContentAsset(tenant_id=1, site_id=1, title="草稿", content_type="article", status="drafting")
    with pytest.raises(Exception) as exc:
        _require_content_ready(draft)
    assert getattr(exc.value, "status_code", None) == 409
    ready = SeoContentAsset(tenant_id=1, site_id=1, title="已审核", content_type="article", status="ready")
    _require_content_ready(ready)
    published = SeoContentAsset(tenant_id=1, site_id=1, title="已发布一次", content_type="article", status="published")
    _require_content_ready(published)


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
    assert catalog["wechat_official"]["content_rules"]["title_max"] == 32
    assert catalog["zhihu"]["content_rules"]["style"]


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
    assert "<script>" not in prepared["content_html"]
    assert "alert(1)" not in prepared["content_html"]

    rich = distribution.prepare_content(
        "富文本",
        '<h2 onclick="steal()">章节</h2><p>正文<script>alert(1)</script><a href="javascript:steal()">链接</a></p>',
        "wordpress",
    )
    assert "script" not in rich["content_html"].lower()
    assert "onclick" not in rich["content_html"].lower()
    assert "javascript:" not in rich["content_html"].lower()
    assert rich["excerpt"] == "章节 正文 链接"

    div_rich = distribution.prepare_content(
        "编辑器正文",
        '<div>第一段</div><div onclick="steal()">第二段<script>alert(1)</script></div>',
        "wordpress",
    )
    assert "script" not in div_rich["content_html"].lower()
    assert "onclick" not in div_rich["content_html"].lower()
    assert div_rich["excerpt"] == "第一段 第二段"

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
    assert SeoDistributionVariant.__tablename__ == "seo_distribution_variants"
    assert SeoContentPublication.__tablename__ == "seo_content_publications"
    assert SeoPublishAttempt.__tablename__ == "seo_publish_attempts"
    assert "tenant_id" in SeoDistributionConnection.__table__.columns
    assert "credentials_encrypted" in SeoDistributionConnection.__table__.columns
    assert "revision_number" in SeoDistributionVariant.__table__.columns
    assert "keyword_checks" in SeoDistributionVariant.__table__.columns
    assert "variant_id" in SeoContentPublication.__table__.columns
    assert "page_url" in SeoContentPublication.__table__.columns
    assert "request_summary" in SeoPublishAttempt.__table__.columns


def test_publish_requests_bound_batch_size_and_require_explicit_confirmation_field() -> None:
    request = DistributionPreflightRequest(
        tenant_id=1,
        site_id=8,
        content_ids=[1, 2],
        connection_ids=[3],
        action="draft",
    )
    publish = DistributionPublishRequest(
        tenant_id=1,
        site_id=8,
        content_id=1,
        connection_id=3,
        action="publish",
    )
    variant = DistributionVariantSaveRequest(
        tenant_id=1,
        site_id=8,
        content_id=1,
        connection_id=3,
        source_version=1,
        title="平台标题",
        content="<p>平台正文</p>",
        status="pending_review",
    )

    assert request.content_ids == [1, 2]
    assert request.site_id == 8
    assert publish.confirm is False
    assert variant.status == "pending_review"
    with pytest.raises(Exception):
        DistributionPreflightRequest(
            tenant_id=1,
            content_ids=list(range(1, 22)),
            connection_ids=[3],
        )


def test_distribution_content_rejects_cross_site_asset() -> None:
    content = SeoContentAsset(
        id=5,
        tenant_id=1,
        site_id=7,
        content_type="article",
        title="测试文章",
        status="drafting",
    )
    session = AsyncMock()
    session.get = AsyncMock(return_value=content)

    with pytest.raises(Exception) as exc:
        asyncio.run(_distribution_content(session, 1, 5, site_id=8))

    assert getattr(exc.value, "status_code", None) == 404


def test_platform_variant_adapts_content_and_reports_keyword_coverage() -> None:
    content = SeoContentAsset(
        id=5,
        tenant_id=1,
        site_id=8,
        keyword_id=21,
        keyword_ids=[21, 22],
        content_type="article",
        title="Growth Sniper SEO 内容分发实战指南",
        draft="<p>Growth Sniper 帮助团队完成 SEO 内容分发，并持续优化关键词排名。</p>",
        status="drafting",
        version_count=3,
    )
    connection = SeoDistributionConnection(
        id=9,
        tenant_id=1,
        platform_code="zhihu",
        name="官方知乎",
        mode="assisted",
        enabled=True,
        status="ready",
    )
    keywords = [
        SeoKeywordAsset(id=21, tenant_id=1, site_id=8, keyword="SEO 内容分发", status="tracking"),
        SeoKeywordAsset(id=22, tenant_id=1, site_id=8, keyword="关键词排名", status="tracking"),
    ]
    request = DistributionAdaptRequest(
        tenant_id=1,
        site_id=8,
        content_id=5,
        connection_id=9,
    )
    context = AuthContext(
        user_id=7,
        username="operator",
        role_name="运营",
        tenant_id=1,
        permissions={"seo.content": "edit"},
    )

    with (
        patch("app.api.seo._seo_site", new=AsyncMock()),
        patch("app.api.seo._distribution_content", new=AsyncMock(return_value=content)),
        patch("app.api.seo._distribution_connection", new=AsyncMock(return_value=connection)),
        patch("app.api.seo._content_keywords", new=AsyncMock(return_value=keywords)),
    ):
        result = asyncio.run(adapt_content_distribution(request, AsyncMock(), context))

    assert result["platform_name"] == "知乎"
    assert result["source_version"] == 3
    assert result["content_rules"]["title_max"] == 60
    assert result["source_content_html"].startswith("<p>")
    assert all(item["in_content"] for item in result["keyword_checks"])
    assert result["ai_generated"] is False


def test_ai_platform_variant_retries_missing_keyword_and_sanitizes_html() -> None:
    content = SeoContentAsset(
        id=5,
        tenant_id=1,
        site_id=8,
        keyword_id=21,
        keyword_ids=[21],
        content_type="article",
        title="内容分发指南",
        draft="<p>原始正文包含 SEO 内容分发。</p>",
        status="drafting",
        version_count=2,
    )
    connection = SeoDistributionConnection(
        id=9,
        tenant_id=1,
        platform_code="zhihu",
        name="官方知乎",
        mode="assisted",
        enabled=True,
        status="ready",
    )
    keyword = SeoKeywordAsset(id=21, tenant_id=1, site_id=8, keyword="SEO 内容分发", status="tracking")
    request = DistributionAdaptRequest(
        tenant_id=1,
        site_id=8,
        content_id=5,
        connection_id=9,
        use_ai=True,
        instruction="面向内容运营负责人",
    )
    context = AuthContext(
        user_id=7,
        username="operator",
        role_name="运营",
        tenant_id=1,
        permissions={"seo.content": "edit"},
    )
    chat_mock = AsyncMock(
        side_effect=[
            {"title": "首轮标题", "content": "<p>首轮遗漏关键词</p>", "feedback": "首轮"},
            {"title": "SEO 内容分发实践", "content": "<p>SEO 内容分发修订稿</p><script>bad()</script>", "feedback": "已修订"},
        ]
    )

    with (
        patch("app.api.seo._seo_site", new=AsyncMock()),
        patch("app.api.seo._distribution_content", new=AsyncMock(return_value=content)),
        patch("app.api.seo._distribution_connection", new=AsyncMock(return_value=connection)),
        patch("app.api.seo._content_keywords", new=AsyncMock(return_value=[keyword])),
        patch("app.api.seo._tenant", new=AsyncMock(return_value=SimpleNamespace(name="Growth Sniper", industry="SaaS"))),
        patch("app.api.seo.is_enabled", return_value=True),
        patch("app.api.seo.chat_json", new=chat_mock),
    ):
        result = asyncio.run(adapt_content_distribution(request, AsyncMock(), context))

    assert chat_mock.await_count == 2
    assert result["ai_generated"] is True
    assert result["feedback"] == "已修订"
    assert result["keyword_checks"][0]["in_content"] is True
    assert "script" not in result["content_html"].lower()


def test_distribution_variant_revision_is_persisted_and_stale_is_computed() -> None:
    content = SeoContentAsset(
        id=5,
        tenant_id=1,
        site_id=8,
        keyword_id=21,
        keyword_ids=[21],
        content_type="article",
        title="SEO 内容分发指南",
        draft="<p>SEO 内容分发原文</p>",
        status="drafting",
        version_count=3,
    )
    connection = SeoDistributionConnection(
        id=9,
        tenant_id=1,
        platform_code="zhihu",
        name="官方知乎",
        mode="assisted",
        enabled=True,
        status="ready",
    )
    latest = SeoDistributionVariant(
        id=31,
        tenant_id=1,
        content_asset_id=5,
        connection_id=9,
        platform_code="zhihu",
        source_version=3,
        revision_number=2,
        status="draft",
        title="旧稿",
        content="<p>旧稿</p>",
        content_chars=2,
    )
    keyword = SeoKeywordAsset(id=21, tenant_id=1, site_id=8, keyword="SEO 内容分发", status="active")
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=latest)
    session.add = MagicMock()
    session.flush = AsyncMock()

    with patch("app.api.seo._content_keywords", new=AsyncMock(return_value=[keyword])):
        row = asyncio.run(
            _create_distribution_variant_revision(
                session,
                tenant_id=1,
                content=content,
                connection=connection,
                source_version=3,
                title="SEO 内容分发实践",
                body="<div>SEO 内容分发正文</div><script>bad()</script>",
                status="pending_review",
                ai_generated=True,
                instruction="面向运营负责人",
                feedback="已优化",
                created_by=7,
            )
        )

    assert row.revision_number == 3
    assert row.status == "pending_review"
    assert row.ai_generated is True
    assert row.keyword_checks[0]["in_content"] is True
    assert "script" not in row.content.lower()
    session.add.assert_called_once_with(row)

    content.version_count = 4
    payload = _distribution_variant_payload(row, content=content, connection=connection)
    assert payload["status"] == "stale"
    assert payload["stored_status"] == "pending_review"
    assert payload["current_source_version"] == 4


def test_distribution_variant_review_approves_only_latest_current_revision() -> None:
    content = SeoContentAsset(
        id=5,
        tenant_id=1,
        site_id=8,
        keyword_id=21,
        keyword_ids=[21],
        content_type="article",
        title="SEO 内容分发指南",
        draft="<p>SEO 内容分发原文</p>",
        status="drafting",
        version_count=3,
    )
    connection = SeoDistributionConnection(
        id=9,
        tenant_id=1,
        platform_code="zhihu",
        name="官方知乎",
        mode="assisted",
        enabled=True,
        status="ready",
    )
    row = SeoDistributionVariant(
        id=32,
        tenant_id=1,
        content_asset_id=5,
        connection_id=9,
        platform_code="zhihu",
        source_version=3,
        revision_number=3,
        status="pending_review",
        title="SEO 内容分发实践",
        content="<p>SEO 内容分发正文</p>",
        content_chars=10,
    )
    keyword = SeoKeywordAsset(id=21, tenant_id=1, site_id=8, keyword="SEO 内容分发", status="active")
    session = AsyncMock()
    session.get = AsyncMock(return_value=row)
    session.commit = AsyncMock()
    context = AuthContext(
        user_id=7,
        username="reviewer",
        role_name="运营",
        tenant_id=1,
        permissions={"seo.content": "edit"},
    )
    request = DistributionVariantReviewRequest(
        tenant_id=1,
        site_id=8,
        decision="approve",
        note="事实与排版已核对",
    )

    with (
        patch("app.api.seo._seo_site", new=AsyncMock()),
        patch("app.api.seo._distribution_content", new=AsyncMock(return_value=content)),
        patch("app.api.seo._distribution_connection", new=AsyncMock(return_value=connection)),
        patch("app.api.seo._latest_distribution_variant", new=AsyncMock(return_value=row)),
        patch("app.api.seo._content_keywords", new=AsyncMock(return_value=[keyword])),
    ):
        result = asyncio.run(review_distribution_variant(32, request, session, context))

    assert result["status"] == "approved"
    assert row.reviewed_by == 7
    assert row.review_note == "事实与排版已核对"
    session.commit.assert_awaited_once()


def test_approved_persisted_variant_is_bound_to_publication() -> None:
    content = SeoContentAsset(
        id=5,
        tenant_id=1,
        site_id=8,
        keyword_id=21,
        keyword_ids=[21],
        content_type="article",
        title="原始文章",
        draft="<p>原始正文</p>",
        status="ready",
        version_count=3,
    )
    connection = SeoDistributionConnection(
        id=9,
        tenant_id=1,
        platform_code="zhihu",
        name="官方知乎",
        mode="assisted",
        enabled=True,
        status="ready",
    )
    variant = SeoDistributionVariant(
        id=33,
        tenant_id=1,
        content_asset_id=5,
        connection_id=9,
        platform_code="zhihu",
        source_version=3,
        revision_number=1,
        status="approved",
        title="SEO 内容分发专属标题",
        content="<p>SEO 内容分发专属正文</p>",
        content_chars=12,
    )
    keyword = SeoKeywordAsset(id=21, tenant_id=1, site_id=8, keyword="SEO 内容分发", status="active")
    session = AsyncMock()
    session.get = AsyncMock(return_value=variant)
    session.scalar = AsyncMock(side_effect=[None, None])
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    context = AuthContext(
        user_id=7,
        username="operator",
        role_name="运营",
        tenant_id=1,
        permissions={"seo.content": "edit"},
    )
    request = DistributionPublishRequest(
        tenant_id=1,
        site_id=8,
        content_id=5,
        connection_id=9,
        variant_id=33,
        action="draft",
    )

    with (
        patch("app.api.seo._seo_site", new=AsyncMock()),
        patch("app.api.seo._distribution_content", new=AsyncMock(return_value=content)),
        patch("app.api.seo._distribution_connection", new=AsyncMock(return_value=connection)),
        patch("app.api.seo._latest_distribution_variant", new=AsyncMock(return_value=variant)),
        patch("app.api.seo._content_keywords", new=AsyncMock(return_value=[keyword])),
        patch("app.api.seo.decrypt_credentials", return_value={}),
        patch(
            "app.api.seo.publish_content",
            new=AsyncMock(
                return_value=distribution.RemotePublishResult(
                    status="manual_required",
                    response_summary={"handoff_url": "https://zhuanlan.zhihu.com/write"},
                )
            ),
        ),
    ):
        result = asyncio.run(publish_content_distribution(request, session, context))

    publication = session.add.call_args_list[0].args[0]
    assert publication.variant_id == 33
    assert publication.adapted_title == "SEO 内容分发专属标题"
    assert "SEO 内容分发专属正文" in publication.adapted_content
    assert result["variant_id"] == 33
    assert result["status"] == "manual_required"


def test_custom_variant_rejects_stale_source_and_missing_target_keyword() -> None:
    content = SeoContentAsset(
        id=5,
        tenant_id=1,
        site_id=8,
        keyword_id=21,
        keyword_ids=[21],
        content_type="article",
        title="SEO 内容分发",
        draft="<p>SEO 内容分发正文</p>",
        status="ready",
        version_count=4,
    )
    connection = SeoDistributionConnection(
        id=9,
        tenant_id=1,
        platform_code="wordpress",
        name="品牌官网",
        mode="api",
        base_url="https://example.com",
        enabled=True,
        status="connected",
        has_credentials=True,
    )
    keyword = SeoKeywordAsset(id=21, tenant_id=1, site_id=8, keyword="SEO 内容分发", status="tracking")
    context = AuthContext(
        user_id=7,
        username="operator",
        role_name="运营",
        tenant_id=1,
        permissions={"seo.content": "edit"},
    )

    stale = DistributionPublishRequest(
        tenant_id=1,
        site_id=8,
        content_id=5,
        connection_id=9,
        source_version=3,
        adapted_title="专属标题",
        adapted_content="<p>SEO 内容分发专属稿</p>",
    )
    with (
        patch("app.api.seo._seo_site", new=AsyncMock()),
        patch("app.api.seo._distribution_content", new=AsyncMock(return_value=content)),
    ):
        with pytest.raises(Exception) as exc:
            asyncio.run(publish_content_distribution(stale, AsyncMock(), context))
    assert getattr(exc.value, "status_code", None) == 409
    assert "新版本" in str(getattr(exc.value, "detail", ""))

    missing = stale.model_copy(update={"source_version": 4, "adapted_content": "<div>没有目标词的专属正文</div>"})
    with (
        patch("app.api.seo._seo_site", new=AsyncMock()),
        patch("app.api.seo._distribution_content", new=AsyncMock(return_value=content)),
        patch("app.api.seo._distribution_connection", new=AsyncMock(return_value=connection)),
        patch("app.api.seo._content_keywords", new=AsyncMock(return_value=[keyword])),
        patch("app.api.seo.decrypt_credentials", return_value={"username": "u", "application_password": "p"}),
    ):
        with pytest.raises(Exception) as exc:
            asyncio.run(publish_content_distribution(missing, AsyncMock(), context))
    assert getattr(exc.value, "status_code", None) == 400
    assert "SEO 内容分发" in str(getattr(exc.value, "detail", ""))


def test_preflight_blocks_unconfigured_api_connection() -> None:
    content = SeoContentAsset(
        id=5,
        tenant_id=1,
        site_id=8,
        content_type="article",
        title="测试文章",
        draft="<p>正文内容</p>",
        status="drafting",
        version_count=1,
    )
    connection = SeoDistributionConnection(
        id=9,
        tenant_id=1,
        platform_code="wordpress",
        name="品牌官网",
        mode="api",
        enabled=True,
        status="configured",
        has_credentials=False,
    )
    session = AsyncMock()
    session.scalars = AsyncMock(return_value=[])
    context = AuthContext(
        user_id=7,
        username="operator",
        role_name="运营",
        tenant_id=1,
        permissions={"seo.content": "edit"},
    )
    request = DistributionPreflightRequest(
        tenant_id=1,
        site_id=8,
        content_ids=[5],
        connection_ids=[9],
        action="draft",
    )

    with (
        patch("app.api.seo._seo_site", new=AsyncMock()),
        patch("app.api.seo._distribution_content", new=AsyncMock(return_value=content)),
        patch("app.api.seo._distribution_connection", new=AsyncMock(return_value=connection)),
    ):
        result = asyncio.run(preflight_content_distribution(request, session, context))

    assert result["blocked"] == 1
    assert "API 平台尚未通过连接测试" in result["rows"][0]["errors"]
    assert "API 平台尚未配置授权信息" in result["rows"][0]["errors"]


def test_failed_publication_retry_requires_explicit_platform_confirmation() -> None:
    request = DistributionRetryRequest(tenant_id=1, site_id=8, confirm=False)
    context = AuthContext(
        user_id=7,
        username="operator",
        role_name="运营",
        tenant_id=1,
        permissions={"seo.content": "edit"},
    )

    with patch("app.api.seo._seo_site", new=AsyncMock()):
        with pytest.raises(Exception) as exc:
            asyncio.run(retry_content_publication(12, request, AsyncMock(), context))

    assert getattr(exc.value, "status_code", None) == 400
    assert "核对平台后台" in str(getattr(exc.value, "detail", ""))


def test_confirmed_failed_task_retries_same_content_version() -> None:
    publication = SeoContentPublication(
        id=12,
        tenant_id=1,
        content_asset_id=5,
        connection_id=9,
        platform_code="wordpress",
        platform_name="WordPress",
        publish_mode="draft",
        status="failed",
        source_version=2,
        adapted_title="知乎专属 SEO 标题",
        adapted_content="<div>保留的专属正文</div>",
        last_error="上次请求失败",
    )
    content = SeoContentAsset(
        id=5,
        tenant_id=1,
        site_id=8,
        content_type="article",
        title="测试文章",
        draft="<p>正文内容</p>",
        status="drafting",
        version_count=2,
    )
    connection = SeoDistributionConnection(
        id=9,
        tenant_id=1,
        platform_code="wordpress",
        name="品牌官网",
        mode="api",
        base_url="https://example.com",
        enabled=True,
        status="connected",
        has_credentials=True,
    )
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=publication)
    session.add = MagicMock()
    session.commit = AsyncMock()
    context = AuthContext(
        user_id=7,
        username="operator",
        role_name="运营",
        tenant_id=1,
        permissions={"seo.content": "edit"},
    )
    request = DistributionRetryRequest(tenant_id=1, site_id=8, confirm=True)

    publish_mock = AsyncMock(
        return_value=distribution.RemotePublishResult(
            status="draft_created",
            external_id="post-1",
            page_url="https://example.com/post-1",
            response_summary={"http_status": 201},
        )
    )
    with (
        patch("app.api.seo._seo_site", new=AsyncMock()),
        patch("app.api.seo._distribution_content", new=AsyncMock(return_value=content)),
        patch("app.api.seo._distribution_connection", new=AsyncMock(return_value=connection)),
        patch("app.api.seo.decrypt_credentials", return_value={"username": "u", "application_password": "p"}),
        patch("app.api.seo.publish_content", new=publish_mock),
    ):
        result = asyncio.run(retry_content_publication(12, request, session, context))

    attempt = session.add.call_args.args[0]
    assert attempt.action == "retry_draft"
    assert attempt.status == "succeeded"
    assert publication.status == "draft_created"
    assert publication.last_error is None
    assert result["external_id"] == "post-1"
    prepared = publish_mock.await_args.args[3]
    assert prepared["title"] == "知乎专属 SEO 标题"
    assert "保留的专属正文" in prepared["content_html"]


def test_manual_handoff_completion_is_site_scoped_and_audited() -> None:
    publication = SeoContentPublication(
        id=12,
        tenant_id=1,
        content_asset_id=5,
        platform_code="zhihu",
        platform_name="知乎",
        publish_mode="assisted",
        status="manual_required",
        source_version=2,
    )
    content = SeoContentAsset(
        id=5,
        tenant_id=1,
        site_id=8,
        content_type="article",
        title="测试文章",
        status="drafting",
        version_count=2,
    )
    session = AsyncMock()
    session.get = AsyncMock(return_value=publication)
    session.scalar = AsyncMock(return_value=None)
    session.add = MagicMock()
    session.commit = AsyncMock()
    context = AuthContext(
        user_id=7,
        username="operator",
        role_name="运营",
        tenant_id=1,
        permissions={"seo.content": "edit"},
    )
    request = DistributionManualComplete(
        tenant_id=1,
        site_id=8,
        page_url="https://zhuanlan.zhihu.com/p/123",
    )
    content_lookup = AsyncMock(return_value=content)

    with (
        patch("app.api.seo._seo_site", new=AsyncMock()),
        patch("app.api.seo._distribution_content", new=content_lookup),
    ):
        result = asyncio.run(complete_manual_publication(12, request, session, context))

    attempt = session.add.call_args.args[0]
    content_lookup.assert_awaited_once_with(session, 1, 5, 8)
    assert attempt.action == "manual_complete"
    assert attempt.response_summary == {"page_url_host": "zhuanlan.zhihu.com"}
    assert publication.status == "published"
    assert result["page_url"] == "https://zhuanlan.zhihu.com/p/123"


def test_distribution_migration_backfills_legacy_links_and_is_linear() -> None:
    root = Path(__file__).parents[1]
    migration = (root / "migrations/versions/20260819_0071_seo_distribution_publishing.py").read_text(encoding="utf-8")

    assert 'revision: str = "0071_seo_distribution"' in migration
    assert 'down_revision: Union[str, None] = "0070_seo_content_keywords"' in migration
    assert "INSERT INTO seo_content_publications" in migration
    assert "WHERE page_url IS NOT NULL" in migration
    assert migration.index('op.drop_table("seo_publish_attempts")') < migration.index('op.drop_table("seo_content_publications")')

    variant_migration = (root / "migrations/versions/20260819_0073_seo_distribution_variants.py").read_text(encoding="utf-8")
    assert 'revision: str = "0073_seo_distribution_variants"' in variant_migration
    assert 'down_revision: Union[str, None] = "0072_merge_login_seo"' in variant_migration
    assert '"seo_distribution_variants"' in variant_migration
    assert '"variant_id"' in variant_migration
    assert variant_migration.index('op.drop_column("seo_content_publications", "variant_id")') < variant_migration.index('op.drop_table("seo_distribution_variants")')


def test_distribution_frontend_exposes_guided_publish_flow() -> None:
    root = Path(__file__).parents[1]
    view = (root / "frontend/src/views/seo/SeoDistributionView.vue").read_text(encoding="utf-8")
    api = (root / "frontend/src/api/seo.js").read_text(encoding="utf-8")

    for label in ("平台连接", "编辑平台连接", "保存并测试", "发布预检", "优先创建草稿", "平台专属稿", "AI 生成平台专属稿", "目标关键词覆盖", "保存草稿", "提交审核", "专属稿审核", "修订记录", "批量生成基础稿", "AI 批量生成并提交审核", "辅助发布交接台", "复制正文（保留格式）", "打开官方编辑器", "确认后重试", "发布尝试记录", "同一文章可保留多个平台链接", "正在转存"):
        assert label in view
    for function_name in (
        "fetchSeoDistributionConnections",
        "adaptSeoDistributionContent",
        "fetchSeoDistributionVariants",
        "saveSeoDistributionVariant",
        "generateSeoDistributionVariants",
        "reviewSeoDistributionVariant",
        "fetchSeoDistributionVariantHistory",
        "preflightSeoDistribution",
        "publishSeoDistribution",
        "completeSeoManualPublication",
        "syncSeoContentPublication",
        "retrySeoContentPublication",
        "fetchSeoPublicationAttempts",
    ):
        assert function_name in api
    credential_keys = {
        field["key"].lower()
        for platform in distribution.platform_catalog()
        for field in platform.get("credential_fields", [])
    }
    assert "cookie" not in credential_keys
