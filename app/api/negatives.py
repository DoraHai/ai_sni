"""否词管理（原型 03-optimize/04-negative-words，优化执行工作流）。

否词的添加/删除支持**单元级**写回（updateAdgroup 追加/移除，dry-run 保护，见 app/baidu/writeback.py）；
计划级否词写回（updateCampaign）暂未做，列表里计划级否词只读。重复/冲突为本地检测。
  - 重复否词：本地检测——单元级否词与所属计划同匹配方式的否词重复
  - 冲突否词：本地检测——否词与作用范围内现役关键词字面冲突（精确否=字面相等、
    短语否=字面包含），会导致该词自身查询漏展
  - 冷门否词：需要否词触发数据，百度不提供（被否词挡掉的查询不进搜索词报告）→ M2 占位
"自研搜索词扫描"= 拓词里 suggested_category='negative' 的候选，前端直接调 expansion 接口。
"""
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.baidu.writeback import (
    WritebackError,
    apply_negative_writeback,
    apply_remove_negative_writeback,
)
from app.database import get_session
from app.models import Adgroup, Campaign, Keyword
from app.security.auth import AuthContext, require_scoped_auth

router = APIRouter(
    prefix="/api/v1/negative-words",
    tags=["否词管理"],
    dependencies=[Depends(require_scoped_auth)],
)

MATCH_LABELS = {"phrase": "短语否", "exact": "精确否"}
SCOPE_LABELS = {"campaign": "计划级", "adgroup": "单元级"}

# 平铺上限：单租户否词数量级在百~千条（配额上限 900），防御性封顶
FLATTEN_CAP = 5000


def _norm(w: Any) -> str | None:
    if not isinstance(w, str):
        return None
    w = w.strip()
    return w or None


def _conflict_keywords(
    neg_word: str, match: str, kw_texts: list[str], limit: int = 3
) -> list[str]:
    """否词与现役关键词字面冲突：精确否=相等，短语否=包含。返回前几个示例。"""
    neg = neg_word.lower()
    hits = []
    for t in kw_texts:
        tl = t.lower()
        if (match == "exact" and tl == neg) or (match == "phrase" and neg in tl):
            hits.append(t)
            if len(hits) >= limit:
                break
    return hits


