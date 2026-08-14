"""Probe Baidu age/gender/region reports for top-spend active accounts.

Temporary, read-only script. It is not imported by routes or schedulers.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import desc, func, select


if __package__ in {None, ""}:
    cwd = Path.cwd()
    if (cwd / "app").is_dir():
        sys.path.insert(0, str(cwd))
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.baidu.client import BaiduAPIClient, BaiduAPIError  # noqa: E402
from app.baidu.services.report import ReportService  # noqa: E402
from app.database import async_session_factory  # noqa: E402
from app.models import BaiduAccount, KwReportSnapshot  # noqa: E402
from app.security.crypto import decrypt  # noqa: E402


START_DATE = date(2026, 8, 7)
END_DATE = date(2026, 8, 13)
TOP_N = 3
OUTPUT_PATH = Path("/tmp/dimension_probe_result_multi_account.json")

REPORTS = {
    "age": {
        "report_type": 1900021,
        "time_unit": "DAY",
        "columns": [
            "date",
            "age",
            "impression",
            "click",
            "cost",
            "ctr",
            "cpc",
            "ocpcTransType",
            "ocpcTargetTrans",
            "ocpcTargetTransCPC",
            "ocpcTargetTransRatio",
        ],
    },
    "gender": {
        "report_type": 1900022,
        "time_unit": "DAY",
        "columns": [
            "date",
            "gender",
            "impression",
            "click",
            "cost",
            "ctr",
            "cpc",
            "ocpcTransType",
            "ocpcTargetTrans",
            "ocpcTargetTransCPC",
            "ocpcTargetTransRatio",
        ],
    },
    "region": {
        "report_type": 1900023,
        "time_unit": "DAY",
        "columns": [
            "date",
            "provinceName",
            "cityName",
            "impression",
            "click",
            "cost",
            "ctr",
            "cpc",
            "ocpcTransType",
            "ocpcTargetTrans",
            "ocpcTargetTransCPC",
            "ocpcTargetTransRatio",
        ],
    },
}


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
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


async def _top_accounts() -> list[tuple[BaiduAccount, float]]:
    spend_start = END_DATE - timedelta(days=29)
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(
                    BaiduAccount,
                    func.coalesce(func.sum(KwReportSnapshot.cost), 0).label("spend"),
                )
                .outerjoin(
                    KwReportSnapshot,
                    (KwReportSnapshot.tenant_id == BaiduAccount.tenant_id)
                    & (KwReportSnapshot.baidu_account_id == BaiduAccount.id)
                    & (KwReportSnapshot.report_date >= spend_start)
                    & (KwReportSnapshot.report_date <= END_DATE),
                )
                .where(BaiduAccount.status == "active")
                .group_by(BaiduAccount.id)
                .order_by(desc("spend"), BaiduAccount.id.asc())
                .limit(TOP_N)
            )
        ).all()
        accounts = [(row[0], float(row[1] or 0)) for row in rows]
        for account, _ in accounts:
            session.expunge(account)
        return accounts


async def main() -> int:
    accounts = await _top_accounts()
    result: dict[str, Any] = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "probe": "dimension_reports_multi_account",
        "probe_window": {
            "start_date": START_DATE.isoformat(),
            "end_date": END_DATE.isoformat(),
            "days": 7,
        },
        "selection": {
            "method": "top active Baidu accounts by kw_report_snapshots cost in last 30 days",
            "top_n": TOP_N,
            "selected_count": len(accounts),
        },
        "accounts": [],
    }

    for account, recent_30d_cost in accounts:
        item: dict[str, Any] = {
            "account": {
                "id": account.id,
                "tenant_id": account.tenant_id,
                "baidu_ucid": account.baidu_ucid,
                "baidu_username_masked": _mask(account.baidu_username),
                "auth_mode": account.auth_mode,
                "status": account.status,
                "recent_30d_cost": round(recent_30d_cost, 2),
            },
            "reports": {},
        }
        service = ReportService(
            BaiduAPIClient(
                username=account.baidu_username,
                access_token=decrypt(account.access_token_encrypted),
            )
        )
        for name, spec in REPORTS.items():
            started_at = datetime.utcnow()
            report_result: dict[str, Any] = {
                "report_type": spec["report_type"],
                "time_unit": spec["time_unit"],
                "columns_requested": spec["columns"],
            }
            try:
                rows = await service._get_report_rows(  # noqa: SLF001
                    report_type=spec["report_type"],
                    start_date=START_DATE.isoformat(),
                    end_date=END_DATE.isoformat(),
                    columns=spec["columns"],
                    time_unit=spec["time_unit"],
                    page_size=10000,
                )
                report_result.update(
                    {
                        "ok": True,
                        "duration_seconds": round(
                            (datetime.utcnow() - started_at).total_seconds(), 3
                        ),
                        "row_count": len(rows),
                        "is_empty": len(rows) == 0,
                        "sample_rows": rows[:5],
                    }
                )
            except Exception as exc:  # noqa: BLE001
                report_result.update(
                    {
                        "ok": False,
                        "duration_seconds": round(
                            (datetime.utcnow() - started_at).total_seconds(), 3
                        ),
                        "error": _error_payload(exc),
                    }
                )
            item["reports"][name] = report_result
        result["accounts"].append(item)

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
