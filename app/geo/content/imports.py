"""GEO 事实/机会批量 CSV 导入。"""

from __future__ import annotations

import csv
import io
from datetime import date
from uuid import uuid4

from app.models import GeoFact, GeoPrompt

FACT_CSV_COLUMNS = (
    "title",
    "statement",
    "fact_type",
    "source_name",
    "source_url",
    "observed_at",
    "trust_level",
    "author_name",
)

PROMPT_CSV_COLUMNS = ("question", "priority", "tags", "demand_note")

VALID_FACT_TYPES = {"product", "case", "metric", "policy", "other"}
VALID_TRUST = {"verified", "needs_review", "draft"}


def _parse_tags(raw: str) -> list[str]:
    if not raw or not raw.strip():
        return []
    return [t.strip() for t in raw.replace(";", ",").split(",") if t.strip()]


def _parse_date(raw: str | None) -> date | None:
    if not raw or not str(raw).strip():
        return None
    text = str(raw).strip()[:10]
    parts = text.replace("/", "-").split("-")
    if len(parts) != 3:
        raise ValueError(f"日期格式无效: {raw}")
    return date(int(parts[0]), int(parts[1]), int(parts[2]))


def parse_csv_rows(file_bytes: bytes) -> list[dict[str, str]]:
    text = file_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV 缺少表头行")
    rows: list[dict[str, str]] = []
    for row in reader:
        normalized = {
            (k or "").strip().lower(): (v or "").strip()
            for k, v in row.items()
            if k
        }
        if any(normalized.values()):
            rows.append(normalized)
    return rows


def validate_fact_row(row: dict[str, str]) -> dict:
    title = row.get("title", "").strip()
    statement = row.get("statement", "").strip()
    source_name = row.get("source_name", "").strip()
    if not title:
        raise ValueError("title 不能为空")
    if len(statement) < 4:
        raise ValueError("statement 至少 4 个字符")
    fact_type = (row.get("fact_type") or "product").strip() or "product"
    if fact_type not in VALID_FACT_TYPES:
        raise ValueError(f"fact_type 无效: {fact_type}")
    trust = (row.get("trust_level") or "needs_review").strip() or "needs_review"
    if trust not in VALID_TRUST:
        raise ValueError(f"trust_level 无效: {trust}")
    if trust in ("verified", "needs_review") and not source_name:
        raise ValueError("verified/needs_review 必须填写 source_name")
    return {
        "title": title,
        "statement": statement,
        "fact_type": fact_type,
        "source_name": source_name or "待补充",
        "source_url": row.get("source_url") or None,
        "observed_at": _parse_date(row.get("observed_at")),
        "trust_level": trust,
        "author_name": row.get("author_name") or None,
    }


def validate_prompt_row(row: dict[str, str]) -> dict:
    question = row.get("question", "").strip()
    if len(question) < 4:
        raise ValueError("question 至少 4 个字符")
    priority_raw = row.get("priority") or "0"
    try:
        priority = int(priority_raw)
    except ValueError as exc:
        raise ValueError(f"priority 无效: {priority_raw}") from exc
    return {
        "question": question,
        "priority": priority,
        "tags": _parse_tags(row.get("tags", "")),
        "demand_note": row.get("demand_note") or None,
    }


async def import_facts_csv(
    session,
    *,
    tenant_id: int,
    user_id: int | None,
    file_bytes: bytes,
) -> dict:
    batch_id = uuid4().hex
    rows = parse_csv_rows(file_bytes)
    ok_count = 0
    errors: list[dict] = []
    for line_no, row in enumerate(rows, start=2):
        try:
            data = validate_fact_row(row)
            session.add(
                GeoFact(
                    tenant_id=tenant_id,
                    title=data["title"],
                    statement=data["statement"],
                    fact_type=data["fact_type"],
                    source_name=data["source_name"],
                    source_url=data["source_url"],
                    observed_at=data["observed_at"],
                    trust_level=data["trust_level"],
                    author_name=data["author_name"],
                    import_batch_id=batch_id,
                    created_by=user_id,
                )
            )
            ok_count += 1
        except Exception as exc:
            errors.append({"line": line_no, "error": str(exc)})
    return {
        "batch_id": batch_id,
        "row_count": len(rows),
        "ok_count": ok_count,
        "errors": errors[:50],
    }


async def import_prompts_csv(
    session,
    *,
    tenant_id: int,
    user_id: int | None,
    file_bytes: bytes,
) -> dict:
    rows = parse_csv_rows(file_bytes)
    created: list[GeoPrompt] = []
    errors: list[dict] = []
    for line_no, row in enumerate(rows, start=2):
        try:
            data = validate_prompt_row(row)
            prompt = GeoPrompt(
                tenant_id=tenant_id,
                question=data["question"],
                priority=data["priority"],
                tags=data["tags"],
                demand_note=data["demand_note"],
                source="import",
                created_by=user_id,
            )
            session.add(prompt)
            created.append(prompt)
        except Exception as exc:
            errors.append({"line": line_no, "error": str(exc)})
    return {
        "count": len(created),
        "errors": errors[:50],
        "items": created,
    }
