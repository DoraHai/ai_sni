"""Trusted GEO source adapter for the shared distribution service.

Source loading returns stored, currently publishable content only. Callers must
reload and compare ``source_revision`` before create, dispatch and result
adoption; no client supplied body, summary or review flag is accepted here.
Intake discovery separately returns private metadata for completed drafts,
including those awaiting review/adaptation; this never grants publishing.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.geo.content.gate import PublishGateError, assert_can_publish
from app.geo.content.routes import (
    _brand_context_for_task,
    _build_rule_input,
    _ensure_tenant_exists,
    _latest_article,
)
from app.geo.project_scope import project_scope, prompt_ids_for_businesses
from app.geo.project_workflows import advisor_available, plan_for
from app.geo.tenant_scope import GeoEntitlementUnavailable, ensure_geo_entitlement
from app.models import GeoChannelAsset, GeoChannelVariant, GeoContentTask, GeoProject
from app.models.role import Role
from app.models.user import User
from app.onsite_workflow import host_scope


PLATFORM_CHANNELS = {
    "wechat-article": "wechat",
    "xiaohongshu-image": "xiaohongshu",
}
ASSET_REQUIRED_PLATFORMS = {"xiaohongshu-image"}
_LIST_SKIPPABLE_CODES = frozenset({
    "geo_distribution_source_not_found",
    "geo_distribution_platform_mismatch",
    "geo_distribution_variant_stale",
    "geo_distribution_master_stale",
    "geo_distribution_variant_unavailable",
    "geo_distribution_content_empty",
    "geo_distribution_source_invalid",
    "geo_distribution_publish_gate_blocked",
    "geo_distribution_assets_unavailable",
    "geo_distribution_asset_manifest_invalid",
    "geo_distribution_adaptation_pending",
    "geo_distribution_manual_finalization_invalid",
})


def _problem(code: str, message: str, status: int = 409) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


def _timestamp_revision(value: datetime | None) -> int:
    if value is None:
        return 0
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return int(aware.timestamp() * 1_000_000)


def _source_revision(
    task: GeoContentTask,
    article,
    variant: GeoChannelVariant,
    assets: list[GeoChannelAsset],
) -> str:
    """Build a legal opaque id containing both master and channel revisions."""
    review_at = _timestamp_revision(getattr(task, "reviewed_at", None))
    channel_at = _timestamp_revision(getattr(variant, "updated_at", None))
    digest = hashlib.sha256(json.dumps({
        "task_id": int(task.id),
        "review_status": str(task.review_status or ""),
        "reviewed_by": getattr(task, "reviewed_by", None),
        "reviewed_at": review_at,
        "article_id": int(article.id),
        "article_version": int(article.version_no),
        "article_title": str(article.title or ""),
        "article_body": str(article.body_markdown or ""),
        "variant_id": int(variant.id),
        "variant_updated_at": channel_at,
        "channel": str(variant.channel or ""),
        "title": str(variant.title or ""),
        "body": str(variant.body_markdown or ""),
        "assets": [
            {
                "id": int(row.id),
                "order": int(row.sort_order),
                "sha256": str(row.sha256),
                "media_type": str(row.media_type),
                "bytes": int(row.byte_size),
            }
            for row in assets
        ],
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]
    return (
        f"geo-a{int(article.id)}-v{int(article.version_no)}-"
        f"c{int(variant.id)}-r{channel_at}-q{review_at}-h{digest}"
    )


def _asset_ref(row: GeoChannelAsset) -> dict[str, Any]:
    return {
        "id": f"geo-asset-{int(row.id)}",
        "sha256": str(row.sha256),
        "mediaType": str(row.media_type),
        "bytes": int(row.byte_size),
    }


async def _reviewed_assets(
    session: AsyncSession,
    task: GeoContentTask,
    article,
    variant: GeoChannelVariant,
    platform: str,
) -> list[GeoChannelAsset]:
    # Existing text-only platforms remain independent of the optional asset
    # table, which allows a staged schema rollout without breaking WeChat.
    if platform not in ASSET_REQUIRED_PLATFORMS:
        return []
    assets = list((await session.scalars(
        select(GeoChannelAsset)
        .where(GeoChannelAsset.variant_id == int(variant.id))
        .order_by(GeoChannelAsset.sort_order, GeoChannelAsset.id)
        .with_for_update(read=True)
    )).all())
    if platform in ASSET_REQUIRED_PLATFORMS and not assets:
        raise _problem(
            "geo_distribution_assets_unavailable",
            "小红书渠道稿尚无经审核的图片素材",
            409,
        )
    if len(assets) > 20 or sum(int(row.byte_size) for row in assets) > 100_000_000:
        raise _problem(
            "geo_distribution_asset_manifest_invalid",
            "GEO 图片素材数量或总量超出分发限制",
            409,
        )
    orders: set[int] = set()
    for row in assets:
        data = bytes(row.content_bytes or b"")
        created_at = _timestamp_revision(row.created_at)
        if (
            int(row.tenant_id) != int(task.tenant_id)
            or int(row.task_id) != int(task.id)
            or int(row.article_version_id) != int(article.id)
            or int(row.variant_id) != int(variant.id)
            or int(row.sort_order) in orders
            or not 0 <= int(row.sort_order) < 20
            or row.media_type not in {"image/png", "image/jpeg"}
            or int(row.byte_size) != len(data)
            or not data
            or len(data) > 20_000_000
            or hashlib.sha256(data).hexdigest() != str(row.sha256)
            or created_at <= 0
            or created_at > _timestamp_revision(task.reviewed_at)
        ):
            raise _problem(
                "geo_distribution_asset_manifest_invalid",
                "GEO 图片素材与当前审核版本不一致",
                409,
            )
        orders.add(int(row.sort_order))
    return assets


async def _current_actor(
    session: AsyncSession, actor_user_id: int, tenant_id: int
) -> User:
    user = await session.get(
        User, actor_user_id, populate_existing=True, with_for_update={"read": True}
    )
    if user is None or not user.is_active:
        raise _problem(
            "geo_distribution_actor_unavailable",
            "当前实名账号不可用，不能读取 GEO 分发来源",
            403,
        )
    if user.tenant_id not in {None, tenant_id}:
        raise _problem(
            "geo_distribution_tenant_forbidden",
            "当前账号无权读取该客户的 GEO 分发来源",
            403,
        )
    role = await session.get(
        Role, user.role_id, populate_existing=True, with_for_update={"read": True}
    )
    permissions = dict(role.permissions or {}) if role else {}
    if not (
        permissions.get("geo.assets") == "edit"
        and permissions.get("geo.content") == "edit"
    ):
        raise _problem(
            "geo_distribution_permission_revoked",
            "当前账号已无 GEO 资产及内容编辑权限",
            403,
        )
    return user


async def authorize_scope(
    session: AsyncSession,
    actor_user_id: int,
    tenant_id: int,
    scope_id: int,
) -> None:
    """Authorize a real current advisor for one active GEO project scope."""
    try:
        await ensure_geo_entitlement(
            session, int(tenant_id), allow_demo_read=False, lock_binding=True
        )
    except GeoEntitlementUnavailable as exc:
        raise _problem(
            "geo_distribution_entitlement_unavailable",
            "该客户的 GEO 服务当前不可用",
            403,
        ) from exc
    try:
        await project_scope(session, int(tenant_id), int(scope_id))
        project = await session.get(
            GeoProject,
            int(scope_id),
            populate_existing=True,
            with_for_update={"read": True},
        )
        if project is None or int(project.tenant_id) != int(tenant_id):
            raise HTTPException(404, "GEO 项目不存在")
        host_scope(project.canonical_domain)
    except HTTPException as exc:
        raise _problem(
            "geo_distribution_scope_mismatch",
            "当前 GEO 项目或网站业务范围不可用",
            404,
        ) from exc
    # Match the established tenant -> project -> user/role lock order used by
    # project mutations so authorization cannot create a cross-path deadlock.
    user = await _current_actor(session, int(actor_user_id), int(tenant_id))
    plan = plan_for(project)
    if (
        project.status != "active"
        or plan.get("status") != "active"
        or int(plan.get("advisor_user_id") or 0) != int(user.id)
        or not await advisor_available(
            session, int(tenant_id), int(user.id), lock=True
        )
    ):
        raise _problem(
            "geo_distribution_assignment_unavailable",
            "当前项目服务或顾问分配已变化，不能读取分发来源",
            403,
        )


async def load_source(
    session: AsyncSession,
    actor_user_id: int,
    tenant_id: int,
    scope_id: int,
    variant_id: int,
    platform: str,
) -> dict[str, Any]:
    """Return a freshly authorized immutable snapshot for shared distribution."""
    await authorize_scope(
        session, int(actor_user_id), int(tenant_id), int(scope_id)
    )
    platform_key = str(platform or "").strip().lower()
    channel = PLATFORM_CHANNELS.get(platform_key)
    if channel is None:
        raise _problem(
            "geo_distribution_platform_unsupported",
            "该分发平台尚未接入 GEO 来源适配器",
            422,
        )
    try:
        project, business_ids = await project_scope(
            session, int(tenant_id), int(scope_id)
        )
    except HTTPException as exc:
        raise _problem(
            "geo_distribution_scope_mismatch",
            "当前 GEO 项目或业务范围不可用",
            404,
        ) from exc
    variant = await session.get(GeoChannelVariant, int(variant_id), populate_existing=True)
    if variant is None:
        raise _problem(
            "geo_distribution_source_not_found", "GEO 分发来源不存在", 404
        )
    task = await session.get(
        GeoContentTask,
        int(variant.task_id),
        populate_existing=True,
        with_for_update=True,
    )
    if task is None or int(task.tenant_id) != int(tenant_id):
        raise _problem(
            "geo_distribution_source_not_found", "GEO 分发来源不存在", 404
        )
    variant = await session.get(
        GeoChannelVariant,
        int(variant_id),
        populate_existing=True,
        with_for_update={"read": True},
    )
    if variant is None or int(variant.task_id) != int(task.id):
        raise _problem(
            "geo_distribution_source_not_found", "GEO 分发来源不存在", 404
        )
    project_prompt_ids = set(
        await prompt_ids_for_businesses(session, int(tenant_id), business_ids)
    )
    if (
        task.business_id is None
        or int(task.business_id) not in set(business_ids)
        or int(task.prompt_id) not in project_prompt_ids
    ):
        raise _problem(
            "geo_distribution_scope_mismatch",
            "该稿件不属于当前 GEO 项目业务范围",
            404,
        )

    if str(variant.channel or "").strip().lower() != channel:
        raise _problem(
            "geo_distribution_platform_mismatch",
            "所选渠道稿与目标分发平台不匹配",
            409,
        )
    latest_variant_id = await session.scalar(
        select(GeoChannelVariant.id)
        .where(
            GeoChannelVariant.task_id == task.id,
            GeoChannelVariant.channel == channel,
        )
        .order_by(
            GeoChannelVariant.updated_at.desc().nullslast(),
            GeoChannelVariant.id.desc(),
        )
        .limit(1)
    )
    if latest_variant_id is None or int(latest_variant_id) != int(variant.id):
        raise _problem(
            "geo_distribution_variant_stale",
            "所选渠道稿不是当前最新版本，请重新创建分发任务",
            409,
        )

    article = await _latest_article(session, task.id, fresh=True)
    if article is None or int(variant.article_version_id) != int(article.id):
        raise _problem(
            "geo_distribution_master_stale",
            "渠道稿对应的母稿已更新，请重新生成并审校渠道稿",
            409,
        )
    if (
        task.review_status != "approved"
        or task.reviewed_by is None
        or task.reviewed_at is None
        or (
            article.created_at is not None
            and _timestamp_revision(task.reviewed_at)
            < _timestamp_revision(article.created_at)
        )
    ):
        raise _problem(
            "geo_distribution_publish_gate_blocked",
            "最新母稿尚未完成有效人工审核，请返回 GEO 工作台重新核验",
            409,
        )
    if variant.status not in {"draft", "exported", "published"}:
        raise _problem(
            "geo_distribution_variant_unavailable",
            "渠道稿当前状态不可用于分发",
            409,
        )
    title = str(variant.title or "").strip()
    body = str(variant.body_markdown or "").strip()
    if not title or not body:
        raise _problem(
            "geo_distribution_content_empty", "渠道稿内容不完整，不能用于分发", 409
        )
    meta = variant.adapt_meta if isinstance(variant.adapt_meta, dict) else {}
    if meta.get("publishable") is False or meta.get("quality") == "adapted_draft_not_publishable":
        raise _problem("geo_distribution_adaptation_pending", "渠道稿仍为预览稿，需要明确完成适配定版", 409)

    try:
        tenant = await _ensure_tenant_exists(session, int(tenant_id), fresh=True)
        brand, _ = await _brand_context_for_task(session, task, tenant, fresh=True)
        rule_input = await _build_rule_input(
            session, task, article, fresh=True, refresh_citations=False
        )
        assert_can_publish(
            rule_input,
            task=task,
            brand=brand,
        )
    except HTTPException as exc:
        raise _problem(
            "geo_distribution_source_invalid",
            "GEO 来源数据不完整，请返回 GEO 工作台核验",
            409,
        ) from exc
    except PublishGateError as exc:
        raise _problem(
            "geo_distribution_publish_gate_blocked",
            "稿件当前未满足 GEO 发布门禁，请返回 GEO 工作台重新核验",
            409,
        ) from exc

    assets = await _reviewed_assets(session, task, article, variant, platform_key)
    from app.geo.content.manual_finalization import assert_record_current
    assert_record_current(task, article, variant, rule_input.facts, assets, int(scope_id))
    revision = _source_revision(task, article, variant, assets)
    return {
        "module": "geo",
        "tenant_id": int(tenant_id),
        "scope_id": int(scope_id),
        "variant_id": int(variant.id),
        "source_revision": revision,
        "content": {
            "version": revision,
            "title": title,
            "body": body,
            "assets": [_asset_ref(row) for row in assets],
        },
    }


async def load_asset(
    session: AsyncSession,
    actor_user_id: int,
    tenant_id: int,
    scope_id: int,
    variant_id: int,
    platform: str,
    asset_id: str | int,
) -> bytes:
    """Load one exact reviewed asset after revalidating the entire source gate."""
    source = await load_source(
        session,
        int(actor_user_id),
        int(tenant_id),
        int(scope_id),
        int(variant_id),
        platform,
    )
    raw_id = str(asset_id)
    if raw_id.startswith("geo-asset-"):
        raw_id = raw_id.removeprefix("geo-asset-")
    try:
        numeric_id = int(raw_id)
    except (TypeError, ValueError) as exc:
        raise _problem("geo_distribution_asset_not_found", "GEO 图片素材不存在", 404) from exc
    expected = next(
        (row for row in source["content"]["assets"] if row["id"] == f"geo-asset-{numeric_id}"),
        None,
    )
    if expected is None:
        raise _problem("geo_distribution_asset_not_found", "GEO 图片素材不存在", 404)
    row = await session.get(
        GeoChannelAsset,
        numeric_id,
        populate_existing=True,
        with_for_update={"read": True},
    )
    if (
        row is None
        or int(row.tenant_id) != int(tenant_id)
        or int(row.variant_id) != int(variant_id)
    ):
        raise _problem("geo_distribution_asset_not_found", "GEO 图片素材不存在", 404)
    data = bytes(row.content_bytes or b"")
    if (
        len(data) != int(expected["bytes"])
        or hashlib.sha256(data).hexdigest() != expected["sha256"]
        or str(row.media_type) != expected["mediaType"]
    ):
        raise _problem(
            "geo_distribution_asset_manifest_invalid",
            "GEO 图片素材字节与审核清单不一致",
            409,
        )
    # Re-decode at the byte boundary as well as at ingestion.  This catches
    # database corruption and fails closed if another module made Pillow
    # accept truncated images process-wide.
    from app.geo.distribution_assets import decode_image

    media_type, _, _ = decode_image(data)
    if media_type != expected["mediaType"]:
        raise _problem(
            "geo_distribution_asset_manifest_invalid",
            "GEO 图片素材解码类型与审核清单不一致",
            409,
        )
    return data


async def list_sources(
    session: AsyncSession,
    actor_user_id: int,
    tenant_id: int,
    scope_id: int,
    platform: str,
) -> list[dict[str, Any]]:
    """List up to 50 current publishable summaries inside one authorized scope."""
    await authorize_scope(
        session, int(actor_user_id), int(tenant_id), int(scope_id)
    )
    platform_key = str(platform or "").strip().lower()
    channel = PLATFORM_CHANNELS.get(platform_key)
    if channel is None:
        raise _problem(
            "geo_distribution_platform_unsupported",
            "该分发平台尚未接入 GEO 来源适配器",
            422,
        )
    try:
        _, business_ids = await project_scope(
            session, int(tenant_id), int(scope_id)
        )
    except HTTPException as exc:
        raise _problem(
            "geo_distribution_scope_mismatch",
            "当前 GEO 项目或业务范围不可用",
            404,
        ) from exc
    prompt_ids = await prompt_ids_for_businesses(
        session, int(tenant_id), business_ids
    )
    ranked = select(
        GeoChannelVariant.id.label("variant_id"),
        func.row_number().over(
            partition_by=GeoChannelVariant.task_id,
            order_by=(
                GeoChannelVariant.updated_at.desc().nullslast(),
                GeoChannelVariant.id.desc(),
            ),
        ).label("position"),
    ).join(
        GeoContentTask, GeoContentTask.id == GeoChannelVariant.task_id
    ).where(
        GeoContentTask.tenant_id == int(tenant_id),
        GeoContentTask.business_id.in_(business_ids or [-1]),
        GeoContentTask.prompt_id.in_(prompt_ids or [-1]),
        GeoChannelVariant.channel == channel,
    ).subquery()
    candidate_ids = list(await session.scalars(
        select(ranked.c.variant_id)
        .where(ranked.c.position == 1)
        .order_by(ranked.c.variant_id.desc())
        .limit(50)
    ))
    results: list[dict[str, Any]] = []
    for candidate_id in candidate_ids:
        try:
            source = await load_source(
                session,
                int(actor_user_id),
                int(tenant_id),
                int(scope_id),
                int(candidate_id),
                platform_key,
            )
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            if detail.get("code") in _LIST_SKIPPABLE_CODES:
                continue
            raise
        results.append({
            "variant_id": source["variant_id"],
            "source_revision": source["source_revision"],
            "title": source["content"]["title"],
            "platform": platform_key,
        })
    return results


_INTAKE_ADAPTATION_CODES = frozenset({
    "geo_distribution_master_stale", "geo_distribution_content_empty",
    "geo_distribution_source_invalid", "geo_distribution_publish_gate_blocked",
    "geo_distribution_assets_unavailable", "geo_distribution_asset_manifest_invalid",
    "geo_distribution_adaptation_pending", "geo_distribution_manual_finalization_invalid",
})
_INTAKE_VERSION = re.compile(r"[A-Za-z0-9_-]{1,100}\Z", re.ASCII)


def _intake_unavailable() -> HTTPException:
    return _problem("geo_distribution_intake_unavailable", "GEO 成稿候选暂不可读取", 503)


def _draft_version(variant: GeoChannelVariant, assets: list[GeoChannelAsset]) -> str:
    # Content identity deliberately excludes approval, row timestamps, asset IDs
    # and delivery/monitor metadata. Re-approval updates the same queue intent.
    value = {
        "channel": variant.channel, "title": variant.title,
        "body": variant.body_markdown,
        "assets": [{"order": row.sort_order, "media_type": row.media_type,
            "bytes": len(bytes(row.content_bytes or b"")),
            "sha256": hashlib.sha256(bytes(row.content_bytes or b"")).hexdigest()}
            for row in assets],
    }
    digest = hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()
    return "geo-draft-v1-" + digest


def _intake_blocker(task, article, variant) -> tuple[str, str] | None:
    if article is None or variant.article_version_id != article.id:
        return "awaiting-adaptation", "geo_distribution_master_stale"
    if not str(variant.title or "").strip() or not str(variant.body_markdown or "").strip():
        return "awaiting-adaptation", "geo_distribution_content_empty"
    from app.geo.content.manual_finalization import record_valid
    if not record_valid(task, article, variant, allow_pending=True):
        return "awaiting-adaptation", "geo_distribution_manual_finalization_invalid"
    meta = variant.adapt_meta
    if meta is not None and not isinstance(meta, dict):
        return "awaiting-adaptation", "geo_distribution_adaptation_invalid"
    if isinstance(meta, dict) and (meta.get("publishable") is False
            or meta.get("quality") == "adapted_draft_not_publishable"):
        return "awaiting-adaptation", "geo_distribution_adaptation_pending"
    review = task.review_status
    if review != "approved":
        reason = {"none": "geo_distribution_review_not_submitted",
            "pending": "geo_distribution_review_pending",
            "rejected": "geo_distribution_review_rejected"}.get(review,
                "geo_distribution_review_invalid")
        return "awaiting-review", reason
    if (task.reviewed_by is None or task.reviewed_at is None
            or (article.created_at is not None
                and _timestamp_revision(task.reviewed_at) < _timestamp_revision(article.created_at))):
        return "awaiting-review", "geo_distribution_review_invalid"
    return None


async def list_intake_candidates(
    session: AsyncSession,
    actor_user_id: int,
    tenant_id: int,
    scope_id: int,
    platform: str,
    *,
    after_variant_id: int | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Page committed completed drafts; readiness never authorizes publishing.

    A temporary identity map on the existing connection ignores caller ORM
    edits and supports a single-connection pool and already-held native locks.
    Its own savepoint is rolled back on close, preserving the caller transaction.
    Caller contract: a short READ COMMITTED transaction without already-flushed
    or SQL-written native changes. Central queue/config writes are allowed;
    native editing must be committed/rolled back before scanning.
    """
    if any(type(value) is not int or value <= 0 for value in (actor_user_id, tenant_id, scope_id)):
        raise _problem("geo_distribution_intake_forbidden", "当前身份或客户项目范围无效", 403)
    if (type(limit) is not int or not 1 <= limit <= 50
            or (after_variant_id is not None
                and (type(after_variant_id) is not int or after_variant_id <= 0))):
        raise _problem("geo_distribution_intake_page_invalid", "候选分页参数无效", 422)
    platform_key = platform.strip().lower() if isinstance(platform, str) else ""
    channel = PLATFORM_CHANNELS.get(platform_key)
    if channel is None:
        raise _problem("geo_distribution_platform_unsupported", "该分发平台尚未接入 GEO 来源适配器", 422)
    try:
        with session.no_autoflush:
            connection = await session.connection()
        async with AsyncSession(bind=connection, autoflush=False, expire_on_commit=False,
                join_transaction_mode="create_savepoint") as read:
            await read.execute(text("SET LOCAL lock_timeout = '3000ms'"))
            await read.execute(text("SET LOCAL statement_timeout = '15000ms'"))
            await authorize_scope(read, actor_user_id, tenant_id, scope_id)
            _, business_ids = await project_scope(read, tenant_id, scope_id)
            prompt_ids = await prompt_ids_for_businesses(read, tenant_id, business_ids)
            ranked = select(GeoChannelVariant.id.label("variant_id"),
                func.row_number().over(partition_by=GeoChannelVariant.task_id,
                    order_by=(GeoChannelVariant.updated_at.desc().nullslast(),
                        GeoChannelVariant.id.desc())).label("position"),
            ).join(GeoContentTask, GeoContentTask.id == GeoChannelVariant.task_id).where(
                GeoContentTask.tenant_id == tenant_id,
                GeoContentTask.business_id.in_(business_ids or [-1]),
                GeoContentTask.prompt_id.in_(prompt_ids or [-1]),
                GeoChannelVariant.channel == channel,
            ).subquery()
            # Rank before filtering completion, so a generating latest row
            # cannot resurrect an older completed variant.
            ids = list(await read.scalars(select(GeoChannelVariant.id).join(
                ranked, ranked.c.variant_id == GeoChannelVariant.id).join(
                GeoContentTask, GeoContentTask.id == GeoChannelVariant.task_id).where(
                ranked.c.position == 1,
                GeoChannelVariant.id > (after_variant_id or 0),
                GeoChannelVariant.status.in_(("draft", "exported", "published")),
                GeoContentTask.status.notin_(("generating", "adapting", "archived", "cancelled")),
            ).order_by(GeoChannelVariant.id).limit(limit + 1)))
            items = []
            for variant_id in ids[:limit]:
                variant = await read.get(GeoChannelVariant, variant_id)
                task = await read.get(GeoContentTask, variant.task_id)
                article = await _latest_article(read, task.id, fresh=True)
                blocker = _intake_blocker(task, article, variant)
                source_revision = None
                if blocker is None:
                    try:
                        source = await load_source(read, actor_user_id, tenant_id,
                            scope_id, variant_id, platform_key)
                    except HTTPException as exc:
                        # Legacy source helpers may wrap an HTTP infrastructure
                        # error in a 409. Do not convert its cause into readiness.
                        cause = exc.__cause__
                        while cause is not None:
                            if isinstance(cause, HTTPException) and (
                                    cause.status_code in {401, 403} or cause.status_code >= 500):
                                raise cause
                            cause = cause.__cause__
                        detail = exc.detail if isinstance(exc.detail, dict) else {}
                        code = detail.get("code")
                        if exc.status_code != 409 or code not in _INTAKE_ADAPTATION_CODES:
                            raise
                        blocker = "awaiting-adaptation", code
                    else:
                        source_revision = source["source_revision"]
                        if not isinstance(source_revision, str) or not _INTAKE_VERSION.fullmatch(source_revision):
                            raise _intake_unavailable()
                # Preserve staged pure-article rollout: WeChat neither ships
                # images through this adapter nor requires the optional table.
                assets = []
                if platform_key in ASSET_REQUIRED_PLATFORMS:
                    assets = list(await read.scalars(select(GeoChannelAsset).where(
                        GeoChannelAsset.variant_id == variant_id).order_by(
                            GeoChannelAsset.sort_order, GeoChannelAsset.id)))
                meta = variant.adapt_meta if isinstance(variant.adapt_meta, dict) else {}
                if "manual_finalization" in meta:
                    from app.geo.content.routes import _task_facts, _fact_dicts
                    from app.geo.content.manual_finalization import digest, asset_digest
                    rec = meta.get("manual_finalization") or {}
                    facts = _fact_dicts(await _task_facts(read, task.id, fresh=True))
                    if rec.get("facts_digest") != digest(facts) or rec.get("assets_digest") != asset_digest(assets):
                        blocker = "awaiting-adaptation", "geo_distribution_manual_finalization_invalid"
                        source_revision = None
                readiness, reason = blocker or ("ready", "geo_distribution_source_ready")
                items.append({"variant_id": int(variant_id),
                    "draft_version": _draft_version(variant, assets),
                    "source_revision": source_revision, "readiness": readiness, "reason": reason})
            return {"items": items, "next_cursor": int(ids[limit - 1]) if len(ids) > limit else None}
    except HTTPException as exc:
        if exc.status_code >= 500:
            raise _intake_unavailable() from exc
        raise
    except (SQLAlchemyError, AttributeError, KeyError, TypeError, ValueError, OverflowError, OSError) as exc:
        raise _intake_unavailable() from exc


async def load_intake_candidate(
    session: AsyncSession,
    actor_user_id: int,
    tenant_id: int,
    scope_id: int,
    variant_id: int,
    platform: str,
) -> dict[str, Any] | None:
    """Recheck one queue intent, preserving pending metadata and auth failures."""
    if type(variant_id) is not int or variant_id <= 0:
        raise _problem("geo_distribution_intake_page_invalid", "渠道成稿 ID 无效", 422)
    page = await list_intake_candidates(session, actor_user_id, tenant_id, scope_id,
        platform, after_variant_id=variant_id - 1 if variant_id > 1 else None, limit=1)
    item = next(iter(page["items"]), None)
    return item if item is not None and item["variant_id"] == variant_id else None
