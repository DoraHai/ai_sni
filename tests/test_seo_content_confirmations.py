import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.seo import (
    ContentConfirmationRequest,
    ContentReviewSubmit,
    SeoServicePlanUpdate,
    _content_allowed_actions,
    _content_confirmation_hash,
    _content_confirmation_status,
    _publication_attempt_requires_manual_check,
    _require_active_content_confirmation,
    create_content_confirmation,
    submit_content_review,
    update_seo_service_plan,
)
from app.models.seo import SeoContentAsset, SeoContentConfirmation, SeoPublishAttempt
from app.security.auth import AuthContext, _required


def _content(**overrides) -> SeoContentAsset:
    values = {
        "id": 88,
        "tenant_id": 1,
        "site_id": 9,
        "title": "准确版本稿件",
        "content_type": "article",
        "draft": "<p>正文</p>",
        "status": "ready",
        "version_count": 3,
    }
    values.update(overrides)
    return SeoContentAsset(**values)


def _ctx(*, tenant_id=None, permission="edit") -> AuthContext:
    return AuthContext(
        user_id=7,
        username="actor",
        role_name="数据库角色",
        tenant_id=tenant_id,
        permissions={"seo.content": permission},
    )


def test_confirmation_hash_and_status_are_bound_to_exact_customer_payload() -> None:
    row = _content()
    digest = _content_confirmation_hash(row)
    confirmation = SeoContentConfirmation(
        tenant_id=1,
        site_id=9,
        content_asset_id=88,
        content_version=3,
        content_hash=digest,
        decision="approve",
        actor_mode="customer_direct",
        actor_user_id=11,
        actor_role_name="客户",
    )

    assert len(digest) == 64
    assert _content_confirmation_status(row, confirmation) == "approved"

    row.title = "修改后的稿件"
    assert _content_confirmation_hash(row) != digest
    assert _content_confirmation_status(row, confirmation) == "stale"


def test_global_content_editor_is_not_implicitly_an_assigned_advisor() -> None:
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=None)

    with patch("app.api.seo._content_confirmation_schema_ready", new=AsyncMock(return_value=True)):
        actions, basis = asyncio.run(
            _content_allowed_actions(session, _content(), _ctx(tenant_id=None), "pending")
        )

    assert actions["confirm_as_advisor_proxy"] is False
    assert actions["confirm_as_customer"] is False
    assert basis["active_site_advisor_assignment"] is False
    assert basis["tenant_bound_customer_account"] is False


def test_tenant_bound_customer_editor_is_not_treated_as_advisor_without_assignment() -> None:
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=None)

    actions, basis = asyncio.run(
        _content_allowed_actions(session, _content(), _ctx(tenant_id=1), "pending")
    )

    assert actions["confirm_as_customer"] is True
    assert actions["confirm_as_advisor_proxy"] is False
    assert basis["tenant_bound_customer_account"] is True
    assert basis["active_site_advisor_assignment"] is False


def test_active_site_assignment_and_edit_permission_enable_advisor_proxy() -> None:
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=SimpleNamespace(id=4, active=True))

    with patch("app.api.seo._content_confirmation_schema_ready", new=AsyncMock(return_value=True)):
        actions, basis = asyncio.run(
            _content_allowed_actions(session, _content(), _ctx(tenant_id=None), "pending")
        )

    assert actions["confirm_as_advisor_proxy"] is True
    assert actions["confirm_as_customer"] is False
    assert basis["active_site_advisor_assignment"] is True


def test_customer_content_editor_cannot_claim_advisor_proxy_without_assignment() -> None:
    row = _content()
    session = AsyncMock()
    session.get = AsyncMock(return_value=row)
    session.scalar = AsyncMock(return_value=None)
    request = ContentConfirmationRequest(
        version_count=3,
        payload_hash=_content_confirmation_hash(row),
        decision="approve",
        actor_mode="advisor_proxy",
    )

    with (
        patch("app.api.seo._content_confirmation_schema_ready", new=AsyncMock(return_value=True)),
        patch("app.api.seo._require_resource_operational_site", new=AsyncMock()),
    ):
        with pytest.raises(HTTPException) as raised:
            asyncio.run(
                create_content_confirmation(88, 1, request, session, _ctx(tenant_id=1))
            )

    assert raised.value.status_code == 403
    assert "已分配" in raised.value.detail
    session.commit.assert_not_awaited()


