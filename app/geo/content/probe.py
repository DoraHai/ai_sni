"""GEO answer-snapshot probe helpers (single + multi-engine drafts).

Multi-engine sampling reuses the tenant LLM credential and asks the model to
answer in the style of each tracking engine. Results are drafts only — never
persisted until the operator saves a snapshot.
"""

from __future__ import annotations

from typing import Any

from app.geo.content.snapshot_suggest import normalize_suggest_payload

# Display / persona hints for simulated multi-engine sampling (one LLM backend).
ENGINE_PERSONAS: dict[str, str] = {
    "chatgpt": "请模拟 ChatGPT（OpenAI）公开回答的语气与结构（可适度分点，少空话）。",
    "deepseek": "请模拟 DeepSeek 公开回答的语气与结构（偏技术、条理清晰）。",
    "doubao": "请模拟豆包公开回答的语气与结构（口语友好、适合国内用户）。",
    "perplexity": "请模拟 Perplexity 公开回答的语气与结构（偏检索综述，可提及常见公开来源类型，勿编造具体不存在的 URL）。",
    "other": "请用常见中文 AI 助手的公开回答语气作答。",
}


def engine_persona(engine: str) -> str:
    return ENGINE_PERSONAS.get(engine, ENGINE_PERSONAS["other"])


def build_probe_system_prompt(*, brand: str, engine: str) -> str:
    return (
        "你是 GEO 可见度探测助手。请用中文直接回答用户问题，像常见 AI 助手的公开回答。"
        f"{engine_persona(engine)}"
        "只返回 JSON："
        '{"raw_text": "完整回答正文", '
        '"suggested_mentions_brand": true/false, '
        '"competitors": ["竞品名"], '
        '"brand_position": "first|mentioned|absent|unknown", '
        '"sentiment": "positive|neutral|negative|unknown"}。'
        f"suggested_mentions_brand 表示回答是否明确提及品牌「{brand}」。"
        "competitors 不要包含该品牌自身；没有竞品就返回 []。"
        "不要编造不存在的官网承诺或正文外竞品。"
    )


def build_probe_user_prompt(*, brand: str, question: str, engine: str) -> str:
    return (
        f"目标引擎标签：{engine}\n"
        f"品牌参考名：{brand}\n"
        f"用户问题：{question}"
    )


async def run_probe_draft(
    *,
    question: str,
    brand: str,
    brand_names: list[str],
    engine: str,
    llm: dict[str, Any],
    chat_json,
) -> dict[str, Any]:
    """Call LLM and normalize a non-persisted probe draft for one engine."""
    from app.ai.deepseek import DeepSeekError

    system = build_probe_system_prompt(brand=brand, engine=engine)
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
    return {
        "engine": engine,
        "provider": llm.get("provider"),
        "model": llm.get("model"),
        "raw_text": raw_text,
        "simulated": engine != "deepseek",
        **suggest,
        "persisted": False,
    }


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
