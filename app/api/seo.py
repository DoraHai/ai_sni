"""SEO 关键词资产、自然排名快照与站内页面优化接口。"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.geo.audit import GeoAuditError, audit_url, normalize_url
from app.models import SeoKeywordAsset, SeoRankSnapshot, SeoSitePage, Tenant
from app.security.auth import AuthContext, require_scoped_auth

router = APIRouter(
    prefix="/api/v1/seo",
    tags=["SEO"],
    dependencies=[Depends(require_scoped_auth)],
)

ENGINES = {"baidu", "google", "bing", "360", "sogou"}
PRIORITIES = {"P0", "P1", "P2", "P3"}
KEYWORD_STATUSES = {"active", "paused", "archived"}
PAGE_STATUSES = {"pending", "healthy", "needs_fix", "error"}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


async def _tenant(session: AsyncSession, tenant_id: int) -> Tenant:
    row = await session.get(Tenant, tenant_id)
    if not row:
        raise HTTPException(404, "客户不存在")
    return row


async def _keyword(
    session: AsyncSession, keyword_id: int, tenant_id: int
) -> SeoKeywordAsset:
    row = await session.get(SeoKeywordAsset, keyword_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(404, "SEO 关键词不存在")
    return row


async def _site_page(
    session: AsyncSession, page_id: int, tenant_id: int
) -> SeoSitePage:
    row = await session.get(SeoSitePage, page_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(404, "站内页面不存在")
    return row


def _keyword_payload(
    row: SeoKeywordAsset,
    latest: SeoRankSnapshot | None = None,
    previous: SeoRankSnapshot | None = None,
) -> dict[str, Any]:
    delta = None
    if latest and previous and latest.rank is not None and previous.rank is not None:
        delta = previous.rank - latest.rank
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "keyword": row.keyword,
        "cluster": row.cluster,
        "intent": row.intent,
        "monthly_volume": row.monthly_volume,
        "difficulty": row.difficulty,
        "priority": row.priority,
        "landing_page": row.landing_page,
        "status": row.status,
        "source": row.source,
        "notes": row.notes,
        "latest_rank": None if not latest else latest.rank,
        "rank_delta": delta,
        "rank_url": None if not latest else latest.result_url,
        "rank_checked_at": None if not latest else _iso(latest.checked_at),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _rank_payload(row: SeoRankSnapshot) -> dict[str, Any]:
    return {
        "id": row.id,
        "keyword_id": row.keyword_id,
        "engine": row.engine,
        "device": row.device,
        "region": row.region,
        "domain": row.domain,
        "subject_type": row.subject_type,
        "rank": row.rank,
        "result_url": row.result_url,
        "source": row.source,
        "checked_at": _iso(row.checked_at),
    }


def _page_payload(row: SeoSitePage) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "url": row.url,
        "page_type": row.page_type,
        "target_keyword_id": row.target_keyword_id,
        "title": row.title,
        "meta_description": row.meta_description,
        "meta_keywords": row.meta_keywords,
        "h1": row.h1,
        "canonical": row.canonical,
        "indexable": row.indexable,
        "http_status": row.http_status,
        "content_units": row.content_units,
        "audit_score": row.audit_score,
        "issue_codes": row.issue_codes or [],
        "title_suggestion": row.title_suggestion,
        "description_suggestion": row.description_suggestion,
        "status": row.status,
        "last_error": row.last_error,
        "last_checked_at": _iso(row.last_checked_at),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


class KeywordCreate(BaseModel):
    tenant_id: int
    keyword: str = Field(min_length=1, max_length=200)
    cluster: str | None = Field(None, max_length=120)
    intent: str | None = Field(None, max_length=24)
    monthly_volume: int | None = Field(None, ge=0)
    difficulty: int | None = Field(None, ge=0, le=100)
    priority: Literal["P0", "P1", "P2", "P3"] = "P2"
    landing_page: str | None = Field(None, max_length=2000)
    status: Literal["active", "paused", "archived"] = "active"
    notes: str | None = Field(None, max_length=5000)


class KeywordUpdate(BaseModel):
    cluster: str | None = Field(None, max_length=120)
    intent: str | None = Field(None, max_length=24)
    monthly_volume: int | None = Field(None, ge=0)
    difficulty: int | None = Field(None, ge=0, le=100)
    priority: Literal["P0", "P1", "P2", "P3"] | None = None
    landing_page: str | None = Field(None, max_length=2000)
    status: Literal["active", "paused", "archived"] | None = None
    notes: str | None = Field(None, max_length=5000)


class KeywordImport(BaseModel):
    tenant_id: int
    items: list[KeywordCreate] = Field(min_length=1, max_length=500)


class RankSnapshotCreate(BaseModel):
    tenant_id: int
    keyword_id: int
    engine: Literal["baidu", "google", "bing", "360", "sogou"]
    device: Literal["desktop", "mobile"] = "desktop"
    region: str = Field("全国", min_length=1, max_length=80)
    domain: str | None = Field(None, max_length=255)
    subject_type: Literal["own", "competitor"] = "own"
    rank: int | None = Field(None, ge=1, le=100)
    result_url: str | None = Field(None, max_length=2000)
    checked_at: datetime = Field(default_factory=datetime.utcnow)
    source: str = Field("manual", min_length=1, max_length=32)


class RankSnapshotBatch(BaseModel):
    tenant_id: int
    items: list[RankSnapshotCreate] = Field(min_length=1, max_length=1000)


class SitePageCreate(BaseModel):
    tenant_id: int
    url: str = Field(min_length=1, max_length=2000)
    page_type: str | None = Field(None, max_length=32)
    target_keyword_id: int | None = None
    title_suggestion: str | None = Field(None, max_length=300)
    description_suggestion: str | None = Field(None, max_length=1000)


class SitePageImport(BaseModel):
    tenant_id: int
    urls: list[str] = Field(min_length=1, max_length=500)


class SitePageUpdate(BaseModel):
    page_type: str | None = Field(None, max_length=32)
    target_keyword_id: int | None = None
    title_suggestion: str | None = Field(None, max_length=300)
    description_suggestion: str | None = Field(None, max_length=1000)
    status: Literal["pending", "healthy", "needs_fix", "error"] | None = None


@router.get("/keywords")
async def list_seo_keywords(
    tenant_id: int,
    q: str | None = None,
    priority: str | None = None,
    intent: str | None = None,
    status: str | None = "active",
    engine: str = Query("baidu"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _tenant(session, tenant_id)
    if engine not in ENGINES:
        raise HTTPException(400, "不支持的搜索引擎")
    conditions = [SeoKeywordAsset.tenant_id == tenant_id]
    if q:
        term = f"%{q.strip()}%"
        conditions.append(
            or_(
                SeoKeywordAsset.keyword.ilike(term),
                SeoKeywordAsset.cluster.ilike(term),
                SeoKeywordAsset.landing_page.ilike(term),
            )
        )
    if priority:
        if priority not in PRIORITIES:
            raise HTTPException(400, "优先级无效")
        conditions.append(SeoKeywordAsset.priority == priority)
    if intent:
        conditions.append(SeoKeywordAsset.intent == intent)
    if status:
        if status not in KEYWORD_STATUSES:
            raise HTTPException(400, "关键词状态无效")
        conditions.append(SeoKeywordAsset.status == status)

    total = await session.scalar(select(func.count()).select_from(SeoKeywordAsset).where(*conditions))
    rows = list(
        await session.scalars(
            select(SeoKeywordAsset)
            .where(*conditions)
            .order_by(SeoKeywordAsset.priority, SeoKeywordAsset.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    ids = [row.id for row in rows]
    grouped: dict[int, list[SeoRankSnapshot]] = defaultdict(list)
    if ids:
        rank_rows = list(
            await session.scalars(
                select(SeoRankSnapshot)
                .where(
                    SeoRankSnapshot.tenant_id == tenant_id,
                    SeoRankSnapshot.keyword_id.in_(ids),
                    SeoRankSnapshot.engine == engine,
                    SeoRankSnapshot.subject_type == "own",
                )
                .order_by(SeoRankSnapshot.checked_at.desc(), SeoRankSnapshot.id.desc())
            )
        )
        for rank in rank_rows:
            if len(grouped[rank.keyword_id]) < 2:
                grouped[rank.keyword_id].append(rank)

    tenant_rows = list(
        await session.scalars(
            select(SeoKeywordAsset).where(
                SeoKeywordAsset.tenant_id == tenant_id,
                SeoKeywordAsset.status == "active",
            )
        )
    )
    return {
        "items": [
            _keyword_payload(
                row,
                grouped[row.id][0] if grouped[row.id] else None,
                grouped[row.id][1] if len(grouped[row.id]) > 1 else None,
            )
            for row in rows
        ],
        "total": int(total or 0),
        "page": page,
        "page_size": page_size,
        "engine": engine,
        "stats": {
            "active": len(tenant_rows),
            "monthly_volume": sum(row.monthly_volume or 0 for row in tenant_rows),
            "with_landing_page": sum(bool(row.landing_page) for row in tenant_rows),
            "high_priority": sum(row.priority in {"P0", "P1"} for row in tenant_rows),
        },
    }


@router.post("/keywords")
async def create_seo_keyword(
    req: KeywordCreate,
    session: AsyncSession = Depends(get_session),
    ctx: AuthContext = Depends(require_scoped_auth),
) -> dict[str, Any]:
    ctx.ensure_tenant(req.tenant_id)
    await _tenant(session, req.tenant_id)
    row = SeoKeywordAsset(
        tenant_id=req.tenant_id,
        keyword=req.keyword.strip(),
        cluster=(req.cluster or "").strip() or None,
        intent=(req.intent or "").strip() or None,
        monthly_volume=req.monthly_volume,
        difficulty=req.difficulty,
        priority=req.priority,
        landing_page=(req.landing_page or "").strip() or None,
        status=req.status,
        source="manual",
        notes=(req.notes or "").strip() or None,
        created_by=ctx.user_id,
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "该关键词已在 SEO 资产库中") from exc
    await session.refresh(row)
    return _keyword_payload(row)


@router.post("/keywords/import")
async def import_seo_keywords(
    req: KeywordImport,
    session: AsyncSession = Depends(get_session),
    ctx: AuthContext = Depends(require_scoped_auth),
) -> dict[str, Any]:
    ctx.ensure_tenant(req.tenant_id)
    await _tenant(session, req.tenant_id)
    existing = set(
        await session.scalars(
            select(SeoKeywordAsset.keyword).where(SeoKeywordAsset.tenant_id == req.tenant_id)
        )
    )
    created = []
    skipped = []
    for item in req.items:
        word = item.keyword.strip()
        if item.tenant_id != req.tenant_id:
            raise HTTPException(400, "导入项 tenant_id 必须一致")
        if word in existing:
            skipped.append(word)
            continue
        row = SeoKeywordAsset(
            tenant_id=req.tenant_id,
            keyword=word,
            cluster=(item.cluster or "").strip() or None,
            intent=(item.intent or "").strip() or None,
            monthly_volume=item.monthly_volume,
            difficulty=item.difficulty,
            priority=item.priority,
            landing_page=(item.landing_page or "").strip() or None,
            status=item.status,
            source="import",
            notes=(item.notes or "").strip() or None,
            created_by=ctx.user_id,
        )
        session.add(row)
        created.append(row)
        existing.add(word)
    await session.commit()
    return {"created": len(created), "skipped": skipped}


@router.get("/keywords/{keyword_id}")
async def get_seo_keyword(
    keyword_id: int,
    tenant_id: int,
    engine: str = Query("baidu"),
    days: int = Query(90, ge=1, le=366),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    row = await _keyword(session, keyword_id, tenant_id)
    since = datetime.utcnow() - timedelta(days=days)
    ranks = list(
        await session.scalars(
            select(SeoRankSnapshot)
            .where(
                SeoRankSnapshot.tenant_id == tenant_id,
                SeoRankSnapshot.keyword_id == keyword_id,
                SeoRankSnapshot.engine == engine,
                SeoRankSnapshot.checked_at >= since,
            )
            .order_by(SeoRankSnapshot.checked_at.asc(), SeoRankSnapshot.id.asc())
        )
    )
    own = [rank for rank in ranks if rank.subject_type == "own"]
    competitors: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rank in ranks:
        if rank.subject_type == "competitor":
            competitors[rank.domain or "未命名竞品"].append(_rank_payload(rank))
    return {
        "keyword": _keyword_payload(
            row,
            own[-1] if own else None,
            own[-2] if len(own) > 1 else None,
        ),
        "rank_history": [_rank_payload(rank) for rank in own],
        "competitor_history": competitors,
        "engine": engine,
    }


@router.patch("/keywords/{keyword_id}")
async def update_seo_keyword(
    keyword_id: int,
    tenant_id: int,
    req: KeywordUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    row = await _keyword(session, keyword_id, tenant_id)
    for key, value in req.model_dump(exclude_unset=True).items():
        if isinstance(value, str):
            value = value.strip() or None
        setattr(row, key, value)
    await session.commit()
    await session.refresh(row)
    return _keyword_payload(row)


@router.post("/rank-snapshots")
async def create_rank_snapshot(
    req: RankSnapshotCreate,
    session: AsyncSession = Depends(get_session),
    ctx: AuthContext = Depends(require_scoped_auth),
) -> dict[str, Any]:
    ctx.ensure_tenant(req.tenant_id)
    await _keyword(session, req.keyword_id, req.tenant_id)
    row = SeoRankSnapshot(**req.model_dump())
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _rank_payload(row)


@router.post("/rank-snapshots/batch")
async def create_rank_snapshots_batch(
    req: RankSnapshotBatch,
    session: AsyncSession = Depends(get_session),
    ctx: AuthContext = Depends(require_scoped_auth),
) -> dict[str, Any]:
    ctx.ensure_tenant(req.tenant_id)
    ids = {item.keyword_id for item in req.items}
    found = set(
        await session.scalars(
            select(SeoKeywordAsset.id).where(
                SeoKeywordAsset.tenant_id == req.tenant_id,
                SeoKeywordAsset.id.in_(ids),
            )
        )
    )
    if found != ids:
        raise HTTPException(400, "批次包含不存在或不属于当前客户的关键词")
    for item in req.items:
        if item.tenant_id != req.tenant_id:
            raise HTTPException(400, "排名快照 tenant_id 必须一致")
        session.add(SeoRankSnapshot(**item.model_dump()))
    await session.commit()
    return {"created": len(req.items)}


@router.get("/site-pages")
async def list_site_pages(
    tenant_id: int,
    q: str | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _tenant(session, tenant_id)
    conditions = [SeoSitePage.tenant_id == tenant_id]
    if q:
        term = f"%{q.strip()}%"
        conditions.append(or_(SeoSitePage.url.ilike(term), SeoSitePage.title.ilike(term)))
    if status:
        if status not in PAGE_STATUSES:
            raise HTTPException(400, "页面状态无效")
        conditions.append(SeoSitePage.status == status)
    total = await session.scalar(select(func.count()).select_from(SeoSitePage).where(*conditions))
    rows = list(
        await session.scalars(
            select(SeoSitePage)
            .where(*conditions)
            .order_by(SeoSitePage.updated_at.desc(), SeoSitePage.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    all_rows = list(
        await session.scalars(select(SeoSitePage).where(SeoSitePage.tenant_id == tenant_id))
    )
    return {
        "items": [_page_payload(row) for row in rows],
        "total": int(total or 0),
        "page": page,
        "page_size": page_size,
        "stats": {
            "total": len(all_rows),
            "healthy": sum(row.status == "healthy" for row in all_rows),
            "needs_fix": sum(row.status == "needs_fix" for row in all_rows),
            "unchecked": sum(row.status == "pending" for row in all_rows),
            "average_score": round(
                sum(row.audit_score or 0 for row in all_rows if row.audit_score is not None)
                / max(sum(row.audit_score is not None for row in all_rows), 1),
                1,
            ),
        },
    }


async def _validate_target_keyword(
    session: AsyncSession, tenant_id: int, keyword_id: int | None
) -> None:
    if keyword_id is not None:
        await _keyword(session, keyword_id, tenant_id)


@router.post("/site-pages")
async def create_site_page(
    req: SitePageCreate,
    session: AsyncSession = Depends(get_session),
    ctx: AuthContext = Depends(require_scoped_auth),
) -> dict[str, Any]:
    ctx.ensure_tenant(req.tenant_id)
    await _tenant(session, req.tenant_id)
    await _validate_target_keyword(session, req.tenant_id, req.target_keyword_id)
    try:
        url = normalize_url(req.url)
    except GeoAuditError as exc:
        raise HTTPException(400, str(exc)) from exc
    row = SeoSitePage(
        tenant_id=req.tenant_id,
        url=url,
        page_type=(req.page_type or "").strip() or None,
        target_keyword_id=req.target_keyword_id,
        title_suggestion=(req.title_suggestion or "").strip() or None,
        description_suggestion=(req.description_suggestion or "").strip() or None,
        created_by=ctx.user_id,
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "该页面已在站内资产库中") from exc
    await session.refresh(row)
    return _page_payload(row)


@router.post("/site-pages/import")
async def import_site_pages(
    req: SitePageImport,
    session: AsyncSession = Depends(get_session),
    ctx: AuthContext = Depends(require_scoped_auth),
) -> dict[str, Any]:
    ctx.ensure_tenant(req.tenant_id)
    await _tenant(session, req.tenant_id)
    existing = set(
        await session.scalars(
            select(SeoSitePage.url).where(SeoSitePage.tenant_id == req.tenant_id)
        )
    )
    created = 0
    skipped = []
    for raw in req.urls:
        try:
            url = normalize_url(raw)
        except GeoAuditError:
            skipped.append({"url": raw, "reason": "网址无效"})
            continue
        if url in existing:
            skipped.append({"url": url, "reason": "已存在"})
            continue
        session.add(
            SeoSitePage(
                tenant_id=req.tenant_id,
                url=url,
                status="pending",
                created_by=ctx.user_id,
            )
        )
        existing.add(url)
        created += 1
    await session.commit()
    return {"created": created, "skipped": skipped}


@router.patch("/site-pages/{page_id}")
async def update_site_page(
    page_id: int,
    tenant_id: int,
    req: SitePageUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    row = await _site_page(session, page_id, tenant_id)
    values = req.model_dump(exclude_unset=True)
    await _validate_target_keyword(session, tenant_id, values.get("target_keyword_id"))
    for key, value in values.items():
        if isinstance(value, str):
            value = value.strip() or None
        setattr(row, key, value)
    await session.commit()
    await session.refresh(row)
    return _page_payload(row)


@router.post("/site-pages/{page_id}/audit")
async def audit_site_page(
    page_id: int,
    tenant_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    row = await _site_page(session, page_id, tenant_id)
    try:
        result = await audit_url(row.url)
    except GeoAuditError as exc:
        row.status = "error"
        row.last_error = str(exc)
        row.last_checked_at = datetime.utcnow()
        await session.commit()
        raise HTTPException(422, str(exc)) from exc

    snapshot = result.get("snapshot") or {}
    checks = result.get("checks") or []
    checks_by_code = {item.get("code"): item for item in checks}
    failed = [item.get("code") for item in checks if not item.get("passed")]
    row.title = result.get("title") or None
    row.meta_description = result.get("description") or None
    row.h1 = (snapshot.get("h1") or [None])[0]
    row.canonical = snapshot.get("canonical") or None
    row.indexable = bool((checks_by_code.get("indexable") or {}).get("passed"))
    row.http_status = 200
    row.content_units = snapshot.get("content_units")
    row.audit_score = result.get("score")
    row.issue_codes = failed
    row.status = "healthy" if not failed else "needs_fix"
    row.last_error = None
    row.last_checked_at = datetime.utcnow()
    await session.commit()
    await session.refresh(row)
    return _page_payload(row)
