"""Tracking engine helpers (Wave B2)."""

from __future__ import annotations

DEFAULT_TRACKING_ENGINES: list[tuple[str, str, int]] = [
    ("chatgpt", "ChatGPT", 10),
    ("deepseek", "DeepSeek", 20),
    ("doubao", "豆包", 30),
    ("kimi", "Kimi", 35),
    ("perplexity", "Perplexity", 40),
    ("other", "其他", 90),
]

# OpenAI-compatible official endpoints. DashScope is DeepSeek-only.
ENGINE_COMPAT_PRESETS: dict[str, tuple[str, str]] = {
    "chatgpt": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "kimi": ("https://api.moonshot.cn/v1", "moonshot-v1-8k"),
    "perplexity": ("https://api.perplexity.ai", "sonar"),
    "doubao": ("https://ark.cn-beijing.volces.com/api/v3", "doubao-pro-32k"),
    "deepseek": ("https://api.deepseek.com", "deepseek-chat"),
}


def is_dashscope_url(url: str | None) -> bool:
    u = str(url or "").lower()
    return "dashscope" in u or "aliyuncs.com" in u


def is_deepseek_engine(engine_key: str | None) -> bool:
    return "deepseek" in str(engine_key or "").lower()


def compat_preset(engine_key: str | None) -> tuple[str, str] | None:
    return ENGINE_COMPAT_PRESETS.get(str(engine_key or "").lower())


def sanitize_engine_endpoint(
    engine_key: str | None,
    api_base_url: str | None,
    model: str | None,
    sample_mode: str | None,
    *,
    has_key: bool = False,
) -> tuple[str | None, str | None, str, bool]:
    """If a non-DeepSeek engine points at DashScope, rewrite to its official compat URL.

    Without a key, keep the official URL but fall back to mock_persona so patrol
    still runs. Returns (url, model, sample_mode, changed).
    """
    mode = (sample_mode or "mock_persona").strip() or "mock_persona"
    if is_deepseek_engine(engine_key) or not is_dashscope_url(api_base_url):
        return api_base_url, model, mode, False
    preset = compat_preset(engine_key)
    if not preset:
        return None, None, "mock_persona", True
    url, preset_model = preset
    next_mode = "openai_compat" if has_key else "mock_persona"
    return url, preset_model or model, next_mode, True


def default_engine_rows(tenant_id: int) -> list[dict]:
    return [
        {
            "tenant_id": tenant_id,
            "engine_key": key,
            "display_name": name,
            "enabled": True,
            "note": None,
            "sort_order": order,
            "sample_mode": "mock_persona",
        }
        for key, name, order in DEFAULT_TRACKING_ENGINES
    ]
