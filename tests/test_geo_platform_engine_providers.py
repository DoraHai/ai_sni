from types import SimpleNamespace

from app.geo.content.engine_providers import (
    platform_engine_public_status,
    resolve_platform_engine_credentials,
    tencent_wsa_public_status,
)
from app.geo.content.engines import default_engine_rows


def _settings(**overrides):
    defaults = {
        "geo_deepseek_api_key": "",
        "geo_deepseek_base_url": "https://api.deepseek.com",
        "geo_deepseek_model": "deepseek-chat",
        "dashscope_api_key": "",
        "dashscope_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "dashscope_model": "deepseek-v3",
        "geo_qwen_api_key": "",
        "geo_qwen_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "geo_qwen_model": "qwen-max",
        "geo_tencent_wsa_api_key": "",
        "geo_tencent_wsa_base_url": "https://api.wsa.cloud.tencent.com",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_deepseek_prefers_official_platform_key():
    settings = _settings(
        geo_deepseek_api_key="official-secret",
        geo_deepseek_model="deepseek-v4-flash",
        dashscope_api_key="dashscope-secret",
    )
    result = resolve_platform_engine_credentials("deepseek", settings=settings)
    assert result is not None
    assert result["api_key"] == "official-secret"
    assert result["provider"] == "deepseek"
    assert result["model"] == "deepseek-v4-flash"


def test_deepseek_falls_back_to_platform_dashscope():
    settings = _settings(dashscope_api_key="dashscope-secret")
    result = resolve_platform_engine_credentials("deepseek", settings=settings)
    assert result is not None
    assert result["api_key"] == "dashscope-secret"
    assert result["provider"] == "dashscope:deepseek"


def test_public_status_never_contains_secret():
    settings = _settings(geo_qwen_api_key="qwen-super-secret")
    result = platform_engine_public_status("qwen", settings=settings)
    assert result["configured"] is True
    assert result["model"] == "qwen-max"
    assert "api_key" not in result
    assert "qwen-super-secret" not in repr(result)


def test_wsa_is_explicitly_not_an_answer_engine():
    result = tencent_wsa_public_status(
        settings=_settings(geo_tencent_wsa_api_key="wsa-secret")
    )
    assert result["configured"] is True
    assert result["answer_engine"] is False
    assert result["role"] == "search_grounding"
    assert "wsa-secret" not in repr(result)


def test_default_engines_include_domestic_platforms():
    keys = {row["engine_key"] for row in default_engine_rows(7)}
    assert {"deepseek", "doubao", "qwen", "hunyuan", "wenxin", "kimi"} <= keys
