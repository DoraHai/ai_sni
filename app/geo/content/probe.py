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
    "kimi": "请模拟 Kimi（月之暗面）公开回答的语气与结构（长文能力强、条理清晰、可适度引用公开常识）。",
    "perplexity": "请模拟 Perplexity 公开回答的语气与结构（偏检索综述，可提及常见公开来源类型，勿编造具体不存在的 URL）。",
    "other": "请用常见中文 AI 助手的公开回答语气作答。",
}

SAMPLE_MODE_PERSONA = "mock_persona"
SAMPLE_MODE_REAL = "openai_compat"


def engine_persona(engine: str) -> str:
    return ENGINE_PERSONAS.get(engine, ENGINE_PERSONAS["other"])


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
) -> tuple[dict[str, Any], str, str | None]:
    """Pick credentials + sample mode for one engine.

    Returns (llm_dict, sample_mode, fallback_reason).
    Prefer per-engine openai_compat when key is present; otherwise tenant LLM + persona.
    """
    mode = SAMPLE_MODE_PERSONA
    if engine_row is not None:
        mode = (getattr(engine_row, "sample_mode", None) or SAMPLE_MODE_PERSONA).strip()

    if mode == SAMPLE_MODE_REAL and engine_row is not None:
        from app.security.crypto import decrypt

        raw_key = None
        enc = getattr(engine_row, "api_key_encrypted", None)
        if enc:
            try:
                raw_key = decrypt(enc)
            except Exception:  # noqa: BLE001
                raw_key = None
        if raw_key:
            base = (getattr(engine_row, "api_base_url", None) or "").strip().rstrip("/")
            model = (getattr(engine_row, "model", None) or "").strip()
            if not base or not model:
                return (
                    tenant_llm or {},
                    SAMPLE_MODE_PERSONA,
                    "openai_compat 缺少 base_url 或 model，已回退人设模拟",
                )
            return (
                {
                    "api_key": raw_key,
                    "base_url": base,
                    "model": model,
                    "provider": f"engine:{engine}",
                    "source": "engine_openai_compat",
                },
                SAMPLE_MODE_REAL,
                None,
            )
        # Real mode without per-engine key：统一回退租户/环境百炼（全引擎共用）
        if tenant_llm and tenant_llm.get("api_key"):
            return (
                {
                    **tenant_llm,
                    "provider": tenant_llm.get("provider") or "dashscope",
                    "source": f"tenant_fallback:{engine}",
                },
                SAMPLE_MODE_REAL,
                None,
            )
        return {}, SAMPLE_MODE_PERSONA, "openai_compat 未配置引擎 Key 且无租户 LLM"

    if not tenant_llm:
        return {}, SAMPLE_MODE_PERSONA, "无租户/环境 LLM 凭证"
    return tenant_llm, SAMPLE_MODE_PERSONA, None


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
    try:
        data = await chat_json(
            system,
            user,
            timeout=60.0,
            api_key=llm["api_key"],
            base_url=llm["base_url"],
            model=llm["model"],
        )
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
