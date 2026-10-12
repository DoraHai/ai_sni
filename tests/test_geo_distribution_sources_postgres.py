"""Isolated PostgreSQL proofs for the trusted GEO distribution source."""
import asyncio
import base64
from datetime import datetime, timedelta
from io import BytesIO
import os
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from PIL import Image, ImageFile

from app.geo.distribution_assets import decode_image, remove_asset, store_asset
from app.geo.distribution_sources import authorize_scope, list_sources, load_asset, load_source
from app.geo.content.gate import PublishGateError
from app.geo.project_scope import set_binding
from app.geo.project_workflows import save_plan
from app.models import GeoArticleVersion, GeoChannelAsset, GeoChannelVariant, GeoContentTask, GeoProject
from app.models.role import Role
from app.models.user import User
from test_geo_project_scope_postgres import database

pytestmark = pytest.mark.skipif(
    not os.getenv("GEO_TEST_POSTGRES_URL"), reason="requires dedicated PostgreSQL"
)


async def prepared(sessions):
    async with sessions() as db:
        await set_binding(db, 1, 10, [20], 0, 7)
        await save_plan(db, 1, 10, {
            "enabled": False,
            "status": "active",
            "prompt_ids": [40],
            "interval_days": 7,
            "advisor_user_id": 7,
        }, 0, 7)
        task = await db.get(GeoContentTask, 50)
        task.business_id = 20
        task.title = "GEO trusted source"
        task.status = "ready"
        task.target_channels = ["wechat"]
        task.review_status = "approved"
        task.reviewed_by = 12
        task.reviewed_at = datetime(2026, 10, 11, 8, 0, 0)
        task.rule_result = {"geo_score": 90}
        article = GeoArticleVersion(
            id=90,
            task_id=50,
            version_no=3,
            kind="master",
            title="Approved master",
            body_markdown="Approved master body",
            outline={},
            author_name="fixture author",
            created_by=7,
            created_at=datetime(2026, 10, 11, 8, 0, 0),
        )
        variant = GeoChannelVariant(
            id=91,
            task_id=50,
            article_version_id=90,
            channel="wechat",
            title="Approved WeChat title",
            body_markdown="Approved WeChat body",
            status="exported",
            adapt_meta={},
            created_at=datetime(2026, 10, 11, 8, 1, 0),
            updated_at=datetime(2026, 10, 11, 8, 1, 0),
        )
        db.add_all([article, variant])
        await db.commit()


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def jpeg_1x1() -> bytes:
    output = BytesIO()
    Image.new("RGB", (1, 1), (255, 0, 0)).save(output, format="JPEG")
    return output.getvalue()


async def prepared_xiaohongshu(sessions) -> tuple[int, str]:
    await prepared(sessions)
    async with sessions() as db:
        db.add(GeoChannelVariant(
            id=92, task_id=50, article_version_id=90, channel="xiaohongshu",
            title="Approved RED title", body_markdown="Approved RED body",
            status="exported", adapt_meta={},
            created_at=datetime(2026, 10, 11, 8, 2, 0),
            updated_at=datetime(2026, 10, 11, 8, 2, 0),
        ))
        await db.commit()
    async with sessions() as db:
        row = await store_asset(db, 7, 1, 10, 92, 0, PNG_1X1)
        asset_id, digest = int(row.id), row.sha256
        task = await db.get(GeoContentTask, 50)
        assert task.review_status == "none" and task.reviewed_at is None
        task.review_status = "approved"
        task.reviewed_by = 12
        task.reviewed_at = row.created_at + timedelta(minutes=1)
        await db.commit()
    return asset_id, digest


def code(exc: HTTPException) -> str:
    assert isinstance(exc.detail, dict)
    return exc.detail["code"]


def test_loads_current_approved_wechat_source_from_database():
    async def scenario():
        async with database() as sessions:
            await prepared(sessions)
            async with sessions() as db:
                assert await authorize_scope(db, 7, 1, 10) is None
            with patch("app.geo.distribution_sources.assert_can_publish") as gate:
                async with sessions() as db:
                    result = await load_source(db, 7, 1, 10, 91, "wechat-article")
            assert gate.call_count == 1
            assert result["module"] == "geo"
            assert result["tenant_id"] == 1 and result["scope_id"] == 10
            assert result["variant_id"] == 91
            assert result["content"] == {
                "version": result["source_revision"],
                "title": "Approved WeChat title",
                "body": "Approved WeChat body",
                "assets": [],
            }
            assert result["source_revision"].startswith("geo-a90-v3-c91-r")
            assert all(ch.isalnum() or ch == "-" for ch in result["source_revision"])

            # A fresh customer re-approval is part of the immutable revision.
            async with sessions() as db:
                task = await db.get(GeoContentTask, 50)
                task.reviewed_at = task.reviewed_at + timedelta(minutes=1)
                await db.commit()
            with patch("app.geo.distribution_sources.assert_can_publish"):
                async with sessions() as db:
                    changed = await load_source(db, 7, 1, 10, 91, "wechat-article")
            assert changed["source_revision"] != result["source_revision"]
    asyncio.run(scenario())


