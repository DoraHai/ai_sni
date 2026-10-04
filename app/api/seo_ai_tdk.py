"""Site-scoped AI TDK generation and human review."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, PositiveInt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.deepseek import chat_json
from app.api.seo_site_analytics import error, scope
from app.config import get_settings
from app.models.seo import SeoKeywordAsset, SeoPageSnapshot, SeoSitePage
from app.models.seo_ai_tdk import SeoPageAiTdkSuggestion as Suggestion
from app.security.auth import AuthContext
from app.seo_ai_tdk import PROMPT_VERSION, digest, generate_batch, generate_one, grounding
from app.seo_demo_source import get_seo_session as get_session, require_seo_scoped_auth as require_scoped_auth

router = APIRouter()


class GenerateRequest(BaseModel):
    tenant_id: PositiveInt
    site_id: PositiveInt
    page_ids: list[PositiveInt] = Field(min_length=1, max_length=20)
    force: bool = False


class FieldReview(BaseModel):
    action: str
    final_value: str | None = None


class LinkReview(BaseModel):
    index: int = Field(ge=0)
    action: str
    final_anchor: str | None = None


class ReviewRequest(BaseModel):
    tenant_id: PositiveInt
    site_id: PositiveInt
    fields: dict[str, FieldReview] = Field(default_factory=dict)
    links: list[LinkReview] = Field(default_factory=list)


async def scoped_page(session, ctx, tenant_id, site_id, page_id, edit=False):
    site = await scope(session, ctx, tenant_id, site_id, edit)
    page = await session.scalar(select(SeoSitePage).where(SeoSitePage.id == page_id,
        SeoSitePage.tenant_id == tenant_id, SeoSitePage.site_id == site_id))
    if page is None:
        raise error(404, "page_not_found", "页面不属于当前客户或网站")
    return site, page


def public(row):
    return {key: getattr(row, key) for key in (
        "id", "page_id", "batch_id", "model_name", "prompt_version", "input_digest",
        "title_ai_value", "title_final_value", "title_status", "title_reviewed_by", "title_reviewed_at",
        "description_ai_value", "description_final_value", "description_status", "description_reviewed_by", "description_reviewed_at",
        "keywords_ai_value", "keywords_final_value", "keywords_status", "keywords_reviewed_by", "keywords_reviewed_at",
        "reason", "internal_link_suggestions",
        "warnings", "dropped_links", "reviewed_by", "reviewed_at", "created_at", "error_code", "error_message")}


@router.post("/site/pages/ai-tdk/generate")
async def generate(req: GenerateRequest, session: AsyncSession = Depends(get_session),
                   ctx: AuthContext = Depends(require_scoped_auth)):
    site = await scope(session, ctx, req.tenant_id, req.site_id, True)
    ids = list(dict.fromkeys(req.page_ids))
    pages = (await session.scalars(select(SeoSitePage).where(SeoSitePage.tenant_id == req.tenant_id,
        SeoSitePage.site_id == req.site_id, SeoSitePage.id.in_(ids)))).all()
    if len(pages) != len(ids):
        raise error(404, "page_not_found", "部分页面不属于当前客户或网站")
    settings = get_settings()
    if not settings.deepseek_api_key.strip():
        raise error(503, "deepseek_not_configured", "未配置 DeepSeek API Key，无法生成 AI 建议")
    all_pages = (await session.scalars(select(SeoSitePage).where(SeoSitePage.tenant_id == req.tenant_id,
        SeoSitePage.site_id == req.site_id).order_by(SeoSitePage.id).limit(5000))).all()
    keywords = (await session.scalars(select(SeoKeywordAsset).where(SeoKeywordAsset.tenant_id == req.tenant_id,
        SeoKeywordAsset.site_id == req.site_id))).all()
    batch_id = str(uuid4())
    by_id = {page.id: page for page in pages}
    pending, results = [], []
    for page_id in ids:
        page = by_id[page_id]
        snapshot = await session.scalar(select(SeoPageSnapshot).where(SeoPageSnapshot.tenant_id == req.tenant_id,
            SeoPageSnapshot.site_id == req.site_id, SeoPageSnapshot.url == page.url)
            .order_by(SeoPageSnapshot.fetched_at.desc(), SeoPageSnapshot.id.desc()).limit(1))
        data = grounding(page, site_name=site.name, keywords=keywords, library=all_pages, snapshot=snapshot)
        value_digest = digest(data)
        latest = await session.scalar(select(Suggestion).where(Suggestion.tenant_id == req.tenant_id,
            Suggestion.site_id == req.site_id, Suggestion.page_id == page_id)
            .order_by(Suggestion.id.desc()).limit(1))
        if latest and not latest.error_code and latest.input_digest == value_digest and not req.force:
            results.append({"page_id": page_id, "status": "skipped", "suggestion_id": latest.id})
            continue
        pending.append({"page_id": page_id, "digest": value_digest, "data": data})

    async def worker(item):
        return await generate_one(item["data"], api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url, model=settings.deepseek_model, caller=chat_json)

    interval = settings.seo_ai_tdk_min_interval_seconds
    generated = await generate_batch(pending, interval=interval, worker=worker)
    pending_by_id = {item["page_id"]: item for item in pending}
    for result in generated:
        item = pending_by_id[result["page_id"]]
        if result["status"] == "error":
            row = Suggestion(tenant_id=req.tenant_id, site_id=req.site_id, page_id=item["page_id"],
                batch_id=batch_id, model_name=settings.deepseek_model, prompt_version=PROMPT_VERSION,
                input_digest=item["digest"], created_by=ctx.user_id,
                internal_link_suggestions=[], warnings=[], dropped_links=0,
                error_code="generation_failed", error_message=result["error"][:500])
            session.add(row)
            await session.flush()
            result["suggestion_id"] = row.id
            results.append(result)
            continue
        value = result["value"]
        row = Suggestion(tenant_id=req.tenant_id, site_id=req.site_id, page_id=item["page_id"],
            batch_id=batch_id, model_name=settings.deepseek_model, prompt_version=PROMPT_VERSION,
            input_digest=item["digest"], created_by=ctx.user_id,
            title_ai_value=value["title"], description_ai_value=value["description"],
            keywords_ai_value=value["keywords"], reason=value["reason"],
            internal_link_suggestions=value["internal_links"], warnings=value["warnings"],
            dropped_links=value["dropped_links"], raw_response_excerpt=None)
        session.add(row)
        await session.flush()
        results.append({"page_id": item["page_id"], "status": "generated", "suggestion_id": row.id,
                        "warnings": row.warnings, "dropped_links": row.dropped_links})
    await session.commit()
    return {"batch_id": batch_id, "items": sorted(results, key=lambda r: ids.index(r["page_id"]))}


@router.get("/site/pages/{page_id}/ai-tdk")
async def get_suggestion(page_id: PositiveInt, tenant_id: PositiveInt, site_id: PositiveInt,
                         session: AsyncSession = Depends(get_session),
                         ctx: AuthContext = Depends(require_scoped_auth)):
    await scoped_page(session, ctx, tenant_id, site_id, page_id)
    rows = (await session.scalars(select(Suggestion).where(Suggestion.tenant_id == tenant_id,
        Suggestion.site_id == site_id, Suggestion.page_id == page_id).order_by(Suggestion.id.desc()).limit(6))).all()
    return {"latest": public(rows[0]) if rows else None,
            "history": [{"id": row.id, "created_at": row.created_at, "model_name": row.model_name} for row in rows[1:]]}


def apply_review(row, req, actor_id):
    if actor_id is None:
        raise ValueError("无法识别审核人")
    if not req.fields and not req.links:
        raise ValueError("请选择至少一项审核操作")
    for field, review in req.fields.items():
        if field not in {"title", "description", "keywords"} or review.action not in {"accept", "edit", "reject"}:
            raise ValueError("审核操作无效")
        ai = getattr(row, f"{field}_ai_value")
        value = ai if review.action == "accept" else (review.final_value or "").strip() if review.action == "edit" else None
        if review.action != "reject" and not value:
            raise ValueError("确认值不能为空")
        if value and (len(value) > ({"title": 30, "description": 120, "keywords": 300}[field]) or
                      field == "description" and len(value) < 70 or
                      field == "keywords" and not 3 <= len([v for v in value.replace("，", ",").split(",") if v.strip()]) <= 6):
            raise ValueError("确认值长度或关键词数量不符合要求")
        setattr(row, f"{field}_final_value", value)
        setattr(row, f"{field}_status", {"accept": "confirmed", "edit": "modified", "reject": "rejected"}[review.action])
        setattr(row, f"{field}_reviewed_by", actor_id)
        setattr(row, f"{field}_reviewed_at", datetime.now(timezone.utc))
    links = [dict(link) for link in (row.internal_link_suggestions or [])]
    for review in req.links:
        if review.index >= len(links) or review.action not in {"accept", "edit", "reject"}:
            raise ValueError("内链审核操作无效")
        link = links[review.index]
        anchor = (review.final_anchor or "").strip() if review.action == "edit" else link["anchor"]
        if review.action == "edit" and not 1 <= len(anchor) <= 80:
            raise ValueError("锚文本须为 1-80 字")
        link["status"] = {"accept": "confirmed", "edit": "modified", "reject": "rejected"}[review.action]
        link["final_anchor"] = anchor if review.action != "reject" else None
        link["reviewed_by"] = actor_id
        link["reviewed_at"] = datetime.now(timezone.utc).isoformat()
    row.internal_link_suggestions = links
    row.reviewed_by = actor_id
    row.reviewed_at = datetime.now(timezone.utc)


@router.post("/site/pages/{page_id}/ai-tdk/{suggestion_id}/review")
async def review(page_id: PositiveInt, suggestion_id: PositiveInt, req: ReviewRequest,
                 session: AsyncSession = Depends(get_session), ctx: AuthContext = Depends(require_scoped_auth)):
    await scoped_page(session, ctx, req.tenant_id, req.site_id, page_id, True)
    row = await session.scalar(select(Suggestion).where(Suggestion.id == suggestion_id,
        Suggestion.tenant_id == req.tenant_id, Suggestion.site_id == req.site_id,
        Suggestion.page_id == page_id).with_for_update())
    latest = await session.scalar(select(Suggestion.id).where(Suggestion.tenant_id == req.tenant_id,
        Suggestion.site_id == req.site_id, Suggestion.page_id == page_id).order_by(Suggestion.id.desc()).limit(1))
    if row is None:
        raise error(404, "suggestion_not_found", "建议不存在")
    if latest != row.id:
        raise error(409, "stale_suggestion", "只能审核最新一版 AI 建议")
    try:
        apply_review(row, req, ctx.user_id)
    except ValueError as exc:
        raise error(422, "invalid_review", str(exc)) from exc
    await session.commit()
    return public(row)
