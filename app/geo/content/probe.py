"""GEO answer-snapshot probe helpers (single + multi-engine drafts).

Default path reuses the tenant LLM with per-engine personas (simulated).
P2 adds optional per-engine OpenAI-compatible credentials (sample_mode=openai_compat).
Results are drafts only — never persisted until the operator saves a snapshot.
"""

from __future__ import annotations

from typing import Any

from app.geo.content.snapshot_suggest import normalize_suggest_payload

# Display / persona hints for simulated multi-engine sampling (one LLM backend).
ENGINE_PERSONAS: dict[str, str] = {
    "chatgpt": "请模拟 ChatGPT（OpenAI）公开回答的语气与结构（可适度分点，少空话）。",
    "deepseek": "请模拟 DeepSeek 公开回答的语气与结构（偏技术、条理清晰）。",
    "doubao": "请模拟豆包公开回答的语气与结构（口语友好、适合国内用户）。",
    "qwen": "请模拟通义千问公开回答的语气与结构（中文表达自然、条理清晰）。",
    "hunyuan": "请模拟腾讯混元公开回答的语气与结构（简洁、稳健、注重实用信息）。",
    "wenxin": "请模拟文心一言公开回答的语气与结构（中文知识表达清晰、重点明确）。",
    "kimi": "请模拟 Kimi（月之暗面）公开回答的语气与结构（长文能力强、条理清晰、可适度引用公开常识）。",
    "perplexity": "请模拟 Perplexity 公开回答的语气与结构（偏检索综述，可提及常见公开来源类型，勿编造具体不存在的 URL）。",
    "other": "请用常见中文 AI 助手的公开回答语气作答。",
}

SAMPLE_MODE_PERSONA = "mock_persona"
SAMPLE_MODE_REAL = "openai_compat"
DASHSCOPE_MARKERS = ("dashscope", "aliyuncs.com")
SKIP_DASHSCOPE_OTHER_ENGINE = "skipped:dashscope_only_for_deepseek"
KIMI_FIXED_TEMPERATURE_MODEL_PREFIXES = ("kimi-k2",)


def is_deepseek_engine(engine: str | None) -> bool:
    return "deepseek" in str(engine or "").lower()


def is_dashscope_endpoint(*, base_url: str = "", provider: str = "", source: str = "") -> bool:
    blob = f"{provider} {source} {base_url}".lower()
    return any(marker in blob for marker in DASHSCOPE_MARKERS)


def dashscope_usable_for_engine(
    engine: str,
    *,
    base_url: str = "",
    provider: str = "",
    source: str = "",
) -> bool:
    """百炼（DashScope）只允许打 DeepSeek，不能冒充 ChatGPT / 豆包 / Kimi。"""
    if not is_dashscope_endpoint(base_url=base_url, provider=provider, source=source):
        return True
    return is_deepseek_engine(engine)


def tenant_llm_for_engine(engine: str, tenant_llm: dict[str, Any] | None) -> dict[str, Any] | None:
    if not tenant_llm:
        return None
    if not dashscope_usable_for_engine(
        engine,
        base_url=str(tenant_llm.get("base_url") or ""),
        provider=str(tenant_llm.get("provider") or ""),
        source=str(tenant_llm.get("source") or ""),
    ):
        return None
    return tenant_llm


def engine_persona(engine: str) -> str:
    return ENGINE_PERSONAS.get(engine, ENGINE_PERSONAS["other"])


def probe_temperature_for_model(model: str | None) -> float | None:
    """Return a GEO probe override only for models with a fixed temperature."""
    value = str(model or "").strip().lower()
    if value.startswith(KIMI_FIXED_TEMPERATURE_MODEL_PREFIXES):
        return 1.0
    return None


def build_probe_system_prompt(*, brand: str, engine: str, simulated: bool = True) -> str:
    persona = engine_persona(engine) if simulated else (
        "请用该引擎常见公开回答的中文语气直接作答，不要声称自己是模拟器。"
    )
    return (
        "你是 GEO 可见度探测助手。请用中文直接回答用户问题，像常见 AI 助手的公开回答。"
        f"{persona}"
        "只返回 JSON："
        '{"raw_text": "完整回答正文", '
        '"suggested_mentions_brand": true/false, '
        '"competitors": ["竞品名"], '
        '"brand_position": "first|alternative|mentioned|absent|unknown", '
        '"sentiment": "positive|neutral|negative|unknown", '
        '"citation_format": "linked|plaintext|mixed|none|unknown", '
        '"citation_accuracy": "accurate|partial|inaccurate|unknown"}。'
        f"suggested_mentions_brand 表示回答是否明确提及品牌「{brand}」。"
        "competitors 不要包含该品牌自身；没有竞品就返回 []。"
        "brand_position：首选 first，备选/次选 alternative，一般提及 mentioned。"
        "citation_format：有链接用 linked，仅文本提及来源用 plaintext，兼有用 mixed。"
        "不要编造不存在的官网承诺或正文外竞品。"
    )