def test_assigned_tenant_editor_cannot_masquerade_as_customer_direct() -> None:
    row = _content()
    session = AsyncMock()
    session.get = AsyncMock(return_value=row)
    session.scalar = AsyncMock(return_value=SimpleNamespace(id=4, active=True))
    request = ContentConfirmationRequest(
        version_count=3,
        payload_hash=_content_confirmation_hash(row),
        decision="approve",
        actor_mode="customer_direct",
    )

    with (
        patch("app.api.seo._content_confirmation_schema_ready", new=AsyncMock(return_value=True)),
        patch("app.api.seo._require_resource_operational_site", new=AsyncMock()),
    ):
        with pytest.raises(HTTPException) as raised:
            asyncio.run(
                create_content_confirmation(88, 1, request, session, _ctx(tenant_id=1))
            )

    assert raised.value.status_code == 403
    assert "顾问代确认模式" in raised.value.detail
    session.commit.assert_not_awaited()


def test_assigned_advisor_proxy_confirmation_records_real_actor_and_exact_version() -> None:
    row = _content()
    assignment = SimpleNamespace(id=4, active=True)
    actor = SimpleNamespace(id=7, display_name="真实顾问", username="advisor")
    session = AsyncMock()
    session.add = MagicMock()
    session.get = AsyncMock(side_effect=[row, actor])
    session.scalar = AsyncMock(side_effect=[assignment, None, assignment])
    request = ContentConfirmationRequest(
        version_count=3,
        payload_hash=_content_confirmation_hash(row),
        decision="approve",
        actor_mode="advisor_proxy",
        note="已与客户线下确认",
    )

    with (
        patch("app.api.seo._content_confirmation_schema_ready", new=AsyncMock(return_value=True)),
        patch("app.api.seo._require_resource_operational_site", new=AsyncMock()),
    ):
        result = asyncio.run(
            create_content_confirmation(88, 1, request, session, _ctx(tenant_id=None))
        )

    confirmation = next(
        call.args[0]
        for call in session.add.call_args_list
        if isinstance(call.args[0], SeoContentConfirmation)
    )
    assert confirmation.actor_user_id == 7
    assert confirmation.actor_mode == "advisor_proxy"
    assert confirmation.actor_role_name == "数据库角色"
    assert confirmation.content_version == 3
    assert confirmation.content_hash == _content_confirmation_hash(row)
    assert result["confirmation"]["status"] == "approved"
    assert result["confirmation"]["latest"]["actor_name"] == "真实顾问"
    assert result["allowed_actions"]["start_publication"] is True
    session.commit.assert_awaited_once()


def test_confirmation_rejects_stale_version_and_returns_current_contract() -> None:
    row = _content(version_count=4)
    session = AsyncMock()
    session.get = AsyncMock(return_value=row)
    request = ContentConfirmationRequest(
        version_count=3,
        payload_hash="0" * 64,
        decision="approve",
        actor_mode="customer_direct",
    )

    with (
        patch("app.api.seo._content_confirmation_schema_ready", new=AsyncMock(return_value=True)),
        patch("app.api.seo._require_resource_operational_site", new=AsyncMock()),
    ):
        with pytest.raises(HTTPException) as raised:
            asyncio.run(
                create_content_confirmation(88, 1, request, session, _ctx(tenant_id=1))
            )

    assert raised.value.status_code == 409
    assert raised.value.detail["code"] == "content_version_conflict"
    assert raised.value.detail["current_version"] == 4
    assert len(raised.value.detail["current_payload_hash"]) == 64


def test_review_accepts_expected_version_and_rejects_stale_workbench_request() -> None:
    row = _content(status="drafting", keyword_id=6, version_count=2)
    session = AsyncMock()
    session.get = AsyncMock(return_value=row)

    with patch("app.api.seo._require_resource_operational_site", new=AsyncMock()):
        with pytest.raises(HTTPException) as raised:
            asyncio.run(
                submit_content_review(
                    88,
                    1,
                    ContentReviewSubmit(version_count=1),
                    session,
                    _ctx(tenant_id=1),
                )
            )

    assert raised.value.status_code == 409
    assert raised.value.detail["code"] == "content_version_conflict"
    session.commit.assert_not_awaited()


def test_publication_gate_rejects_missing_confirmation() -> None:
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=None)

    with (
        patch("app.api.seo._content_confirmation_schema_ready", new=AsyncMock(return_value=True)),
        pytest.raises(HTTPException) as raised,
    ):
        asyncio.run(_require_active_content_confirmation(session, _content()))

    assert raised.value.status_code == 409
    assert raised.value.detail["code"] == "content_confirmation_required"
    assert raised.value.detail["confirmation_status"] == "pending"


