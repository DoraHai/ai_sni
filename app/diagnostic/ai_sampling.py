"""DeepSeek 品牌提及抽样。

问题生成与品牌命中判断均由确定性代码完成；模型只负责回答中立问题，避免把待测
品牌注入提示词后人为抬高提及率。
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

MAX_QUESTIONS = 3
URL_PATTERN = re.compile(r"https?://[^\s<>()\[\]{}\"']+")


def _compact(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", (value or "").lower())


def _remove_brand_terms(value: str, brand_terms: list[str]) -> str:
    cleaned = (value or "").strip()
    for term in sorted((item for item in brand_terms if item), key=len, reverse=True):
        cleaned = re.sub(re.escape(term), "", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", cleaned).strip(" ，、｜|-/")


def build_neutral_questions(
    *,
    industry: str,
    core_products: list[str],
    audience_segments: list[str],
    brand_terms: list[str],
) -> list[str]:
    """根据品牌资产生成三个不含品牌词的中立采购问题。"""
    product_candidates = [*core_products, industry]
    product = next(
        (
            cleaned
            for item in product_candidates
            if (cleaned := _remove_brand_terms(str(item), brand_terms))
        ),
        "企业产品与服务",
    )
    audience = next(
        (
            cleaned
            for item in audience_segments
            if (cleaned := _remove_brand_terms(str(item), brand_terms))
        ),
        "企业用户",
    )
    return [
        f"{product}领域有哪些值得关注的供应商或品牌？",
        f"选择{product}时，应该重点比较哪些品牌、能力和服务条件？",
        f"面向{audience}，哪些{product}解决方案更值得推荐，为什么？",
    ]


def clean_questions(questions: list[str], brand_terms: list[str]) -> list[str]:
    """清理空问题、去重，并阻止待测品牌名称进入实际模型问题。"""
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in questions[:MAX_QUESTIONS]:
        question = re.sub(r"\s+", " ", str(raw or "")).strip()
        if not question:
            continue
        compact_question = _compact(question)
        if any(_compact(term) and _compact(term) in compact_question for term in brand_terms):
            raise ValueError("抽样问题不能包含待测品牌名称或品牌别名")
        if compact_question in seen:
            continue
        seen.add(compact_question)
        cleaned.append(question[:300])
    return cleaned


def detect_brand_mentions(response: str, brand_terms: list[str]) -> list[str]:
    """按规范化后的品牌名/别名匹配模型原始回答。"""
    compact_response = _compact(response)
    matches: list[str] = []
    for term in brand_terms:
        normalized = _compact(term)
        if len(normalized) >= 2 and normalized in compact_response and term not in matches:
            matches.append(term)
    return matches


async def run_deepseek_sample(
    *,
    questions: list[str],
    brand_name: str,
    brand_terms: list[str],
    model: str,
    chat: Callable[..., Awaitable[str]] | None = None,
) -> dict[str, Any]:
    """并行执行独立问题，保存完整回答并由程序计算提及率。"""
    if chat is None:
        # 延迟导入，确定性问题生成与命中判断测试不依赖数据库环境配置。
        from app.diagnostic.ai_client import chat_messages

        chat = chat_messages
    system = (
        "你是面向采购者的中立行业顾问。直接回答用户的问题，基于你掌握的信息列出"
        "最多6个值得比较的品牌或供应商，并简要说明依据。不要猜测用户偏好，不要为了"
        "迎合用户而强行加入品牌；信息不足时明确说明。不要输出JSON。"
    )

    async def ask(question: str) -> str:
        return await chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": question},
            ],
            json_mode=False,
            temperature=0.2,
            timeout=60,
        )

    responses = await asyncio.gather(*(ask(question) for question in questions))
    results = []
    for question, raw_response in zip(questions, responses, strict=True):
        response = str(raw_response or "").strip()
        matched_terms = detect_brand_mentions(response, brand_terms)
        results.append(
            {
                "question": question,
                "response": response,
                "mentioned": bool(matched_terms),
                "matched_terms": matched_terms,
                "source_urls": sorted(set(URL_PATTERN.findall(response))),
            }
        )
    mention_count = sum(1 for item in results if item["mentioned"])
    total = len(results)
    return {
        "platform": "DeepSeek",
        "model": model,
        "brand_name": brand_name,
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "question_count": total,
        "mention_count": mention_count,
        "mention_rate": round(mention_count / total, 4) if total else 0,
        "results": results,
        "methodology": "中立问题独立调用；品牌提及由后端按品牌名及已确认别名进行文本匹配。",
        "limitations": "仅代表本次 DeepSeek 单平台、少量问题抽样，不代表所有AI平台或长期稳定表现。",
    }
