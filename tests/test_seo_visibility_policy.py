"""Pure policy contracts only: no DB adapter, provider, email or environment."""
from dataclasses import replace
from datetime import datetime, timezone
import socket

import pytest
from fastapi import HTTPException

from app.seo_visibility_policy import (
    KEY, Reservation, VisibilityScope, authorize, questions_for_site,
    reserve_quota, settle_quota, used,
)

NOW = datetime(2026, 10, 19, 15, 59, tzinfo=timezone.utc)
TOMORROW = datetime(2026, 10, 19, 16, 0, tzinfo=timezone.utc)
SCOPE = VisibilityScope(7, 4, frozenset({4, 5}), frozenset({2}), "advisor", True, True)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("This suite must never connect to databases/providers/mail")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def reserve(settings=None, *, advisor=7, tenant=4, request="a", fingerprint="a" * 64, now=NOW):
    return reserve_quota(settings, tenant_id=tenant, advisor_id=advisor,
                         request_id=request, fingerprint=fingerprint, now=now)


def denied(call, status=403):
    with pytest.raises(HTTPException) as caught:
        call()
    assert caught.value.status_code == status


@pytest.mark.parametrize("write", [False, True])
def test_only_live_selected_authorized_tenant_and_assigned_site(write):
    authorize(SCOPE, tenant_id=4, site_id=2, write=write)
    denied(lambda: authorize(SCOPE, tenant_id=5, site_id=2, write=write))
    denied(lambda: authorize(SCOPE, tenant_id=99, site_id=2, write=write))
    denied(lambda: authorize(SCOPE, tenant_id=4, site_id=3, write=write))
    denied(lambda: authorize(replace(SCOPE, granted_tenant_ids=frozenset()), tenant_id=4, site_id=2, write=write))
    denied(lambda: authorize(replace(SCOPE, assigned_site_ids=frozenset()), tenant_id=4, site_id=2, write=write))


def test_read_and_edit_permissions():
    reader = replace(SCOPE, can_edit=False)
    authorize(reader, tenant_id=4, site_id=2)
    denied(lambda: authorize(reader, tenant_id=4, site_id=2, write=True))
    denied(lambda: authorize(replace(SCOPE, can_view=False), tenant_id=4, site_id=2))
    denied(lambda: authorize(replace(SCOPE, user_id=None), tenant_id=4, site_id=2))


@pytest.mark.parametrize("setting", ["engines", "model", "patrol_interval", "api_key", "permissions"])
@pytest.mark.parametrize("role", ["advisor", "customer"])
def test_configuration_reserved_for_superadmin(setting, role):
    # Every planned configuration change uses the same explicit admin check.
    assert setting
    denied(lambda: authorize(replace(SCOPE, role=role), tenant_id=4, site_id=2, write=True, configuration=True))
    authorize(replace(SCOPE, role="superadmin"), tenant_id=4, site_id=2, write=True, configuration=True)


def test_ten_per_advisor_per_client_per_beijing_day():
    state = {"other": {"kept": True}}
    for n in range(10):
        state, _ = reserve(state, request=str(n))
    assert used(state, 4, 7, now=NOW) == 10
    denied(lambda: reserve(state, request="eleven"), 429)
    independent, _ = reserve(state, advisor=8)
    assert used(independent, 4, 8, now=NOW) == 1
    other_client, _ = reserve(tenant=5)
    assert used(other_client, 5, 7, now=NOW) == 1
    tomorrow, _ = reserve(state, now=TOMORROW)
    assert used(tomorrow, 4, 7, now=TOMORROW) == 1
    assert used(state, 4, 7, now=TOMORROW) == 0
    assert tomorrow["other"] == {"kept": True}


def test_fail_without_results_refunds_exactly_once_and_new_attempt_allowed():
    state, receipt = reserve()
    refunded = settle_quota(state, receipt, has_result=False)
    assert used(refunded, 4, 7, now=NOW) == 0
    assert settle_quota(refunded, receipt, has_result=False) == refunded
    assert settle_quota(refunded, receipt, has_result=True) == refunded
    denied(lambda: reserve(refunded), 409)
    retried, _ = reserve(refunded, request="new")
    assert used(retried, 4, 7, now=NOW) == 1
    assert used(state, 4, 7, now=NOW) == 1  # Inputs never mutate.


def test_partial_result_consumes_before_next_failure_and_cannot_be_refunded():
    state, receipt = reserve()
    partial = settle_quota(state, receipt, has_result=True)
    assert used(partial, 4, 7, now=NOW) == 1
    assert partial[KEY]["actors"]["7"]["a"]["state"] == "consumed"
    assert settle_quota(partial, receipt, has_result=False) == partial
    assert settle_quota(partial, receipt, has_result=True) == partial


def test_retry_is_idempotent_and_cannot_change_payload():
    state, receipt = reserve()
    again, second = reserve(state)
    assert (again, second) == (state, receipt)
    denied(lambda: reserve(state, fingerprint="b" * 64), 409)
    for n in range(1, 10):
        state, _ = reserve(state, request=str(n))
    assert reserve(state)[0] == state  # Retrieval allowed even at the limit.


@pytest.mark.parametrize("field,value", [("tenant_id", 5), ("advisor_id", 8), ("day", "2026-10-18"), ("request_id", "other")])
def test_refund_receipt_cannot_touch_other_scope(field, value):
    state, receipt = reserve()
    assert settle_quota(state, replace(receipt, **{field: value}), has_result=False) == state


def test_yesterday_cleanup_cannot_refund_today():
    yesterday, receipt = reserve()
    today, _ = reserve(yesterday, now=TOMORROW)
    assert settle_quota(today, receipt, has_result=False) == today
    denied(lambda: reserve(today, tenant=5, now=TOMORROW), 403)


def test_neutral_questions_reuse_geo_without_brand_priming():
    questions = questions_for_site(industry="泵", products=["测试品牌工业泵"],
                                   audience=["化工企业"], brand_terms=["测试品牌"])
    assert len(questions) == 3
    assert all("测试品牌" not in item for item in questions)
    assert any("工业泵" in item for item in questions)


def test_invalid_time_identity_and_result_evidence_rejected():
    with pytest.raises(ValueError): reserve(now=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError): reserve(advisor=True)
    with pytest.raises(ValueError): reserve(request="")
    with pytest.raises(ValueError): reserve(fingerprint="short")
    state, receipt = reserve()
    with pytest.raises(ValueError): settle_quota(state, receipt, has_result="false")
