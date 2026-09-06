"""Offline API contracts: virtual auth, no external calls or production DB."""
import asyncio
import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import test_writeback_approval  # noqa: F401; dummy credentials before app imports
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.api import sem_tasks as api
from app.security.auth import AuthContext


def context(tenant=3, edit=True, user=9):
    return AuthContext(user_id=user, username="test", role_name="operator", tenant_id=tenant,
                       permissions={"monitor.dashboard": "view",
                                    "verify.adjustments": "edit" if edit else "view"})


def metric(value=3, when=None, key="sem.approvals.pending_count", status="available"):
    return dict(metric_key=key, value=value, unit="approval", as_of=(when or datetime.now(timezone.utc)).isoformat(),
                trend_7d=None, definition="当前客户待审批记录数，不代表实际广告执行结果", data_status=status)


def evidence(value=3, when=None):
    return dict(tenant_id=3, scope="tenant", source="sem.metrics.snapshot.v1", metric=metric(value, when),
                observed_at=datetime.now(timezone.utc).isoformat())


def task():
    now = datetime.now(timezone.utc)
    return SimpleNamespace(id=11, tenant_id=3, module="sem", action_type="metric_target", title="减少待处理审批",
                           params=dict(metric_key="sem.approvals.pending_count", direction="down", target_value=1),
                           status="open", created_by="user:9", assignee_role="operator",
                           baseline_snapshot=evidence(3, now-timedelta(hours=1)), completion_evidence=None,
                           created_at=now, updated_at=now)


@pytest.fixture
def setup(monkeypatch):
    db = SimpleNamespace(scalar=AsyncMock(return_value=task()), scalars=AsyncMock(),
                         add=Mock(), commit=AsyncMock(), refresh=AsyncMock())
    async def refresh(row):
        row.id = getattr(row, "id", None) or 11
        row.created_at = row.updated_at = datetime.now(timezone.utc)
    db.refresh.side_effect = refresh
    monkeypatch.setattr(api, "get_settings", lambda: SimpleNamespace(sem_tasks_enabled=True))
    monkeypatch.setattr(api, "ensure_module_access", AsyncMock())
    monkeypatch.setattr(api, "snapshot", AsyncMock(return_value={"tenant_id": 3, "items": [metric()]}))
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.require_auth] = lambda: context()
    async def session():
        yield db
    app.dependency_overrides[api.get_session] = session
    with TestClient(app) as client:
        yield client, app, db


PAYLOAD = dict(title="减少待处理审批", params=dict(metric_key="sem.approvals.pending_count", direction="down", target_value=1))


def test_create_records_server_baseline_and_real_actor(setup):
    client, _, db = setup
    r = client.post("/api/v1/sem/tasks?tenant_id=3", json=PAYLOAD)
    assert r.status_code == 201, r.text
    assert r.headers["cache-control"] == "no-store"
    assert r.json()["created_by"] == "user:9"
    assert r.json()["baseline_snapshot"]["metric"]["value"] == 3
    assert r.json()["completion_evidence"] is None
    db.commit.assert_awaited_once()


@pytest.mark.parametrize("extra", [{"created_by": "cockpit"}, {"status": "done"},
    {"completion_evidence": {"ok": True}}, {"module": "seo"}, {"action_type": "keyword_bid"},
    {"title": " "}, {"assignee_role": "root"},
    {"params": dict(metric_key="sem.spend.budget_utilization_pct", direction="down", target_value=1)},
    {"params": dict(metric_key="sem.approvals.pending_count", direction="down", target_value=True)},
    {"params": dict(metric_key="sem.approvals.pending_count", direction="up", target_value=5)},
    {"params": dict(metric_key="sem.approvals.pending_count", direction="down", target_value=1, token="not-allowed")},
])
def test_create_forbids_spoofing_and_unsupported_actions(setup, extra):
    client, _, db = setup
    assert client.post("/api/v1/sem/tasks?tenant_id=3", json=PAYLOAD | extra).status_code == 422
    db.add.assert_not_called()


@pytest.mark.parametrize("tenant", ["0", "-1", "3.5", "99999999999999999999"])
def test_bad_tenant_id(setup, tenant):
    client, _, db = setup
    assert client.get("/api/v1/sem/tasks?tenant_id="+tenant).status_code == 422
    db.scalars.assert_not_awaited()


@pytest.mark.parametrize("ctx", [context(4), context(edit=False), context(user=None)])
def test_mutation_auth_fails_before_task_access(setup, ctx):
    client, app, db = setup
    app.dependency_overrides[api.require_auth] = lambda: ctx
    assert client.post("/api/v1/sem/tasks?tenant_id=3", json=PAYLOAD).status_code == 403
    db.add.assert_not_called()


