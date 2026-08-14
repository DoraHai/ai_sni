"""Probe province fields on the existing keyword report.

Temporary, read-only script. It is not imported by routes or schedulers.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select


if __package__ in {None, ""}:
    cwd = Path.cwd()
    if (cwd / "app").is_dir():
        sys.path.insert(0, str(cwd))
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.baidu.client import BaiduAPIClient, BaiduAPIError  # noqa: E402
from app.baidu.services.report import KEYWORD_REPORT_COLUMNS, ReportService  # noqa: E402
from app.database import async_session_factory  # noqa: E402
from app.models import BaiduAccount  # noqa: E402
from app.security.crypto import decrypt  # noqa: E402


TENANT_ID = 1
BAIDU_ACCOUNT_ID = 1
START_DATE = "2026-08-07"
END_DATE = "2026-08-13"
OUTPUT_PATH = Path("/tmp/keyword_region_probe_result.json")


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def _mask(value: str | None) -> str | None:
    if not value:
        return value
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}***{value[-2:]}"


def _error_payload(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, BaiduAPIError):
        return {
            "type": exc.__class__.__name__,
            "code": exc.code,
            "message": exc.message,
            "raw": _json_safe(exc.raw),
        }
    return {"type": exc.__class__.__name__, "message": str(exc)}


def _field_names(rows: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in row:
            if key not in seen:
                seen.add(key)
                names.append(key)
    return names


async def main() -> int:
    async with async_session_factory() as session:
        account = await session.scalar(
            select(BaiduAccount).where(
                BaiduAccount.id == BAIDU_ACCOUNT_ID,
                BaiduAccount.tenant_id == TENANT_ID,
                BaiduAccount.status == "active",
            )
        )
        if account is None:
            raise RuntimeError("tenant_id=1 / baidu_account_id=1 is not an active Baidu account.")
        session.expunge(account)

    incompatible_with_region = {"topPvWinA", "topFirstPvWinA"}
    columns = [
        column
        for column in dict.fromkeys(KEYWORD_REPORT_COLUMNS + ["provinceName", "provinceCityName"])
        if column not in incompatible_with_region
    ]
    result: dict[str, Any] = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "probe": "keyword_report_region_fields",
        "tenant_id": TENANT_ID,
        "baidu_account_id": BAIDU_ACCOUNT_ID,
        "account": {
            "baidu_ucid": account.baidu_ucid,
            "baidu_username_masked": _mask(account.baidu_username),
            "auth_mode": account.auth_mode,
            "status": account.status,
        },
        "request": {
            "report_type": ReportService.KEYWORD_REPORT_TYPE,
            "start_date": START_DATE,
            "end_date": END_DATE,
            "time_unit": "DAY",
            "columns": columns,
            "excluded_default_columns": sorted(incompatible_with_region),
        },
    }

    try:
        service = ReportService(
            BaiduAPIClient(
                username=account.baidu_username,
                access_token=decrypt(account.access_token_encrypted),
            )
        )
        rows = await service.get_keyword_report(
            START_DATE,
            END_DATE,
            columns=columns,
            time_unit="DAY",
            page_size=10000,
        )
        field_names = _field_names(rows)
        result["ok"] = True
        result["row_count"] = len(rows)
        result["field_names"] = field_names
        result["has_provinceName"] = "provinceName" in field_names
        result["has_provinceCityName"] = "provinceCityName" in field_names
        result["sample_rows"] = rows[:5]
    except Exception as exc:  # noqa: BLE001
        result["ok"] = False
        result["error"] = _error_payload(exc)

    OUTPUT_PATH.write_text(
        json.dumps(_json_safe(result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(_json_safe(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    raise SystemExit(asyncio.run(main()))
