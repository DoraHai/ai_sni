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
    assert catalog["wechat_official"]["available"] is False


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

    for label in ("平台连接", "发布预检", "优先创建草稿", "复制并打开编辑器", "同一文章可保留多个平台链接"):
        assert label in view
    for function_name in (
        "fetchSeoDistributionConnections",
        "preflightSeoDistribution",
        "publishSeoDistribution",
        "completeSeoManualPublication",
    ):
        assert function_name in api
    credential_keys = {
        field["key"].lower()
        for platform in distribution.platform_catalog()
        for field in platform.get("credential_fields", [])
    }
    assert "cookie" not in credential_keys
