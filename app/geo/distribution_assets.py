"""Controlled immutable image storage for reviewed GEO channel variants."""
from __future__ import annotations

import hashlib
from io import BytesIO

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from PIL import Image, ImageFile, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.geo.content.review import invalidate_review
from app.geo.distribution_sources import authorize_scope
from app.geo.project_scope import project_scope, prompt_ids_for_businesses
from app.models import GeoChannelAsset, GeoChannelVariant, GeoContentTask
from app.security.auth import AuthContext, require_scoped_auth


MAX_ASSET_BYTES = 20_000_000
MAX_ASSET_COUNT = 20
MAX_VARIANT_BYTES = 100_000_000
MAX_IMAGE_PIXELS = 25_000_000
MEDIA_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg"}

router = APIRouter(tags=["GEO 分发素材"], dependencies=[Depends(require_scoped_auth)])


def _problem(code: str, message: str, status: int = 409) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


def _assert_strict_decoder() -> None:
    if ImageFile.LOAD_TRUNCATED_IMAGES:
        raise _problem(
            "geo_distribution_image_decoder_unsafe",
            "当前图片解码器允许截断内容，已停止 GEO 素材处理",
            503,
        )


def decode_image(data: bytes) -> tuple[str, int, int]:
    """Fully decode one bounded PNG/JPEG and return its canonical media type."""
    _assert_strict_decoder()
    if not data:
        raise _problem("geo_distribution_asset_empty", "图片内容为空", 422)
    if len(data) > MAX_ASSET_BYTES:
        raise _problem("geo_distribution_asset_too_large", "单张图片不能超过 20MB", 413)
    try:
        with Image.open(BytesIO(data)) as probe:
            detected = str(probe.format or "").upper()
            width, height = probe.size
            probe.verify()
        _assert_strict_decoder()
        if detected not in MEDIA_TYPES:
            raise _problem(
                "geo_distribution_asset_type_unsupported",
                "只支持真实 PNG 或 JPEG 图片",
                422,
            )
        if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
            raise _problem(
                "geo_distribution_asset_dimensions_invalid",
                "图片尺寸不可用或解码像素过多",
                422,
            )
        # verify() validates structure; a second open/load performs an actual decode.
        with Image.open(BytesIO(data)) as decoded:
            decoded.load()
            _assert_strict_decoder()
            if (
                str(decoded.format or "").upper() != detected
                or int(getattr(decoded, "n_frames", 1)) != 1
            ):
                raise UnidentifiedImageError("format changed during decode")
    except HTTPException:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise _problem(
            "geo_distribution_asset_dimensions_invalid",
            "图片解码像素过多",
            422,
        ) from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise _problem(
            "geo_distribution_asset_decode_failed",
            "图片无法完整解码为 PNG 或 JPEG",
            422,
        ) from exc
    return MEDIA_TYPES[detected], width, height


