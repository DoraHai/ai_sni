"""调价台账：百度操作记录查询（原型 04-verify/01-adjustment-log）。

数据来自 operation_records（getOperationRecord 同步，只读）。
AI 建议值 / 是否采纳 / 调后效果三列是 M2 建议引擎的平台自存字段，本期返回 null 占位。
"""
import re
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dashboard import _f
from app.database import get_session
from app.models import (
    OPT_CONTENT_LABELS,
    OPT_LEVEL_LABELS,
    Adgroup,
    Campaign,
    Keyword,
    OperationRecord,
)
from app.security.auth import require_scoped_auth

router = APIRouter(
    prefix="/api/v1/operation-records",
    tags=["调价台账"],
    dependencies=[Depends(require_scoped_auth)],
)

_NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")

OPT_TYPE_LABELS = {
    1: "设置", 2: "新增", 3: "删除", 4: "修改", 5: "暂停",
    6: "启用", 7: "重命名", 8: "激活", 9: "取消", 10: "系统激活", 11: "关键词转移",
}


# 百度操作记录的对象名有时带括号/引号包裹（如「[碳足迹]」），匹配 keywords 表前剥掉两端
_KW_WRAPPERS = " []【】「」『』\"'“”‘’"


def _norm_kw(name: str | None) -> str:
    return (name or "").strip(_KW_WRAPPERS).strip()


def _change(old: str | None, new: str | None) -> dict[str, Any] | None:
    """old/new 都是数值时算变化幅度；单次调价超 20% 是业务硬上限，标 over_limit。"""
    if not old or not new or not _NUM_RE.match(old.strip()) or not _NUM_RE.match(new.strip()):
        return None
    o, n = float(old), float(new)
    if o == 0:
        return None
    pct = round((n - o) / o * 100, 1)
    return {"pct": pct, "over_limit": abs(pct) > 20}


@router.get("")
async def list_operation_records(
    tenant_id: int = Query(..., description="本地租户 ID"),
    opt_level: int | None = Query(None, description="5=关键词 1=单元 2=计划"),
    opt_content: str | None = Query(None, description="操作内容代码，如 bidPriceWord"),
    q: str | None = Query(None, description="被操作对象模糊搜索"),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    over_limit: bool | None = Query(None, description="true=只看超 20% 上限的调价"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """台账列表 + 本月统计卡。默认全期倒序。"""
    cond = [OperationRecord.tenant_id == tenant_id]
    if opt_level is not None:
        cond.append(OperationRecord.opt_level == opt_level)
    if opt_content:
        cond.append(OperationRecord.opt_content == opt_content)
    if q:
        cond.append(OperationRecord.opt_obj.ilike(f"%{q}%"))
    if start_date:
        cond.append(OperationRecord.opt_time >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        cond.append(
            OperationRecord.opt_time
            < datetime.combine(end_date + timedelta(days=1), datetime.min.time())
        )

    rows_all = (
        await session.scalars(
            select(OperationRecord).where(*cond).order_by(OperationRecord.opt_time.desc())
        )
    ).all()

    # over_limit 筛选要先算 change，在 Python 侧过滤（数据量＝单租户操作流水，可控）
    enriched = []
    for r in rows_all:
        change = _change(r.old_value, r.new_value)
        if over_limit and not (change and change["over_limit"]):
            continue
        enriched.append((r, change))

    total = len(enriched)
    page_rows = enriched[(page - 1) * page_size : (page - 1) * page_size + page_size]

    camp_names = {
        c.campaign_id: c.campaign_name
        for c in (
            await session.scalars(select(Campaign).where(Campaign.tenant_id == tenant_id))
        ).all()
    }
    adg_names = {
        a.adgroup_id: a.adgroup_name
        for a in (
            await session.scalars(select(Adgroup).where(Adgroup.tenant_id == tenant_id))
        ).all()
    }

    # 关键词级记录（opt_level=5）按名解析 keyword_id，供前端跳转详情页。
    # 操作记录里百度只给关键词名（opt_obj）不给 ID；同字面常对应多个 ID（不同单元/匹配方式，
    # 苏尔寿账户普遍如此）。无法确知操作的是哪一个，取**累计展现最高**的那个（最可能是主词，
    # 也最值得下钻）；查无匹配则 null（前端不可点）。
    # ⚠️ 百度对部分操作（如出价）的对象名带方括号「[碳足迹]」，需剥掉两端括号/引号再匹配。
    kw_objs = {
        _norm_kw(r.opt_obj) for r, _ in page_rows if r.opt_level == 5 and r.opt_obj
    }
    kw_id_map: dict[str, int] = {}
    if kw_objs:
        best: dict[str, tuple[int, int]] = {}  # 归一化名 -> (total_impression, keyword_id)
        for name, kid, imp in (
            await session.execute(
                select(
                    Keyword.keyword, Keyword.keyword_id, Keyword.total_impression
                ).where(Keyword.tenant_id == tenant_id, Keyword.keyword.in_(kw_objs))
            )
        ).all():
            imp = int(imp or 0)
            if name not in best or imp > best[name][0]:
                best[name] = (imp, kid)
        kw_id_map = {name: v[1] for name, v in best.items()}

    # ===== 本月统计卡（不受筛选影响） =====
    month_start = date.today().replace(day=1)
    month_rows = (
        await session.scalars(
            select(OperationRecord).where(
                OperationRecord.tenant_id == tenant_id,
                OperationRecord.opt_time >= datetime.combine(month_start, datetime.min.time()),
            )
        )
    ).all()
    month_over = sum(
        1 for r in month_rows if (c := _change(r.old_value, r.new_value)) and c["over_limit"]
    )
    summary = {
        "month_total": len(month_rows),
        "month_keyword_level": sum(1 for r in month_rows if r.opt_level == 5),
        "month_coef_level": sum(1 for r in month_rows if r.opt_level in (1, 2)),
        "month_over_limit": month_over,
    }

    last_synced = await session.scalar(
        select(func.max(OperationRecord.synced_at)).where(
            OperationRecord.tenant_id == tenant_id
        )
    )

    return {
        "summary": summary,
        "total": total,
        "page": page,
        "page_size": page_size,
        "last_synced_at": last_synced.isoformat() if last_synced else None,
        "content_options": [
            {"code": code, "label": label} for code, label in OPT_CONTENT_LABELS.items()
        ],
        "records": [
            {
                "id": r.id,
                "opt_time": r.opt_time.isoformat(),
                "opt_level": r.opt_level,
                "level_label": OPT_LEVEL_LABELS.get(r.opt_level),
                "opt_type": r.opt_type,
                "type_label": OPT_TYPE_LABELS.get(r.opt_type),
                "opt_content": r.opt_content,
                "content_label": OPT_CONTENT_LABELS.get(r.opt_content, r.opt_content),
                "opt_obj": r.opt_obj,
                # 唯一解析到的关键词 ID（仅 opt_level=5），前端据此把关键词做成可跳详情页的链接
                "keyword_id": kw_id_map.get(_norm_kw(r.opt_obj)) if r.opt_level == 5 else None,
                "campaign_name": camp_names.get(r.plan_id),
                "adgroup_name": adg_names.get(r.unit_id),
                "old_value": r.old_value,
                "new_value": r.new_value,
                "change": change,
                "source": "百度后台",  # 平台写回 M2 上线后才有更细来源
                # M2 建议引擎字段占位
                "ai_suggestion": None,
                "adopted": None,
                "effect_review": None,
            }
            for r, change in page_rows
        ],
    }
