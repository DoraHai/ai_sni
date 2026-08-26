"""投放分析报告接口（客户交付页，AI 应用路线 ③）。

生成见 app/ai/monthly_report.py。数据模块实时聚合，AI 叙述按日期区间缓存。
内部版 / 客户版的模块可见性由前端控制（后端一次返回全量）。
"""
import logging
import csv
import copy
import html
import io
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.monthly_report import get_analysis_report, get_monthly_report
from app.database import get_session
from app.models import KwReportSnapshot, Tenant
from app.security.auth import AuthContext, require_scoped_auth

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/reports",
    tags=["投放分析报告"],
    dependencies=[Depends(require_scoped_auth)],
)


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return str(round(v, 4))
    return str(v)


def _client_report_view(report: dict) -> dict:
    """Build a client-safe view without internal work or synchronization diagnostics."""
    output = copy.deepcopy(report)
    data = output["data"]
    data.pop("operational_focus", None)
    data.pop("alerts_review", None)
    data.pop("pending_modules", None)
    delivery = data.get("client_delivery") or {}
    data["operations"] = {
        "total": int(delivery.get("completed_count") or 0),
        "by_level": {},
        "over_limit": 0,
        "ai_suggestions_adopted": 0,
    }
    narrative = output.get("narrative")
    if narrative:
        narrative["module_comments"] = {
            key: value
            for key, value in (narrative.get("module_comments") or {}).items()
            if key not in {"alerts", "operations"}
        }
        period = data["period"]
        completed = int(delivery.get("completed_count") or 0)
        ready = int(delivery.get("ready_effects") or 0)
        observing = int(delivery.get("observing_effects") or 0)
        narrative["summary"] = (
            f"本报告覆盖 {period['start_date']} 至 {period['end_date']} 的投放表现。"
            f"区间内已由百度操作记录确认 {completed} 项优化动作；"
            f"其中 {ready} 项效果样本已成熟，{observing} 项仍在观察中。"
        )
        narrative["next_period_plan"] = []
    output["view"] = "client"
    return output


def _report_view(report: dict, version: str, ctx: AuthContext) -> dict:
    if ctx.tenant_id is not None or version == "client":
        return _client_report_view(report)
    report["view"] = "internal"
    return report


def _rows_from_report(report: dict) -> list[list[str]]:
    data = report["data"]
    narrative = report.get("narrative") or {}
    period = data["period"]
    rows: list[list[str]] = [
        ["模块", "指标/对象", "数值1", "数值2", "数值3", "备注"],
        [
            "报告信息",
            data["tenant"]["name"],
            "自定义区间",
            period["start_date"],
            period["end_date"],
            f"投放 {period['active_days']}/{period['days']} 天",
        ],
    ]
    if narrative.get("summary"):
        rows.append(["AI 总览", "摘要", narrative["summary"], "", "", ""])

    for key, label in (
        ("cost", "消费"),
        ("click", "点击"),
        ("impression", "展现"),
        ("cpc", "平均点击成本"),
        ("ctr", "点击率"),
    ):
        item = data["kpi"][key]
        rows.append([
            "整体数据",
            label,
            _fmt(item.get("current")),
            _fmt(item.get("previous")),
            _fmt(item.get("change_pct")),
            "当前值 / 上一等长区间值 / 变化%",
        ])
    budget = data["budget"]
    rows.append([
        "预算",
        "区间消费与月预算参考",
        _fmt(budget.get("period_cost", budget.get("month_cost"))),
        _fmt(budget.get("monthly_budget")),
        _fmt(budget.get("usage_pct")),
        "区间消费 / 月预算参考 / 比例%",
    ])

    for row in data.get("trend") or []:
        rows.append([
            "日趋势",
            row["date"],
            _fmt(row.get("cost")),
            _fmt(row.get("click")),
            _fmt(row.get("impression")),
            "消费 / 点击 / 展现",
        ])
    for row in data.get("by_category") or []:
        rows.append([
            "分类报告",
            row.get("category_label"),
            _fmt(row.get("cost")),
            _fmt(row.get("cost_share_pct")),
            _fmt(row.get("ctr")),
            "消费 / 占比% / 点击率",
        ])
    for row in data.get("top_keywords") or []:
        rows.append([
            "TOP关键词",
            row.get("keyword"),
            _fmt(row.get("cost")),
            _fmt(row.get("click")),
            _fmt(row.get("avg_rank")),
            "消费 / 点击 / 平均排名",
        ])
    for row in data.get("device_split") or []:
        rows.append([
            "设备分布",
            row.get("device"),
            _fmt(row.get("cost")),
            _fmt(row.get("cost_share_pct")),
            _fmt(row.get("cpc")),
            "消费 / 占比% / 平均点击成本",
        ])
    for status, count in (data.get("alerts_review") or {}).items():
        rows.append(["异常处置", status, _fmt(count), "", "", "open=未处理 resolved=已处理 merged=已归并"])

    operations = data.get("operations") or {}
    rows.append([
        "优化操作",
        "区间操作",
        _fmt(operations.get("total")),
        _fmt(operations.get("over_limit")),
        _fmt(operations.get("ai_suggestions_adopted")),
        "操作数 / 超20%上限 / AI建议采纳",
    ])
    for level, count in (operations.get("by_level") or {}).items():
        rows.append(["优化操作", level, _fmt(count), "", "", "按操作层级统计"])
    for action in (data.get("client_delivery") or {}).get("completed_actions") or []:
        effect = action.get("effect") or {}
        sample = effect.get("sample") or {}
        effect_note = sample.get("message") or "该动作无需效果窗口"
        rows.append([
            "已完成动作",
            action.get("object"),
            action.get("action"),
            action.get("old_value"),
            action.get("new_value"),
            f"{action.get('evidence')} · {effect_note}",
        ])
    plans = narrative.get("next_period_plan") or narrative.get("next_month_plan") or []
    for idx, item in enumerate(plans, 1):
        rows.append(["后续计划", f"计划{idx}", item, "", "", ""])
    return rows


