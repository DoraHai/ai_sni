import asyncio
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.geo.content import routes
from app.geo.content.schemas import ReviewDecision
from app.security.auth import AuthContext, _required, require_scoped_auth


def _ctx(*, tenant_id=7, level="view", user_id=9, role_name="品牌方客户"):
    permissions = {"geo.content": level} if level else {}
    return AuthContext(
        user_id=user_id,
        username="reviewer",
        role_name=role_name,
        tenant_id=tenant_id,
        permissions=permissions,
    )


def _request(path, method="POST"):
    return Request({
        "type": "http",
        "method": method,
        "path": path,
        "query_string": b"tenant_id=7",
        "headers": [],
    })


def test_only_review_decision_downgrades_geo_post_to_view_permission():
    assert _required("/api/v1/geo/content-tasks/14/review", "POST") == ({"geo.content"}, False)
    for path in (
        "/api/v1/geo/content-tasks/14/submit-review",
        "/api/v1/geo/content-tasks/14/generate",
        "/api/v1/geo/content-tasks/14/variants",
        "/api/v1/geo/content-tasks/14/push",
        "/api/v1/geo/content-tasks/14/article",
    ):
        assert _required(path, "POST") == ({"geo.content"}, True)


@pytest.mark.parametrize("blocked_path", [
    "/api/v1/geo/content-tasks/14/submit-review",
    "/api/v1/geo/content-tasks/14/generate",
    "/api/v1/geo/content-tasks/14/variants",
    "/api/v1/geo/content-tasks/14/push",
    "/api/v1/geo/content-tasks/14/article",
])
def test_scoped_auth_allows_geo_viewer_only_into_review_decision_route(blocked_path):
    reviewer = _ctx()
    assert asyncio.run(require_scoped_auth(
        request=_request("/api/v1/geo/content-tasks/14/review"), ctx=reviewer
    )) is reviewer
    with pytest.raises(HTTPException) as error:
        asyncio.run(require_scoped_auth(
            request=_request(blocked_path), ctx=reviewer
        ))
    assert error.value.status_code == 403


def test_scoped_auth_rejects_account_without_geo_content_access():
    with pytest.raises(HTTPException) as error:
        asyncio.run(require_scoped_auth(
            request=_request("/api/v1/geo/content-tasks/14/review"),
            ctx=_ctx(level=None),
        ))
    assert error.value.status_code == 403


def test_auth_payload_exposes_database_role_name_as_frontend_role_label():
    source = Path("app/api/auth.py").read_text(encoding="utf-8")
    assert '"role_label": role.name if role else "?"' in source
    assert '"permissions": (role.permissions or {}) if role else {}' in source


@pytest.mark.parametrize("decision", ["approved", "rejected"])
def test_bound_customer_reviewer_can_decide_current_pending_version(decision):
    updated = datetime(2026, 9, 8, 15, 45, 58)
    task = NS(id=14, tenant_id=7, review_status="pending", updated_at=updated, review_audit={
        "schema_version": "geo.review.audit.v1",
        "events": [{"event": "submitted", "actor_user_id": 9, "actor_role": "品牌方客户",
                    "tenant_id": 7, "article_id": 22, "occurred_at": "2026-09-08T15:40:00Z"}],
    })
    session = NS(refresh=AsyncMock(), commit=AsyncMock())
    req = ReviewDecision(
        decision=decision,
        note="客户确认",
        expected_article_id=22,
        expected_updated_at=routes._iso(updated),
    )
    with patch.object(routes, "_get_task", AsyncMock(return_value=task)), patch.object(
        routes, "_latest_article", AsyncMock(return_value=NS(id=22))
    ), patch.object(routes, "_sync_task_pipeline", AsyncMock()), patch.object(
        routes, "_task_payload", AsyncMock(return_value={"review_status": decision})
    ):
        result = asyncio.run(routes.decide_task_review(14, req, 7, _ctx(), session))
    assert result == {"review_status": decision}
    assert task.review_status == decision
    assert task.reviewed_by == 9
    session.commit.assert_awaited_once()


def test_customer_reviewer_must_be_bound_to_requested_tenant():
    lookup = AsyncMock()
    with patch.object(routes, "_get_task", lookup), pytest.raises(HTTPException) as error:
        asyncio.run(routes.decide_task_review(
            14,
            ReviewDecision(
                decision="approved",
                expected_article_id=22,
                expected_updated_at="revision",
            ),
            7,
            _ctx(tenant_id=8),
            NS(),
        ))
    assert error.value.status_code == 403
    lookup.assert_not_awaited()


