"""Bounded SEM planner sampling; no account-wide recommendation, AI or ad writes."""
from datetime import datetime

from app.baidu.sync import (
    KeywordPlannerService, _account_client, _existing_keyword_texts,
    _planner_row_to_record, _tenant_brand_terms, _upsert_candidates,
)


async def sample_planner_candidates(session, account, seed: str, limit: int) -> int:
    if not seed.strip() or any(c in seed for c in ",，\n\r"):
        raise ValueError("小批量拉取必须填写一个种子词")
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("小批量上限必须为 1–20")
    brands = await _tenant_brand_terms(session, account.tenant_id)
    existing = await _existing_keyword_texts(session, account.tenant_id)
    service = KeywordPlannerService(_account_client(account))
    rows = await service.get_words_by_seed(seed.strip(), limit)
    records = {}
    now = datetime.utcnow()
    for row in rows:
        rec = _planner_row_to_record(row, account, seed.strip(), brands, now)
        if rec is None or rec["word"].lower() in existing:
            continue
        records.setdefault(rec["word"].lower(), rec)
        if len(records) >= limit:
            break  # Local cap even when the provider ignores maxNum.
    if records:
        await _upsert_candidates(session, list(records.values()))
    return len(records)
