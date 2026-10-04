"""No-network grounding, validation and throttling tests."""
import asyncio
from types import SimpleNamespace as Row

import httpx
import pytest

from app.ai.deepseek import DeepSeekError
from app.seo_ai_tdk import SYSTEM_PROMPT, digest, generate_batch, generate_one, grounding, validate_response


def source():
    page = Row(id=1, url="https://example.test/a", title="工业泵", meta_description="页面说明", meta_keywords="泵",
               h1="工业泵", target_keyword_id=3)
    keywords = [Row(id=3, keyword="工业泵", landing_page=None), Row(id=4, keyword="配件", landing_page=page.url),
                Row(id=5, keyword="外站词", landing_page="https://other.test/")]
    library = [page, Row(id=2, url="https://example.test/b", title="工业泵配件")]
    return grounding(page, site_name="示例品牌", keywords=keywords, library=library,
                     snapshot=Row(h1_texts=["工业泵", "安装说明"]))


def raw():
    return {"title": "工业泵配件", "description": "介绍工业泵配件及页面已公开的信息。" * 6,
            "keywords": ["工业泵", "配件", "安装", "安装"], "reason": "根据页面内容调整",
            "internal_links": [{"anchor": "配件", "target_page_id": 2, "reason": "相关"},
                               {"anchor": "自己", "target_page_id": 1, "reason": "无效"},
                               {"anchor": "外站", "target_page_id": 999, "reason": "无效"}]}


def test_grounding_is_stored_and_bounded():
    data = source()
    assert data["target_keywords"] == ["工业泵", "配件"]
    assert data["page"]["h1_texts"] == ["工业泵", "安装说明"]
    assert data["page"]["h2"] == [] and data["page"]["visible_text_excerpt"] == ""
    assert len(data["site_pages"]) == 1 and data["site_pages"][0]["id"] == 2
    assert digest(data) == digest(source())
    assert all(word in SYSTEM_PROMPT for word in ("不得编造", "型号", "规格", "价格", "认证", "客户名称", "30", "70-120"))
    page = Row(id=1, url="https://example.test/" + "a" * 3000, title="标题" * 500,
               meta_description="说明" * 500, meta_keywords="词" * 500, h1="一级" * 500,
               target_keyword_id=None)
    many = [Row(id=i, url=f"https://example.test/{i}", title="相关") for i in range(2, 250)]
    bounded = grounding(page, site_name="品牌" * 100, library=many,
                        snapshot=Row(h1_texts=["标题" * 500] * 20))
    assert len(bounded["site_pages"]) == 200
    assert len(bounded["page"]["title"]) == 300 and len(bounded["page"]["h1_texts"]) == 10
    assert len(bounded["page"]["h1_texts"][0]) == 300 and len(bounded["page"]["url"]) == 2048


def test_validation_drops_invalid_links_and_flags_ungrounded_models():
    proposal = raw(); proposal["title"] = "工业泵 XZ-999"
    result = validate_response(proposal, source())
    assert result["dropped_links"] == 2 and len(result["internal_links"]) == 1
    assert any("XZ-999" in warning for warning in result["warnings"])
    assert result["keywords"] == "工业泵, 配件, 安装"
    with pytest.raises(ValueError, match="格式无效"):
        validate_response({"title": "missing"}, source())


def test_missing_key_prevents_transport_and_invalid_json_is_chinese():
    calls = []
    async def transport(*_args, **_kwargs):
        calls.append(True)
        raise ValueError("invalid JSON")
    with pytest.raises(ValueError, match="未配置 DeepSeek API Key"):
        asyncio.run(generate_one(source(), api_key="", base_url="", model="test", caller=transport))
    assert not calls
    async def no_sleep(_delay):
        return None
    with pytest.raises(ValueError, match="无效 JSON"):
        asyncio.run(generate_one(source(), api_key="fake", base_url="", model="test", caller=transport, sleep=no_sleep))
    assert calls == [True, True]


def test_one_retry_for_malformed_or_overlong_output_but_not_rate_limits():
    slept = []
    async def no_sleep(delay):
        slept.append(delay)
    replies = [ValueError("invalid JSON"), raw()]
    async def flaky(*_args, **_kwargs):
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
    assert asyncio.run(generate_one(source(), api_key="k", base_url="", model="m", caller=flaky, sleep=no_sleep))["title"] == "工业泵配件"
    assert slept == [1.0]
    prompts = []
    long_then_ok = [{**raw(), "title": "工业泵配件" * 10}, raw()]
    async def lengthy(_system, user, **_kwargs):
        prompts.append(user)
        return long_then_ok.pop(0)
    result = asyncio.run(generate_one(source(), api_key="k", base_url="", model="m", caller=lengthy, sleep=no_sleep))
    assert result["title"] == "工业泵配件" and not result["warnings"]
    assert len(prompts) == 2 and "长度校正" in prompts[1] and "Title 为 50 字符" in prompts[1]
    always_long = []
    async def stubborn(*_args, **_kwargs):
        always_long.append(True)
        return {**raw(), "title": "工业泵配件 - 工业泵配件 - 工业泵配件 - 工业泵配件 - 工业泵配件"}
    result = asyncio.run(generate_one(source(), api_key="k", base_url="", model="m", caller=stubborn, sleep=no_sleep))
    assert len(always_long) == 2 and result["title"] == "工业泵配件 - 工业泵配件 - 工业泵配件 - 工业泵配件 - 工业泵配件"[:30].rstrip(" -")
    limited = []
    async def rate_limited(*_args, **_kwargs):
        limited.append(True)
        request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
        response = httpx.Response(429, request=request)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise DeepSeekError("AI 请求/解析失败: 429") from exc
    with pytest.raises(ValueError, match="DeepSeek 服务请求失败"):
        asyncio.run(generate_one(source(), api_key="k", base_url="", model="m", caller=rate_limited, sleep=no_sleep))
    assert limited == [True]


def test_numbers_from_other_pages_do_not_ground_current_page():
    data = source()
    data["site_pages"].append({"id": 3, "url": "https://example.test/sk-500p", "title": "SK-500P 100 行业"})
    result = validate_response({**raw(), "title": "工业泵 SK-500P"}, data)
    assert any("SK-500P" in warning for warning in result["warnings"])


def test_rate_limit_and_serial_concurrency_with_fake_clock():
    now = [0.0]; starts = []; active = [0]; peak = [0]
    async def sleep(delay): now[0] += delay
    async def worker(item):
        starts.append(now[0]); active[0] += 1; peak[0] = max(peak[0], active[0]); active[0] -= 1
        return item["page_id"]
    results = asyncio.run(generate_batch([{"page_id": i} for i in range(3)], interval=0.5,
        clock=lambda: now[0], sleep=sleep, worker=worker))
    assert starts == [0, 0.5, 1.0] and peak[0] <= 2
    assert all(item["status"] == "generated" for item in results)
