import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import DBAPIError

from app.api.seo import (
    ContentConfirmationRequest,
    ContentReviewSubmit,
    SeoServicePlanUpdate,
    _content_allowed_actions,
    _content_confirmation_hash,
    _content_confirmation_schema_ready,
    _content_confirmation_status,
    _validated_content_confirmation_status,
    _content_delivery_payload,
    _publication_attempt_requires_manual_check,
    _require_active_content_confirmation,
    create_content_confirmation,
    get_seo_service_plan,
    submit_content_review,
    update_seo_service_plan,
)
from app.models.seo import SeoContentAsset, SeoContentConfirmation, SeoPublishAttempt
from app.models.user import User
from app.models.role import Role
from app.api.seo_messages import scope as message_scope
from app.seo_customer_identity import customer_account_for_tenant
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


def test_historical_internal_customer_direct_confirmation_is_pending():
    row = _content()
    confirmation = SeoContentConfirmation(
        tenant_id=1, site_id=9, content_asset_id=88, content_version=3,
        content_hash=_content_confirmation_hash(row), decision="approve",
        actor_mode="customer_direct", actor_user_id=11,
    )
    with patch("app.api.seo.customer_account_for_tenant", new=AsyncMock(return_value=False)):
        assert asyncio.run(_validated_content_confirmation_status(AsyncMock(), row, confirmation)) == "pending"


@pytest.mark.parametrize("revision", ["0106_seo_content_messages", "0107_seo_site_delete"])
def test_message_customer_path_uses_the_same_identity_rule(revision):
    session = AsyncMock()
    revisions = MagicMock()
    revisions.scalars.return_value = [revision]
    session.execute.return_value = revisions
    user = User(id=7, username="customer", role_id=1, tenant_id=1,
                is_active=True, password_hash="unused")
    session.scalar.side_effect = [user, _content()]
    session.get.return_value = SimpleNamespace(tenant_id=1)
    session.scalars.return_value = []
    ctx = AuthContext(7, "customer", "品牌方客户", 1, {"seo.content": "view"})
    with (patch("app.api.seo_messages.ensure_module_access", new=AsyncMock()),
          patch("app.api.seo_messages.seo_site_is_operational", new=AsyncMock(return_value=True)),
          patch("app.api.seo_messages.customer_account_for_tenant", new=AsyncMock(return_value=True)) as customer):
        actor, _ = asyncio.run(message_scope(session, ctx, 1, 9, 88))
        assert actor["kind"] == "customer"
        customer.assert_awaited_once_with(session, ctx, 1)


def test_content_confirmation_gate_accepts_existing_0107_revision():
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = "0107_seo_site_delete"
    session.execute.return_value = result
    assert asyncio.run(_content_confirmation_schema_ready(session)) is True


def test_customer_identity_fails_closed_when_geo_table_is_unavailable():
    session = AsyncMock()
    session.begin_nested = MagicMock()
    user = User(id=7, username="customer", role_id=1, tenant_id=1,
                is_active=True, password_hash="unused")
    role = Role(id=1, name="品牌方客户", is_system=True,
                permissions={"seo.content": "view"})
    session.scalar.side_effect = [user, DBAPIError("SELECT", {}, Exception("missing table"))]
    session.get.return_value = role
    session.scalars.return_value = []
    ctx = AuthContext(7, "customer", "品牌方客户", 1, {"seo.content": "view"})
    assert asyncio.run(customer_account_for_tenant(session, ctx, 1)) is False


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


def test_tenant_bound_content_editor_is_not_customer_without_assignment() -> None:
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=None)

    actions, basis = asyncio.run(
        _content_allowed_actions(session, _content(), _ctx(tenant_id=1), "pending")
    )

    assert actions["confirm_as_customer"] is False
    assert actions["confirm_as_advisor_proxy"] is False
    assert basis["tenant_bound_customer_account"] is False
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
    assert "真实客户账号" in raised.value.detail
    session.commit.assert_not_awaited()