def test_disabled_before_schema_access(setup, monkeypatch):
    client, _, db = setup
    monkeypatch.setattr(api, "get_settings", lambda: SimpleNamespace(sem_tasks_enabled=False))
    assert client.get("/api/v1/sem/tasks?tenant_id=3").status_code == 503
    db.scalars.assert_not_awaited()
    api.ensure_module_access.assert_not_awaited()


def test_unauthenticated_and_module_denied(setup):
    client, app, db = setup
    app.dependency_overrides.pop(api.require_auth)
    assert client.get("/api/v1/sem/tasks?tenant_id=3").status_code == 401
    app.dependency_overrides[api.require_auth] = lambda: context()
    api.ensure_module_access.side_effect = HTTPException(403, "disabled")
    assert client.get("/api/v1/sem/tasks?tenant_id=3").status_code == 403
    db.scalars.assert_not_awaited()


def test_verify_changes_status_with_embedded_evidence_and_is_idempotent(setup):
    client, _, db = setup
    api.snapshot.return_value = {"items": [metric(1)]}
    r = client.post("/api/v1/sem/tasks/11/verify?tenant_id=3")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "done"
    assert r.json()["completion_evidence"]["baseline"]["metric"]["value"] == 3
    first = r.json()["completion_evidence"]
    assert client.post("/api/v1/sem/tasks/11/verify?tenant_id=3").json()["completion_evidence"] == first
    db.commit.assert_awaited_once()
    api.snapshot.assert_awaited_once()
    sql = str(db.scalar.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql and "sem_tasks.tenant_id =" in sql


@pytest.mark.parametrize("value", [2, 3, 4])
def test_verify_not_met_does_not_complete(setup, value):
    client, _, db = setup
    api.snapshot.return_value = {"items": [metric(value)]}
    assert client.post("/api/v1/sem/tasks/11/verify?tenant_id=3").status_code == 409
    assert db.scalar.return_value.status == "open"
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("change", [{"status": "done"}, {"params": {}}, {"title": None}, {}, {"baseline_snapshot": {}}])
def test_patch_cannot_retarget_or_mark_done(setup, change):
    client, _, db = setup
    assert client.patch("/api/v1/sem/tasks/11?tenant_id=3", json=change).status_code == 422
    db.commit.assert_not_awaited()


def test_cancel_is_soft_and_terminal(setup):
    client, _, db = setup
    assert client.delete("/api/v1/sem/tasks/11?tenant_id=3").json()["status"] == "cancelled"
    assert client.delete("/api/v1/sem/tasks/11?tenant_id=3").status_code == 200
    assert client.post("/api/v1/sem/tasks/11/verify?tenant_id=3").status_code == 409
    assert client.patch("/api/v1/sem/tasks/11?tenant_id=3", json={"title": "修改"}).status_code == 409
    db.commit.assert_awaited_once()


def test_list_keyset_scope_and_limit(setup):
    client, _, db = setup
    rows = [task(), task(), task()]
    for row, id_ in zip(rows, [9, 8, 7]):
        row.id = id_
    db.scalars.return_value = SimpleNamespace(all=lambda: rows)
    r = client.get("/api/v1/sem/tasks?tenant_id=3&status=open&before_id=10&limit=2")
    assert r.status_code == 200, r.text
    assert r.json()["has_more"] and r.json()["next_before_id"] == 8
    assert len(r.json()["items"]) == 2
    query = db.scalars.call_args.args[0].compile(dialect=postgresql.dialect())
    assert query.params["tenant_id_1"] == 3 and query.params["id_1"] == 10
    assert "ORDER BY sem_tasks.id DESC" in str(query)


def test_missing_cross_tenant_task_is_404(setup):
    client, _, db = setup
    db.scalar.return_value = None
    assert client.get("/api/v1/sem/tasks/11?tenant_id=3").status_code == 404
    query = db.scalar.call_args.args[0].compile(dialect=postgresql.dialect())
    assert query.params["tenant_id_1"] == 3


@pytest.mark.parametrize("kind", ["unavailable", "stale", "future"])
def test_no_stale_or_missing_evidence(setup, kind):
    client, _, db = setup
    m = metric()
    if kind == "unavailable":
        m.update(value=None, as_of=None, data_status="identity_blocked")
    else:
        m["as_of"] = (datetime.now(timezone.utc)+timedelta(hours=1 if kind == "future" else -1)).isoformat()
    api.snapshot.return_value = {"items": [m]}
    assert client.post("/api/v1/sem/tasks?tenant_id=3", json=PAYLOAD).status_code == 409
    db.add.assert_not_called()


@pytest.mark.parametrize("field,value", [("tenant_id", 4), ("scope", "account"), ("source", "unknown")])
def test_evidence_scope_mismatch_fails(field, value):
    current = evidence(1)
    current[field] = value
    with pytest.raises(HTTPException):
        api.validate_change(task(), current)


def test_equal_timestamp_cannot_finish():
    row = task()
    current = copy.deepcopy(row.baseline_snapshot)
    current["metric"]["value"] = 1
    with pytest.raises(HTTPException):
        api.validate_change(row, current)


def test_task_feature_defaults_off_and_ci_has_native_gate():
    import ast
    from pathlib import Path
    import yaml
    tree = ast.parse(Path("app/config.py").read_text(encoding="utf-8"))
    settings = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Settings")
    flag = next(n for n in settings.body if isinstance(n, ast.AnnAssign) and n.target.id == "sem_tasks_enabled")
    assert ast.literal_eval(flag.value) is False
    config = yaml.load(Path(".github/workflows/ci.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    job = config["jobs"]["sem-task-contracts"]
    assert job["services"]["postgres"]["env"]["POSTGRES_DB"] == "sem_tasks_test"
    step = job["steps"][-1]
    assert "test_sem_tasks_postgres.py" in step["run"]
    assert "${{" not in step["env"]["SEM_TASK_TEST_DATABASE_URL"]


def test_identity_preview_requires_separate_task_provenance_review():
    from pathlib import Path
    source = Path("app/api/customer_modules.py").read_text(encoding="utf-8")
    assert '"sem_tasks"' in source.split('"excluded_scope": [', 1)[1].split(']', 1)[0]
    assert '"sem_task_baseline_provenance_review"' in source


def test_patch_active_task_and_read_only_access(setup):
    client, app, db = setup
    assert client.patch("/api/v1/sem/tasks/11?tenant_id=3", json={"status": "in_progress"}).json()["status"] == "in_progress"
    app.dependency_overrides[api.require_auth] = lambda: context(edit=False)
    assert client.get("/api/v1/sem/tasks/11?tenant_id=3").status_code == 200
    assert client.delete("/api/v1/sem/tasks/11?tenant_id=3").status_code == 403


def test_already_met_target_cannot_create_finished_task(setup):
    client, _, db = setup
    api.snapshot.return_value = {"items": [metric(1)]}
    assert client.post("/api/v1/sem/tasks?tenant_id=3", json=PAYLOAD).status_code == 409
    db.add.assert_not_called()


def test_openapi_exposes_typed_task_contract(setup):
    client, _, _ = setup
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    fields = schemas["TaskResponse"]["properties"]
    assert {"id", "tenant_id", "module", "action_type", "title", "params", "status", "created_by",
            "assignee_role", "completion_evidence", "baseline_snapshot", "created_at", "updated_at"} == set(fields)
    assert fields["created_at"]["format"] == "date-time"


@pytest.mark.parametrize("tenant_id", [2**31, 2**53 + 1, 2**63 - 1])
def test_bigint_tenant_create_is_exact_and_scoped(setup, tenant_id):
    client, app, db = setup
    app.dependency_overrides[api.require_auth] = lambda: context(tenant=tenant_id)
    api.snapshot.return_value = {"tenant_id": tenant_id, "items": [metric()]}
    response = client.post(f"/api/v1/sem/tasks?tenant_id={tenant_id}", json=PAYLOAD)
    assert response.status_code == 201, response.text
    assert response.json()["tenant_id"] == tenant_id
    assert response.json()["baseline_snapshot"]["tenant_id"] == tenant_id
    api.ensure_module_access.assert_awaited_once_with(db, context(tenant=tenant_id), tenant_id, "sem")


def test_bigint_other_tenant_still_denied(setup):
    client, app, db = setup
    app.dependency_overrides[api.require_auth] = lambda: context(tenant=2**53 + 1)
    assert client.get(f"/api/v1/sem/tasks?tenant_id={2**53}").status_code == 403
    db.scalars.assert_not_awaited()


def test_bigint_overflow_rejected_before_database(setup):
    client, _, db = setup
    assert client.get(f"/api/v1/sem/tasks?tenant_id={2**63}").status_code == 422
    db.scalars.assert_not_awaited()


def test_task_ddl_and_mapper_use_bigint_tenant_id():
    from pathlib import Path
    from sqlalchemy import BigInteger
    from sqlalchemy.schema import CreateTable
    from app.models.sem_task import SemTask
    assert isinstance(SemTask.__table__.c.tenant_id.type, BigInteger)
    assert "tenant_id BIGINT NOT NULL" in str(CreateTable(SemTask.__table__).compile(dialect=postgresql.dialect()))
    assert "tenant_id BIGINT NOT NULL" in Path("docs/SEM_TASK_SCHEMA_REVIEW.sql").read_text()
