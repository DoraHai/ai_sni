"""SEO-only diagnostic review; all writes are local, append-only intent records."""

from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, PositiveInt, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.module_workspace import SeoSite
from app.models.seo import SeoImageAltReview, SeoPageIndexReview, SeoSitePage, SeoPageSnapshot
from app.security.auth import AuthContext, require_scoped_auth
from app.seo_site_diagnostics import assessed_condition, checked_iso, diagnostic_payload

router = APIRouter()


async def _scope(session, ctx, tenant_id, site_id, *, write=False):
    ctx.ensure_tenant(tenant_id)
    if not (ctx.can_edit("seo.site") if write else ctx.can_view("seo.site")):
        raise HTTPException(403, "无权操作站内优化")
    site = await session.scalar(select(SeoSite.id).where(SeoSite.id == site_id, SeoSite.tenant_id == tenant_id))
    if site is None:
        raise HTTPException(404, "SEO 网站不存在")


def review_payload(row):
    if row is None:
        return None
    return {"id": row.id, "intent": row.intent, "reason": row.reason,
            "actor_id": row.actor_id, "actor_name": row.actor_name,
            "created_at": checked_iso(row.created_at), "evidence": row.evidence}


@router.get("/site-pages/diagnostics")
async def list_diagnostics(
    tenant_id: PositiveInt, site_id: PositiveInt,
    q: str = Query("", max_length=200),
    review_state: Literal["all", "unreviewed", "reviewed"] = "all",
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
    ctx: AuthContext = Depends(require_scoped_auth), session: AsyncSession = Depends(get_session),
):
    await _scope(session, ctx, tenant_id, site_id)
    p, r = SeoSitePage, SeoPageIndexReview
    latest = (select(r.page_id, func.max(r.id).label("review_id"))
              .where(r.tenant_id == tenant_id, r.site_id == site_id)
              .group_by(r.page_id).subquery())
    scope = [p.tenant_id == tenant_id, p.site_id == site_id]
    query = select(p, r).outerjoin(latest, latest.c.page_id == p.id).outerjoin(r, r.id == latest.c.review_id)
    conditions = list(scope)
    if q.strip():
        term = f"%{q.strip()}%"
        conditions.append(or_(p.url.ilike(term), p.title.ilike(term)))
    if review_state == "unreviewed":
        conditions.append(or_(r.id.is_(None), r.intent == "undecided"))
    elif review_state == "reviewed":
        conditions.append(r.intent.in_(("index", "noindex")))
    query = query.where(*conditions)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await session.execute(query.order_by(p.id).offset((page - 1) * page_size).limit(page_size))).all()
    coverage = (await session.execute(select(
        func.count(p.id), func.count(p.id).filter(assessed_condition(p)),
        func.count(p.id).filter(p.last_checked_at.is_(None)), func.max(p.last_checked_at),
    ).where(*scope))).one()
    return {
        "items": [{"id": row.id, "url": row.url, "title": row.title,
                   "diagnostic": diagnostic_payload(row, review.intent if review else "undecided"),
                   "review": review_payload(review)} for row, review in rows],
        "total": int(total or 0), "page": page, "page_size": page_size,
        "coverage": {"inventory": coverage[0], "assessed": coverage[1], "not_checked": coverage[2],
                     "unavailable": coverage[0] - coverage[1] - coverage[2],
                     "latest_checked_at": checked_iso(coverage[3]), "scope": "stored_page_inventory"},
    }


@router.get("/site-pages/image-evidence")
async def get_image_evidence(
    tenant_id: PositiveInt, site_id: PositiveInt, page_id: PositiveInt,
    ctx: AuthContext = Depends(require_scoped_auth), session: AsyncSession = Depends(get_session),
    snapshot_id: PositiveInt | None = None,
):
    await _scope(session, ctx, tenant_id, site_id)
    page = await session.scalar(select(SeoSitePage).where(
        SeoSitePage.id == page_id, SeoSitePage.tenant_id == tenant_id, SeoSitePage.site_id == site_id,
    ))
    if page is None:
        raise HTTPException(404, "页面不存在")
    # Do not fall back to an older successful observation if the latest failed.
    snapshot_query = select(SeoPageSnapshot).where(
        SeoPageSnapshot.tenant_id == tenant_id, SeoPageSnapshot.site_id == site_id,
        SeoPageSnapshot.url == page.url,
    )
    if snapshot_id is not None:
        snapshot_query = snapshot_query.where(SeoPageSnapshot.id == snapshot_id)
    else:
        snapshot_query = snapshot_query.order_by(
            SeoPageSnapshot.fetched_at.desc(), SeoPageSnapshot.id.desc()).limit(1)
    snapshot = await session.scalar(snapshot_query)
    if snapshot_id is not None and snapshot is None:
        raise HTTPException(404, "图片快照不存在")
    fetch_error = None
    fetched_at = None
    if snapshot is not None:
        fetch_error = snapshot.error_type
        if not fetch_error and (snapshot.status_code is None or not 200 <= snapshot.status_code < 300):
            fetch_error = "http_status_unavailable" if snapshot.status_code is None else f"http_{snapshot.status_code}"
        # fetched_at is DB-generated local CST, unlike site-page checked_at UTC.
        fetched_at = snapshot.fetched_at
        if fetched_at is not None and fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone(timedelta(hours=8)))
    return {"page_id": page.id, "url": page.url,
            "snapshot_id": snapshot.id if snapshot else None,
            "fetched_at": fetched_at.isoformat() if fetched_at else None,
            "fetch_error": fetch_error,
            "legacy_candidate_count": snapshot.images_missing_alt_count if snapshot else None,
            "evidence": snapshot.image_alt_evidence if snapshot and not fetch_error else None}