def test_current_database_identity_permission_tenant_and_assignment_are_required():
    async def scenario():
        async with database() as sessions:
            await prepared(sessions)
            async with sessions() as db:
                role = await db.get(Role, 5)
                role.permissions = {"geo.assets": "view", "geo.content": "view"}
                await db.commit()
            with patch("app.geo.distribution_sources.assert_can_publish"):
                async with sessions() as db:
                    with pytest.raises(HTTPException) as revoked:
                        await load_source(db, 7, 1, 10, 91, "wechat-article")
            assert revoked.value.status_code == 403
            assert code(revoked.value) == "geo_distribution_permission_revoked"

            async with sessions() as db:
                role = await db.get(Role, 5)
                role.permissions = {"geo.assets": "edit", "geo.content": "edit"}
                user = await db.get(User, 7)
                user.tenant_id = 2
                await db.commit()
            async with sessions() as db:
                with pytest.raises(HTTPException) as tenant:
                    await load_source(db, 7, 1, 10, 91, "wechat-article")
            assert code(tenant.value) == "geo_distribution_tenant_forbidden"

            async with sessions() as db:
                user = await db.get(User, 7)
                user.tenant_id = None
                project = await db.get(GeoProject, 10)
                settings = dict(project.project_settings or {})
                plan = dict(settings["geo_service_plan"])
                plan["advisor_user_id"] = 999
                settings["geo_service_plan"] = plan
                project.project_settings = settings
                await db.commit()
            async with sessions() as db:
                with pytest.raises(HTTPException) as assignment:
                    await load_source(db, 7, 1, 10, 91, "wechat-article")
            assert code(assignment.value) == "geo_distribution_assignment_unavailable"
            async with sessions() as db:
                with pytest.raises(HTTPException) as scope_auth:
                    await authorize_scope(db, 7, 1, 10)
            assert code(scope_auth.value) == "geo_distribution_assignment_unavailable"
    asyncio.run(scenario())


def test_stale_master_review_gate_and_project_scope_fail_closed():
    async def scenario():
        async with database() as sessions:
            await prepared(sessions)
            async with sessions() as db:
                db.add(GeoArticleVersion(
                    id=92, task_id=50, version_no=4, kind="master",
                    title="new master", body_markdown="new master body",
                    outline={}, author_name="fixture", created_by=7,
                    created_at=datetime(2026, 10, 11, 9, 0, 0),
                ))
                await db.commit()
            with patch("app.geo.distribution_sources.assert_can_publish"):
                async with sessions() as db:
                    with pytest.raises(HTTPException) as stale:
                        await load_source(db, 7, 1, 10, 91, "wechat-article")
            assert code(stale.value) == "geo_distribution_master_stale"

            async with sessions() as db:
                article = await db.get(GeoArticleVersion, 92)
                variant = await db.get(GeoChannelVariant, 91)
                variant.article_version_id = article.id
                task = await db.get(GeoContentTask, 50)
                task.review_status = "none"
                task.reviewed_at = None
                await db.commit()
            with patch(
                "app.geo.distribution_sources.assert_can_publish",
                side_effect=PublishGateError("review revoked"),
            ):
                async with sessions() as db:
                    with pytest.raises(HTTPException) as gate:
                        await load_source(db, 7, 1, 10, 91, "wechat-article")
            assert code(gate.value) == "geo_distribution_publish_gate_blocked"
            assert "review revoked" not in gate.value.detail["message"]

            async with sessions() as db:
                with pytest.raises(HTTPException) as scope:
                    await load_source(db, 7, 1, 11, 91, "wechat-article")
            assert code(scope.value) == "geo_distribution_assignment_unavailable"
    asyncio.run(scenario())