async def _mutable_variant(
    session: AsyncSession,
    actor_user_id: int,
    tenant_id: int,
    scope_id: int,
    variant_id: int,
) -> tuple[GeoContentTask, GeoChannelVariant]:
    await authorize_scope(session, actor_user_id, tenant_id, scope_id)
    _, business_ids = await project_scope(session, tenant_id, scope_id)
    prompt_ids = set(await prompt_ids_for_businesses(session, tenant_id, business_ids))
    # Discover the parent without a lock, then take the established task ->
    # variant lock order also used by source reads and content mutations.
    variant = await session.get(GeoChannelVariant, variant_id, populate_existing=True)
    if variant is None or str(variant.channel or "").lower() != "xiaohongshu":
        raise _problem("geo_distribution_source_not_found", "小红书渠道稿不存在", 404)
    task = await session.get(
        GeoContentTask, int(variant.task_id), populate_existing=True, with_for_update=True
    )
    variant = await session.get(
        GeoChannelVariant, variant_id, populate_existing=True, with_for_update=True
    )
    if (
        task is None
        or variant is None
        or int(variant.task_id) != int(task.id)
        or str(variant.channel or "").lower() != "xiaohongshu"
        or int(task.tenant_id) != tenant_id
        or task.business_id is None
        or int(task.business_id) not in set(business_ids)
        or int(task.prompt_id) not in prompt_ids
    ):
        raise _problem("geo_distribution_scope_mismatch", "渠道稿不属于当前 GEO 项目", 404)
    latest_id = await session.scalar(
        select(GeoChannelVariant.id)
        .where(
            GeoChannelVariant.task_id == task.id,
            GeoChannelVariant.channel == "xiaohongshu",
        )
        .order_by(
            GeoChannelVariant.updated_at.desc().nullslast(),
            GeoChannelVariant.id.desc(),
        )
        .limit(1)
    )
    if latest_id is None or int(latest_id) != int(variant.id):
        raise _problem("geo_distribution_variant_stale", "只能给当前最新小红书渠道稿维护素材")
    from app.geo.content.routes import _latest_article

    article = await _latest_article(session, task.id, fresh=True)
    if article is None or int(variant.article_version_id) != int(article.id):
        raise _problem("geo_distribution_master_stale", "渠道稿对应的母稿已更新")
    return task, variant


def asset_manifest(row: GeoChannelAsset) -> dict:
    return {
        "id": f"geo-asset-{int(row.id)}",
        "sha256": str(row.sha256),
        "mediaType": str(row.media_type),
        "bytes": int(row.byte_size),
    }


async def store_asset(
    session: AsyncSession,
    actor_user_id: int,
    tenant_id: int,
    scope_id: int,
    variant_id: int,
    sort_order: int,
    data: bytes,
) -> GeoChannelAsset:
    """Store immutable bytes and invalidate any review of the previous set."""
    if not 0 <= int(sort_order) < MAX_ASSET_COUNT:
        raise _problem("geo_distribution_asset_order_invalid", "图片顺序必须在 0 到 19 之间", 422)
    task, variant = await _mutable_variant(
        session, actor_user_id, tenant_id, scope_id, variant_id
    )
    media_type, _, _ = decode_image(data)
    count, total = (await session.execute(
        select(func.count(GeoChannelAsset.id), func.coalesce(func.sum(GeoChannelAsset.byte_size), 0))
        .where(GeoChannelAsset.variant_id == variant.id)
    )).one()
    if int(count) >= MAX_ASSET_COUNT:
        raise _problem("geo_distribution_asset_count_exceeded", "每个渠道稿最多 20 张图片", 422)
    if int(total) + len(data) > MAX_VARIANT_BYTES:
        raise _problem("geo_distribution_asset_total_exceeded", "每个渠道稿图片总量不能超过 100MB", 413)
    existing = await session.scalar(select(GeoChannelAsset.id).where(
        GeoChannelAsset.variant_id == variant.id,
        GeoChannelAsset.sort_order == int(sort_order),
    ))
    if existing is not None:
        raise _problem("geo_distribution_asset_order_conflict", "该图片顺序已被占用")
    row = GeoChannelAsset(
        tenant_id=tenant_id,
        task_id=task.id,
        article_version_id=variant.article_version_id,
        variant_id=variant.id,
        sort_order=int(sort_order),
        media_type=media_type,
        byte_size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        content_bytes=data,
        created_by=actor_user_id,
    )
    session.add(row)
    invalidate_review(task)
    await session.flush()
    return row


async def remove_asset(
    session: AsyncSession,
    actor_user_id: int,
    tenant_id: int,
    scope_id: int,
    variant_id: int,
    asset_id: int,
) -> None:
    task, variant = await _mutable_variant(
        session, actor_user_id, tenant_id, scope_id, variant_id
    )
    row = await session.get(GeoChannelAsset, asset_id, with_for_update=True)
    if row is None or int(row.variant_id) != int(variant.id) or int(row.tenant_id) != tenant_id:
        raise _problem("geo_distribution_asset_not_found", "GEO 图片素材不存在", 404)
    await session.delete(row)
    invalidate_review(task)
    await session.flush()