def image_review_payload(row):
    return {
        "id": row.id, "snapshot_id": row.snapshot_id, "position": row.position,
        "source_url": row.source_url, "observed_alt_state": row.observed_alt_state,
        "decision": row.decision, "alt_suggestion": row.alt_suggestion,
        "note": row.note, "review_status": row.review_status,
        "actor_id": row.actor_id, "actor_name": row.actor_name,
        "reviewed_at": checked_iso(row.reviewed_at), "updated_at": checked_iso(row.updated_at),
    }


def _image_candidate_payload(page, snapshot, candidate, review):
    saved = image_review_payload(review) if review else None
    return {
        "page_id": page.id, "page_title": page.title, "page_url": page.url,
        "snapshot_id": snapshot.id, "fetched_at": _image_snapshot_time(snapshot),
        "position": candidate.get("position"), "section": candidate.get("section"),
        "source_url": candidate.get("source_url"),
        "source_attribute": candidate.get("source_attribute"),
        "in_link": bool(candidate.get("in_link")),
        "observed_alt_state": candidate.get("alt_state"),
        "decision": review.decision if review else "undecided",
        "alt_suggestion": review.alt_suggestion if review else None,
        "note": review.note if review else None,
        "review_status": review.review_status if review else "unreviewed",
        "review": saved,
    }


@router.get("/site-pages/image-remediation-workbench")
async def list_image_remediation_workbench(
    tenant_id: PositiveInt, site_id: PositiveInt,
    q: str = Query("", max_length=200),
    review_state: Literal["all", "unreviewed", "draft", "approved"] = "all",
    decision: Literal["all", "undecided", "decorative", "informative"] = "all",
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100),
    ctx: AuthContext = Depends(require_scoped_auth), session: AsyncSession = Depends(get_session),
):
    """Latest-snapshot-only work queue for human image-alt remediation."""
    await _scope(session, ctx, tenant_id, site_id)
    page_query = select(SeoSitePage).where(
        SeoSitePage.tenant_id == tenant_id, SeoSitePage.site_id == site_id,
    )
    if q.strip():
        term = f"%{q.strip()}%"
        page_query = page_query.where(or_(SeoSitePage.url.ilike(term), SeoSitePage.title.ilike(term)))
    pages = list(await session.scalars(page_query.order_by(SeoSitePage.id)))
    if not pages:
        return {"items": [], "total": 0, "page": page, "page_size": page_size,
                "stats": {"page_count": 0, "candidate_count": 0, "unreviewed_count": 0,
                          "draft_count": 0, "approved_count": 0,
                          "informative_approved_count": 0, "decorative_approved_count": 0}}

    page_by_url = {row.url: row for row in pages}
    ranked_snapshots = select(
        SeoPageSnapshot.id,
        func.row_number().over(
            partition_by=SeoPageSnapshot.url,
            order_by=(SeoPageSnapshot.fetched_at.desc(), SeoPageSnapshot.id.desc()),
        ).label("latest_rank"),
    ).where(
        SeoPageSnapshot.tenant_id == tenant_id, SeoPageSnapshot.site_id == site_id,
        SeoPageSnapshot.url.in_(list(page_by_url)),
    ).subquery()
    latest_ids = select(ranked_snapshots.c.id).where(ranked_snapshots.c.latest_rank == 1)
    current = list(await session.scalars(select(SeoPageSnapshot).where(
        SeoPageSnapshot.id.in_(latest_ids),
        SeoPageSnapshot.tenant_id == tenant_id, SeoPageSnapshot.site_id == site_id,
    ).order_by(SeoPageSnapshot.url)))
    current = [row for row in current
               if not row.error_type and row.status_code is not None and 200 <= row.status_code < 300
               and isinstance(row.image_alt_evidence, dict)]
    snapshot_ids = [row.id for row in current]
    reviews = []
    if snapshot_ids:
        reviews = list(await session.scalars(select(SeoImageAltReview).where(
            SeoImageAltReview.tenant_id == tenant_id, SeoImageAltReview.site_id == site_id,
            SeoImageAltReview.snapshot_id.in_(snapshot_ids),
        )))
    review_by_key = {(row.snapshot_id, row.position): row for row in reviews}

    all_items = []
    candidate_pages = set()
    for snapshot in current:
        source_page = page_by_url[snapshot.url]
        for candidate in snapshot.image_alt_evidence.get("items", []):
            if not isinstance(candidate, dict) or candidate.get("alt_state") not in {"missing", "empty", "whitespace"}:
                continue
            position = candidate.get("position")
            if not isinstance(position, int) or position <= 0:
                continue
            candidate_pages.add(source_page.id)
            all_items.append(_image_candidate_payload(
                source_page, snapshot, candidate, review_by_key.get((snapshot.id, position))))
    stats = {
        "page_count": len(candidate_pages), "candidate_count": len(all_items),
        "unreviewed_count": sum(row["review_status"] == "unreviewed" or row["decision"] == "undecided" for row in all_items),
        "draft_count": sum(row["review_status"] == "draft" for row in all_items),
        "approved_count": sum(row["review_status"] == "approved" for row in all_items),
        "informative_approved_count": sum(row["review_status"] == "approved" and row["decision"] == "informative" and bool(row["alt_suggestion"]) for row in all_items),
        "decorative_approved_count": sum(row["review_status"] == "approved" and row["decision"] == "decorative" for row in all_items),
    }
    filtered = [row for row in all_items if (
        review_state == "all" or
        (review_state == "unreviewed" and (row["review_status"] == "unreviewed" or row["decision"] == "undecided")) or
        row["review_status"] == review_state
    ) and (decision == "all" or row["decision"] == decision)]
    priority = {"unreviewed": 0, "draft": 1, "approved": 2}
    filtered.sort(key=lambda row: (priority.get(row["review_status"], 3), row["page_id"], row["position"]))
    start = (page - 1) * page_size
    return {"items": filtered[start:start + page_size], "total": len(filtered),
            "page": page, "page_size": page_size, "stats": stats}