def test_unknown_publish_attempt_requires_manual_check_before_retry() -> None:
    unknown = SeoPublishAttempt(
        tenant_id=1,
        publication_id=9,
        action="publish",
        status="failed",
        response_summary={"requires_manual_review": True, "outcome": "unknown"},
    )
    definite_failure = SeoPublishAttempt(
        tenant_id=1,
        publication_id=9,
        action="publish",
        status="failed",
        response_summary={"outcome": "failed"},
    )

    assert _publication_attempt_requires_manual_check(unknown) is True
    assert _publication_attempt_requires_manual_check(definite_failure) is False


def test_workbench_route_permissions_are_registered_as_read_gate_then_verified_in_endpoint() -> None:
    assert _required(
        "/api/v1/seo/workbench/content-assets/88/delivery", "GET"
    ) == ({"seo.content"}, False)
    assert _required(
        "/api/v1/seo/workbench/content-assets/88/confirmations", "POST"
    ) == ({"seo.content"}, False)
    assert _required(
        "/api/v1/seo/workbench/service-plan", "PUT"
    ) == ({"seo.content", "seo.site"}, False)


def test_assigned_advisor_updates_versioned_service_plan_with_actual_actor() -> None:
    site = SimpleNamespace(
        id=9, tenant_id=1,
        site_settings={"seo_service_plan": {"revision": 2, "optimization_directions": ["旧方向"]}},
    )
    session = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    ctx = AuthContext(
        user_id=7, username="advisor", role_name="顾问", tenant_id=None,
        permissions={"seo.content": "edit", "seo.site": "edit"},
    )
    request = SeoServicePlanUpdate(
        tenant_id=1, site_id=9, expected_revision=2,
        optimization_directions=[" 技术 SEO ", "内容增长", "技术 SEO"],
        content_topics=["减速机选型"], service_note="首期计划", status="active",
    )
    with (
        patch("app.api.seo._content_confirmation_schema_ready", new=AsyncMock(return_value=True)),
        patch("app.api.seo._site_advisor_assignment", new=AsyncMock(return_value=SimpleNamespace(id=3))),
        patch("app.api.seo._seo_site_for_update", new=AsyncMock(return_value=site)),
    ):
        result = asyncio.run(update_seo_service_plan(request, session, ctx))

    assert result["revision"] == 3
    assert result["optimization_directions"] == ["技术 SEO", "内容增长"]
    assert result["updated_by"] == 7
    assert site.site_settings["seo_service_plan"]["updated_by"] == 7
    session.commit.assert_awaited_once()


def test_service_plan_rejects_unassigned_advisor_and_stale_revision() -> None:
    ctx = AuthContext(
        user_id=7, username="advisor", role_name="顾问", tenant_id=None,
        permissions={"seo.content": "edit", "seo.site": "edit"},
    )
    request = SeoServicePlanUpdate(
        tenant_id=1, site_id=9, expected_revision=1,
        optimization_directions=["技术 SEO"],
    )
    with (
        patch("app.api.seo._content_confirmation_schema_ready", new=AsyncMock(return_value=True)),
        patch("app.api.seo._site_advisor_assignment", new=AsyncMock(return_value=None)),
        pytest.raises(HTTPException) as unassigned,
    ):
        asyncio.run(update_seo_service_plan(request, AsyncMock(), ctx))
    assert unassigned.value.status_code == 403

    site = SimpleNamespace(
        id=9, tenant_id=1,
        site_settings={"seo_service_plan": {"revision": 2, "optimization_directions": ["技术 SEO"]}},
    )
    session = AsyncMock()
    with (
        patch("app.api.seo._content_confirmation_schema_ready", new=AsyncMock(return_value=True)),
        patch("app.api.seo._site_advisor_assignment", new=AsyncMock(return_value=SimpleNamespace(id=3))),
        patch("app.api.seo._seo_site_for_update", new=AsyncMock(return_value=site)),
        pytest.raises(HTTPException) as stale,
    ):
        asyncio.run(update_seo_service_plan(request, session, ctx))
    assert stale.value.status_code == 409
    assert stale.value.detail["code"] == "service_plan_version_conflict"
    assert stale.value.detail["current_revision"] == 2
    session.commit.assert_not_awaited()


def test_confirmation_migration_is_linear_and_declares_required_constraints() -> None:
    source = (
        Path(__file__).parents[1]
        / "migrations/versions/20261007_0105_seo_content_confirmations.py"
    ).read_text(encoding="utf-8")

    assert 'revision = "0105_seo_content_confirmations"' in source
    assert 'down_revision = "0104_seo_page_ai_tdk"' in source
    assert "seo_site_advisor_assignments" in source
    assert "seo_content_confirmations" in source
    assert "ck_seo_content_confirmation_actor_mode" in source
