"""首次接入：AI 智能搭建草案与演练写入。"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.deepseek import DeepSeekError, chat_json, is_enabled
from app.ai.expansion_eval import evaluate_candidates_for_tenant
from app.baidu import BaiduAPIError
from app.baidu.services.adgroup import AdgroupService
from app.baidu.services.campaign import CampaignService
from app.baidu.services.creative import CreativeService
from app.baidu.services.keyword import KeywordService
from app.baidu.sync import _account_client, sync_planner_candidates_for_account, sync_url_candidates_for_account
from app.config import get_settings
from app.database import get_session
from app.models import BaiduAccount, KeywordCandidate, Tenant, WritebackAction
from app.security.auth import AuthContext, require_scoped_auth
from app.sem_urlwords import UrlFetchError, extract_words, fetch_page_text

router = APIRouter(
    prefix="/api/v1/onboarding-builder",
    tags=["智能搭建"],
    dependencies=[Depends(require_scoped_auth)],
)

logger = logging.getLogger(__name__)


class DraftRequest(BaseModel):
    tenant_id: int = Field(..., description="本地租户 ID")
    landing_url: str | None = Field(None, max_length=500, description="落地页 URL")
    landing_text: str | None = Field(None, max_length=12000, description="图片式落地页文案")
    business_summary: str = Field(..., min_length=2, max_length=2000, description="业务概述")
    goal: str = Field(..., min_length=2, max_length=200, description="投放目的")
    budget: str | None = Field(None, max_length=200, description="预算信息")
    regions: str | None = Field(None, max_length=500, description="投放区域")
    schedule: str | None = Field(None, max_length=500, description="投放时段")
    schedule_blocks: list[dict[str, Any]] | None = Field(None, description="结构化投放时段")
    device_preference: str | None = Field("不限", max_length=50, description="设备偏好")


class ApplyDraftRequest(BaseModel):
    tenant_id: int = Field(..., description="本地租户 ID")
    draft: dict[str, Any] = Field(..., description="已确认的搭建草案")


def _text(v: Any, default: str = "") -> str:
    return str(v).strip() if v is not None else default


def _bool(v: Any, default: bool = True) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() not in ("false", "0", "no", "否")
    return default


def _num(v: Any, default: float) -> float:
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return default


def _bounded_num(v: Any, default: float, min_value: float, max_value: float) -> float:
    value = _num(v, default)
    return round(max(min_value, min(max_value, value)), 2)


def _split_regions(regions: str | None) -> list[str]:
    parts = re.split(r"[,，、\s]+", regions or "")
    out = [p.strip() for p in parts if p.strip()]
    return out[:12] or ["按业务覆盖城市投放"]


def _split_schedule(schedule: str | None) -> list[str]:
    parts = re.split(r"[,，、]+", schedule or "")
    out = [p.strip() for p in parts if p.strip()]
    return out[:8] or ["周一至周日 09:00-22:00"]


def _normalize_schedule_blocks(blocks: Any) -> list[dict]:
    rows = blocks if isinstance(blocks, list) else []
    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        week_days = row.get("weekDays") or row.get("week_days") or []
        week_days = [int(day) for day in week_days if str(day).isdigit() and 1 <= int(day) <= 7]
        try:
            start_hour = int(row.get("startHour") if row.get("startHour") is not None else row.get("start_hour"))
            end_hour = int(row.get("endHour") if row.get("endHour") is not None else row.get("end_hour"))
        except (TypeError, ValueError):
            continue
        if not week_days or not (0 <= start_hour <= 23) or not (1 <= end_hour <= 24) or start_hour >= end_hour:
            continue
        out.append(
            {
                "weekDays": sorted(set(week_days)),
                "startHour": start_hour,
                "endHour": end_hour,
            }
        )
        if len(out) >= 8:
            break
    return out


def _schedule_price_factors(blocks: Any) -> list[dict[str, Any]]:
    normalized = _normalize_schedule_blocks(blocks)
    factors: list[dict[str, Any]] = []
    for block in normalized:
        for week_day in block["weekDays"]:
            for hour in range(block["startHour"], block["endHour"]):
                factors.append({"timeId": week_day * 100 + hour, "priceFactor": 1})
    return factors[:168]


def _equipment_type(device: str | None) -> int:
    text = _text(device)
    if "移动" in text and "PC" not in text.upper() and "不限" not in text:
        return 2
    if "PC" in text.upper() and "移动" not in text and "不限" not in text:
        return 1
    return 3


def _match_type(match: str | None) -> tuple[int, int, str]:
    text = _text(match)
    if "精确" in text:
        return 1, 1, "exact"
    if "智能" in text:
        return 2, 3, "phrase"
    return 2, 1, "phrase"


def _display_url(url: str | None) -> str:
    host = urlparse(_text(url)).netloc or "example.com"
    return host[:36] or "example.com"


def _response_id(resp: dict[str, Any], key: str) -> int | None:
    data = resp.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        raw = data[0].get(key)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
    return None


def _safe_json(data: Any) -> str:
    try:
        return json.dumps(data, ensure_ascii=False, default=str)[:2000]
    except TypeError:
        return str(data)[:2000]


def _schedule_blocks_text(blocks: list[dict]) -> list[str]:
    names = {1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五", 6: "周六", 7: "周日"}
    out: list[str] = []
    for block in blocks:
        days = block["weekDays"]
        if days == [1, 2, 3, 4, 5, 6, 7]:
            day_text = "周一至周日"
        elif days == [1, 2, 3, 4, 5]:
            day_text = "周一至周五"
        elif days == [6, 7]:
            day_text = "周六至周日"
        else:
            day_text = "、".join(names.get(day, str(day)) for day in days)
        out.append(f"{day_text} {block['startHour']:02d}:00-{block['endHour']:02d}:00")
    return out


def _request_schedule(req: DraftRequest) -> tuple[list[str], list[dict]]:
    blocks = _normalize_schedule_blocks(req.schedule_blocks)
    if blocks:
        return _schedule_blocks_text(blocks), blocks
    return _split_schedule(req.schedule), []


def _keyword_items(items: Any, fallback_words: list[str]) -> list[dict]:
    rows = items if isinstance(items, list) else []
    out: list[dict] = []
    for row in rows:
        if isinstance(row, str):
            row = {"word": row}
        if not isinstance(row, dict):
            continue
        word = _text(row.get("word") or row.get("keyword"))
        if not word:
            continue
        out.append(
            {
                "selected": _bool(row.get("selected"), True),
                "word": word[:40],
                "match": _text(row.get("match") or row.get("matchType"), "短语匹配")[:20],
                "bid": _num(row.get("bid") or row.get("price"), 2.0),
                "reason": _text(row.get("reason"), "贴合落地页核心卖点")[:120],
            }
        )
        if len(out) >= 12:
            break
    for w in fallback_words:
        if len(out) >= 8:
            break
        if w and all(x["word"] != w for x in out):
            out.append({"selected": True, "word": w[:40], "match": "短语匹配", "bid": 2.0, "reason": "页面提取候选词"})
    return out[:12]


async def _candidate_words(session: AsyncSession, tenant_id: int, limit: int = 24) -> list[str]:
    """复用拓词模块候选库，优先拿已评估可拓展的高质量候选。"""
    try:
        rows = (
            await session.scalars(
                select(KeywordCandidate)
                .where(
                    KeywordCandidate.tenant_id == tenant_id,
                    KeywordCandidate.status == "pending",
                    or_(KeywordCandidate.suggested_category.is_(None), KeywordCandidate.suggested_category != "negative"),
                )
                .order_by(
                    case(
                        (KeywordCandidate.ai_recommend == "adopt", 0),
                        (KeywordCandidate.ai_recommend == "watch", 1),
                        else_=2,
                    ),
                    case(
                        (KeywordCandidate.ai_relevance == "relevant", 0),
                        (KeywordCandidate.ai_relevance.is_(None), 1),
                        else_=2,
                    ),
                    KeywordCandidate.potential_score.desc().nulls_last(),
                    KeywordCandidate.monthly_pv.desc().nulls_last(),
                    KeywordCandidate.click.desc().nulls_last(),
                    KeywordCandidate.id.desc(),
                )
                .limit(limit)
            )
        ).all()
    except Exception as e:
        await session.rollback()
        logger.warning("智能搭建读取拓词候选失败，降级使用页面提词 tenant=%s: %s", tenant_id, e)
        return []

    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if row.ai_relevance in ("generic", "irrelevant") or row.ai_recommend == "drop":
            continue
        word = _text(row.word)
        if not word:
            continue
        key = word.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(word)
    return out


def _merge_words(*groups: list[str], limit: int = 30) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for word in group:
            word = _text(word)
            if not word:
                continue
            key = word.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(word)
            if len(out) >= limit:
                return out
    return out


async def _active_baidu_account(session: AsyncSession, tenant_id: int) -> BaiduAccount | None:
    return await session.scalar(
        select(BaiduAccount).where(
            BaiduAccount.tenant_id == tenant_id,
            BaiduAccount.status == "active",
        )
    )


async def _preheat_expansion_candidates(
    session: AsyncSession,
    tenant: Tenant,
    seeds: list[str],
    landing_url: str | None,
) -> dict[str, Any]:
    """首次接入候选不足时，轻量跑一轮拓词候选入库。

    这里只读百度，不写入广告账户；失败降级，不阻断草案生成。
    """
    acc = await _active_baidu_account(session, tenant.id)
    if acc is None:
        return {"enabled": False, "reason": "no_active_baidu_account"}

    seed_list = [w for w in _merge_words(seeds, limit=8) if 2 <= len(w) <= 24][:8]
    if not seed_list:
        seed_list = [t for t in (tenant.brand_terms or []) if t] or [tenant.name]
    seed_list = [s for s in seed_list if s][:8]

    result: dict[str, Any] = {
        "enabled": True,
        "seeds": seed_list,
        "planner_candidates": 0,
        "url_candidates": 0,
        "ai_eval": None,
        "errors": [],
    }

    try:
        result["planner_candidates"] = await sync_planner_candidates_for_account(
            session,
            acc,
            seed_list,
            max_num=80,
        )
    except BaiduAPIError as e:
        logger.warning("智能搭建规划师预热被百度拒绝 tenant=%s code=%s", tenant.id, e.code)
        result["errors"].append({"source": "planner", "message": "关键词规划数据暂时无法获取"})
    except Exception:
        await session.rollback()
        logger.exception("智能搭建规划师预热失败 tenant=%s", tenant.id)
        result["errors"].append({"source": "planner", "message": "关键词规划数据暂时无法获取"})

    if landing_url:
        try:
            url_count, _ = await sync_url_candidates_for_account(session, acc, [landing_url])
            result["url_candidates"] = url_count
        except BaiduAPIError as e:
            logger.warning("智能搭建 URL 拓词被百度拒绝 tenant=%s code=%s", tenant.id, e.code)
            result["errors"].append({"source": "url", "message": "落地页拓词数据暂时无法获取"})
        except Exception:
            await session.rollback()
            logger.exception("智能搭建 URL 拓词预热失败 tenant=%s", tenant.id)
            result["errors"].append({"source": "url", "message": "落地页拓词数据暂时无法获取"})

    try:
        result["ai_eval"] = await evaluate_candidates_for_tenant(session, tenant, limit=50)
    except Exception:
        await session.rollback()
        logger.exception("智能搭建拓词 AI 评估预热失败 tenant=%s", tenant.id)
        result["errors"].append({"source": "ai_eval", "message": "AI 评估暂时不可用"})

    return result


def _creative_items(items: Any, business: str, goal: str) -> list[dict]:
    rows = items if isinstance(items, list) else []
    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = _text(row.get("title"))
        if not title:
            continue
        out.append(
            {
                "selected": _bool(row.get("selected"), True),
                "title": title[:40],
                "description1": _text(row.get("description1") or row.get("description"), business)[:80],
                "description2": _text(row.get("description2"), f"围绕{goal}优化投放，支持持续跟踪。")[:80],
            }
        )
        if len(out) >= 3:
            break
    if not out:
        base = re.sub(r"\s+", "", business)[:18] or "专业服务"
        out = [
            {
                "selected": True,
                "title": f"{base[:12]}方案咨询",
                "description1": f"围绕{goal}制定搜索推广计划，匹配高意向人群。",
                "description2": "支持落地页承接、关键词优化和线索转化跟踪。",
            }
        ]
    return out


def _normalize_draft(raw: Any, req: DraftRequest, words: list[str], landing_page: str) -> dict:
    data = raw if isinstance(raw, dict) else {}
    campaigns = data.get("campaigns") if isinstance(data.get("campaigns"), list) else []
    normalized_campaigns: list[dict] = []
    request_schedule, request_schedule_blocks = _request_schedule(req)
    for camp in campaigns[:1]:
        if not isinstance(camp, dict):
            continue
        adgroups_raw = camp.get("adgroups") if isinstance(camp.get("adgroups"), list) else []
        adgroups: list[dict] = []
        for idx, adg in enumerate(adgroups_raw[:1]):
            if not isinstance(adg, dict):
                continue
            kw_words = words[:10]
            adgroups.append(
                {
                    "selected": _bool(adg.get("selected"), True),
                    "name": _text(adg.get("name"), f"核心单元{idx + 1}")[:60],
                    "max_price": _num(adg.get("max_price") or adg.get("maxPrice"), 2.0),
                    "landing_page": _text(adg.get("landing_page") or adg.get("landingPage"), landing_page)[:500],
                    "keywords": _keyword_items(adg.get("keywords"), kw_words),
                    "creatives": _creative_items(adg.get("creatives"), req.business_summary, req.goal),
                    "negative_words": [
                        _text(w)[:20]
                        for w in (adg.get("negative_words") or adg.get("negativeWords") or [])
                        if _text(w)
                    ][:12],
                }
            )
        if adgroups:
            normalized_campaigns.append(
                {
                    "selected": _bool(camp.get("selected"), True),
                    "name": _text(camp.get("name"), "AI搭建-搜索推广")[:60],
                    "budget": _num(camp.get("budget"), 100.0),
                    "device": _text(camp.get("device"), req.device_preference or "不限")[:20],
                    "regions": [str(x).strip() for x in (camp.get("regions") or _split_regions(req.regions)) if str(x).strip()][:12],
                    "schedule": [str(x).strip() for x in (camp.get("schedule") or request_schedule) if str(x).strip()][:8],
                    "schedule_blocks": _normalize_schedule_blocks(camp.get("schedule_blocks") or camp.get("scheduleBlocks")) or request_schedule_blocks,
                    "goal": _text(camp.get("goal"), req.goal)[:120],
                    "adgroups": adgroups,
                }
            )

    if not normalized_campaigns:
        return _fallback_draft(req, words, landing_page)

    return {
        "summary": _text(data.get("summary"), "已生成可编辑的百度搜索推广搭建草案。")[:300],
        "assumptions": [_text(x)[:120] for x in (data.get("assumptions") or []) if _text(x)][:8],
        "campaigns": normalized_campaigns,
        "risks": [_text(x)[:120] for x in (data.get("risks") or []) if _text(x)][:8],
        "next_steps": [_text(x)[:120] for x in (data.get("next_steps") or data.get("nextSteps") or []) if _text(x)][:8],
    }


def _fallback_draft(req: DraftRequest, words: list[str], landing_page: str) -> dict:
    request_schedule, request_schedule_blocks = _request_schedule(req)
    core = [w for w in words if 2 <= len(w) <= 16][:12] or ["品牌词", "业务咨询", "方案报价", "厂家服务", "定制方案", "电话咨询"]
    business_short = (core[0] if core else re.sub(r"\s+", "", req.business_summary))[:12] or "业务"
    adgroup = {
        "selected": True,
        "name": f"{business_short}_核心业务",
        "max_price": 2.0,
        "landing_page": landing_page,
        "keywords": [
            {"selected": True, "word": w[:40], "match": "短语匹配", "bid": 2.0, "reason": "根据落地页与业务描述提取"}
            for w in core[:10]
        ],
        "creatives": _creative_items([], req.business_summary, req.goal),
        "negative_words": ["招聘", "免费", "教程", "下载"],
    }
    return {
        "summary": "已按规则生成一版保守搭建草案，可继续微调后再进入写入流程。",
        "assumptions": ["首版优先覆盖高意向搜索词，预算和区域按输入信息保守设置。"],
        "campaigns": [
            {
                "selected": True,
                "name": f"{business_short}_搜索推广",
                "budget": 100.0,
                "device": req.device_preference or "不限",
                "regions": _split_regions(req.regions),
                "schedule": request_schedule,
                "schedule_blocks": request_schedule_blocks,
                "goal": req.goal,
                "adgroups": [adgroup],
            }
        ],
        "risks": ["当前只是草案，尚未写入百度；上线前需要人工确认出价、地域、创意合规。"],
        "next_steps": ["检查计划预算", "确认单元落地页", "勾选关键词和创意", "进入一键搭建写入流程"],
    }


def _prompt(req: DraftRequest, title: str, page_text: str, candidate_words: list[str]) -> tuple[str, str]:
    system = (
        "你是资深百度搜索推广搭建专家。请严格返回 JSON，不要 Markdown。"
        "输出一套可落地的搜索推广搭建草案，字段必须包含 summary、assumptions、campaigns、risks、next_steps。"
        "campaigns 下包含 name、budget、device、regions、schedule、goal、adgroups；"
        "adgroups 下包含 name、max_price、landing_page、keywords、creatives、negative_words；"
        "keywords 下包含 word、match、bid、reason；creatives 下包含 title、description1、description2。"
        "只生成 1 个计划，该计划只包含 1 个单元；单元关键词 8 到 12 个、创意不超过 3 条。"
        "关键词优先从 keyword_candidates 中选择高意向、可直接投放的词；候选不足时再根据落地页和业务描述补充。"
        "所有名称和文案使用中文，避免夸大、第一、最强等高风险表述。"
    )
    user = json.dumps(
        {
            "landing_url": req.landing_url,
            "landing_title": title,
            "landing_text": page_text[:5000],
            "manual_landing_text": (req.landing_text or "")[:5000],
            "keyword_candidates": candidate_words[:24],
            "business_summary": req.business_summary,
            "goal": req.goal,
            "budget": req.budget,
            "regions": req.regions,
            "schedule": req.schedule,
            "schedule_blocks": _normalize_schedule_blocks(req.schedule_blocks),
            "device_preference": req.device_preference,
        },
        ensure_ascii=False,
    )
    return system, user


async def _record_builder_action(
    session: AsyncSession,
    *,
    tenant_id: int,
    account: BaiduAccount,
    action_type: str,
    word: str,
    payload: dict[str, Any],
    call,
    dry_run: bool,
    operator_user_id: int | None,
    operator_name: str | None,
    campaign_id: int | None = None,
    campaign_name: str | None = None,
    adgroup_id: int | None = None,
    adgroup_name: str | None = None,
    price: float | None = None,
    new_value: float | None = None,
    match_mode: str | None = None,
) -> tuple[WritebackAction, dict[str, Any] | None]:
    rec = WritebackAction(
        tenant_id=tenant_id,
        baidu_account_id=account.id,
        action_type=action_type,
        word=word[:500] or action_type,
        match_mode=match_mode,
        price=price,
        new_value=new_value,
        campaign_id=campaign_id,
        campaign_name=campaign_name,
        adgroup_id=adgroup_id,
        adgroup_name=adgroup_name,
        dry_run=dry_run,
        status="pending",
        baidu_response=_safe_json({"request": payload}),
        operator_user_id=operator_user_id,
        operator_name=operator_name,
    )
    session.add(rec)
    await session.flush()

    resp: dict[str, Any] | None = None
    try:
        resp = await call()
        rec.status = "dry_run" if dry_run or resp.get("_dry_run") else "success"
        rec.baidu_response = _safe_json({"request": payload, "response": resp})
    except BaiduAPIError as e:
        rec.status = "failed"
        rec.error_msg = f"[{e.code}] {e.message}"[:2000]
    except Exception as e:
        rec.status = "failed"
        rec.error_msg = str(e)[:2000]
        logger.exception("智能搭建演练动作异常 type=%s word=%s", action_type, word)
    rec.executed_at = datetime.utcnow()
    await session.flush()
    return rec, resp


def _action_payload_summary(rec: WritebackAction) -> dict[str, Any]:
    return {
        "id": rec.id,
        "action_type": rec.action_type,
        "word": rec.word,
        "status": rec.status,
        "dry_run": rec.dry_run,
        "campaign_name": rec.campaign_name,
        "adgroup_name": rec.adgroup_name,
        "price": float(rec.price) if rec.price is not None else None,
        "new_value": float(rec.new_value) if rec.new_value is not None else None,
        "error_msg": rec.error_msg,
    }


@router.post("/apply")
async def apply_draft(
    req: ApplyDraftRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """按已确认草案执行一键搭建。

    当前线上仍保持演练模式：所有百度写接口由 BaiduAPIClient dry-run 安全网拦截。
    """
    ctx.ensure_tenant(req.tenant_id)
    tenant = await session.get(Tenant, req.tenant_id)
    if tenant is None:
        raise HTTPException(404, "租户不存在，请先选择有效客户")
    account = await _active_baidu_account(session, req.tenant_id)
    if account is None:
        raise HTTPException(400, "当前客户没有可用的百度授权账户")

    dry_run = get_settings().baidu_write_dry_run
    if not dry_run:
        raise HTTPException(
            503,
            "智能搭建真实执行暂未启用；请保持演练模式，并通过独立审批流程执行投放变更",
        )
    client = _account_client(account)
    campaign_svc = CampaignService(client)
    adgroup_svc = AdgroupService(client)
    keyword_svc = KeywordService(client)
    creative_svc = CreativeService(client)
    actions: list[WritebackAction] = []

    campaigns = req.draft.get("campaigns") if isinstance(req.draft.get("campaigns"), list) else []
    selected_campaigns = [c for c in campaigns if isinstance(c, dict) and _bool(c.get("selected"), True)]
    if not selected_campaigns:
        raise HTTPException(422, "请至少勾选 1 个计划")

    for cidx, camp in enumerate(selected_campaigns[:1]):
        campaign_name = _text(camp.get("name"), f"{tenant.name}_搜索推广")[:30]
        budget = _bounded_num(camp.get("budget"), 100.0, 50.0, 10000000.0)
        campaign_payload: dict[str, Any] = {
            "campaignName": campaign_name,
            "budget": budget,
            "pause": False,
            "marketingTargetId": 0,
            "equipmentType": _equipment_type(camp.get("device")),
            "campaignBidType": 0,
            "campaignOcpcBidType": 0,
        }
        schedule_price_factors = _schedule_price_factors(camp.get("schedule_blocks") or camp.get("scheduleBlocks"))
        if schedule_price_factors:
            campaign_payload["schedulePriceFactors"] = schedule_price_factors

        rec, resp = await _record_builder_action(
            session,
            tenant_id=req.tenant_id,
            account=account,
            action_type="build_campaign",
            word=campaign_name,
            payload=campaign_payload,
            call=lambda payload=campaign_payload: campaign_svc.add_campaign(payload),
            dry_run=dry_run,
            operator_user_id=ctx.user_id,
            operator_name=ctx.username,
            campaign_id=-(100000 + cidx),
            campaign_name=campaign_name,
            new_value=budget,
        )
        actions.append(rec)
        campaign_id = _response_id(resp or {}, "campaignId") or rec.campaign_id or -(100000 + cidx)

        adgroups = camp.get("adgroups") if isinstance(camp.get("adgroups"), list) else []
        selected_adgroups = [a for a in adgroups if isinstance(a, dict) and _bool(a.get("selected"), True)]
        for aidx, adg in enumerate(selected_adgroups[:1]):
            adgroup_name = _text(adg.get("name"), "通用业务单元")[:30]
            max_price = _bounded_num(adg.get("max_price") or adg.get("maxPrice"), 2.0, 0.01, 999.99)
            landing_page = _text(adg.get("landing_page") or adg.get("landingPage"))
            if not landing_page:
                raise HTTPException(422, f"单元「{adgroup_name}」缺少落地页 URL")
            adgroup_payload = {
                "campaignId": campaign_id,
                "adgroupName": adgroup_name,
                "maxPrice": max_price,
                "pause": False,
                "pcFinalUrl": landing_page,
                "mobileFinalUrl": landing_page,
                "segmentRecommendStatus": 0,
                "creativeTextOptimizationStatus": True,
            }
            rec, resp = await _record_builder_action(
                session,
                tenant_id=req.tenant_id,
                account=account,
                action_type="build_adgroup",
                word=adgroup_name,
                payload=adgroup_payload,
                call=lambda payload=adgroup_payload: adgroup_svc.add_adgroup(payload),
                dry_run=dry_run,
                operator_user_id=ctx.user_id,
                operator_name=ctx.username,
                campaign_id=campaign_id,
                campaign_name=campaign_name,
                adgroup_id=-(200000 + aidx),
                adgroup_name=adgroup_name,
                price=max_price,
            )
            actions.append(rec)
            adgroup_id = _response_id(resp or {}, "adgroupId") or rec.adgroup_id or -(200000 + aidx)

            keywords = adg.get("keywords") if isinstance(adg.get("keywords"), list) else []
            selected_keywords = [kw for kw in keywords if isinstance(kw, dict) and _bool(kw.get("selected"), True)]
            for kw in selected_keywords[:80]:
                word = _text(kw.get("word") or kw.get("keyword"))[:40]
                if not word:
                    continue
                match_type, phrase_type, match_mode = _match_type(kw.get("match") or kw.get("matchType"))
                bid = _bounded_num(kw.get("bid") or kw.get("price") or max_price, max_price, 0.01, 999.99)
                keyword_payload = {
                    "adgroupId": adgroup_id,
                    "keyword": word,
                    "matchType": match_type,
                    "phraseType": phrase_type,
                    "price": bid,
                }
                rec, _ = await _record_builder_action(
                    session,
                    tenant_id=req.tenant_id,
                    account=account,
                    action_type="build_keyword",
                    word=word,
                    payload=keyword_payload,
                    call=lambda adgroup_id=adgroup_id, word=word, match_type=match_type, phrase_type=phrase_type, bid=bid: keyword_svc.add_word(adgroup_id, word, match_type, phrase_type, bid),
                    dry_run=dry_run,
                    operator_user_id=ctx.user_id,
                    operator_name=ctx.username,
                    campaign_id=campaign_id,
                    campaign_name=campaign_name,
                    adgroup_id=adgroup_id,
                    adgroup_name=adgroup_name,
                    price=bid,
                    match_mode=match_mode,
                )
                actions.append(rec)

            display_url = _display_url(landing_page)
            creatives = adg.get("creatives") if isinstance(adg.get("creatives"), list) else []
            selected_creatives = [cr for cr in creatives if isinstance(cr, dict) and _bool(cr.get("selected"), True)]
            for cr in selected_creatives[:5]:
                title = _text(cr.get("title"))[:50]
                desc1 = _text(cr.get("description1") or cr.get("description"))[:80]
                desc2 = _text(cr.get("description2"))[:80]
                if not title or not desc1:
                    continue
                creative_payload = {
                    "campaignId": campaign_id,
                    "adgroupId": adgroup_id,
                    "title": title,
                    "description1": desc1,
                    "description2": desc2,
                    "pcDestinationUrl": landing_page,
                    "pcDisplayUrl": display_url,
                    "mobileDestinationUrl": landing_page,
                    "mobileDisplayUrl": display_url,
                    "pcFinalUrl": landing_page,
                    "mobileFinalUrl": landing_page,
                }
                rec, _ = await _record_builder_action(
                    session,
                    tenant_id=req.tenant_id,
                    account=account,
                    action_type="build_creative",
                    word=title,
                    payload=creative_payload,
                    call=lambda payload=creative_payload: creative_svc.add_creative(payload),
                    dry_run=dry_run,
                    operator_user_id=ctx.user_id,
                    operator_name=ctx.username,
                    campaign_id=campaign_id,
                    campaign_name=campaign_name,
                    adgroup_id=adgroup_id,
                    adgroup_name=adgroup_name,
                )
                actions.append(rec)

    await session.commit()
    summary = {
        "total": len(actions),
        "dry_run": sum(1 for a in actions if a.status == "dry_run"),
        "success": sum(1 for a in actions if a.status == "success"),
        "failed": sum(1 for a in actions if a.status == "failed"),
    }
    return {
        "status": "ok",
        "dry_run": dry_run,
        "summary": summary,
        "actions": [_action_payload_summary(a) for a in actions],
    }


@router.post("/draft")
async def generate_draft(
    req: DraftRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(req.tenant_id)
    if not (req.landing_url or req.landing_text or req.business_summary):
        raise HTTPException(422, "请至少填写落地页链接、落地页文字或业务概述")
    tenant = await session.get(Tenant, req.tenant_id)
    if tenant is None:
        raise HTTPException(404, "租户不存在，请先选择有效客户")

    fetched_title = ""
    fetched_text = ""
    fetch_warning = ""
    if req.landing_url:
        try:
            fetched_title, fetched_text = await fetch_page_text(req.landing_url)
        except UrlFetchError as e:
            fetch_warning = str(e)

    combined = " ".join([fetched_title, fetched_text, req.landing_text or "", req.business_summary, req.goal])
    page_words = extract_words(fetched_title or req.business_summary, combined, 30)
    candidate_words = await _candidate_words(session, req.tenant_id)
    expansion_preheat: dict[str, Any] | None = None
    if len(candidate_words) < 8:
        expansion_preheat = await _preheat_expansion_candidates(
            session,
            tenant,
            page_words,
            req.landing_url,
        )
        candidate_words = await _candidate_words(session, req.tenant_id)
    words = _merge_words(candidate_words, page_words, limit=30)
    landing_page = (req.landing_url or "").strip()

    source = "fallback"
    raw: dict[str, Any] = {}
    if is_enabled():
        system, user = _prompt(req, fetched_title, fetched_text, words)
        try:
            raw = await chat_json(system, user, timeout=75.0)
            source = "ai"
        except DeepSeekError as e:
            fetch_warning = (fetch_warning + "；" if fetch_warning else "") + str(e)

    draft = _normalize_draft(raw, req, words, landing_page)
    return {
        "ai_enabled": is_enabled(),
        "source": source,
        "fetched_title": fetched_title,
        "fetch_warning": fetch_warning,
        "expansion_preheat": expansion_preheat,
        "draft": draft,
    }