async def _page_and_latest_snapshot(session, tenant_id, site_id, page_id, *, lock_page=False):
    page_query = select(SeoSitePage).where(
        SeoSitePage.id == page_id, SeoSitePage.tenant_id == tenant_id, SeoSitePage.site_id == site_id,
    )
    page = await session.scalar(page_query.with_for_update() if lock_page else page_query)
    if page is None:
        raise HTTPException(404, "页面不存在")
    snapshot = await session.scalar(select(SeoPageSnapshot).where(
        SeoPageSnapshot.tenant_id == tenant_id, SeoPageSnapshot.site_id == site_id,
        SeoPageSnapshot.url == page.url,
    ).order_by(SeoPageSnapshot.fetched_at.desc(), SeoPageSnapshot.id.desc()).limit(1))
    return page, snapshot


async def _page_and_snapshot(session, tenant_id, site_id, page_id, snapshot_id):
    page = await session.scalar(select(SeoSitePage).where(
        SeoSitePage.id == page_id, SeoSitePage.tenant_id == tenant_id, SeoSitePage.site_id == site_id,
    ))
    if page is None:
        raise HTTPException(404, "页面不存在")
    snapshot = await session.scalar(select(SeoPageSnapshot).where(
        SeoPageSnapshot.id == snapshot_id, SeoPageSnapshot.tenant_id == tenant_id,
        SeoPageSnapshot.site_id == site_id, SeoPageSnapshot.url == page.url,
    ))
    if snapshot is None:
        raise HTTPException(404, "图片快照不存在")
    return page, snapshot


@router.get("/site-pages/image-remediation")
async def get_image_remediation(
    tenant_id: PositiveInt, site_id: PositiveInt, page_id: PositiveInt,
    ctx: AuthContext = Depends(require_scoped_auth), session: AsyncSession = Depends(get_session),
    snapshot_id: PositiveInt | None = None,
):
    await _scope(session, ctx, tenant_id, site_id)
    if snapshot_id is None:
        _, snapshot = await _page_and_latest_snapshot(session, tenant_id, site_id, page_id)
    else:
        _, snapshot = await _page_and_snapshot(session, tenant_id, site_id, page_id, snapshot_id)
    if snapshot is None or snapshot.error_type or not snapshot.image_alt_evidence:
        return {"snapshot_id": snapshot.id if snapshot else None, "items": []}
    reviews = list(await session.scalars(select(SeoImageAltReview).where(
        SeoImageAltReview.tenant_id == tenant_id, SeoImageAltReview.site_id == site_id,
        SeoImageAltReview.page_id == page_id, SeoImageAltReview.snapshot_id == snapshot.id,
    ).order_by(SeoImageAltReview.position)))
    return {"snapshot_id": snapshot.id, "items": [image_review_payload(row) for row in reviews]}