def build_probe_user_prompt(*, brand: str, question: str, engine: str) -> str:
    return (
        f"目标引擎标签：{engine}\n"
        f"品牌参考名：{brand}\n"
        f"用户问题：{question}"
    )


def resolve_engine_llm(
    *,
    engine: str,
    tenant_llm: dict[str, Any] | None,
    engine_row: Any | None = None,
    monitoring_stance: str | None = None,
) -> tuple[dict[str, Any], str, str | None]:
    """Pick credentials + sample mode for one engine.

    Returns (llm_dict, sample_mode, fallback_reason).
    Prefer platform-managed per-engine credentials; otherwise use the platform
    capability LLM for a clearly labelled persona simulation. Tenant database
    credentials are intentionally ignored.

    monitoring_stance (W3):
      real_only — 无真 Key 时不降级 persona，返回空 llm + skip reason
      simulation — 强制 persona 标记
      hybrid — 现行为
    """
    stance = (monitoring_stance or "hybrid").strip().lower()
    del engine_row  # legacy signature; tenant rows no longer carry credentials
    usable_tenant = tenant_llm_for_engine(engine, tenant_llm)

    if stance == "simulation":
        if not usable_tenant:
            return {}, SAMPLE_MODE_PERSONA, "simulation 定位：无可用租户 LLM"
        return usable_tenant, SAMPLE_MODE_PERSONA, "simulation 定位：强制人设模拟"

    from app.geo.content.engine_providers import resolve_platform_engine_credentials

    platform_llm = resolve_platform_engine_credentials(engine)
    if platform_llm:
        return platform_llm, SAMPLE_MODE_REAL, None

    if stance == "real_only":
        return {}, SAMPLE_MODE_REAL, "skipped:real_only_no_platform_key"

    if not usable_tenant:
        if tenant_llm:
            return {}, SAMPLE_MODE_PERSONA, SKIP_DASHSCOPE_OTHER_ENGINE
        return {}, SAMPLE_MODE_PERSONA, "无平台 AI 能力凭证"
    return usable_tenant, SAMPLE_MODE_PERSONA, None


async def run_probe_draft(
    *,
    question: str,
    brand: str,
    brand_names: list[str],
    engine: str,
    llm: dict[str, Any],
    chat_json,
    sample_mode: str = SAMPLE_MODE_PERSONA,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    """Call LLM and normalize a non-persisted probe draft for one engine."""
    from app.ai.deepseek import DeepSeekError

    simulated = sample_mode != SAMPLE_MODE_REAL
    system = build_probe_system_prompt(brand=brand, engine=engine, simulated=simulated)
    user = build_probe_user_prompt(brand=brand, question=question, engine=engine)
    call_kwargs: dict[str, Any] = {
        "timeout": 60.0,
        "api_key": llm["api_key"],
        "base_url": llm["base_url"],
        "model": llm["model"],
    }
    fixed_temperature = probe_temperature_for_model(llm.get("model"))
    if fixed_temperature is not None:
        call_kwargs["temperature"] = fixed_temperature
    try:
        data = await chat_json(system, user, **call_kwargs)
    except DeepSeekError:
        raise
    raw_text = str(data.get("raw_text") or "").strip()
    if len(raw_text) < 4:
        raise ValueError("探测结果过短，请改用粘贴")
    suggest = normalize_suggest_payload(
        data, raw_text=raw_text, brand_names=brand_names
    )
    out = {
        "engine": engine,
        "provider": llm.get("provider"),
        "model": llm.get("model"),
        "raw_text": raw_text,
        "sample_mode": sample_mode,
        "simulated": simulated,
        **suggest,
        "persisted": False,
    }
    if fallback_reason:
        out["fallback_reason"] = fallback_reason
    return out


def resolve_batch_engines(
    requested: list[str] | None,
    enabled_keys: list[str],
) -> list[str]:
    """Pick engines for batch probe; skip 'other' when using enabled defaults."""
    if requested:
        seen: list[str] = []
        for key in requested:
            if key not in seen:
                seen.append(key)
        return seen
    keys = [k for k in enabled_keys if k != "other"]
    return keys or list(enabled_keys)