def _download_filename(tenant_id: int, year: int, month: int, ext: str) -> str:
    return f"monthly_report_{tenant_id}_{year}_{month:02d}.{ext}"


def _download_period_filename(
    tenant_id: int, start_date: date, end_date: date, ext: str
) -> str:
    return (
        f"analysis_report_{tenant_id}_{start_date.isoformat()}_"
        f"{end_date.isoformat()}.{ext}"
    )


def _validate_period(start_date: date, end_date: date) -> None:
    if start_date > end_date:
        raise HTTPException(400, "统计起始日期不能晚于截止日期")
    if (end_date - start_date).days > 365:
        raise HTTPException(400, "单次报告区间不能超过 366 天")


@router.get("/analysis")
async def analysis_report(
    tenant_id: int = Query(..., description="本地租户 ID"),
    start_date: date = Query(..., description="统计起始日期"),
    end_date: date = Query(..., description="统计截止日期"),
    force: bool = Query(False, description="true=强制重新生成 AI 叙述"),
    version: str = Query("internal", pattern="^(internal|client)$"),
    session: AsyncSession = Depends(get_session),
    ctx: AuthContext = Depends(require_scoped_auth),
) -> dict:
    """某租户自定义日期区间的投放分析报告。"""
    _validate_period(start_date, end_date)
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "租户不存在，请确认 tenant_id")
    ctx.ensure_tenant(tenant_id)
    report = await get_analysis_report(
        session, tenant, start_date, end_date, force=force
    )
    return _report_view(report, version, ctx)