def _image_snapshot_time(snapshot):
    value = snapshot.fetched_at
    if value is not None and value.tzinfo is None:
        value = value.replace(tzinfo=timezone(timedelta(hours=8)))
    return value.isoformat() if value else None


@router.get("/site-pages/image-remediation-history")
async def list_image_remediation_history(
    tenant_id: PositiveInt, site_id: PositiveInt, page_id: PositiveInt,
    before_snapshot_id: PositiveInt | None = None,
    limit: int = Query(20, ge=1, le=50),
    ctx: AuthContext = Depends(require_scoped_auth), session: AsyncSession = Depends(get_session),
):
    await _scope(session, ctx, tenant_id, site_id)
    page, current = await _page_and_latest_snapshot(session, tenant_id, site_id, page_id)
    query = select(SeoPageSnapshot).where(
        SeoPageSnapshot.tenant_id == tenant_id, SeoPageSnapshot.site_id == site_id,
        SeoPageSnapshot.url == page.url, SeoPageSnapshot.image_alt_evidence.is_not(None),
    )
    if before_snapshot_id is not None:
        query = query.where(SeoPageSnapshot.id < before_snapshot_id)
    snapshots = list(await session.scalars(query.order_by(
        SeoPageSnapshot.fetched_at.desc(), SeoPageSnapshot.id.desc()).limit(limit + 1)))
    visible = snapshots[:limit]
    snapshot_ids = [row.id for row in visible]
    reviews = []
    if snapshot_ids:
        reviews = list(await session.scalars(select(SeoImageAltReview).where(
            SeoImageAltReview.tenant_id == tenant_id, SeoImageAltReview.site_id == site_id,
            SeoImageAltReview.page_id == page_id,
            SeoImageAltReview.snapshot_id.in_(snapshot_ids),
        ).order_by(SeoImageAltReview.snapshot_id.desc(), SeoImageAltReview.position)))
    grouped = defaultdict(list)
    for review in reviews:
        grouped[review.snapshot_id].append(review)
    items = []
    for snapshot in visible:
        evidence = snapshot.image_alt_evidence if isinstance(snapshot.image_alt_evidence, dict) else {}
        saved = grouped[snapshot.id]
        items.append({
            "snapshot_id": snapshot.id,
            "fetched_at": _image_snapshot_time(snapshot),
            "candidate_count": int(evidence.get("candidate_count") or len(evidence.get("items", []))),
            "saved_count": len(saved),
            "approved_count": sum(row.review_status == "approved" for row in saved),
            "draft_count": sum(row.review_status == "draft" for row in saved),
            "is_current": bool(current and current.id == snapshot.id),
        })
    return {
        "current_snapshot_id": current.id if current else None,
        "items": items,
        "next_before_snapshot_id": visible[-1].id if len(snapshots) > limit and visible else None,
    }


class ImageAltReviewUpdate(BaseModel):
    tenant_id: PositiveInt
    site_id: PositiveInt
    page_id: PositiveInt
    expected_snapshot_id: PositiveInt
    expected_review_id: PositiveInt | None
    position: PositiveInt
    decision: Literal["undecided", "decorative", "informative"]
    alt_suggestion: str | None = Field(None, max_length=300)
    note: str | None = Field(None, max_length=1000)
    review_status: Literal["draft", "approved"] = "draft"

    @field_validator("alt_suggestion", "note")
    @classmethod
    def trim_optional(cls, value):
        return value.strip() or None if value is not None else None