def test_unbound_viewer_cannot_decide_customer_review():
    lookup = AsyncMock()
    with patch.object(routes, "_get_task", lookup), pytest.raises(HTTPException) as error:
        asyncio.run(routes.decide_task_review(
            14,
            ReviewDecision(
                decision="approved",
                expected_article_id=22,
                expected_updated_at="revision",
            ),
            7,
            _ctx(tenant_id=None),
            NS(),
        ))
    assert error.value.status_code == 403
    lookup.assert_not_awaited()


def test_custom_tenant_readonly_role_cannot_decide_customer_review():
    lookup = AsyncMock()
    with patch.object(routes, "_get_task", lookup), pytest.raises(HTTPException) as error:
        asyncio.run(routes.decide_task_review(
            14,
            ReviewDecision(
                decision="approved",
                expected_article_id=22,
                expected_updated_at="revision",
            ),
            7,
            _ctx(role_name="__workbench_test_readonly__"),
            NS(),
        ))
    assert error.value.status_code == 403
    lookup.assert_not_awaited()


def test_customer_reviewer_must_send_both_concurrency_preconditions():
    lookup = AsyncMock()
    for request in (
        ReviewDecision(decision="approved", expected_updated_at="revision"),
        ReviewDecision(decision="approved", expected_article_id=22),
    ):
        with patch.object(routes, "_get_task", lookup), pytest.raises(HTTPException) as error:
            asyncio.run(routes.decide_task_review(14, request, 7, _ctx(), NS()))
        assert error.value.status_code == 400
    lookup.assert_not_awaited()


def test_customer_reviewer_cannot_approve_non_pending_task():
    updated = datetime(2026, 9, 8, 15, 45, 58)
    task = NS(id=14, tenant_id=7, review_status="approved", updated_at=updated)
    session = NS(refresh=AsyncMock(), commit=AsyncMock())
    req = ReviewDecision(
        decision="approved",
        expected_article_id=22,
        expected_updated_at=routes._iso(updated),
    )
    with patch.object(routes, "_get_task", AsyncMock(return_value=task)), patch.object(
        routes, "_latest_article", AsyncMock(return_value=NS(id=22))
    ), pytest.raises(HTTPException) as error:
        asyncio.run(routes.decide_task_review(14, req, 7, _ctx(), session))
    assert error.value.status_code == 400
    session.commit.assert_not_awaited()


def test_existing_geo_editor_review_flow_remains_compatible():
    task = NS(id=14, tenant_id=7, review_status="pending", updated_at=datetime(2026, 9, 8), review_audit={
        "schema_version": "geo.review.audit.v1",
        "events": [{"event": "submitted", "actor_user_id": 9, "actor_role": "品牌方客户",
                    "tenant_id": 7, "article_id": 22, "occurred_at": "2026-09-08T00:00:00Z"}],
    })
    session = NS(refresh=AsyncMock(), commit=AsyncMock())
    editor = _ctx(tenant_id=None, level="edit")
    with patch.object(routes, "_get_task", AsyncMock(return_value=task)), patch.object(
        routes, "_latest_article", AsyncMock(return_value=NS(id=22))
    ), patch.object(
        routes, "_sync_task_pipeline", AsyncMock()
    ), patch.object(
        routes, "_task_payload", AsyncMock(return_value={"review_status": "approved"})
    ):
        result = asyncio.run(routes.decide_task_review(
            14, ReviewDecision(decision="approved"), 7, editor, session
        ))
    assert result == {"review_status": "approved"}
    assert task.reviewed_by == 9
    session.commit.assert_awaited_once()


def test_legacy_pending_review_without_submit_event_fails_closed():
    task = NS(id=14, tenant_id=7, review_status="pending", updated_at=datetime(2026, 9, 8), review_audit=None)
    session = NS(refresh=AsyncMock(), commit=AsyncMock())
    with patch.object(routes, "_get_task", AsyncMock(return_value=task)), patch.object(
        routes, "_latest_article", AsyncMock(return_value=NS(id=22))
    ), pytest.raises(HTTPException) as error:
        asyncio.run(routes.decide_task_review(
            14, ReviewDecision(decision="approved"), 7, _ctx(tenant_id=None, level="edit"), session
        ))
    assert error.value.status_code == 400
    assert "重新提交审核" in str(error.value.detail)
    session.commit.assert_not_awaited()
