"""Tracking engine helpers (Wave B2)."""

from __future__ import annotations

DEFAULT_TRACKING_ENGINES: list[tuple[str, str, int]] = [
    ("chatgpt", "ChatGPT", 10),
    ("deepseek", "DeepSeek", 20),
    ("doubao", "豆包", 30),
    ("perplexity", "Perplexity", 40),
    ("other", "其他", 90),
]


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
