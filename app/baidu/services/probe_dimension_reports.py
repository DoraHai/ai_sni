"""Probe Baidu dimension report availability.

Temporary, read-only script. It is intentionally not imported by API routes or
schedulers. It calls OpenApiReportService.getReportData for age, gender, and
region report types, then writes a compact raw-shape sample to
/tmp/dimension_probe_result.json when available.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from datetime import date, datetime, timedelta
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
from app.baidu.services.report import ReportService  # noqa: E402
from app.database import async_session_factory  # noqa: E402
from app.models import BaiduAccount  # noqa: E402
from app.security.crypto import decrypt  # noqa: E402


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


def _mask(value: str | None) -> str | None:
    if not value:
        return value
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}***{value[-2:]}"


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def _error_payload(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, BaiduAPIError):
        return {
            "type": exc.__class__.__name__,
            "code": exc.code,
            "message": exc.message,
            "raw": _json_safe(exc.raw),
        }
    return {
        "type": exc.__class__.__name__,
        "message": str(exc),
    }


def _summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    keys: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in row:
            if key not in seen:
                seen.add(key)
                keys.append(key)

    return {
        "is_empty": len(rows) == 0,
        "row_count": len(rows),
        "field_names": keys,
        "sample_rows": rows[:3],
    }


async def _select_account(account_id: int | None, tenant_id: int | None) -> BaiduAccount:
    async with async_session_factory() as session:
        stmt = select(BaiduAccount).where(BaiduAccount.status == "active")
        if account_id is not None:
            stmt = stmt.where(BaiduAccount.id == account_id)
        if tenant_id is not None:
            stmt = stmt.where(BaiduAccount.tenant_id == tenant_id)
        stmt = stmt.order_by(BaiduAccount.id.asc()).limit(1)
        account = await session.scalar(stmt)
        if account is None:
            raise RuntimeError("No active Baidu account matched the probe filters.")
        session.expunge(account)
        return account


def _output_path() -> Path:
    preferred = Path("/tmp/dimension_probe_result.json")
    try:
        preferred.parent.mkdir(parents=True, exist_ok=True)
        return preferred
    except OSError:
        return Path(tempfile.gettempdir()) / "dimension_probe_result.json"


async def run_probe(account_id: int | None, tenant_id: int | None) -> dict[str, Any]:
    today = date.today()
    end_date = today - timedelta(days=1)
    start_date = end_date - timedelta(days=6)
    account = await _select_account(account_id, tenant_id)

    client = BaiduAPIClient(
        username=account.baidu_username,
        access_token=decrypt(account.access_token_encrypted),
    )
    service = ReportService(client)

    result: dict[str, Any] = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "probe_window": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "days": 7,
        },
        "account": {
            "id": account.id,
            "tenant_id": account.tenant_id,
            "baidu_ucid": account.baidu_ucid,
            "baidu_username_masked": _mask(account.baidu_username),
            "auth_mode": account.auth_mode,
            "status": account.status,
            "expires_at": _json_safe(account.expires_at),
        },
        "reports": {},
    }

    for name, spec in REPORTS.items():
        started_at = datetime.utcnow()
        body = {
            "report_type": spec["report_type"],
            "time_unit": spec["time_unit"],
            "columns_requested": spec["columns"],
        }
        try:
            rows = await service._get_report_rows(  # noqa: SLF001
                report_type=spec["report_type"],
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
                columns=spec["columns"],
                time_unit=spec["time_unit"],
                page_size=10000,
            )
            body.update(
                {
                    "ok": True,
                    "duration_seconds": round(
                        (datetime.utcnow() - started_at).total_seconds(), 3
                    ),
                    "response": _summarize_rows(rows),
                }
            )
        except Exception as exc:  # noqa: BLE001
            body.update(
                {
                    "ok": False,
                    "duration_seconds": round(
                        (datetime.utcnow() - started_at).total_seconds(), 3
                    ),
                    "error": _error_payload(exc),
                }
            )
        result["reports"][name] = body

    path = _output_path()
    result["output_path"] = str(path)
    path.write_text(
        json.dumps(_json_safe(result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe Baidu age/gender/region reportType availability."
    )
    parser.add_argument("--account-id", type=int, default=None)
    parser.add_argument("--tenant-id", type=int, default=None)
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    result = await run_probe(args.account_id, args.tenant_id)
    print(json.dumps(_json_safe(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    raise SystemExit(asyncio.run(main()))