@router.put("/site-pages/image-remediation")
async def save_image_remediation(
    req: ImageAltReviewUpdate, ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
):
    await _scope(session, ctx, req.tenant_id, req.site_id, write=True)
    if ctx.user_id is None:
        raise HTTPException(403, "图片用途必须由已登录的真实用户确认")
    _, snapshot = await _page_and_latest_snapshot(
        session, req.tenant_id, req.site_id, req.page_id, lock_page=True)
    if snapshot is None or snapshot.id != req.expected_snapshot_id:
        raise HTTPException(409, "图片证据已更新，请重新读取后确认")
    evidence = snapshot.image_alt_evidence if not snapshot.error_type else None
    candidates = evidence.get("items", []) if isinstance(evidence, dict) else []
    candidate = next((item for item in candidates if item.get("position") == req.position), None)
    if candidate is None:
        raise HTTPException(409, "当前快照中不存在该图片证据")
    observed_state = candidate.get("alt_state")
    if observed_state not in {"missing", "empty", "whitespace"}:
        raise HTTPException(409, "当前图片证据状态无效，请重新检测页面后再确认")
    suggestion = req.alt_suggestion
    if req.decision != "informative":
        suggestion = None
    if req.review_status == "approved" and req.decision == "undecided":
        raise HTTPException(422, "审核前请先确认图片用途")
    if req.review_status == "approved" and req.decision == "informative" and not suggestion:
        raise HTTPException(422, "内容图审核通过前必须填写 Alt 建议")
    row = await session.scalar(select(SeoImageAltReview).where(
        SeoImageAltReview.snapshot_id == snapshot.id,
        SeoImageAltReview.position == req.position,
    ).with_for_update())
    if (row.id if row else None) != req.expected_review_id:
        raise HTTPException(409, "图片整改记录已被其他操作更新，请刷新后重试")
    values = {
        "tenant_id": req.tenant_id, "site_id": req.site_id, "page_id": req.page_id,
        "snapshot_id": snapshot.id, "position": req.position,
        "source_url": candidate.get("source_url"),
        "observed_alt_state": observed_state, "decision": req.decision,
        "alt_suggestion": suggestion, "note": req.note, "review_status": req.review_status,
        "actor_id": ctx.user_id, "actor_name": ctx.username,
        "reviewed_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
    }
    if row is None:
        row = SeoImageAltReview(**values)
        session.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    await session.commit()
    await session.refresh(row)
    return image_review_payload(row)


class ImageAltReviewCopy(BaseModel):
    tenant_id: PositiveInt
    site_id: PositiveInt
    page_id: PositiveInt
    expected_snapshot_id: PositiveInt
    source_snapshot_id: PositiveInt


class ImageAltReviewReuse(BaseModel):
    tenant_id: PositiveInt
    site_id: PositiveInt
    page_id: PositiveInt
    expected_snapshot_id: PositiveInt


_IMAGE_FINGERPRINT_FIELDS = (
    "source_url", "source_attribute", "srcset", "section", "element_id",
    "in_link", "role", "alt_state",
)


def _image_fingerprint(candidate):
    if not isinstance(candidate, dict):
        return None
    return tuple(candidate.get(field) for field in _IMAGE_FINGERPRINT_FIELDS)


def _unique_candidates(evidence):
    grouped = defaultdict(list)
    items = evidence.get("items", []) if isinstance(evidence, dict) else []
    for candidate in items:
        fingerprint = _image_fingerprint(candidate)
        if fingerprint is not None:
            grouped[fingerprint].append(candidate)
    return {fingerprint: rows[0] for fingerprint, rows in grouped.items() if len(rows) == 1}


_CROSS_PAGE_IMAGE_FINGERPRINT_FIELDS = (
    "source_url", "source_attribute", "section", "in_link", "role", "alt_state",
)


def _cross_page_image_fingerprint(candidate):
    if not isinstance(candidate, dict) or candidate.get("source_url_truncated"):
        return None
    source_url = candidate.get("source_url")
    if not isinstance(source_url, str) or not source_url.startswith(("http://", "https://")):
        return None
    return tuple(candidate.get(field) for field in _CROSS_PAGE_IMAGE_FINGERPRINT_FIELDS)


def _unique_cross_page_candidates(evidence):
    grouped = defaultdict(list)
    items = evidence.get("items", []) if isinstance(evidence, dict) else []
    for candidate in items:
        fingerprint = _cross_page_image_fingerprint(candidate)
        if fingerprint is not None:
            grouped[fingerprint].append(candidate)
    return (
        {fingerprint: rows[0] for fingerprint, rows in grouped.items() if len(rows) == 1},
        sum(len(rows) for rows in grouped.values() if len(rows) > 1),
    )