async def list_editable_assets(
    session: AsyncSession,
    actor_user_id: int,
    tenant_id: int,
    scope_id: int,
    variant_id: int,
) -> tuple[GeoContentTask, list[GeoChannelAsset]]:
    task, variant = await _mutable_variant(
        session, actor_user_id, tenant_id, scope_id, variant_id
    )
    rows = list((await session.scalars(
        select(GeoChannelAsset)
        .where(GeoChannelAsset.variant_id == variant.id)
        .order_by(GeoChannelAsset.sort_order, GeoChannelAsset.id)
    )).all())
    for row in rows:
        data = bytes(row.content_bytes or b"")
        media_type, _, _ = decode_image(data)
        if (
            int(row.tenant_id) != tenant_id
            or int(row.task_id) != int(task.id)
            or int(row.article_version_id) != int(variant.article_version_id)
            or int(row.byte_size) != len(data)
            or hashlib.sha256(data).hexdigest() != str(row.sha256)
            or media_type != str(row.media_type)
        ):
            raise _problem(
                "geo_distribution_asset_manifest_invalid",
                "GEO 图片素材字节与清单不一致",
                409,
            )
    return task, rows


@router.get("/distribution-assets")
async def get_distribution_assets(
    tenant_id: int,
    scope_id: int,
    variant_id: int,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if ctx.user_id is None:
        raise _problem("geo_distribution_actor_unavailable", "需要已登录实名顾问", 403)
    task, rows = await list_editable_assets(
        session, int(ctx.user_id), tenant_id, scope_id, variant_id
    )
    return {
        "variant_id": variant_id,
        "review_status": str(task.review_status or "none"),
        "assets": [
            {**asset_manifest(row), "sort_order": int(row.sort_order)}
            for row in rows
        ],
    }


@router.get("/distribution-assets/{asset_id}/content")
async def get_distribution_asset_content(
    asset_id: int,
    tenant_id: int,
    scope_id: int,
    variant_id: int,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> Response:
    if ctx.user_id is None:
        raise _problem("geo_distribution_actor_unavailable", "需要已登录实名顾问", 403)
    _, rows = await list_editable_assets(
        session, int(ctx.user_id), tenant_id, scope_id, variant_id
    )
    row = next((item for item in rows if int(item.id) == asset_id), None)
    if row is None:
        raise _problem("geo_distribution_asset_not_found", "GEO 图片素材不存在", 404)
    return Response(
        bytes(row.content_bytes),
        media_type=row.media_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "ETag": f'"{row.sha256}"',
        },
    )


@router.post("/distribution-assets")
async def upload_distribution_asset(
    tenant_id: int = Form(...),
    scope_id: int = Form(...),
    variant_id: int = Form(...),
    sort_order: int = Form(...),
    file: UploadFile = File(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if ctx.user_id is None:
        raise _problem("geo_distribution_actor_unavailable", "需要已登录实名顾问", 403)
    # Reject stale/cross-scope variants before reading, decoding or persisting it.
    await _mutable_variant(
        session, int(ctx.user_id), tenant_id, scope_id, variant_id
    )
    data = await file.read(MAX_ASSET_BYTES + 1)
    row = await store_asset(
        session, int(ctx.user_id), tenant_id, scope_id, variant_id, sort_order, data
    )
    await session.commit()
    return {"asset": asset_manifest(row), "review_invalidated": True}


@router.delete("/distribution-assets/{asset_id}")
async def delete_distribution_asset(
    asset_id: int,
    tenant_id: int,
    scope_id: int,
    variant_id: int,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if ctx.user_id is None:
        raise _problem("geo_distribution_actor_unavailable", "需要已登录实名顾问", 403)
    await remove_asset(
        session, int(ctx.user_id), tenant_id, scope_id, variant_id, asset_id
    )
    await session.commit()
    return {"deleted": True, "review_invalidated": True}
