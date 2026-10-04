"""Authenticated, site-scoped HTTP access to SEO page captures."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
import logging
import os
from pathlib import Path
import re
from collections import defaultdict
from typing import Literal
import uuid
from urllib.parse import quote
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, PositiveInt
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import async_session_factory
from app.models.module_workspace import SeoSite
from app.models.seo import SeoContentAsset, SeoContentPublication, SeoKeywordAsset, SeoSitePage
from app.models.seo_page_capture import SeoPageCapture
from app.module_scope import seo_site_is_operational
from app.security.auth import AuthContext
from app.seo_demo_source import get_seo_session as get_session, require_seo_scoped_auth as require_scoped_auth
from app.seo_page_capture import CaptureError, PageCaptureService, _check_url, capture_storage_path
from app.seo_capture_upload import UploadImageError, clean_image
from app.seo_serp import canonical_url, domain_matches
from app.seo_publication_export import (build_publication_list_workbook, capture_fields,
                                        month_bounds, publication_summary)

router = APIRouter()
logger = logging.getLogger(__name__)
_COOLDOWN = timedelta(seconds=60)
_BEIJING = timezone(timedelta(hours=8))  # China has no DST; works without Windows tzdata.
_INVALID_ESCAPE = re.compile(r"%(?![0-9a-fA-F]{2})")


class CaptureCreate(BaseModel):
    tenant_id: PositiveInt
    site_id: PositiveInt
    url: str | None = None
    relation_type: Literal["site_page", "publication"] | None = None
    relation_id: PositiveInt | None = None


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


def _require_capture_view(ctx: AuthContext) -> None:
    if not ctx.can_view("seo.site"):
        raise _error(403, "forbidden", "需要网站查看权限")


@router.get("/site/publications/export")
async def export_publication_list(tenant_id: PositiveInt, site_id: PositiveInt, month: str,
                                  session: AsyncSession = Depends(get_session),
                                  ctx: AuthContext = Depends(require_scoped_auth)) -> Response:
    ctx.ensure_tenant(tenant_id)
    _require_capture_view(ctx)
    site = await _site(session, tenant_id, site_id)
    try:
        start, end = month_bounds(month)
    except ValueError:
        raise _error(422, "invalid_month", "月份须为 YYYY-MM") from None
    # Publication timestamps in this branch are naive UTC; captured_at is aware UTC.
    pairs = (await session.execute(select(SeoContentPublication, SeoContentAsset).join(
        SeoContentAsset, SeoContentPublication.content_asset_id == SeoContentAsset.id).where(
        SeoContentPublication.tenant_id == tenant_id, SeoContentAsset.tenant_id == tenant_id,
        SeoContentAsset.site_id == site_id, SeoContentPublication.status == "published",
        SeoContentPublication.published_at >= start, SeoContentPublication.published_at < end,
    ).order_by(SeoContentPublication.published_at, SeoContentPublication.id))).all()
    publication_ids = [publication.id for publication, _ in pairs]
    captures = defaultdict(list)
    if publication_ids:
        evidence = (await session.scalars(select(SeoPageCapture).where(
            SeoPageCapture.tenant_id == tenant_id, SeoPageCapture.site_id == site_id,
            SeoPageCapture.relation_type == "publication", SeoPageCapture.relation_id.in_(publication_ids),
        ))).all()
        for capture in evidence:
            captures[capture.relation_id].append(capture)
    keyword_ids = {key for _, asset in pairs for key in (asset.keyword_ids or ([asset.keyword_id] if asset.keyword_id else [])) if isinstance(key, int)}
    keywords = {}
    if keyword_ids:
        found = (await session.scalars(select(SeoKeywordAsset).where(
            SeoKeywordAsset.tenant_id == tenant_id, SeoKeywordAsset.site_id == site_id,
            SeoKeywordAsset.id.in_(keyword_ids)))).all()
        keywords = {keyword.id: keyword.keyword for keyword in found}
    rows = []
    for publication, asset in pairs:
        selected = asset.keyword_ids or ([asset.keyword_id] if asset.keyword_id else [])
        capture = capture_fields(captures[publication.id])
        rows.append({"platform": publication.platform_name, "title": asset.title,
                     "keywords": "、".join(keywords[key] for key in selected if key in keywords),
                     "page_url": publication.page_url, "published_at": publication.published_at,
                     "capture_status": capture["capture_status"], "image_key": capture["image_key"],
                     "captured_at": capture["captured_at"], "notes": capture["capture_note"],
                     "capture_kind": capture["capture_kind"]})
    settings = get_settings()
    def load_image(key: str) -> bytes:
        return capture_storage_path(settings.seo_page_capture_storage_dir, key).read_bytes()
    summary = publication_summary(rows, site.name, month, datetime.now(timezone.utc))
    workbook = build_publication_list_workbook(rows, summary, image_loader=load_image,
                                               max_pixels=settings.seo_page_capture_max_pixels)
    safe_site = re.sub(r'[\\/:*?"<>|\r\n]+', "_", site.name).strip(" .") or "站点"
    filename = f"发布清单-{safe_site}-{month}.xlsx"
    return Response(workbook, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename=publication-list-{month}.xlsx; filename*=UTF-8''{quote(filename)}",
                             "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


def _deadline() -> datetime:
    # Covers the renderer's own timeout plus dispatch and DB settling.
    return datetime.now(timezone.utc) - timedelta(seconds=get_settings().seo_page_capture_timeout_seconds + 60)


async def _expire_stale(session: AsyncSession, tenant_id: int, site_id: int) -> None:
    await session.execute(
        update(SeoPageCapture)
        .where(SeoPageCapture.tenant_id == tenant_id, SeoPageCapture.site_id == site_id,
               SeoPageCapture.status.in_(("pending", "running")),
               SeoPageCapture.captured_at < _deadline())
        .values(status="failed", error_code="timeout")
    )


async def _site(session: AsyncSession, tenant_id: int, site_id: int) -> SeoSite:
    site = await session.get(SeoSite, site_id)
    if site is None or site.tenant_id != tenant_id:
        raise _error(404, "site_not_found", "SEO 网站不属于当前客户")
    return site


async def _capture(session: AsyncSession, tenant_id: int, capture_id: int,
                   *, allow_stale_update: bool = True) -> SeoPageCapture:
    row = await session.get(SeoPageCapture, capture_id)
    if row is None or row.tenant_id != tenant_id:
        raise _error(404, "capture_not_found", "截图不存在")
    await _site(session, tenant_id, row.site_id)
    if allow_stale_update:
        await _expire_stale(session, tenant_id, row.site_id)
        await session.commit()
        await session.refresh(row)
    return row


def _primary_source(request: Request) -> bool:
    decision = getattr(request.state, "seo_data_source_decision", None)
    return getattr(decision, "source", "primary") == "primary"


def _discard_image(result) -> None:
    if result is None or not result.storage_key:
        return
    try:
        capture_storage_path(get_settings().seo_page_capture_storage_dir, result.storage_key).unlink(missing_ok=True)
    except (OSError, ValueError):
        logger.warning("Could not remove discarded SEO capture image")


@lru_cache(maxsize=1)
def _capture_service() -> PageCaptureService:
    # Share the service's semaphore among HTTP background tasks in this process.
    return PageCaptureService()


def _payload(row: SeoPageCapture) -> dict:
    return {name: getattr(row, name) for name in (
        "id", "tenant_id", "site_id", "relation_type", "relation_id", "source_url", "status",
        "error_code", "final_url", "http_status", "redirect_chain", "warnings",
        "viewport_width", "viewport_height", "image_width", "image_height", "sha256", "captured_at",
        "source", "uploaded_by", "uploaded_at", "content_type",
    )}


def _publication_url(value: str | None) -> str | None:
    """Conservative identity: retain path, trailing slash, query spelling and order."""
    if not value or value != value.strip() or _INVALID_ESCAPE.search(value):
        return None
    try:
        parts = urlsplit(value)
        scheme = parts.scheme.lower()
        if scheme not in {"http", "https"} or not parts.hostname or parts.username is not None or parts.password is not None:
            return None
        port = parts.port
        host = parts.hostname.lower()
        netloc = f"[{host}]" if ":" in host else host
        if port is not None and (scheme, port) not in {("http", 80), ("https", 443)}:
            netloc += f":{port}"
        return urlunsplit((scheme, netloc, parts.path, parts.query, ""))
    except (UnicodeError, ValueError):
        return None


def _capture_boundary(value: str, *, upper: bool) -> tuple[datetime, bool]:
    """Date-only bounds are Asia/Shanghai calendar days; timestamps keep their offset."""
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            day = date.fromisoformat(value)
            local = datetime.combine(day + timedelta(days=1) if upper else day, time.min, _BEIJING)
            return local.astimezone(timezone.utc), upper
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(timezone.utc), False
    except ValueError:
        raise _error(422, "invalid_capture_range", "日期使用 YYYY-MM-DD；时间须含时区偏移") from None


async def _relation(session: AsyncSession, tenant_id: int, site_id: int, url: str | None,
                    relation_type: str | None, relation_id: int | None) -> tuple[str, int, str]:
    if (relation_type is None) != (relation_id is None):
        raise _error(422, "invalid_relation", "relation_type 和 relation_id 必须同时提供")
    if relation_type is None:
        if url is None:
            raise _error(422, "site_page_required", "请提供站内页面 URL 或发布记录关联")
        # An omitted relation means one exact URL match in this site's page inventory.
        pages = list(await session.scalars(select(SeoSitePage).where(
            SeoSitePage.tenant_id == tenant_id, SeoSitePage.site_id == site_id, SeoSitePage.url == url,
        ).limit(2)))
        if len(pages) != 1:
            raise _error(422, "site_page_required", "请指定站内页面，或提供唯一匹配的页面 URL")
        return "site_page", pages[0].id, url
    if relation_type == "site_page":
        if url is None:
            raise _error(422, "invalid_site_url", "站内页面截图必须提供 URL")
        page = await session.get(SeoSitePage, relation_id)
        if page is None or page.tenant_id != tenant_id or page.site_id != site_id:
            raise _error(404, "relation_not_found", "站内页面不属于当前网站")
        if canonical_url(page.url) != canonical_url(url):
            raise _error(422, "relation_url_mismatch", "截图 URL 与站内页面 URL 不一致")
    else:
        publication = await session.get(SeoContentPublication, relation_id)
        if publication is None or publication.tenant_id != tenant_id:
            raise _error(404, "relation_not_found", "发布记录不属于当前网站")
        content = await session.get(SeoContentAsset, publication.content_asset_id)
        if content is None or content.tenant_id != tenant_id or content.site_id != site_id:
            raise _error(404, "relation_not_found", "发布记录不属于当前网站")
        registered = _publication_url(publication.page_url) if publication.status == "published" else None
        if registered is None:
            raise _error(422, "publication_url_missing", "该发布记录没有已登记的发布链接")
        if url is None:
            url = publication.page_url
        elif _publication_url(url) != registered:
            raise _error(422, "publication_url_mismatch", "链接与发布记录不一致")
    return relation_type, relation_id, url


async def execute_page_capture(capture_id: int) -> None:
    """Use a fresh session after the response, following the SEO crawl-run pattern."""
    async with async_session_factory() as session:
        row = await session.get(SeoPageCapture, capture_id)
        if row is None or row.status != "pending":
            return
        site = await session.get(SeoSite, row.site_id)
        if (site is None or site.tenant_id != row.tenant_id
                or not await seo_site_is_operational(session, row.tenant_id, row.site_id)):
            row.status, row.error_code = "failed", "site_inactive"
            await session.commit()
            return
        try:
            await _relation(session, row.tenant_id, row.site_id, row.source_url,
                            row.relation_type, row.relation_id)
            _check_url(row.source_url)
            if row.relation_type == "site_page" and not domain_matches(
                    row.source_url, f"https://{site.canonical_domain}"):
                raise _error(422, "invalid_site_url", "链接不属于该站点")
        except (HTTPException, CaptureError) as exc:
            row.status = "failed"
            row.error_code = exc.detail["code"] if isinstance(exc, HTTPException) else exc.code
            await session.commit()
            return
        row.status = "running"
        row.captured_at = datetime.now(timezone.utc)
        await session.commit()
        arguments = dict(tenant_id=row.tenant_id, site_id=row.site_id,
                         relation_type=row.relation_type, relation_id=row.relation_id, url=row.source_url)
    try:
        result = await asyncio.wait_for(
            _capture_service().capture_page(**arguments),
            timeout=get_settings().seo_page_capture_timeout_seconds + 10,
        )
    except Exception:
        logger.exception("SEO page capture worker failed: capture_id=%s", capture_id)
        result = None
    async with async_session_factory() as session:
        row = await session.get(SeoPageCapture, capture_id)
        if row is None or row.status != "running":
            _discard_image(result)
            return
        if not await seo_site_is_operational(session, row.tenant_id, row.site_id):
            row.status, row.error_code = "failed", "site_inactive"
            _discard_image(result)
        elif result is None:
            row.status, row.error_code = "failed", "worker_error"
        else:
            for name in ("status", "error_code", "final_url", "http_status", "redirect_chain",
                         "warnings", "viewport_width", "viewport_height", "image_width", "image_height",
                         "sha256", "storage_key", "captured_at"):
                setattr(row, name, getattr(result, name))
        await session.commit()


@router.post("/site/page-captures", status_code=202)
async def create_page_capture(req: CaptureCreate, background_tasks: BackgroundTasks,
                              session: AsyncSession = Depends(get_session),
                              ctx: AuthContext = Depends(require_scoped_auth)) -> dict:
    ctx.ensure_tenant(req.tenant_id)
    if not ctx.can_edit("seo.site"):
        raise _error(403, "forbidden", "需要网站编辑权限")
    settings = get_settings()
    if not settings.seo_page_capture_enabled:
        raise _error(409, "capture_disabled", "页面截图功能未开启")
    # The site lock also serializes duplicate reservations across workers.
    site = await session.scalar(select(SeoSite).where(
        SeoSite.id == req.site_id, SeoSite.tenant_id == req.tenant_id,
    ).with_for_update().execution_options(populate_existing=True))
    if site is None or site.tenant_id != req.tenant_id:
        raise _error(404, "site_not_found", "SEO 网站不属于当前客户")
    if site.status != "active":
        raise _error(409, "site_inactive", "SEO 网站已暂停或归档")
    if req.relation_type != "publication" and req.url is not None:
        try:
            _check_url(req.url)
            valid_domain = domain_matches(req.url, f"https://{site.canonical_domain}")
        except (CaptureError, ValueError):
            valid_domain = False
        if not valid_domain:
            raise _error(422, "invalid_site_url", "URL 必须是当前网站域名下的 HTTP 或 HTTPS 地址")
    relation_type, relation_id, url = await _relation(
        session, req.tenant_id, req.site_id, req.url, req.relation_type, req.relation_id,
    )
    if relation_type == "site_page":
        try:
            _check_url(url)
            valid_domain = domain_matches(url, f"https://{site.canonical_domain}")
        except (CaptureError, ValueError):
            valid_domain = False
        if not valid_domain:
            raise _error(422, "invalid_site_url", "URL 必须是当前网站域名下的 HTTP 或 HTTPS 地址")
    else:
        try:
            _check_url(url)
        except CaptureError as exc:
            raise _error(422, exc.code, "发布链接必须是可访问的公网 HTTP 或 HTTPS 地址") from exc
    await _expire_stale(session, req.tenant_id, req.site_id)
    recent = await session.scalar(select(SeoPageCapture).where(
        SeoPageCapture.tenant_id == req.tenant_id, SeoPageCapture.site_id == req.site_id,
        SeoPageCapture.relation_type == relation_type, SeoPageCapture.relation_id == relation_id,
        SeoPageCapture.captured_at >= datetime.now(timezone.utc) - _COOLDOWN,
    ).order_by(SeoPageCapture.id.desc()).limit(1))
    if recent is not None:
        raise _error(409, "capture_recent", "该页面刚刚提交过截图请求")
    row = SeoPageCapture(tenant_id=req.tenant_id, site_id=req.site_id,
                         relation_type=relation_type, relation_id=relation_id,
                         source_url=url, status="pending", captured_at=datetime.now(timezone.utc),
                         redirect_chain=[], warnings={},
                         viewport_width=settings.seo_page_capture_viewport_width,
                         viewport_height=settings.seo_page_capture_viewport_height)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    background_tasks.add_task(execute_page_capture, row.id)
    return {"id": row.id, "status": row.status}


@router.post("/site/page-captures/upload", status_code=201)
async def upload_page_capture(tenant_id: PositiveInt = Form(...), site_id: PositiveInt = Form(...),
                              relation_type: Literal["publication"] = Form(...),
                              relation_id: PositiveInt = Form(...), file: UploadFile = File(...),
                              session: AsyncSession = Depends(get_session),
                              ctx: AuthContext = Depends(require_scoped_auth)) -> dict:
    """Manual evidence remains available when browser capture is disabled."""
    ctx.ensure_tenant(tenant_id)
    if not ctx.can_edit("seo.site") or ctx.user_id is None:
        raise _error(403, "forbidden", "需要网站编辑权限和登录用户")
    site = await _site(session, tenant_id, site_id)
    if site.status != "active":
        raise _error(409, "site_inactive", "SEO 网站已暂停或归档")
    _, _, url = await _relation(session, tenant_id, site_id, None, relation_type, relation_id)
    settings = get_settings()
    limit = settings.seo_page_capture_upload_max_bytes
    data = bytearray()
    while chunk := await file.read(min(65536, limit + 1 - len(data))):
        data.extend(chunk)
        if len(data) > limit:
            raise _error(413, "image_too_large", "图片过大")
    try:
        cleaned, mime, extension, width, height = clean_image(bytes(data), settings.seo_page_capture_max_pixels)
    except UploadImageError as exc:
        raise _error(422 if exc.code != "image_too_large" else 413, exc.code, str(exc)) from exc
    key = f"{uuid.uuid4().hex}.{extension}"
    try:
        path = capture_storage_path(settings.seo_page_capture_storage_dir, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(cleaned)
        except Exception:
            path.unlink(missing_ok=True)
            raise
    except (OSError, ValueError) as exc:
        raise _error(500, "storage_error", "截图存储失败") from exc
    now = datetime.now(timezone.utc)
    row = SeoPageCapture(tenant_id=tenant_id, site_id=site_id, relation_type="publication",
                         relation_id=relation_id, source_url=url, final_url=url, status="succeeded",
                         source="manual", uploaded_by=ctx.user_id, uploaded_at=now,
                         captured_at=now, content_type=mime, redirect_chain=[], warnings={},
                         viewport_width=settings.seo_page_capture_viewport_width,
                         viewport_height=settings.seo_page_capture_viewport_height,
                         image_width=width, image_height=height, sha256=hashlib.sha256(cleaned).hexdigest(),
                         storage_key=key)
    try:
        session.add(row)
        await session.commit()
        await session.refresh(row)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return _payload(row)


@router.get("/site/page-captures/{capture_id}")
async def get_page_capture(capture_id: PositiveInt, tenant_id: PositiveInt,
                           request: Request,
                           session: AsyncSession = Depends(get_session),
                           ctx: AuthContext = Depends(require_scoped_auth)) -> dict:
    ctx.ensure_tenant(tenant_id)
    _require_capture_view(ctx)
    return _payload(await _capture(session, tenant_id, capture_id,
                                   allow_stale_update=_primary_source(request)))


@router.get("/site/page-captures/{capture_id}/image")
async def get_page_capture_image(capture_id: PositiveInt, tenant_id: PositiveInt,
                                 request: Request,
                                 session: AsyncSession = Depends(get_session),
                                 ctx: AuthContext = Depends(require_scoped_auth)) -> Response:
    ctx.ensure_tenant(tenant_id)
    _require_capture_view(ctx)
    row = await _capture(session, tenant_id, capture_id,
                         allow_stale_update=_primary_source(request))
    if row.status != "succeeded" or not row.storage_key:
        raise _error(404, "image_not_ready", "截图图片尚不可用")
    try:
        path = capture_storage_path(get_settings().seo_page_capture_storage_dir, row.storage_key)
        data = Path(path).read_bytes()
    except (OSError, ValueError):
        raise _error(404, "image_not_found", "截图图片不可用") from None
    signatures = {"image/png": b"\x89PNG\r\n\x1a\n", "image/jpeg": b"\xff\xd8", "image/webp": b"RIFF"}
    mime = row.content_type
    if mime not in signatures or not data.startswith(signatures[mime]) or (mime == "image/webp" and data[8:12] != b"WEBP"):
        raise _error(404, "image_not_found", "截图图片不可用")
    return Response(data, media_type=mime, headers={
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
    })


@router.get("/site/page-captures")
async def list_page_captures(tenant_id: PositiveInt, site_id: PositiveInt,
                             request: Request,
                             relation_type: Literal["site_page", "publication"] | None = None,
                             relation_id: PositiveInt | None = None,
                             captured_from: str | None = None, captured_to: str | None = None,
                             status: Literal["pending", "running", "succeeded", "failed"] | None = None,
                             source: Literal["auto", "manual"] | None = None,
                             latest_per_relation: bool = False,
                             page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                             session: AsyncSession = Depends(get_session),
                             ctx: AuthContext = Depends(require_scoped_auth)) -> dict:
    ctx.ensure_tenant(tenant_id)
    _require_capture_view(ctx)
    await _site(session, tenant_id, site_id)
    if relation_id is not None and relation_type is None:
        raise _error(422, "invalid_relation", "relation_type 和 relation_id 必须同时提供")
    if _primary_source(request):
        await _expire_stale(session, tenant_id, site_id)
        await session.commit()
    conditions = [SeoPageCapture.tenant_id == tenant_id, SeoPageCapture.site_id == site_id]
    if relation_type is not None:
        conditions.append(SeoPageCapture.relation_type == relation_type)
    if relation_id is not None:
        conditions.append(SeoPageCapture.relation_id == relation_id)
    lower = _capture_boundary(captured_from, upper=False)[0] if captured_from else None
    upper, exclusive = _capture_boundary(captured_to, upper=True) if captured_to else (None, False)
    if lower is not None and upper is not None and (upper < lower or (exclusive and upper == lower)):
        raise _error(422, "invalid_capture_range", "结束时间不能早于开始时间")
    if lower is not None:
        conditions.append(SeoPageCapture.captured_at >= lower)
    if upper is not None:
        conditions.append(SeoPageCapture.captured_at < upper if exclusive else SeoPageCapture.captured_at <= upper)
    if status is not None:
        conditions.append(SeoPageCapture.status == status)
    if source is not None:
        conditions.append(SeoPageCapture.source == source)
    if latest_per_relation:
        ranked = select(
            SeoPageCapture.id.label("capture_id"),
            func.row_number().over(
                partition_by=(SeoPageCapture.relation_type, SeoPageCapture.relation_id),
                order_by=(SeoPageCapture.captured_at.desc(), SeoPageCapture.id.desc()),
            ).label("rank"),
        ).where(*conditions).subquery()
        selected = select(SeoPageCapture).join(ranked, SeoPageCapture.id == ranked.c.capture_id).where(ranked.c.rank == 1)
        total_query = select(func.count()).select_from(ranked).where(ranked.c.rank == 1)
    else:
        selected = select(SeoPageCapture).where(*conditions)
        total_query = select(func.count()).select_from(SeoPageCapture).where(*conditions)
    total = await session.scalar(total_query)
    rows = list(await session.scalars(selected
        .order_by(SeoPageCapture.captured_at.desc(), SeoPageCapture.id.desc())
        .offset((page - 1) * page_size).limit(page_size)))
    return {"items": [_payload(row) for row in rows], "total": total or 0,
            "page": page, "page_size": page_size}
