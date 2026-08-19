"""DeepSeek 客户端（OpenAI 兼容 /chat/completions）。

用于 AI 调价建议判断层。阿里云大陆 ECS 直连 api.deepseek.com 正常（Claude 不可用，
见交接文档）。不配 DEEPSEEK_API_KEY 时整个 AI 层禁用，建议引擎只产规则版。
"""
import json
import logging
import re

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class DeepSeekError(Exception):
    pass


def _parse_json_content(content: str) -> dict:
    """Parse model JSON output with a few tolerant cleanups."""
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def is_enabled() -> bool:
    """是否配置了 DeepSeek（决定建议引擎走 AI 判断还是规则版）。"""
    return bool(get_settings().deepseek_api_key)


async def chat_json(system: str, user: str, timeout: float = 30.0) -> dict:
    """调 deepseek-chat，强制 JSON 输出，解析成 dict。失败抛 DeepSeekError。"""
    s = get_settings()
    if not s.deepseek_api_key:
        raise DeepSeekError("未配置 DEEPSEEK_API_KEY")
    url = s.deepseek_base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": s.deepseek_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.3,  # 判断要稳定，不要发散
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {s.deepseek_api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return _parse_json_content(content)
    except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError) as e:
        raise DeepSeekError(f"DeepSeek 调用/解析失败: {e}") from e


async def chat_messages(
    messages: list[dict],
    json_mode: bool = False,
    temperature: float = 0.5,
    timeout: float = 45.0,
):
    """多轮对话调用（对话助手用）。messages = [{role, content}, ...]，第一条通常是 system。

    json_mode=True 时强制 JSON 输出并解析成 dict；否则返回自由文本 str。失败抛 DeepSeekError。
    """
    s = get_settings()
    if not s.deepseek_api_key:
        raise DeepSeekError("未配置 DEEPSEEK_API_KEY")
    url = s.deepseek_base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": s.deepseek_model,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    headers = {
        "Authorization": f"Bearer {s.deepseek_api_key}",
        "Content-Type": "application/json",
    }
    # 调用/解析失败自动重试一次（DeepSeek 偶发返回截断的非法 JSON，重试即好）
    last_err: Exception | None = None
    for _attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            content = data["choices"][0]["message"]["content"]
            if json_mode:
                try:
                    return _parse_json_content(content)
                except json.JSONDecodeError:
                    if content and content.strip():
                        return {
                            "reply": content.strip(),
                            "suggestions": [],
                            "actions": [],
                            "memories": [],
                        }
                    raise
            return content
        except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError) as e:
            last_err = e
            logger.warning("DeepSeek 调用/解析失败（第 %d 次）：%s", _attempt + 1, e)
    raise DeepSeekError(f"DeepSeek 调用/解析失败（重试后仍失败）: {last_err}")