async def _cross_page_reuse_plan(session, tenant_id, site_id, page_id, target, *, lock_existing=False):
    """Return only exact, non-conflicting reuse candidates within one tenant/site."""
    target_candidates, repeated_target_count = _unique_cross_page_candidates(target.image_alt_evidence)
    existing_query = select(SeoImageAltReview).where(
        SeoImageAltReview.tenant_id == tenant_id,
        SeoImageAltReview.site_id == site_id,
        SeoImageAltReview.page_id == page_id,
        SeoImageAltReview.snapshot_id == target.id,
    )
    if lock_existing:
        existing_query = existing_query.with_for_update()
    existing = list(await session.scalars(existing_query))
    existing_positions = {row.position for row in existing}
    if not target_candidates:
        return {
            "reusable": [], "skipped_existing": 0,
            "skipped_ambiguous": repeated_target_count, "candidate_count": repeated_target_count,
        }

    target_urls = {fingerprint[0] for fingerprint in target_candidates}
    approved = list(await session.scalars(select(SeoImageAltReview).where(
        SeoImageAltReview.tenant_id == tenant_id,
        SeoImageAltReview.site_id == site_id,
        SeoImageAltReview.page_id != page_id,
        SeoImageAltReview.source_url.in_(target_urls),
        SeoImageAltReview.review_status == "approved",
        SeoImageAltReview.decision.in_(("decorative", "informative")),
    ).order_by(SeoImageAltReview.updated_at.desc(), SeoImageAltReview.id.desc())))
    snapshot_ids = {row.snapshot_id for row in approved}
    page_ids = {row.page_id for row in approved}
    snapshots = list(await session.scalars(select(SeoPageSnapshot).where(
        SeoPageSnapshot.tenant_id == tenant_id,
        SeoPageSnapshot.site_id == site_id,
        SeoPageSnapshot.id.in_(snapshot_ids),
    ))) if snapshot_ids else []
    pages = list(await session.scalars(select(SeoSitePage).where(
        SeoSitePage.tenant_id == tenant_id,
        SeoSitePage.site_id == site_id,
        SeoSitePage.id.in_(page_ids),
    ))) if page_ids else []
    snapshot_by_id = {row.id: row for row in snapshots}
    page_by_id = {row.id: row for row in pages}
    source_unique = {}
    for snapshot in snapshots:
        unique, _ = _unique_cross_page_candidates(snapshot.image_alt_evidence)
        source_unique[snapshot.id] = unique

    source_matches = defaultdict(list)
    for review in approved:
        snapshot = snapshot_by_id.get(review.snapshot_id)
        source_page = page_by_id.get(review.page_id)
        if (snapshot is None or source_page is None or snapshot.error_type
                or snapshot.url != source_page.url):
            continue
        source_items = snapshot.image_alt_evidence.get("items", []) if isinstance(
            snapshot.image_alt_evidence, dict) else []
        candidate = next((item for item in source_items if item.get("position") == review.position), None)
        fingerprint = _cross_page_image_fingerprint(candidate)
        if (fingerprint is None or source_unique.get(snapshot.id, {}).get(fingerprint) is not candidate
                or review.source_url != candidate.get("source_url")
                or review.observed_alt_state != candidate.get("alt_state")
                or (review.decision == "informative" and not (review.alt_suggestion or "").strip())):
            continue
        source_matches[fingerprint].append((review, source_page, snapshot))

    reusable = []
    skipped_existing = 0
    skipped_ambiguous = repeated_target_count
    for fingerprint, target_candidate in target_candidates.items():
        position = target_candidate.get("position")
        if not isinstance(position, int) or position <= 0:
            skipped_ambiguous += 1
            continue
        matches = source_matches.get(fingerprint, [])
        conclusions = {
            (row.decision, (row.alt_suggestion or "").strip() if row.decision == "informative" else None)
            for row, _, _ in matches
        }
        if len(conclusions) > 1:
            skipped_ambiguous += 1
            continue
        if len(conclusions) == 1:
            if position in existing_positions:
                skipped_existing += 1
                continue
            review, source_page, source_snapshot = matches[0]
            reusable.append((target_candidate, review, source_page, source_snapshot))
    return {
        "reusable": reusable,
        "skipped_existing": skipped_existing,
        "skipped_ambiguous": skipped_ambiguous,
        "candidate_count": len(target.image_alt_evidence.get("items", []))
        if isinstance(target.image_alt_evidence, dict) else 0,
    }