@router.get("/analysis/export")
async def export_analysis_report(
    tenant_id: int = Query(..., description="本地租户 ID"),
    start_date: date = Query(..., description="统计起始日期"),
    end_date: date = Query(..., description="统计截止日期"),
    format: str = Query(
        "csv", pattern="^(csv|xls)$", description="csv 或 xls（Excel 可打开）"
    ),
    version: str = Query("internal", pattern="^(internal|client)$"),
    session: AsyncSession = Depends(get_session),
    ctx: AuthContext = Depends(require_scoped_auth),
) -> Response:
    """导出自定义日期区间报告。"""
    _validate_period(start_date, end_date)
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "租户不存在，请确认 tenant_id")
    ctx.ensure_tenant(tenant_id)
    report = await get_analysis_report(
        session, tenant, start_date, end_date, force=False
    )
    rows = _rows_from_report(_report_view(report, version, ctx))
    filename = _download_period_filename(
        tenant_id, start_date, end_date, format
    )

    if format == "xls":
        table_rows = []
        for row in rows:
            cells = "".join(
                f"<td>{html.escape(_fmt(cell))}</td>" for cell in row
            )
            table_rows.append(f"<tr>{cells}</tr>")
        body = (
            '<html><head><meta charset="utf-8"></head><body>'
            '<table border="1">'
            + "".join(table_rows)
            + "</table></body></html>"
        )
        return Response(
            body,
            media_type="application/vnd.ms-excel; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerows(rows)
    return Response(
        "\ufeff" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/monthly")
async def monthly_report(
    tenant_id: int = Query(..., description="本地租户 ID"),
    year: int = Query(..., ge=2020, le=2100),
    month: int = Query(..., ge=1, le=12),
    force: bool = Query(False, description="true=强制重新生成 AI 叙述（忽略缓存）"),
    version: str = Query("internal", pattern="^(internal|client)$"),
    session: AsyncSession = Depends(get_session),
    ctx: AuthContext = Depends(require_scoped_auth),
) -> dict:
    """某租户某月的分析报告。数据模块实时聚合；AI 叙述缓存命中直接返回、未配 key 则为 null。"""
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "租户不存在，请确认 tenant_id")
    ctx.ensure_tenant(tenant_id)
    report = await get_monthly_report(session, tenant, year, month, force=force)
    return _report_view(report, version, ctx)


@router.get("/monthly/export")
async def export_monthly_report(
    tenant_id: int = Query(..., description="本地租户 ID"),
    year: int = Query(..., ge=2020, le=2100),
    month: int = Query(..., ge=1, le=12),
    format: str = Query("csv", pattern="^(csv|xls)$", description="csv 或 xls（Excel 可打开）"),
    version: str = Query("internal", pattern="^(internal|client)$"),
    session: AsyncSession = Depends(get_session),
    ctx: AuthContext = Depends(require_scoped_auth),
) -> Response:
    """导出月报表格。csv 为标准逗号分隔；xls 为 Excel 可直接打开的 HTML 表格。"""
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "租户不存在，请确认 tenant_id")
    ctx.ensure_tenant(tenant_id)
    report = await get_monthly_report(session, tenant, year, month, force=False)
    rows = _rows_from_report(_report_view(report, version, ctx))

    if format == "xls":
        table_rows = []
        for row in rows:
            cells = "".join(f"<td>{html.escape(_fmt(cell))}</td>" for cell in row)
            table_rows.append(f"<tr>{cells}</tr>")
        body = (
            "<html><head><meta charset=\"utf-8\"></head><body>"
            "<table border=\"1\">"
            + "".join(table_rows)
            + "</table></body></html>"
        )
        filename = _download_filename(tenant_id, year, month, "xls")
        return Response(
            body,
            media_type="application/vnd.ms-excel; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerows(rows)
    filename = _download_filename(tenant_id, year, month, "csv")
    return Response(
        "\ufeff" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/monthly/available-months")
async def available_months(
    tenant_id: int = Query(..., description="本地租户 ID"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """有报告数据（kw_report_snapshots）的月份列表，给前端月份选择器/历史用，按时间倒序。"""
    # date_trunc('month', report_date) 取每个有数据的月份
    rows = (
        await session.execute(
            select(
                func.extract("year", KwReportSnapshot.report_date),
                func.extract("month", KwReportSnapshot.report_date),
                func.sum(KwReportSnapshot.cost),
            )
            .where(KwReportSnapshot.tenant_id == tenant_id)
            .group_by(
                func.extract("year", KwReportSnapshot.report_date),
                func.extract("month", KwReportSnapshot.report_date),
            )
        )
    ).all()
    months = sorted(
        (
            {
                "year": int(y),
                "month": int(m),
                "label": f"{int(y)}年{int(m)}月",
                "cost": round(float(c or 0), 2),
            }
            for y, m, c in rows
        ),
        key=lambda x: (x["year"], x["month"]),
        reverse=True,
    )
    # 默认月份：最近一个有消费的月（没有则上个月）
    default = next((m for m in months if m["cost"] > 0), months[0] if months else None)
    if default is None:
        today = date.today()
        prev = today.replace(day=1)
        prev = (prev.replace(year=prev.year - 1, month=12) if prev.month == 1
                else prev.replace(month=prev.month - 1))
        default = {"year": prev.year, "month": prev.month, "label": f"{prev.year}年{prev.month}月"}
    return {"months": months, "default": {"year": default["year"], "month": default["month"]}}