def test_latest_channel_and_unsupported_or_asset_platforms_are_explicit():
    async def scenario():
        async with database() as sessions:
            await prepared(sessions)
            async with sessions() as db:
                db.add(GeoChannelVariant(
                    id=93, task_id=50, article_version_id=90, channel="wechat",
                    title="newer", body_markdown="newer body", status="exported",
                    adapt_meta={}, created_at=datetime(2026, 10, 11, 8, 2, 0),
                    updated_at=datetime(2026, 10, 11, 8, 2, 0),
                ))
                await db.commit()
            with patch("app.geo.distribution_sources.assert_can_publish"):
                async with sessions() as db:
                    with pytest.raises(HTTPException) as stale:
                        await load_source(db, 7, 1, 10, 91, "wechat-article")
            assert code(stale.value) == "geo_distribution_variant_stale"

            async with sessions() as db:
                with pytest.raises(HTTPException) as assets:
                    await load_source(db, 7, 1, 10, 91, "xiaohongshu-image")
                with pytest.raises(HTTPException) as unsupported:
                    await load_source(db, 7, 1, 10, 91, "unknown")
            assert code(assets.value) == "geo_distribution_platform_mismatch"
            assert code(unsupported.value) == "geo_distribution_platform_unsupported"
    asyncio.run(scenario())


def test_lists_only_latest_ready_summaries_inside_authorized_scope():
    async def scenario():
        async with database() as sessions:
            await prepared(sessions)
            async with sessions() as db:
                # A newer approved channel revision replaces variant 91.
                db.add(GeoChannelVariant(
                    id=93, task_id=50, article_version_id=90, channel="wechat",
                    title="latest approved", body_markdown="latest approved body",
                    status="exported", adapt_meta={},
                    created_at=datetime(2026, 10, 11, 8, 2, 0),
                    updated_at=datetime(2026, 10, 11, 8, 2, 0),
                ))
                # Same project scope but no human approval: must be skipped.
                db.add(GeoContentTask(
                    id=55, tenant_id=1, prompt_id=40, business_id=20,
                    title="unapproved", status="ready", target_channels=["wechat"],
                    pipeline_step="review", review_status="none",
                ))
                db.add(GeoArticleVersion(
                    id=94, task_id=55, version_no=1, kind="master",
                    title="unapproved", body_markdown="unapproved body", outline={},
                    author_name="fixture", created_by=7,
                    created_at=datetime(2026, 10, 11, 8, 3, 0),
                ))
                db.add(GeoChannelVariant(
                    id=95, task_id=55, article_version_id=94, channel="wechat",
                    title="must not leak", body_markdown="must not leak body",
                    status="exported", adapt_meta={},
                    created_at=datetime(2026, 10, 11, 8, 4, 0),
                    updated_at=datetime(2026, 10, 11, 8, 4, 0),
                ))
                # Tenant-local but outside project 10's business binding.
                task = await db.get(GeoContentTask, 51)
                task.review_status = "approved"
                task.reviewed_by = 12
                task.reviewed_at = datetime(2026, 10, 11, 8, 6, 0)
                db.add(GeoArticleVersion(
                    id=96, task_id=51, version_no=1, kind="master",
                    title="outside", body_markdown="outside body", outline={},
                    author_name="fixture", created_by=7,
                    created_at=datetime(2026, 10, 11, 8, 5, 0),
                ))
                db.add(GeoChannelVariant(
                    id=97, task_id=51, article_version_id=96, channel="wechat",
                    title="outside scope", body_markdown="outside scope body",
                    status="exported", adapt_meta={},
                    created_at=datetime(2026, 10, 11, 8, 5, 0),
                    updated_at=datetime(2026, 10, 11, 8, 5, 0),
                ))
                await db.commit()
            with patch("app.geo.distribution_sources.assert_can_publish"):
                async with sessions() as db:
                    rows = await list_sources(db, 7, 1, 10, "wechat-article")
            assert len(rows) == 1
            assert rows[0]["variant_id"] == 93
            assert rows[0]["title"] == "latest approved"
            assert rows[0]["platform"] == "wechat-article"
            assert set(rows[0]) == {
                "variant_id", "source_revision", "title", "platform"
            }
            assert "body" not in rows[0]
            async with sessions() as db:
                assert await list_sources(db, 7, 1, 10, "xiaohongshu-image") == []

            async with sessions() as db:
                role = await db.get(Role, 5)
                role.permissions = {"geo.assets": "view", "geo.content": "view"}
                await db.commit()
            async with sessions() as db:
                with pytest.raises(HTTPException) as denied:
                    await list_sources(db, 7, 1, 10, "wechat-article")
            assert code(denied.value) == "geo_distribution_permission_revoked"
    asyncio.run(scenario())