@router.post("/site-pages/image-remediation/copy")
async def copy_image_remediation(
    req: ImageAltReviewCopy, ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
):
    await _scope(session, ctx, req.tenant_id, req.site_id, write=True)
    if ctx.user_id is None:
        raise HTTPException(403, "图片整改记录必须由已登录的真实用户复制")
    page, target = await _page_and_latest_snapshot(
        session, req.tenant_id, req.site_id, req.page_id, lock_page=True)
    if target is None or target.id != req.expected_snapshot_id:
        raise HTTPException(409, "图片证据已更新，请重新读取后确认")
    if req.source_snapshot_id == target.id:
        raise HTTPException(422, "请选择较早的图片快照")
    source = await session.scalar(select(SeoPageSnapshot).where(
        SeoPageSnapshot.id == req.source_snapshot_id,
        SeoPageSnapshot.tenant_id == req.tenant_id,
        SeoPageSnapshot.site_id == req.site_id,
        SeoPageSnapshot.url == page.url,
    ))
    if source is None or source.error_type or not source.image_alt_evidence:
        raise HTTPException(404, "来源图片快照不存在或没有可复用证据")
    if (source.fetched_at, source.id) >= (target.fetched_at, target.id):
        raise HTTPException(422, "来源图片快照必须早于当前快照")
    if target.error_type or not target.image_alt_evidence:
        raise HTTPException(409, "当前图片快照没有可审核证据")

    source_candidates = _unique_candidates(source.image_alt_evidence)
    target_candidates = _unique_candidates(target.image_alt_evidence)
    source_by_position = {
        item.get("position"): item
        for item in source.image_alt_evidence.get("items", [])
        if isinstance(item, dict)
    }
    approved = list(await session.scalars(select(SeoImageAltReview).where(
        SeoImageAltReview.tenant_id == req.tenant_id,
        SeoImageAltReview.site_id == req.site_id,
        SeoImageAltReview.page_id == req.page_id,
        SeoImageAltReview.snapshot_id == source.id,
        SeoImageAltReview.review_status == "approved",
        SeoImageAltReview.decision.in_(("decorative", "informative")),
    ).order_by(SeoImageAltReview.position)))
    existing = list(await session.scalars(select(SeoImageAltReview).where(
        SeoImageAltReview.tenant_id == req.tenant_id,
        SeoImageAltReview.site_id == req.site_id,
        SeoImageAltReview.page_id == req.page_id,
        SeoImageAltReview.snapshot_id == target.id,
    ).with_for_update()))
    existing_positions = {row.position for row in existing}
    now = datetime.now(timezone.utc)
    copied = []
    skipped_ambiguous = 0
    skipped_existing = 0
    for prior in approved:
        source_candidate = source_by_position.get(prior.position)
        fingerprint = _image_fingerprint(source_candidate)
        if (fingerprint is None or source_candidates.get(fingerprint) is not source_candidate
                or fingerprint not in target_candidates):
            skipped_ambiguous += 1
            continue
        if (prior.observed_alt_state != source_candidate.get("alt_state")
                or prior.source_url != source_candidate.get("source_url")
                or (prior.decision == "informative" and not prior.alt_suggestion)):
            skipped_ambiguous += 1
            continue
        target_candidate = target_candidates[fingerprint]
        target_position = target_candidate.get("position")
        if not isinstance(target_position, int) or target_position <= 0:
            skipped_ambiguous += 1
            continue
        if target_position in existing_positions:
            skipped_existing += 1
            continue
        provenance = f"复制自快照 #{source.id}，需核对当前图片后重新审核"
        note = f"{provenance}；{prior.note}" if prior.note else provenance
        row = SeoImageAltReview(
            tenant_id=req.tenant_id, site_id=req.site_id, page_id=req.page_id,
            snapshot_id=target.id, position=target_position,
            source_url=target_candidate.get("source_url"),
            observed_alt_state=target_candidate.get("alt_state"),
            decision=prior.decision,
            alt_suggestion=prior.alt_suggestion if prior.decision == "informative" else None,
            note=note[:1000], review_status="draft",
            actor_id=ctx.user_id, actor_name=ctx.username,
            reviewed_at=now, updated_at=now,
        )
        session.add(row)
        copied.append(target_position)
        existing_positions.add(target_position)
    if copied:
        await session.commit()
    return {
        "source_snapshot_id": source.id,
        "target_snapshot_id": target.id,
        "approved_source_count": len(approved),
        "copied": len(copied),
        "copied_positions": sorted(copied),
        "skipped_existing": skipped_existing,
        "skipped_ambiguous": skipped_ambiguous,
        "review_status": "draft",
    }


@router.get("/site-pages/image-remediation-reuse-preview")
async def preview_cross_page_image_remediation_reuse(
    tenant_id: PositiveInt, site_id: PositiveInt, page_id: PositiveInt,
    ctx: AuthContext = Depends(require_scoped_auth), session: AsyncSession = Depends(get_session),
):
    await _scope(session, ctx, tenant_id, site_id)
    _, target = await _page_and_latest_snapshot(session, tenant_id, site_id, page_id)
    if target is None or target.error_type or not target.image_alt_evidence:
        return {"target_snapshot_id": target.id if target else None, "eligible_count": 0,
                "source_page_count": 0, "skipped_existing": 0, "skipped_ambiguous": 0}
    plan = await _cross_page_reuse_plan(session, tenant_id, site_id, page_id, target)
    return {
        "target_snapshot_id": target.id,
        "eligible_count": len(plan["reusable"]),
        "source_page_count": len({row[2].id for row in plan["reusable"]}),
        "skipped_existing": plan["skipped_existing"],
        "skipped_ambiguous": plan["skipped_ambiguous"],
    }


