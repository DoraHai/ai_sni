import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import DBAPIError

from app.api.seo import (
    ContentConfirmationRequest,
    delete_advisor_assignment,
    router,
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


def _visibility_ctx(customer=True):
    return AuthContext(7, "viewer", "品牌方客户" if customer else "顾问", 1,
                       {"seo.content": "view" if customer else "edit"}, is_advisor=not customer,
                       scope_kind="advisor_tenant" if not customer else None,
                       grant_id=5 if not customer else None,
                       advisor_tenant_ids=frozenset({1}) if not customer else frozenset())


@pytest.mark.parametrize("state", ["planned", "drafting", "review", "archived", "cancelled", "unknown"])
@pytest.mark.parametrize("entry", ["delivery", "review_history", "assistant", "distribution", "confirmation"])
def test_customer_hidden_content_returns_404_before_related_reads(state, entry):
    from app.api import seo as api, seo_workbench_assistant as assistant
    row = _content(status=state)
    session = AsyncMock()
    session.get.return_value = session.scalar.return_value = row
    ctx = _visibility_ctx()
    with patch.object(api, "_seo_site", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc:
            if entry == "delivery":
                asyncio.run(api.get_content_delivery(88, 1, 9, session, ctx))
            elif entry == "review_history":
                asyncio.run(api.get_content_review_history(88, 1, session, ctx))
            elif entry == "assistant":
                asyncio.run(assistant.selected_content(session, SimpleNamespace(content_id=88, tenant_id=1, site_id=9), ctx))
            elif entry == "confirmation":
                req = ContentConfirmationRequest(version_count=1, payload_hash="0" * 64,
                    decision="approve", actor_mode="customer_direct")
                asyncio.run(api.create_content_confirmation(88, 1, req, session, ctx))
            else:
                asyncio.run(api._distribution_content(session, 1, 88, 9, require_operational=False, ctx=ctx))
        assert exc.value.status_code == 404
    session.scalars.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.parametrize("customer,state,allowed", [
    (True, "ready", True), (True, "published", True), (True, "drafting", False),
    (False, "drafting", True), (False, "review", True), (False, "archived", True),
])
def test_customer_visibility_gate_preserves_reviewed_delivery_and_internal_access(customer, state, allowed):
    from app.seo_customer_identity import require_customer_content_visible
    if allowed:
        require_customer_content_visible(_visibility_ctx(customer), _content(status=state))
    else:
        with pytest.raises(HTTPException) as exc:
            require_customer_content_visible(_visibility_ctx(customer), _content(status=state))
        assert exc.value.status_code == 404


@pytest.mark.parametrize("customer", [True, False])
@pytest.mark.parametrize("status", [None, "drafting", "ready,drafting"])
def test_content_list_counts_and_pagination_share_customer_visibility(customer, status):
    from app.api import seo as api
    session = AsyncMock()
    seen = []
    def inspect_query(statement):
        compiled = statement.compile()
        seen.append(str(statement))
        has_visibility = ("ready", "published") in [tuple(v) for v in compiled.params.values() if isinstance(v, (tuple, list))]
        assert has_visibility is customer
    async def execute(statement):
        inspect_query(statement)
        result = MagicMock()
        result.all.return_value = [("ready", 1)] if status != "drafting" else []
        return result
    async def scalar(statement):
        inspect_query(statement)
        return 0 if status == "drafting" else 1
    async def scalars(statement):
        inspect_query(statement)
        return []
    session.execute.side_effect = execute
    session.scalar.side_effect = scalar
    session.scalars.side_effect = scalars
    with (patch.object(api, "_tenant", new=AsyncMock()),
          patch.object(api, "_seo_site", new=AsyncMock()),
          patch.object(api, "_content_review_user_names", new=AsyncMock(return_value={}))):
        result = asyncio.run(api.list_content_assets(tenant_id=1, site_id=9, status=status,
            q="", page=2, page_size=1, session=session, ctx=_visibility_ctx(customer)))
    assert result["items"] == []
    assert result["total"] == sum(result["status_counts"].values())
    assert len(seen) == 3 and "LIMIT" in seen[-1] and "OFFSET" in seen[-1]


@pytest.mark.parametrize("customer", [True, False])
@pytest.mark.parametrize("state", ["drafting", "ready", "published"])
def test_human_conversation_checks_parent_visibility(customer, state):
    from app.api import seo_messages as messages
    session = AsyncMock()
    revisions = MagicMock()
    revisions.scalars.return_value = [messages.SCHEMA]
    session.execute.return_value = revisions
    session.scalar.side_effect = [SimpleNamespace(id=7, is_active=True, tenant_id=1, display_name="账号", username="actor"), _content(status=state)]
    session.get.return_value = SimpleNamespace(tenant_id=1)
    session.scalars.return_value = [] if customer else [SimpleNamespace(tenant_id=1, site_id=9, active=True)]
    with (patch.object(messages, "ensure_module_access", new=AsyncMock()),
          patch.object(messages, "seo_site_is_operational", new=AsyncMock(return_value=True)),
          patch.object(messages, "customer_account_for_tenant", new=AsyncMock(return_value=customer))):
        if customer and state == "drafting":
            with pytest.raises(HTTPException) as exc:
                asyncio.run(messages.scope(session, _visibility_ctx(customer), 1, 9, 88))
            assert exc.value.status_code == 404
        else:
            actor, operational = asyncio.run(messages.scope(session, _visibility_ctx(customer), 1, 9, 88))
            assert actor["kind"] == ("customer" if customer else "advisor") and operational


@pytest.mark.parametrize("customer", [True, False])
def test_publication_groups_exclude_hidden_linked_receipts_without_changing_internal_queries(customer):
    from app.seo_publication_groups import sources
    for query in sources(1, 9, _visibility_ctx(customer)):
        values = query.element.compile().params.values()
        assert (("ready", "published") in [tuple(v) for v in values if isinstance(v, (tuple, list))]) is customer


def test_customer_publication_capture_rejects_hidden_parent():
    from app.api.seo_page_captures import _require_visible_capture_content
    session = AsyncMock()
    session.scalar.return_value = _content(status="drafting")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(_require_visible_capture_content(session, _visibility_ctx(),
            SimpleNamespace(relation_type="publication", relation_id=12, tenant_id=1, site_id=9)))
    assert exc.value.status_code == 404


@pytest.mark.parametrize("customer", [True, False])
@pytest.mark.parametrize("entry", ["answers", "placements", "maintenance"])
def test_qa_related_read_queries_share_visibility(customer, entry):
    from app.api import seo_qa as qa
    session = AsyncMock()
    async def execute(statement):
        values = statement.compile().params.values()
        assert (("ready", "published") in [tuple(v) for v in values if isinstance(v, (tuple, list))]) is customer
        return []
    session.execute.side_effect = execute
    with (patch.object(qa, "access", new=AsyncMock()), patch.object(qa, "record", new=AsyncMock())):
        kwargs = dict(tenant_id=1, site_id=9, session=session, ctx=_visibility_ctx(customer))
        if entry == "answers":
            kwargs["question_id"] = 12
        asyncio.run(getattr(qa, entry)(**kwargs))
    session.execute.assert_awaited_once()


def test_manual_completion_rejects_hidden_content_before_recording_result():
    from app.api import seo as api
    ctx = _visibility_ctx()
    ctx.permissions["seo.content"] = "edit"
    session = AsyncMock()
    session.get.return_value = SimpleNamespace(tenant_id=1, content_asset_id=88, distribution_variant_id=None)
    req = api.DistributionManualComplete(tenant_id=1, site_id=9, page_url="https://example.com/article")
    with (patch.object(api, "_seo_site", new=AsyncMock()),
          patch.object(api, "_is_offline_receipt_publication", return_value=False),
          patch.object(api, "_distribution_content", new=AsyncMock(return_value=_content(status="drafting")))):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(api.complete_manual_publication(12, req, session, ctx))
        assert exc.value.status_code == 404
    session.commit.assert_not_awaited()


@pytest.mark.parametrize("entry", ["receipt", "report_metrics"])
def test_qa_receipt_and_metrics_reject_hidden_parent_before_placement_read(entry):
    from app.api import seo_qa as qa
    session = AsyncMock()
    session.scalar.return_value = 88
    req = SimpleNamespace(tenant_id=1, site_id=9)
    parent = AsyncMock(return_value=_content(status="drafting"))
    with (patch.object(qa, "access", new=AsyncMock()), patch.object(qa, "record", new=parent)):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(getattr(qa, entry)(12, req, _visibility_ctx(), session))
        assert exc.value.status_code == 404
    parent.assert_awaited_once_with(session, SeoContentAsset, 88, 1, 9, True)
    session.commit.assert_not_awaited()


@pytest.mark.parametrize("entry", ["verify", "assistant_receipt"])
@pytest.mark.parametrize("state", ["drafting", "review", None])
def test_qa_verification_and_assistant_receipt_reject_hidden_or_missing_parent(entry, state):
    from app.api import seo_qa as qa
    session = AsyncMock()
    session.scalar.return_value = _content(status=state) if state else None
    placement = SimpleNamespace(answer_id=17, tenant_id=1, site_id=9)
    with (patch.object(qa, "access", new=AsyncMock()),
          patch.object(qa, "record", new=AsyncMock(return_value=placement)),
          patch("app.seo_backlinks.fetch_backlink_page", new=AsyncMock()) as fetch):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(getattr(qa, entry)(12, SimpleNamespace(tenant_id=1, site_id=9), _visibility_ctx(), session))
        assert exc.value.status_code == 404
    fetch.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.fixture(autouse=True)
def installed_confirmation_schema(monkeypatch):
    # These isolated permission tests model a fully migrated database.
    monkeypatch.setattr("app.seo_content_confirmation_schema.content_confirmation_schema_ready",
                        AsyncMock(return_value=True))


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


@pytest.mark.parametrize("revision", ["0106_seo_content_messages", "0107_seo_site_delete", "0108_advisor_account_links"])
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
        customer.assert_awaited_once_with(session, ctx, 1, lock=False)


def test_api_and_workflow_use_the_shared_capability_gate():
    from app.seo_content_workflow import schema_ready
    session = AsyncMock()
    for entry in (_content_confirmation_schema_ready, schema_ready):
        with patch("app.seo_content_confirmation_schema.content_confirmation_schema_ready",
                   new=AsyncMock(return_value=True)) as shared:
            assert asyncio.run(entry(session)) is True
            shared.assert_awaited_once_with(session)


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


def test_customer_identity_read_only_session_uses_no_share_locks():
    session = AsyncMock()
    session.begin_nested = MagicMock()
    user = User(id=7, username="customer", role_id=1, tenant_id=1,
                is_active=True, password_hash="unused")
    role = Role(id=1, name="品牌方客户", is_system=True,
                permissions={"seo.content": "view"})
    async def scalar(statement):
        assert "FOR SHARE" not in str(statement)
        return user if "FROM users" in str(statement) else None
    async def get(_model, _ident, **kwargs):
        assert "with_for_update" not in kwargs
        return role
    async def scalars(statement):
        assert "FOR SHARE" not in str(statement)
        return []
    session.scalar.side_effect = scalar
    session.get.side_effect = get
    session.scalars.side_effect = scalars
    ctx = AuthContext(7, "customer", "品牌方客户", 1, {"seo.content": "view"})
    assert asyncio.run(customer_account_for_tenant(session, ctx, 1)) is True


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


def _advisor_delete_ctx(*, tenant_id=None, permissions=None, user_id=7):
    return AuthContext(
        user_id=user_id,
        username="test-admin",
        role_name="管理员",
        tenant_id=tenant_id,
        permissions=permissions if permissions is not None else {
            "seo.content": "edit", "settings.accounts": "edit",
        },
    )


def _delete_advisor_assignment(session, ctx, *, tenant_id=1, site_id=9):
    return asyncio.run(delete_advisor_assignment(
        assignment_id=42, tenant_id=tenant_id, site_id=site_id,
        session=session, ctx=ctx,
    ))


def test_delete_assignment_in_validated_scope():
    assert any(
        route.path.endswith("/workbench/advisor-assignments/{assignment_id}")
        and "DELETE" in route.methods
        for route in router.routes
    )
    row = SimpleNamespace(id=42, tenant_id=1, site_id=9)
    session = AsyncMock()
    session.get.return_value = row
    with (
        patch("app.api.seo._content_confirmation_schema_ready", new=AsyncMock(return_value=True)),
        patch("app.api.seo._seo_site", new=AsyncMock(return_value=object())) as site,
    ):
        assert _delete_advisor_assignment(session, _advisor_delete_ctx()) == {"status": "ok"}
    site.assert_awaited_once_with(session, 1, 9)
    session.get.assert_awaited_once()
    assert session.get.call_args.kwargs["with_for_update"] is True
    session.delete.assert_awaited_once_with(row)
    session.commit.assert_awaited_once()


@pytest.mark.parametrize("ctx", [
    _advisor_delete_ctx(permissions={"seo.content": "edit", "settings.accounts": "view"}),
    _advisor_delete_ctx(permissions={"seo.content": "view", "settings.accounts": "edit"}),
    _advisor_delete_ctx(user_id=None),
    _advisor_delete_ctx(tenant_id=2),
])
def test_delete_assignment_forbidden_without_full_scope_and_permission(ctx):
    session = AsyncMock()
    with patch("app.api.seo._content_confirmation_schema_ready", new=AsyncMock(return_value=True)):
        with pytest.raises(HTTPException) as exc:
            _delete_advisor_assignment(session, ctx)
    assert exc.value.status_code == 403
    session.get.assert_not_awaited()
    session.delete.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.parametrize("row", [
    None,
    SimpleNamespace(id=42, tenant_id=2, site_id=9),
    SimpleNamespace(id=42, tenant_id=1, site_id=10),
])
def test_delete_assignment_missing_or_outside_scope_returns_404(row):
    session = AsyncMock()
    session.get.return_value = row
    with (
        patch("app.api.seo._content_confirmation_schema_ready", new=AsyncMock(return_value=True)),
        patch("app.api.seo._seo_site", new=AsyncMock(return_value=object())),
    ):
        with pytest.raises(HTTPException) as exc:
            _delete_advisor_assignment(session, _advisor_delete_ctx())
    assert exc.value.status_code == 404
    session.delete.assert_not_awaited()
    session.commit.assert_not_awaited()


# Shared capability gate regression tests (also run by the production baseline).
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError

from app.models.seo import SeoContentConfirmation, SeoSiteAdvisorAssignment
from app.seo_content_confirmation_schema import content_confirmation_schema_ready as ready


def catalog():
    rows = []
    for model in (SeoContentConfirmation, SeoSiteAdvisorAssignment):
        for col in model.__table__.columns:
            kind = col.type.compile(dialect=postgresql.dialect()).lower().replace('varchar', 'character varying')
            if kind == 'timestamp': kind = 'timestamp without time zone'
            rows.append((model.__tablename__, col.name, kind, True))
    return rows


def session_for(revisions, rows):
    version, columns = MagicMock(), MagicMock()
    version.scalars.return_value = revisions
    columns.all.return_value = rows
    return AsyncMock(execute=AsyncMock(side_effect=[version, columns]))


@pytest.mark.parametrize('revision', [
    '0105_seo_content_confirmations', '0106_seo_content_messages',
    '0107_seo_site_delete', '0108_advisor_account_links', '0109_advisor_tenant_grants',
    '0110_distribution_inbox', '0111_geo_autopatrol', 'future_shared_revision',
])
def test_complete_capabilities_accept_shared_future_revisions(revision):
    assert asyncio.run(ready(session_for([revision], catalog()))) is True


def test_only_legacy_without_either_table_may_skip_confirmation():
    assert asyncio.run(ready(session_for(['0104_seo_page_ai_tdk'], []))) is False
    with pytest.raises(HTTPException) as error:
        asyncio.run(ready(session_for(['0104_seo_page_ai_tdk'], catalog())))
    assert error.value.status_code == 503


@pytest.mark.parametrize('revisions,rows', [
    ([], catalog()), (['0105', '0111'], catalog()),
    (['0111_geo_autopatrol'], []), (['unknown'], []),
    (['0104_seo_page_ai_tdk'], catalog()[:1]),
    (['0104_seo_page_ai_tdk'], [('seo_content_confirmations', None, None, True)]),
    (['0111_geo_autopatrol'], catalog()[1:]),
    (['0111_geo_autopatrol'], [r for r in catalog() if r[0] != 'seo_site_advisor_assignments']),
    (['0111_geo_autopatrol'], [(r[0], r[1], 'text', r[3]) for r in catalog()]),
    (['0111_geo_autopatrol'], [(r[0], r[1], r[2], False) for r in catalog()]),
])
def test_damage_unknown_incomplete_and_permissions_fail_closed(revisions, rows):
    with pytest.raises(HTTPException) as error:
        asyncio.run(ready(session_for(revisions, rows)))
    assert error.value.status_code == 503


def test_database_errors_do_not_expose_details_or_skip_confirmation():
    session = AsyncMock()
    session.execute.side_effect = SQLAlchemyError('private database details')
    with pytest.raises(HTTPException) as error:
        asyncio.run(ready(session))
    assert error.value.status_code == 503
    assert 'private' not in str(error.value.detail)


def test_false_is_not_cached_after_a_migration():
    session = session_for(['0104_seo_page_ai_tdk'], [])
    later = session_for(['0111_geo_autopatrol'], catalog())
    session.execute.side_effect = list(session.execute.side_effect) + list(later.execute.side_effect)
    assert asyncio.run(ready(session)) is False
    assert asyncio.run(ready(session)) is True


def test_public_catalog_is_explicit():
    session = session_for(['0111_geo_autopatrol'], catalog())
    assert asyncio.run(ready(session)) is True
    queries = [str(c.args[0]) for c in session.execute.call_args_list]
    assert 'public.alembic_version' in queries[0]
    assert "n.nspname = 'public'" in queries[1]


@pytest.mark.parametrize("default_tenant,grant_id,allowed", [
    (1, None, True), (99, 10, True), (None, 10, True),
    (99, None, False), (None, None, False),
])
def test_assignment_target_must_be_local_or_have_active_tenant_grant(default_tenant, grant_id, allowed):
    from app.api.seo import AdvisorAssignmentRequest, upsert_advisor_assignment
    from app.models.seo import SeoSiteAdvisorAssignment
    session = AsyncMock()
    advisor = User(id=8, username="advisor", role_id=2, tenant_id=default_tenant, is_active=True)
    role = Role(id=2, name="advisor", permissions={"seo.content": "edit"})
    session.get.side_effect = [advisor, role]
    row = SeoSiteAdvisorAssignment(id=55, tenant_id=1, site_id=9, advisor_user_id=8, active=False)
    session.scalar.side_effect = [row] if default_tenant == 1 else [grant_id, row]
    actor = AuthContext(7, "admin", "admin", None,
                        {"seo.content": "edit", "settings.accounts": "edit"})
    req = AdvisorAssignmentRequest(tenant_id=1, site_id=9, advisor_user_id=8, active=True)
    with patch("app.api.seo._seo_site", new=AsyncMock()):
        if allowed:
            result = asyncio.run(upsert_advisor_assignment(req, session, actor))
            assert result["active"] and result["assigned_by"] == 7
            session.commit.assert_awaited_once()
        else:
            with pytest.raises(HTTPException) as error:
                asyncio.run(upsert_advisor_assignment(req, session, actor))
            assert error.value.status_code == 409
            session.commit.assert_not_awaited()
    if default_tenant != 1:
        statement = str(session.scalar.call_args_list[0].args[0])
        assert "advisor_tenant_grants.revoked_at IS NULL" in statement