def test_xiaohongshu_manifest_bytes_and_revision_are_immutable_and_ordered():
    async def scenario():
        async with database() as sessions:
            asset_id, digest = await prepared_xiaohongshu(sessions)
            with patch("app.geo.distribution_sources.assert_can_publish") as gate:
                async with sessions() as db:
                    source = await load_source(db, 7, 1, 10, 92, "xiaohongshu-image")
                    loaded = await load_asset(
                        db, 7, 1, 10, 92, "xiaohongshu-image", f"geo-asset-{asset_id}"
                    )
                    listed = await list_sources(db, 7, 1, 10, "xiaohongshu-image")
            assert gate.call_count == 3
            assert loaded == PNG_1X1
            assert listed == [{
                "variant_id": 92,
                "source_revision": source["source_revision"],
                "title": "Approved RED title",
                "platform": "xiaohongshu-image",
            }]
            assert source["content"]["assets"] == [{
                "id": f"geo-asset-{asset_id}",
                "sha256": digest,
                "mediaType": "image/png",
                "bytes": len(PNG_1X1),
            }]
            before = source["source_revision"]

            previous = ImageFile.LOAD_TRUNCATED_IMAGES
            try:
                ImageFile.LOAD_TRUNCATED_IMAGES = True
                with patch("app.geo.distribution_sources.assert_can_publish"):
                    async with sessions() as db:
                        with pytest.raises(HTTPException) as unsafe:
                            await load_asset(
                                db, 7, 1, 10, 92, "xiaohongshu-image",
                                f"geo-asset-{asset_id}",
                            )
                assert unsafe.value.status_code == 503
                assert code(unsafe.value) == "geo_distribution_image_decoder_unsafe"
            finally:
                ImageFile.LOAD_TRUNCATED_IMAGES = previous

            # Tampered bytes fail closed even when stale digest/size metadata remain.
            async with sessions() as db:
                row = await db.get(GeoChannelAsset, asset_id)
                row.content_bytes = PNG_1X1[:-1] + b"x"
                await db.commit()
            with patch("app.geo.distribution_sources.assert_can_publish"):
                async with sessions() as db:
                    with pytest.raises(HTTPException) as tampered:
                        await load_source(db, 7, 1, 10, 92, "xiaohongshu-image")
            assert code(tampered.value) == "geo_distribution_asset_manifest_invalid"

            # Restore bytes, then a material change invalidates approval immediately.
            async with sessions() as db:
                row = await db.get(GeoChannelAsset, asset_id)
                row.content_bytes = PNG_1X1
                await db.commit()
                await remove_asset(db, 7, 1, 10, 92, asset_id)
                await db.commit()
                task = await db.get(GeoContentTask, 50)
                assert task.review_status == "none" and task.reviewed_at is None
            with patch("app.geo.distribution_sources.assert_can_publish"):
                async with sessions() as db:
                    with pytest.raises(HTTPException) as revoked:
                        await load_source(db, 7, 1, 10, 92, "xiaohongshu-image")
            assert code(revoked.value) == "geo_distribution_publish_gate_blocked"
            assert before.startswith("geo-a90-v3-c92-r")
    asyncio.run(scenario())


def test_asset_ingress_requires_real_bounded_png_or_jpeg_and_no_url_or_path():
    assert decode_image(PNG_1X1) == ("image/png", 1, 1)
    jpeg = jpeg_1x1()
    assert decode_image(jpeg) == ("image/jpeg", 1, 1)
    for payload in (
        b"\x89PNG\r\n\x1a\nnot decoded",
        jpeg[:-2],
        b"https://127.0.0.1/private/image.png",
        b"C:\\secret\\customer.jpg",
    ):
        with pytest.raises(HTTPException) as invalid:
            decode_image(payload)
        assert code(invalid.value) == "geo_distribution_asset_decode_failed"


def test_asset_decode_fails_closed_when_pillow_truncated_mode_is_enabled():
    previous = ImageFile.LOAD_TRUNCATED_IMAGES
    try:
        ImageFile.LOAD_TRUNCATED_IMAGES = True
        with pytest.raises(HTTPException) as unsafe:
            decode_image(PNG_1X1)
        assert unsafe.value.status_code == 503
        assert code(unsafe.value) == "geo_distribution_image_decoder_unsafe"
    finally:
        ImageFile.LOAD_TRUNCATED_IMAGES = previous