@router.post("/site-pages/image-remediation/reuse")
async def reuse_cross_page_image_remediation(
    req: ImageAltReviewReuse, ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
):
    await _scope(session, ctx, req.tenant_id, req.site_id, write=True)
    if ctx.user_id is None:
        raise HTTPException(403, "图片整改记录必须由已登录的真实用户复用")
    _, target = await _page_and_latest_snapshot(
        session, req.tenant_id, req.site_id, req.page_id, lock_page=True)
    if target is None or target.id != req.expected_snapshot_id:
        raise HTTPException(409, "图片证据已更新，请重新读取后确认")
    if target.error_type or not target.image_alt_evidence:
        raise HTTPException(409, "当前图片快照没有可审核证据")
    plan = await _cross_page_reuse_plan(
        session, req.tenant_id, req.site_id, req.page_id, target, lock_existing=True)
    now = datetime.now(timezone.utc)
    copied_positions = []
    source_page_ids = set()
    for target_candidate, prior, source_page, source_snapshot in plan["reusable"]:
        position = target_candidate["position"]
        provenance = f"复用自页面 #{source_page.id} 快照 #{source_snapshot.id}，需核对当前页面语境后重新审核"
        note = f"{provenance}；{prior.note}" if prior.note else provenance
        session.add(SeoImageAltReview(
            tenant_id=req.tenant_id, site_id=req.site_id, page_id=req.page_id,
            snapshot_id=target.id, position=position,
            source_url=target_candidate.get("source_url"),
            observed_alt_state=target_candidate.get("alt_state"),
            decision=prior.decision,
            alt_suggestion=(prior.alt_suggestion or "").strip() if prior.decision == "informative" else None,
            note=note[:1000], review_status="draft",
            actor_id=ctx.user_id, actor_name=ctx.username,
            reviewed_at=now, updated_at=now,
        ))
        copied_positions.append(position)
        source_page_ids.add(source_page.id)
    if copied_positions:
        await session.commit()
    return {
        "target_snapshot_id": target.id,
        "eligible_count": len(plan["reusable"]),
        "copied": len(copied_positions),
        "copied_positions": sorted(copied_positions),
        "source_page_count": len(source_page_ids),
        "skipped_existing": plan["skipped_existing"],
        "skipped_ambiguous": plan["skipped_ambiguous"],
        "review_status": "draft",
    }


class IndexReviewCreate(BaseModel):
    tenant_id: PositiveInt
    site_id: PositiveInt
    page_id: PositiveInt
    # Required even on the first review (null); optimistic concurrency token.
    expected_review_id: PositiveInt | None
    intent: Literal["undecided", "index", "noindex"]
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("请填写确认原因")
        return value


@router.post("/site-pages/index-reviews")
async def create_index_review(
    req: IndexReviewCreate, ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
):
    await _scope(session, ctx, req.tenant_id, req.site_id, write=True)
    if ctx.user_id is None:
        raise HTTPException(403, "索引意图必须由已登录的真实用户确认")
    row = await session.scalar(select(SeoSitePage).where(
        SeoSitePage.id == req.page_id, SeoSitePage.tenant_id == req.tenant_id,
        SeoSitePage.site_id == req.site_id,
    ).with_for_update())
    if row is None:
        raise HTTPException(404, "页面不存在")
    latest = await session.scalar(select(SeoPageIndexReview).where(
        SeoPageIndexReview.tenant_id == req.tenant_id, SeoPageIndexReview.site_id == req.site_id,
        SeoPageIndexReview.page_id == req.page_id,
    ).order_by(SeoPageIndexReview.id.desc()).limit(1))
    if (latest.id if latest else None) != req.expected_review_id:
        raise HTTPException(409, "索引意图已被其他操作更新，请刷新后重试")
    review = SeoPageIndexReview(
        tenant_id=req.tenant_id, site_id=req.site_id, page_id=req.page_id,
        intent=req.intent, reason=req.reason, actor_id=ctx.user_id, actor_name=ctx.username,
        evidence=diagnostic_payload(row, req.intent), created_at=datetime.now(timezone.utc),
    )
    session.add(review)
    await session.commit()
    await session.refresh(review)
    return {"review": review_payload(review), "diagnostic": review.evidence}


@router.get("/site-pages/index-reviews")
async def list_index_reviews(
    tenant_id: PositiveInt, site_id: PositiveInt, page_id: PositiveInt,
    before_id: PositiveInt | None = None, limit: int = Query(20, ge=1, le=100),
    ctx: AuthContext = Depends(require_scoped_auth), session: AsyncSession = Depends(get_session),
):
    await _scope(session, ctx, tenant_id, site_id)
    page = await session.scalar(select(SeoSitePage.id).where(
        SeoSitePage.id == page_id, SeoSitePage.tenant_id == tenant_id, SeoSitePage.site_id == site_id,
    ))
    if page is None:
        raise HTTPException(404, "页面不存在")
    r = SeoPageIndexReview
    query = select(r).where(r.tenant_id == tenant_id, r.site_id == site_id, r.page_id == page_id)
    if before_id is not None:
        query = query.where(r.id < before_id)
    rows = list(await session.scalars(query.order_by(r.id.desc()).limit(limit + 1)))
    return {"items": [review_payload(row) for row in rows[:limit]],
            "next_before_id": rows[limit - 1].id if len(rows) > limit else None}