@pytest.mark.parametrize("case,expected", [
    ("customer", True), ("editor", False), ("other_site_advisor", False),
    ("other_site_assignment_viewer", False),
    ("administrator", False), ("cross_tenant", False), ("api_key", False),
    ("internal_viewer", False), ("geo_editor", False), ("custom_customer_name", False),
    ("geo_advisor", False), ("disabled", False), ("actor_mismatch", False),
    ("tenant_api_key", False),
])
def test_customer_confirmation_identity_matches_allowed_actions(case, expected):
    row = _content()
    permissions = {"seo.content": "view"}
    tenant = 2 if case == "cross_tenant" else 1
    if case in {"editor", "other_site_advisor"}:
        permissions["seo.content"] = "edit"
    if case == "administrator":
        permissions["settings.accounts"] = "edit"
    if case == "geo_editor":
        permissions["geo.content"] = "edit"
    ctx = AuthContext(None if case in {"api_key", "tenant_api_key"} else 7, "actor", "customer",
                      None if case == "api_key" else tenant, permissions,
                      is_superadmin=case in {"api_key", "tenant_api_key"})
    if case == "internal_viewer":
        ctx.role_name = "operations"
    user = User(id=8 if case == "actor_mismatch" else 7, username="actor", role_id=1, tenant_id=tenant,
                is_active=case != "disabled", password_hash="unused")
    role = Role(id=1, name="customer" if case == "custom_customer_name" else
                "operations" if case == "internal_viewer" else "品牌方客户",
                is_system=case != "custom_customer_name", permissions=permissions)
    session = AsyncMock()
    session.add = MagicMock()
    session.begin_nested = MagicMock()

    async def get(model, ident, **kwargs):
        return row if model is SeoContentAsset else user if model is User else role if model is Role else None

    session.get.side_effect = get
    async def scalar(statement):
        if "FROM users" in str(statement):
            return user
        if "FROM geo_projects" in str(statement):
            return 55 if case == "geo_advisor" else None
        return None
    session.scalar.side_effect = scalar
    session.scalars.return_value = [88] if case in {"other_site_advisor", "other_site_assignment_viewer"} else []
    req = ContentConfirmationRequest(version_count=3, payload_hash=_content_confirmation_hash(row),
                                      decision="approve", actor_mode="customer_direct")
    with (patch("app.api.seo._content_confirmation_schema_ready", new=AsyncMock(return_value=True)),
          patch("app.api.seo._require_resource_operational_site", new=AsyncMock()),
          patch("app.api.seo._content_delivery_payload", new=AsyncMock(return_value={"ok": True}))):
        actions, basis = asyncio.run(_content_allowed_actions(session, row, ctx, "pending"))
        assert actions["confirm_as_customer"] is expected
        assert actions["reject_as_customer"] is expected
        assert basis["tenant_bound_customer_account"] is expected
        if expected:
            assert asyncio.run(create_content_confirmation(88, 1, req, session, ctx)) == {"ok": True}
            session.commit.assert_awaited_once()
        else:
            with pytest.raises(HTTPException) as denied:
                asyncio.run(create_content_confirmation(88, 1, req, session, ctx))
            assert denied.value.status_code == 403
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


def test_service_plan_read_reports_server_verified_update_capability() -> None:
    site = SimpleNamespace(id=9, tenant_id=1, site_settings={})
    session = AsyncMock()
    ctx = AuthContext(
        user_id=7, username="advisor", role_name="顾问", tenant_id=None,
        permissions={"seo.content": "edit", "seo.site": "edit"},
    )
    assignment = SimpleNamespace(id=3)
    with (
        patch("app.seo_workflow_capabilities.trigger_capabilities", new=AsyncMock(return_value={})),
        patch("app.api.seo.ensure_module_access", new=AsyncMock()),
        patch("app.api.seo._seo_site", new=AsyncMock(return_value=site)),
        patch("app.api.seo._content_confirmation_schema_ready", new=AsyncMock(return_value=True)),
        patch("app.api.seo._site_advisor_assignment", new=AsyncMock(return_value=assignment)) as lookup,
    ):
        result = asyncio.run(get_seo_service_plan(1, 9, session, ctx))
    assert result["allowed_actions"] == {"update_service_plan": True}
    assert result["permission_basis"] == {
        "actor_user_id": 7,
        "schema_ready": True,
        "seo_content_permission": "edit",
        "seo_site_permission": "edit",
        "active_site_advisor_assignment": True,
        "update_denial_reason": None,
    }
    lookup.assert_awaited_once_with(session, 1, 9, 7, schema_ready=True)


def test_pre_migration_delivery_marks_confirmation_unavailable() -> None:
    row = _content(status="ready")
    session = AsyncMock()
    with patch(
        "app.api.seo._content_confirmation_schema_ready",
        new=AsyncMock(return_value=False),
    ):
        result = asyncio.run(_content_delivery_payload(
            session, row, _ctx(tenant_id=1),
        ))
    assert result["confirmation"]["status"] == "unavailable"
    assert result["workflow_status"] == "confirmation_unavailable"
    assert result["allowed_actions"]["confirm_as_customer"] is False
    assert result["allowed_actions"]["confirm_as_advisor_proxy"] is False
    assert result["allowed_actions"]["start_publication"] is False


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