@router.get("")
async def list_negative_words(
    tenant_id: int = Query(..., description="本地租户 ID"),
    scope: str | None = Query(None, description="campaign / adgroup"),
    match: str | None = Query(None, description="phrase / exact"),
    flag: str | None = Query(None, description="duplicate / conflict，只看命中检测的"),
    q: str | None = Query(None, description="搜索否词 / 计划 / 单元"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """现有否词平铺（计划级 + 单元级）+ 重复/冲突检测 + 汇总计数。

    数据量级小（配额上限 900 条），一次返回不分页，封顶 5000。
    """
    campaigns = (
        await session.scalars(
            select(Campaign).where(Campaign.tenant_id == tenant_id)
        )
    ).all()
    adgroups = (
        await session.scalars(
            select(Adgroup).where(Adgroup.tenant_id == tenant_id)
        )
    ).all()
    camp_by_id = {c.campaign_id: c for c in campaigns}

    # 现役关键词字面（冲突检测用）：按计划/单元分桶，只看未暂停的词
    kw_rows = (
        await session.execute(
            select(Keyword.keyword, Keyword.campaign_id, Keyword.adgroup_id).where(
                Keyword.tenant_id == tenant_id,
                Keyword.keyword.isnot(None),
                Keyword.pause.isnot(True),
            )
        )
    ).all()
    kws_by_camp: dict[int, list[str]] = {}
    kws_by_adg: dict[int, list[str]] = {}
    for text, camp_id, adg_id in kw_rows:
        if camp_id is not None:
            kws_by_camp.setdefault(camp_id, []).append(text)
        if adg_id is not None:
            kws_by_adg.setdefault(adg_id, []).append(text)

    # 计划级否词集合（按匹配方式），单元重复检测用
    camp_neg_sets: dict[int, dict[str, set[str]]] = {}
    for c in campaigns:
        camp_neg_sets[c.campaign_id] = {
            "phrase": {w.lower() for raw in (c.negative_words or []) if (w := _norm(raw))},
            "exact": {
                w.lower() for raw in (c.exact_negative_words or []) if (w := _norm(raw))
            },
        }

    items: list[dict[str, Any]] = []
    seen_items: set[tuple] = set()

    def add_item(
        word: str,
        match_key: str,
        scope_key: str,
        camp: Campaign | None,
        adg: Adgroup | None,
        kw_texts: list[str],
    ) -> None:
        if len(items) >= FLATTEN_CAP:
            return
        item_key = (
            scope_key,
            camp.campaign_id if camp else None,
            adg.adgroup_id if adg else None,
            match_key,
            word.casefold(),
        )
        if item_key in seen_items:
            return
        seen_items.add(item_key)
        flags = []
        notes = []
        if (
            scope_key == "adgroup"
            and camp is not None
            and word.lower() in camp_neg_sets.get(camp.campaign_id, {}).get(match_key, set())
        ):
            flags.append("duplicate")
            notes.append(f"所属计划已有同匹配方式否词「{word}」，本条可清理（合并）")
        conflicts = _conflict_keywords(word, match_key, kw_texts)
        if conflicts:
            flags.append("conflict")
            notes.append(
                "与现役关键词冲突，导致漏展：" + " / ".join(conflicts)
            )
        items.append(
            {
                "word": word,
                "match": match_key,
                "match_label": MATCH_LABELS[match_key],
                "scope": scope_key,
                "scope_label": SCOPE_LABELS[scope_key],
                "campaign_id": camp.campaign_id if camp else None,
                "campaign_name": camp.campaign_name if camp else None,
                "adgroup_id": adg.adgroup_id if adg else None,
                "adgroup_name": adg.adgroup_name if adg else None,
                "flags": flags,
                "note": "；".join(notes) or None,
                "conflict_keywords": conflicts,
            }
        )

    for c in campaigns:
        kw_texts = kws_by_camp.get(c.campaign_id, [])
        for raw in c.negative_words or []:
            if w := _norm(raw):
                add_item(w, "phrase", "campaign", c, None, kw_texts)
        for raw in c.exact_negative_words or []:
            if w := _norm(raw):
                add_item(w, "exact", "campaign", c, None, kw_texts)
    for a in adgroups:
        camp = camp_by_id.get(a.campaign_id)
        kw_texts = kws_by_adg.get(a.adgroup_id, [])
        for raw in a.negative_words or []:
            if w := _norm(raw):
                add_item(w, "phrase", "adgroup", camp, a, kw_texts)
        for raw in a.exact_negative_words or []:
            if w := _norm(raw):
                add_item(w, "exact", "adgroup", camp, a, kw_texts)

    # 汇总在筛选前算（KPI 卡不随筛选变）
    summary = {
        "total": len(items),
        "campaign_level": sum(1 for i in items if i["scope"] == "campaign"),
        "adgroup_level": sum(1 for i in items if i["scope"] == "adgroup"),
        "phrase": sum(1 for i in items if i["match"] == "phrase"),
        "exact": sum(1 for i in items if i["match"] == "exact"),
        "duplicates": sum(1 for i in items if "duplicate" in i["flags"]),
        "conflicts": sum(1 for i in items if "conflict" in i["flags"]),
    }

    if scope in SCOPE_LABELS:
        items = [i for i in items if i["scope"] == scope]
    if match in MATCH_LABELS:
        items = [i for i in items if i["match"] == match]
    if flag in ("duplicate", "conflict"):
        items = [i for i in items if flag in i["flags"]]
    if q:
        ql = q.lower()
        items = [
            i
            for i in items
            if ql in i["word"].lower()
            or ql in (i["campaign_name"] or "").lower()
            or ql in (i["adgroup_name"] or "").lower()
        ]

    return {"summary": summary, "total": len(items), "items": items}


# ===== 否词写回（单元级 updateAdgroup，dry-run 保护，记 writeback_actions） =====


class NegativeRequest(BaseModel):
    tenant_id: int
    word: str
    adgroup_id: int
    match_mode: Literal["exact", "phrase"] = "exact"


@router.post("/add")
async def add_negative(
    req: NegativeRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """手动添加单元否词（updateAdgroup 追加）。dry-run 保护 + 台账。"""
    ctx.ensure_tenant(req.tenant_id)
    try:
        rec = await apply_negative_writeback(
            session, req.tenant_id, req.word, req.adgroup_id,
            match_mode=req.match_mode, operator_user_id=ctx.user_id, operator_name=ctx.username,
        )
    except WritebackError as e:
        raise HTTPException(400, str(e))
    if rec.status == "failed":
        raise HTTPException(502, "百度否词写回失败，已记录失败台账，请稍后重试")
    return {"status": "ok", "dry_run": rec.dry_run, "writeback_status": rec.status}


@router.post("/remove")
async def remove_negative(
    req: NegativeRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """删除单元否词（updateAdgroup 移除）。dry-run 保护 + 台账。计划级否词不支持（updateCampaign 未做）。"""
    ctx.ensure_tenant(req.tenant_id)
    try:
        rec = await apply_remove_negative_writeback(
            session, req.tenant_id, req.word, req.adgroup_id,
            match_mode=req.match_mode, operator_user_id=ctx.user_id, operator_name=ctx.username,
        )
    except WritebackError as e:
        raise HTTPException(400, str(e))
    if rec.status == "failed":
        raise HTTPException(502, "百度否词删除失败，已记录失败台账，请稍后重试")
    return {"status": "ok", "dry_run": rec.dry_run, "writeback_status": rec.status}
