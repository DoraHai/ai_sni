"""Platform-managed credentials for GEO answer-engine sampling.

Credentials are read only from the server environment.  Tenant rows control
which engines are monitored, but never provide or override API credentials.
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings


ENGINE_PROVIDER_SPECS: dict[str, dict[str, str]] = {
    "chatgpt": {
        "label": "OpenAI",
        "key_attr": "geo_openai_api_key",
        "base_attr": "geo_openai_base_url",
        "model_attr": "geo_openai_model",
    },
    "deepseek": {
        "label": "DeepSeek 官方",
        "key_attr": "geo_deepseek_api_key",
        "base_attr": "geo_deepseek_base_url",
        "model_attr": "geo_deepseek_model",
    },
    "qwen": {
        "label": "阿里云百炼 · 通义千问",
        "key_attr": "geo_qwen_api_key",
        "base_attr": "geo_qwen_base_url",
        "model_attr": "geo_qwen_model",
    },
    "doubao": {
        "label": "火山方舟 · 豆包",
        "key_attr": "geo_doubao_api_key",
        "base_attr": "geo_doubao_base_url",
        "model_attr": "geo_doubao_model",
    },
    "hunyuan": {
        "label": "腾讯混元",
        "key_attr": "geo_hunyuan_api_key",
        "base_attr": "geo_hunyuan_base_url",
        "model_attr": "geo_hunyuan_model",
    },
    "wenxin": {
        "label": "百度千帆 · 文心",
        "key_attr": "geo_qianfan_api_key",
        "base_attr": "geo_qianfan_base_url",
        "model_attr": "geo_qianfan_model",
    },
    "kimi": {
        "label": "月之暗面 · Kimi",
        "key_attr": "geo_kimi_api_key",
        "base_attr": "geo_kimi_base_url",
        "model_attr": "geo_kimi_model",
    },
    "perplexity": {
        "label": "Perplexity",
        "key_attr": "geo_perplexity_api_key",
        "base_attr": "geo_perplexity_base_url",
        "model_attr": "geo_perplexity_model",
    },
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def resolve_platform_engine_credentials(
    engine_key: str | None,
    *,
    settings: Any | None = None,
) -> dict[str, str] | None:
    """Return server-owned credentials for an answer engine, if configured."""
    key = _clean(engine_key).lower()
    spec = ENGINE_PROVIDER_SPECS.get(key)
    if not spec:
        return None
    s = settings or get_settings()
    api_key = _clean(getattr(s, spec["key_attr"], ""))

    # Keep the existing platform-level DashScope DeepSeek as a safe fallback.
    if key == "deepseek" and not api_key:
        api_key = _clean(getattr(s, "dashscope_api_key", ""))
        if api_key:
            return {
                "api_key": api_key,
                "base_url": _clean(getattr(s, "dashscope_base_url", "")).rstrip("/"),
                "model": _clean(getattr(s, "dashscope_model", "")),
                "provider": "dashscope:deepseek",
                "provider_label": "阿里云百炼 · DeepSeek",
                "source": "env:DASHSCOPE",
            }

    if not api_key:
        return None
    base_url = _clean(getattr(s, spec["base_attr"], "")).rstrip("/")
    model = _clean(getattr(s, spec["model_attr"], ""))
    if not base_url or not model:
        return None
    return {
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "provider": key,
        "provider_label": spec["label"],
        "source": f"env:{spec['key_attr'].upper().removesuffix('_API_KEY')}",
    }


def platform_engine_public_status(
    engine_key: str | None,
    *,
    settings: Any | None = None,
) -> dict[str, Any]:
    """Return non-secret platform configuration metadata for API/UI payloads."""
    key = _clean(engine_key).lower()
    spec = ENGINE_PROVIDER_SPECS.get(key)
    s = settings or get_settings()
    llm = resolve_platform_engine_credentials(key, settings=s)
    if llm:
        return {
            "platform_managed": True,
            "configured": True,
            "provider": llm["provider"],
            "provider_label": llm["provider_label"],
            "base_url": llm["base_url"],
            "model": llm["model"],
            "source": llm["source"],
        }
    return {
        "platform_managed": bool(spec),
        "configured": False,
        "provider": key if spec else None,
        "provider_label": spec["label"] if spec else None,
        "base_url": (
            _clean(getattr(s, spec["base_attr"], "")).rstrip("/") if spec else None
        ),
        "model": _clean(getattr(s, spec["model_attr"], "")) if spec else None,
        "source": None,
    }


def tencent_wsa_public_status(*, settings: Any | None = None) -> dict[str, Any]:
    """Expose WSA configuration state without treating it as an answer engine."""
    s = settings or get_settings()
    configured = bool(_clean(getattr(s, "geo_tencent_wsa_api_key", "")))
    return {
        "service_key": "tencent_wsa",
        "display_name": "腾讯联网搜索 WSA",
        "configured": configured,
        "platform_managed": True,
        "role": "search_grounding",
        "answer_engine": False,
        "base_url": _clean(getattr(s, "geo_tencent_wsa_base_url", "")).rstrip("/"),
    }
