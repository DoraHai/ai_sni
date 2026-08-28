import base64
import json
from unittest.mock import patch

import pytest

from app.seo_traffic import GscError, gsc_status, validate_property


def _settings(value: str = "") -> object:
    return type("Settings", (), {"seo_gsc_service_account_json_b64": value})()


def test_validate_property_enforces_current_site_domain() -> None:
    assert validate_property("sc-domain:example.com", "www.example.com") == "sc-domain:example.com"
    assert validate_property("https://www.example.com", "example.com") == "https://www.example.com/"
    with pytest.raises(GscError) as exc:
        validate_property("sc-domain:example.net", "example.com")
    assert exc.value.code == "property_mismatch"


def test_gsc_status_exposes_email_but_never_private_key() -> None:
    encoded = base64.b64encode(json.dumps({
        "client_email": "seo@example.iam.gserviceaccount.com",
        "private_key": "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----\n",
    }).encode()).decode()
    with patch("app.seo_traffic.get_settings", return_value=_settings(encoded)):
        status = gsc_status()
    assert status == {
        "configured": True,
        "provider": "google_search_console",
        "service_account_email": "seo@example.iam.gserviceaccount.com",
    }
    assert "private" not in str(status).lower()


def test_gsc_status_is_not_configured_when_secret_is_absent() -> None:
    with patch("app.seo_traffic.get_settings", return_value=_settings()):
        assert gsc_status()["configured"] is False
