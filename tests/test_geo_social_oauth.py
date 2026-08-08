"""Social OAuth / WeChat MP unit tests (no network)."""

from __future__ import annotations

import os

import pytest

from app.geo.content.connectors.oauth2 import (
    build_authorize_url,
    parse_oauth_state,
    sign_oauth_state,
    token_needs_refresh,
)
from app.geo.content.connectors.social import (
    build_social_payload,
    normalize_social_credentials,
    resolve_provider,
)
from app.geo.content.connectors.wechat_mp import publish_wechat_mp, wechat_mp_mock_enabled


def test_sign_and_parse_state():
    st = sign_oauth_state(tenant_id=1, account_id=42, ttl_sec=300)
    p = parse_oauth_state(st)
    assert p["tenant_id"] == 1
    assert p["account_id"] == 42


def test_resolve_provider_heuristics():
    assert resolve_provider({"app_id": "wx1", "app_secret": "s"}) == "wechat_mp"
    assert (
        resolve_provider(
            {
                "client_id": "c",
                "authorize_url": "https://a/x",
                "token_url": "https://a/t",
            }
        )
        == "oauth2"
    )
    assert resolve_provider({"api_url": "https://x", "access_token": "t", "platform": "wechat"}) == "gateway"


def test_normalize_wechat_mp():
    c = normalize_social_credentials(
        {"provider": "wechat_mp", "app_id": "mock_wx", "app_secret": "sec"}
    )
    assert c["provider"] == "wechat_mp"
    assert c["platform"] == "wechat"


def test_normalize_gateway_requires_https():
    with pytest.raises(Exception):
        normalize_social_credentials(
            {"platform": "zhihu", "api_url": "http://insecure", "access_token": "t"}
        )


def test_build_authorize_url():
    url = build_authorize_url(
        {
            "client_id": "cid",
            "authorize_url": "https://example.com/oauth/authorize",
            "redirect_uri": "https://app.example.com/api/v1/geo/oauth/social/callback",
            "scope": "write",
        },
        state="abc.state",
    )
    assert "client_id=cid" in url
    assert "state=abc.state" in url
    assert "scope=write" in url


def test_wechat_mp_mock_publish():
    import asyncio

    os.environ["GEO_WECHAT_MP_MOCK"] = "1"
    assert wechat_mp_mock_enabled("anything")
    r = asyncio.run(
        publish_wechat_mp(
            {"app_id": "wx_real_looking", "app_secret": "s"},
            mode="draft",
            title="测试标题",
            body_markdown="正文",
            body_html="<p>正文</p>",
        )
    )
    assert r["ok"]
    assert r.get("media_id")
    assert r.get("mock") is True
    os.environ.pop("GEO_WECHAT_MP_MOCK", None)


def test_wechat_mp_mock_by_app_id_prefix():
    import asyncio

    r = asyncio.run(
        publish_wechat_mp(
            {"app_id": "mock_wx_demo", "app_secret": "s"},
            mode="publish",
            title="t",
            body_markdown="b",
        )
    )
    assert r["ok"]
    assert r.get("publish_id") or r.get("media_id")


def test_payload_wechat_articles():
    p = build_social_payload(
        platform="wechat",
        mode="draft",
        tenant_id=1,
        task_id=2,
        channel="wechat",
        title="标题",
        body_markdown="md",
        extra={"thumb_media_id": "thumb1"},
    )
    assert "articles" in p
    assert p["articles"][0]["title"] == "标题"
    assert p["articles"][0]["thumb_media_id"] == "thumb1"


def test_payload_zhihu_baijia_toutiao():
    z = build_social_payload(
        platform="zhihu",
        mode="draft",
        tenant_id=1,
        task_id=1,
        channel="zhihu",
        title="Z",
        body_markdown="m",
        body_html="<p>m</p>",
    )
    assert z["zhihu"]["content_html"] == "<p>m</p>"
    b = build_social_payload(
        platform="baijiahao",
        mode="draft",
        tenant_id=1,
        task_id=1,
        channel="baijiahao",
        title="T" * 50,
        body_markdown="m",
    )
    assert b["article"]["is_original"] == 1
    assert len(b["article"]["title"]) <= 40
    t = build_social_payload(
        platform="toutiao",
        mode="draft",
        tenant_id=1,
        task_id=1,
        channel="toutiao",
        title="TT",
        body_markdown="m",
    )
    assert t["data"]["title"] == "TT"


def test_wechat_cover_thumb_cached():
    import asyncio

    r = asyncio.run(
        publish_wechat_mp(
            {
                "app_id": "mock_wx_cover",
                "app_secret": "s",
                "thumb_media_id": "already_uploaded",
            },
            mode="draft",
            title="t",
            body_markdown="b",
        )
    )
    assert r["ok"]
    assert r.get("thumb_media_id") == "already_uploaded"


def test_token_needs_refresh_empty():
    assert token_needs_refresh({}) is True
    assert token_needs_refresh({"access_token": "x"}) is False
