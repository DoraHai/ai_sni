from app.geo.content.engines import sanitize_engine_endpoint


def test_kimi_dashscope_rewrites_to_moonshot():
    url, model, mode, changed = sanitize_engine_endpoint(
        "kimi",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "deepseek-v3",
        "openai_compat",
        has_key=True,
    )
    assert changed is True
    assert "moonshot" in url
    assert mode == "openai_compat"


def test_kimi_dashscope_without_key_falls_back_to_mock():
    url, model, mode, changed = sanitize_engine_endpoint(
        "kimi",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "qwen-plus",
        "openai_compat",
        has_key=False,
    )
    assert changed is True
    assert "moonshot" in (url or "")
    assert mode == "mock_persona"


def test_deepseek_keeps_dashscope():
    url, model, mode, changed = sanitize_engine_endpoint(
        "deepseek",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "deepseek-v3",
        "openai_compat",
        has_key=True,
    )
    assert changed is False
    assert "dashscope" in url
    assert mode == "openai_compat"
