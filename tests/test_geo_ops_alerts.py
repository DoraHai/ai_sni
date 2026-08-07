"""Ops alerts unit tests."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.geo.content.ops_alerts import account_token_health


def test_token_health_expired():
    past = (datetime.utcnow() - timedelta(hours=1)).isoformat(timespec="seconds")
    h = account_token_health({"access_token": "x", "token_expires_at": past, "provider": "oauth2"})
    assert h["token_expired"] is True
    assert h["token_expiring_soon"] is False
    assert h["oauth_authorized"] is True


def test_token_health_expiring_soon():
    soon = (datetime.utcnow() + timedelta(hours=12)).isoformat(timespec="seconds")
    h = account_token_health({"access_token": "x", "token_expires_at": soon})
    assert h["token_expired"] is False
    assert h["token_expiring_soon"] is True


def test_oauth_pending():
    h = account_token_health({"provider": "oauth2", "authorize_url": "https://x"})
    assert h["oauth_authorized"] is False


def test_wechat_mp_no_token_still_ok_with_secrets():
    h = account_token_health({"provider": "wechat_mp", "app_id": "a", "app_secret": "b"})
    assert h["oauth_authorized"] is True
