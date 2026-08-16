"""竞品报告存档：版本、状态、导出。"""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any

from app.models.geo_competitor_report import GeoCompetitorReport, GeoCompetitorReportVersion


def report_payload(row: GeoCompetitorReport, *, versions: list[GeoCompetitorReportVersion] | None = None) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "business_id": row.business_id,
        "period_id": row.period_id,
        "competitor": row.competitor,
        "title": row.title,
        "status": row.status,
        "insight": row.insight,
        "action": row.action,
        "note": row.note,
        "markdown": row.markdown,
        "source_urls": list(row.source_urls or []),
        "platform_keys": list(row.platform_keys or []),
        "evidence": row.evidence or {},
        "version_no": row.version_no,
        "created_by": row.created_by,
        "confirmed_by": row.confirmed_by,
        "confirmed_at": row.confirmed_at.isoformat() if row.confirmed_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "versions": [
            {
                "version_no": v.version_no,
                "insight": v.insight,
                "action": v.action,
                "note": v.note,
                "markdown": v.markdown,
                "created_at": v.created_at.isoformat() if v.created_at else None,
                "created_by": v.created_by,
            }
            for v in (versions or [])
        ],
    }


def snapshot_version(row: GeoCompetitorReport, *, user_id: int | None) -> GeoCompetitorReportVersion:
    return GeoCompetitorReportVersion(
        report_id=row.id,
        tenant_id=row.tenant_id,
        version_no=int(row.version_no or 1),
        markdown=row.markdown,
        insight=row.insight,
        action=row.action,
        note=row.note,
        created_by=user_id,
    )


def markdown_to_simple_html(md: str, title: str) -> str:
    body = escape(md or "")
    body = body.replace("\n", "<br>\n")
    return (
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
        f"<title>{escape(title)}</title>"
        "<style>body{font-family:sans-serif;max-width:760px;margin:40px auto;line-height:1.6;color:#111}"
        "h1{font-size:22px}</style></head><body>"
        f"<h1>{escape(title)}</h1><article>{body}</article></body></html>"
    )


def apply_snapshot_fields(row: GeoCompetitorReport, **fields: Any) -> None:
    for key, val in fields.items():
        if val is not None or key in {"insight", "action", "note", "markdown"}:
            setattr(row, key, val)
    row.updated_at = datetime.utcnow()
