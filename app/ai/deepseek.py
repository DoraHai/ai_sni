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


def _resolve_creds(
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> tuple[str, str, str]:
    """Resolve OpenAI-compatible credentials.

    Priority when caller does not pass overrides:
    1) 阿里云百炼 DASHSCOPE_*（全站默认）
    2) DeepSeek 官方 DEEPSEEK_*
    Explicit api_key/base_url/model from GEO 租户配置始终优先。
    """
    s = get_settings()
    dash_key = (getattr(s, "dashscope_api_key", None) or "").strip()
    deep_key = (s.deepseek_api_key or "").strip()
    # Caller-provided key wins (tenant GEO AI settings, etc.)
    if api_key and str(api_key).strip():
        key = str(api_key).strip()
        url_base = (
            base_url
            or (s.dashscope_base_url if dash_key else None)
            or s.deepseek_base_url
            or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ).rstrip("/")
        mdl = (
            model
            or (s.dashscope_model if dash_key else None)
            or s.deepseek_model
            or "deepseek-v3"
        )
        return key, url_base, mdl

    # Env: prefer 百炼 so SEM/GEO 共用同一 Key
    if dash_key:
        key = dash_key
        url_base = (
            base_url or getattr(s, "dashscope_base_url", None) or ""
        ).rstrip("/") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        mdl = model or getattr(s, "dashscope_model", None) or "deepseek-v3"
        return key, url_base, mdl

    if deep_key:
        key = deep_key
        url_base = (base_url or s.deepseek_base_url or "").rstrip("/")
        mdl = model or s.deepseek_model or "deepseek-chat"
        return key, url_base, mdl

    raise DeepSeekError(
        "未配置 AI API Key（请设置 DASHSCOPE_API_KEY 百炼，或 DEEPSEEK_API_KEY）"
    )


def is_enabled() -> bool:
    """是否配置了可用 AI Key（优先百炼 env，其次 DeepSeek）。"""
    s = get_settings()
    return bool(
        (getattr(s, "dashscope_api_key", None) or "").strip()
        or (s.deepseek_api_key or "").strip()
    )


async def chat_json(
    system: str,
    user: str,
    timeout: float = 30.0,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
) -> dict:
    """调 OpenAI 兼容 /chat/completions，强制 JSON 输出。失败抛 DeepSeekError。"""
    key, url_base, mdl = _resolve_creds(api_key=api_key, base_url=base_url, model=model)
    url = url_base + "/chat/completions"
    # 默认 0.3 偏判断；成稿润色可传更高 temperature 提升叙述完整度
    temp = 0.3 if temperature is None else float(temperature)
    temp = max(0.0, min(temp, 1.2))
    payload = {
        "model": mdl,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
        "temperature": temp,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {key}",
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
        snippet = ""
        try:
            snippet = str(locals().get("content") or "")[:160]
        except Exception:  # pragma: no cover
            snippet = ""
        if isinstance(e, json.JSONDecodeError) and snippet:
            raise DeepSeekError(
                f"AI 返回了非 JSON 内容（模型 {mdl}）：{snippet!r}"
            ) from e
        raise DeepSeekError(f"AI 调用/解析失败: {e}") from e


async def chat_messages(
    messages: list[dict],
    json_mode: bool = False,
    temperature: float = 0.5,
    timeout: float = 45.0,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
):
    """多轮对话调用（对话助手用）。messages = [{role, content}, ...]，第一条通常是 system。

    json_mode=True 时强制 JSON 输出并解析成 dict；否则返回自由文本 str。失败抛 DeepSeekError。
    """
    key, url_base, mdl = _resolve_creds(api_key=api_key, base_url=base_url, model=model)
    url = url_base + "/chat/completions"
    payload = {
        "model": mdl,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    headers = {
        "Authorization": f"Bearer {key}",
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
            raise DeepSeekError(f"AI 调用/解析失败（重试后仍失败）: {last_err}")
