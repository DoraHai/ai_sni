"""Synthetic local databases only. No app.main/config/.env or remote clients."""
import copy
import io
import json
import multiprocessing
import socket
import sqlite3
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.sem_phase0.contracts import LandingSubmission
from app.sem_phase0.screenshots import Screenshot, clean_screenshot
from app.sem_phase0.store import AdvisorPrincipal, RevisionConflict, ScopeDenied, SubmissionStore
from app.sem_phase1a.contracts import (ApplyRequest, ApprovalRequest, BatchCreateRequest, CreateRequest,
                                      RulingRequest, Source, StructureRequest)
from app.sem_phase1a.errors import ShadowError
from app.sem_phase1a.planning import checks, negative_matches
from app.sem_phase1a.principals import LocalGrantPrincipalAdapter, SessionIdentity, principal_dependency
from app.sem_phase1a.router import create_router
from app.sem_phase1a.service import ShadowService, digest
from app.sem_phase1a.sources import FIXTURES, comparisons
from app.sem_phase1a.store import SQLiteShadowStore

from sem_phase1a_auth_fixture import auth_db, adapter

ROOT = "/api/v1/sem/phase1a/shadow/plans"


def principal():
    return AdvisorPrincipal("synthetic-advisor", "advisor", frozenset({(101, 201)}))


def payload(**changes):
    data = json.loads((FIXTURES / "submission.internal.json").read_text(encoding="utf-8"))
    return LandingSubmission.model_validate({**data, **changes})


@pytest.fixture
def env(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("合成测试禁止网络")
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    submissions = SubmissionStore(tmp_path / "submissions.sqlite")
    submissions.submit(principal(), payload(), [])
    service = ShadowService(submissions, SQLiteShadowStore(tmp_path / "shadow.sqlite"))
    return submissions, service


def generated(service):
    state = service.create(principal(), CreateRequest(tenant_id=101, account_id=201,
                           page_id="synthetic-page", submission_revision=1))
    return service.rule(principal(), state["plan_id"], RulingRequest(expected_version=1, reason="合成裁定"))


def edit(service, state, *operations):
    return service.edit_structure(principal(), state["plan_id"], StructureRequest(
        expected_version=state["version"], reason="合成结构调整", operations=list(operations)))


def client(service, who=None, dependency=None):
    app = FastAPI()
    app.include_router(create_router(service, dependency or (lambda: who or principal())))
    return TestClient(app)


def test_restart_preserves_plans_rulings_approvals_history_and_preview(env):
    submissions, service = env
    state = generated(service)
    state = service.approve(principal(), state["plan_id"], ApprovalRequest(expected_version=2,
                            row_ids=[r["row_id"] for r in state["rows"]], reason="合成逐项审阅"))
    exported = service.export(principal(), state["plan_id"], "advisor")
    preview = service.preview(principal(), state["plan_id"], exported, "advisor")
    before = service.read(principal(), state["plan_id"])
    restarted = ShadowService(SubmissionStore(submissions.path), SQLiteShadowStore(service.store.path))
    assert restarted.read(principal(), state["plan_id"]) == before
    after = restarted.apply(principal(), state["plan_id"], ApplyRequest(
        expected_version=2, preview_id=preview["preview_id"]))
    assert after["version"] == 3 and after["rulings"] == before["rulings"]
    assert after["approvals"] == {} and len(after["history"][-1]["approvals"]) == len(after["rows"])
    assert not after["execution_export_enabled"] and after["customer_confirmation"] == "pending"


def _apply_process(submission_path, shadow_path, plan_id, preview_id, barrier, results):
    # Explicit spawn target: each process uses independent objects/connections.
    socket.create_connection = lambda *a, **kw: (_ for _ in ()).throw(AssertionError("network forbidden"))
    service = ShadowService(SubmissionStore(submission_path), SQLiteShadowStore(shadow_path))
    barrier.wait(timeout=30)
    try:
        state = service.apply(principal(), plan_id, ApplyRequest(expected_version=2, preview_id=preview_id))
        results.put(("applied", state["version"]))
    except RevisionConflict:
        results.put(("conflict", None))


def test_multiprocess_only_one_consumption(env):
    submissions, service = env
    state = generated(service)
    preview = service.preview(principal(), state["plan_id"], service.export(principal(), state["plan_id"], "advisor"), "advisor")
    context = multiprocessing.get_context("spawn")
    barrier, results = context.Barrier(3), context.Queue()
    processes = [context.Process(target=_apply_process, args=(submissions.path, service.store.path,
                 state["plan_id"], preview["preview_id"], barrier, results)) for _ in range(2)]
    try:
        for process in processes:
            process.start()
        barrier.wait(timeout=30)
        outcomes = [results.get(timeout=30), results.get(timeout=30)]
        for process in processes:
            process.join(timeout=30)
            assert process.exitcode == 0
        assert sorted(outcomes) == [("applied", 3), ("conflict", None)]
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join()
        results.close()
    after = service.read(principal(), state["plan_id"])
    assert after["version"] == 3
    assert sum(e["action"] == "advisor_preview_applied" for e in after["audit"]) == 1
    with service.store.transaction() as tx:
        assert tx.previews.get(preview["preview_id"])["preview"]["applied"]


def test_multiconnection_competing_previews_and_no_lost_audit(env):
    submissions, service = env
    state = generated(service)
    services = [ShadowService(submissions, SQLiteShadowStore(service.store.path)) for _ in range(4)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda svc: svc.export(principal(), state["plan_id"], "advisor"), services))
    assert sum(e["action"] == "excel_exported_internal_only" for e in service.read(principal(), state["plan_id"])["audit"]) == 4
    data = service.export(principal(), state["plan_id"], "advisor")
    previews = [svc.preview(principal(), state["plan_id"], data, "advisor") for svc in services[:2]]
    def apply(pair):
        svc, preview = pair
        try:
            svc.apply(principal(), state["plan_id"], ApplyRequest(expected_version=2, preview_id=preview["preview_id"]))
            return "applied"
        except RevisionConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(apply, zip(services, previews))) == ["applied", "conflict"]


def test_failed_commit_rolls_back_plan_and_preview(env, monkeypatch):
    _, service = env
    state = generated(service)
    preview = service.preview(principal(), state["plan_id"], service.export(principal(), state["plan_id"], "advisor"), "advisor")
    before = service.read(principal(), state["plan_id"])
    from app.sem_phase1a.store import _Records
    real_flush = _Records.flush
    def fail_on_preview(records):
        if records.table == "shadow_previews":
            raise RuntimeError("synthetic commit failure")
        real_flush(records)
    with monkeypatch.context() as patch:
        patch.setattr(_Records, "flush", fail_on_preview)
        with pytest.raises(RuntimeError):
            service.apply(principal(), state["plan_id"], ApplyRequest(expected_version=2, preview_id=preview["preview_id"]))
    assert service.read(principal(), state["plan_id"]) == before
    with service.store.transaction() as tx:
        assert not tx.previews.get(preview["preview_id"])["preview"]["applied"]
    assert service.apply(principal(), state["plan_id"], ApplyRequest(expected_version=2, preview_id=preview["preview_id"]))["version"] == 3


def test_storage_cas_rejects_stale_revision(env):
    _, service = env
    state = generated(service)
    before = service.read(principal(), state["plan_id"])
    with pytest.raises(RevisionConflict):
        with service.store.transaction() as tx:
            value = tx.plans.get(state["plan_id"])
            tx.plans.loaded[state["plan_id"]][0] -= 1  # synthetic stale storage revision
            value["version"] += 1
    assert service.read(principal(), state["plan_id"]) == before


def test_preview_expiry_cleanup_and_restart(env):
    submissions, initial = env
    clock = [1000.0]
    service = ShadowService(submissions, initial.store, clock=lambda: clock[0], preview_ttl=10)
    state = generated(service)
    preview = service.preview(principal(), state["plan_id"], service.export(principal(), state["plan_id"], "advisor"), "advisor")
    assert preview["expires_at"] == 1010
    assert service.cleanup_previews() == 0
    clock[0] = 1010
    with pytest.raises(ShadowError) as exc:
        service.apply(principal(), state["plan_id"], ApplyRequest(expected_version=2, preview_id=preview["preview_id"]))
    assert exc.value.code == "PREVIEW_EXPIRED"
    assert service.read(principal(), state["plan_id"])["version"] == 2
    assert service.cleanup_previews() == 1 and service.cleanup_previews() == 0
    with service.store.transaction() as tx:
        assert tx.previews.get(preview["preview_id"]) is None


def make_batch(submissions, service, periods=None):
    periods = periods or ["daily"] * 3
    for index, (line, word) in enumerate((("line-a", "甲"), ("line-a", "乙"), ("line-b", "丙")), 1):
        submissions.submit(principal(), payload(product_line_id=line, landing_page_id=f"page-{index}",
            landing_url=f"https://example.invalid/synthetic-{index}", budget_cents=1000*index,
            budget_period=periods[index-1], page_content=f"product: 合成{word}产品\nbenefit: 合成{word}优势\nkeywords: 合成{word}关键词",
            negative_keywords=[f"合成{word}禁词"]), [])
    return service.create(principal(), BatchCreateRequest(tenant_id=101, account_id=201, pages=[
        {"page_id": f"page-{i}", "submission_revision": 1, "fixture_id": "fallback"} for i in range(1, 4)]))


def test_multi_product_multi_page_budget_sources_expiry_and_roundtrip(env):
    submissions, service = env
    state = make_batch(submissions, service)
    state = service.rule(principal(), state["plan_id"], RulingRequest(expected_version=1, reason="合成多页裁定"))
    assert len([r for r in state["rows"] if r["kind"] == "campaign"]) == 2
    assert len([r for r in state["rows"] if r["kind"] == "unit"]) == 3
    assert state["rows"][0]["budget_cents"] == 6000
    assert sorted(r["budget_cents"] for r in state["rows"] if r["kind"] == "campaign") == [3000, 3000]
    assert state["p5"]["passed"]
    assert not {"budget_tree", "declared_boundary", "structure", "conflicts"}.intersection(i["rule"] for i in state["p6"]["issues"])
    assert all(set(r["source_refs"]) <= {s["source_id"] for s in state["sources"]} for r in state["rows"])
    data = service.export(principal(), state["plan_id"], "advisor")
    preview = service.preview(principal(), state["plan_id"], data, "advisor")
    assert not preview["changes"]
    suggestions = service.expiry(principal(), state["plan_id"], datetime.fromisoformat("2026-11-09T00:00:00+08:00"))
    assert {s["page_id"] for s in suggestions} == {"page-1", "page-2", "page-3"}
    assert len({tuple(s["source_refs"]) for s in suggestions}) == 3
    submissions.submit(principal(), payload(product_line_id="line-b", landing_page_id="page-3",
        landing_url="https://example.invalid/synthetic-3", expected_revision=1), [])
    with pytest.raises(RevisionConflict):
        service.read(principal(), state["plan_id"])


def test_multi_page_mixed_period_rejected(env):
    submissions, service = env
    with pytest.raises(ShadowError) as exc:
        make_batch(submissions, service, ["daily", "total", "daily"])
    assert exc.value.code == "BUDGET_INVALID"
    with closing(sqlite3.connect(service.store.path)) as db, db:
        assert db.execute("SELECT count(*) FROM shadow_plans").fetchone()[0] == 0


def test_duplicate_page_reference_and_cross_account_blocked(env):
    _, service = env
    with pytest.raises(ValueError):
        BatchCreateRequest(tenant_id=101, account_id=201, pages=[{"page_id": "same", "submission_revision": 1}]*2)
    with pytest.raises(ScopeDenied):
        service.create(principal(), BatchCreateRequest(tenant_id=102, account_id=202,
            pages=[{"page_id": "synthetic-page", "submission_revision": 1}]))


def test_structure_add_update_move_delete_audit_and_invalidation(env):
    _, service = env
    state = generated(service)
    state = service.approve(principal(), state["plan_id"], ApprovalRequest(expected_version=2,
        row_ids=[r["row_id"] for r in state["rows"]], reason="演练审阅"))
    project, campaign, unit, keyword = state["rows"][:4]
    preview = service.preview(principal(), state["plan_id"], service.export(principal(), state["plan_id"], "advisor"), "advisor")
    state = edit(service, state, {"action": "add_campaign", "parent_id": project["row_id"], "text": "新增合成方案", "budget_cents": 4000})
    new_campaign = next(r for r in state["rows"] if r["text"] == "新增合成方案")
    assert not state["approvals"] and state["history"][-1]["approvals"]
    assert {"budget_tree", "structure"} <= {i["rule"] for i in state["p6"]["issues"]}
    state = edit(service, state, {"action": "add_unit", "parent_id": new_campaign["row_id"], "text": "新增合成单元", "budget_cents": 4000},
        {"action": "update", "row_id": campaign["row_id"], "budget_cents": 8000, "text": "改名合成方案"},
        {"action": "update", "row_id": unit["row_id"], "budget_cents": 8000})
    new_unit = next(r for r in state["rows"] if r["text"] == "新增合成单元")
    assert not {"budget_tree", "structure"}.intersection(i["rule"] for i in state["p6"]["issues"])
    state = edit(service, state, {"action": "move_keyword", "row_id": keyword["row_id"], "parent_id": new_unit["row_id"]})
    moved = next(r for r in state["rows"] if r["row_id"] == keyword["row_id"])
    assert moved["parent_id"] == new_unit["row_id"] and moved["source_refs"] == keyword["source_refs"]
    state = edit(service, state, {"action": "delete", "row_id": new_unit["row_id"]})
    assert not {new_unit["row_id"], keyword["row_id"]}.intersection(r["row_id"] for r in state["rows"])
    state = edit(service, state, {"action": "delete", "row_id": new_campaign["row_id"]},
        {"action": "update", "row_id": campaign["row_id"], "budget_cents": 12000},
        {"action": "update", "row_id": unit["row_id"], "budget_cents": 12000})
    events = [e for e in state["audit"] if e["action"] == "structure_edited"]
    assert len(events) == 9
    assert all(e["details"]["reason"] and "p5" in e["details"] and "p6" in e["details"] for e in events)
    assert not state["enable_allowed"] and state["customer_confirmation"] == "pending"
    with pytest.raises(RevisionConflict):
        service.apply(principal(), state["plan_id"], ApplyRequest(expected_version=state["version"], preview_id=preview["preview_id"]))


@pytest.mark.parametrize("operation", [
    {"action": "delete", "row_id": "r-1"},
    {"action": "update", "row_id": "r-4", "text": "不允许"},
    {"action": "move_keyword", "row_id": "r-4", "parent_id": "r-1"},
    {"action": "add_unit", "parent_id": "r-1", "text": "单元", "budget_cents": 1},
    {"action": "add_campaign", "parent_id": "r-1", "text": "方案", "budget_cents": 1, "source_refs": ["unknown"]},
    {"action": "delete", "row_id": "r-2", "text": "ignored?"},
])
def test_structure_failure_atomic_including_prior_operation(env, operation):
    _, service = env
    state = generated(service)
    before = service.read(principal(), state["plan_id"])
    with pytest.raises(ShadowError):
        edit(service, state, {"action": "update", "row_id": "r-2", "text": "应回滚"}, operation)
    assert service.read(principal(), state["plan_id"]) == before


def test_api_batch_structure_and_codes_without_input_echo(env):
    submissions, service = env
    make_batch(submissions, service)
    api = client(service)
    created = api.post(ROOT + "/batch", json={"tenant_id": 101, "account_id": 201,
        "pages": [{"page_id": "page-1", "submission_revision": 1}]})
    assert created.status_code == 201
    pid = created.json()["plan_id"]
    assert api.post(f"{ROOT}/{pid}/rulings", json={"expected_version": 1, "reason": "合成"}).status_code == 200
    response = api.post(f"{ROOT}/{pid}/structure", json={"expected_version": 2, "reason": "合成",
        "operations": [{"action": "update", "row_id": "r-2", "text": "合成改名"}]})
    assert response.status_code == 200 and response.json()["version"] == 3
    invalid = api.post(ROOT, json={"tenant_id": "never-echo-untrusted", "page_id": "also-untrusted"})
    assert invalid.json()["detail"]["code"] == "CONTRACT_INVALID" and "untrusted" not in invalid.text
    stale = api.post(f"{ROOT}/{pid}/structure", json={"expected_version": 2, "reason": "never-echo-untrusted",
        "operations": [{"action": "delete", "row_id": "r-2"}]})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "VERSION_CONFLICT" and "untrusted" not in stale.text
    invalid_excel = api.post(f"{ROOT}/{pid}/previews/advisor", files={"file": ("internal.xlsx", b"never-echo-untrusted")})
    assert invalid_excel.json()["detail"]["code"] == "EXCEL_INVALID_OR_TAMPERED" and "untrusted" not in invalid_excel.text


@pytest.mark.parametrize("change", ["remove", "source", "hash", "actor", "reason", "at"])
def test_p6_checks_each_conflict_decision(env, change):
    _, service = env
    state = generated(service)
    field = next(c["field"] for c in state["comparisons"] if c["conflict"])
    rulings = copy.deepcopy(state["rulings"])
    if change == "remove":
        del rulings[-1]["decisions"][field]
    else:
        key = {"source": "source_id", "hash": "artifact_sha256"}.get(change, change)
        rulings[-1]["decisions"][field][key] = "wrong" if change in {"source", "hash"} else ""
    from app.sem_phase1a.contracts import PlanRow
    report = checks([PlanRow.model_validate(r) for r in state["rows"]],
        [Source.model_validate(s) for s in state["sources"]], state["budget_cap_cents"], state["selected"], rulings)
    assert "conflicts" in {i["rule"] for i in report["issues"]}


@pytest.mark.parametrize("negative,positive,hit", [
    ("免费", "免费", True), ("免费", "付费咨询", False), ("免费", "免费试用", False),
    ("费", "费用咨询", False), ("维修", "汽车维修", False), ("免费 维修", "服务 免费，维修 咨询", True),
    ("免费维修", "合成 免费维修 咨询", True), ("free", "carefree", False),
    ("free", "FREE repair", True), ("free repair", "free-repair services", True),
    ("免费", "abc免费123", True), ("ＡＢＣ", "abc service", True), ("", "anything", False),
])
def test_negative_phrase_boundaries(negative, positive, hit):
    assert negative_matches(negative, positive) == hit


def test_source_priority_independent_of_collection_order(env):
    _, service = env
    state = generated(service)
    sources = [Source.model_validate(s) for s in state["sources"]]
    assert comparisons(sources) == comparisons(list(reversed(sources)))
    assert next(c for c in comparisons(sources) if c["field"] == "benefit")["candidates"][0]["origin"] == "fixture_html"


def test_no_deadline_human_readable(env):
    submissions, service = env
    submissions.submit(principal(), payload(expected_revision=1, case_type="new_product", ends_at=None, no_deadline_explicit=True), [])
    state = service.create(principal(), CreateRequest(tenant_id=101, account_id=201, page_id="synthetic-page", submission_revision=2))
    state = service.rule(principal(), state["plan_id"], RulingRequest(expected_version=1, reason="无截止合成"))
    assert "无截止" in next(r["text"] for r in state["rows"] if r["kind"] == "timing")
    assert service.expiry(principal(), state["plan_id"], datetime.fromisoformat("2026-11-09T00:00:00+08:00")) == []


@pytest.mark.parametrize("fmt,name,mime,expected_warnings", [
    ("PNG", "shot.jpg", "image/jpeg", ["EXTENSION_MISMATCH", "MIME_MISMATCH"]),
    ("PNG", "shot.png", "application/octet-stream", ["MIME_MISMATCH"]),
    ("JPEG", "shot.txt", "image/jpeg", ["EXTENSION_MISMATCH"]),
    ("WEBP", "shot.webp", "image/webp", []),
])
def test_screenshot_decode_wins_over_filename_mime(fmt, name, mime, expected_warnings):
    out = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(out, format=fmt)
    data, meta = clean_screenshot(Screenshot("page", name, mime, out.getvalue()))
    assert meta["warnings"] == expected_warnings
    assert Image.open(io.BytesIO(data)).format == "PNG"


@pytest.mark.parametrize("fmt", ["GIF", "BMP", "TIFF"])
def test_screenshot_decoded_format_whitelist(fmt):
    out = io.BytesIO()
    Image.new("RGB", (8, 8)).save(out, format=fmt)
    with pytest.raises(ValueError):
        clean_screenshot(Screenshot("page", "forged.png", "image/png", out.getvalue()))


@pytest.mark.parametrize("corruption", ["contract", "hash", "scope", "revision"])
def test_phase0_read_revalidates_persisted_payload(env, corruption):
    submissions, _ = env
    data = payload().model_dump(mode="json")
    if corruption == "contract":
        data["case_type"] = "page_change"
    if corruption == "scope":
        data["tenant_id"] = 102
    if corruption == "revision":
        data["expected_revision"] = 99
    with closing(sqlite3.connect(submissions.path)) as db, db:
        db.execute("UPDATE phase0_submissions SET payload=?,payload_sha256=?",
            (json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")), "wrong" if corruption == "hash" else digest(data)))
    with pytest.raises(ValueError, match="存储校验失败"):
        submissions.read(principal(), 101, 201, "synthetic-page", 1)


def test_authorization_read_only_and_no_cache(auth_db):
    reader = adapter(auth_db)
    before = auth_db.read_bytes()
    who = reader.resolve(SessionIdentity(1, "advisor", 101, 10))
    assert who.writable_accounts == frozenset({(101, 201)}) and auth_db.read_bytes() == before
    assert reader.resolve(SessionIdentity(1, "advisor", 102, 20)).writable_accounts == frozenset({(102, 202)})
    with closing(sqlite3.connect(auth_db)) as db, db:
        db.execute("UPDATE advisor_tenant_grants SET revoked_at='2026-10-29' WHERE id=10")
    with pytest.raises(ScopeDenied):
        reader.resolve(SessionIdentity(1, "advisor", 101, 10))


@pytest.mark.parametrize("sql", [
    "UPDATE users SET is_active=0 WHERE id=1",
    "UPDATE users SET locked_until='2026-11-01T00:00:00+00:00' WHERE id=1",
    "UPDATE users SET tenant_id=102 WHERE id=1",
    "UPDATE tenant_modules SET status='suspended' WHERE tenant_id=101",
    "UPDATE tenant_modules SET status='closed' WHERE tenant_id=101",
    "UPDATE tenant_modules SET expires_at='2026-10-28' WHERE tenant_id=101",
    "DELETE FROM tenant_modules WHERE tenant_id=101",
    "DROP TABLE advisor_tenant_grants",
    "DELETE FROM tenants WHERE id=101",
])
def test_authorization_fail_closed(auth_db, sql):
    with closing(sqlite3.connect(auth_db)) as db, db:
        db.execute(sql)
    with pytest.raises(ScopeDenied):
        adapter(auth_db).resolve(SessionIdentity(1, "advisor", 101, 10))


@pytest.mark.parametrize("identity", [SessionIdentity(1, "advisor", 101, 20), SessionIdentity(1, "advisor", None, 10),
    SessionIdentity(1, "admin", 101, 10), SessionIdentity(3, "customer", 101), SessionIdentity(999, "advisor", 101, 10)])
def test_authorization_cross_scope_and_unknown_identity(auth_db, identity):
    with pytest.raises(ScopeDenied):
        adapter(auth_db).resolve(identity)


def test_customer_read_only_and_suspended_denied_all_routes(env, auth_db):
    _, service = env
    state = generated(service)
    dependency = principal_dependency(adapter(auth_db), lambda: SessionIdentity(2, "customer", 101))
    api = client(service, dependency=dependency)
    pid = state["plan_id"]
    assert api.get(f"{ROOT}/{pid}").status_code == 200
    assert api.get(f"{ROOT}/{pid}/expiry-suggestions").status_code == 200
    for endpoint, body in [
        ("rulings", {"expected_version": 2, "reason": "合成"}),
        ("approvals", {"expected_version": 2, "row_ids": ["r-1"], "reason": "合成"}),
        ("apply-preview", {"expected_version": 2, "preview_id": "missing"}),
        ("structure", {"expected_version": 2, "reason": "合成", "operations": [{"action": "delete", "row_id": "r-2"}]}),
    ]:
        assert api.post(f"{ROOT}/{pid}/{endpoint}", json=body).status_code == 403
    assert api.get(f"{ROOT}/{pid}/excel/advisor").status_code == 403
    assert api.post(f"{ROOT}/{pid}/previews/advisor", files={"file": ("internal.xlsx", b"not read")}).status_code == 403
    with closing(sqlite3.connect(auth_db)) as db, db:
        db.execute("UPDATE tenant_modules SET status='suspended' WHERE tenant_id=101")
    assert api.get(f"{ROOT}/{pid}").status_code == 403
    advisor_api = client(service, dependency=principal_dependency(adapter(auth_db), lambda: SessionIdentity(1, "advisor", 101, 10)))
    assert advisor_api.get(f"{ROOT}/{pid}").status_code == 403
    assert advisor_api.post(f"{ROOT}/{pid}/rulings", json={"expected_version": 2, "reason": "合成"}).status_code == 403


@pytest.mark.parametrize("kind,expected", [("duplicate", "DUPLICATE_BLOCKED"), ("budget", "BUDGET_INVALID")])
def test_api_actionable_check_codes(env, kind, expected):
    from openpyxl import load_workbook

    _, service = env
    state = generated(service)
    data = service.export(principal(), state["plan_id"], "advisor")
    book = load_workbook(io.BytesIO(data))
    book["内部规划"]["D8" if kind == "duplicate" else "E5"] = "合成旧型号滤芯" if kind == "duplicate" else 999999
    out = io.BytesIO()
    book.save(out)
    book.close()
    preview = service.preview(principal(), state["plan_id"], out.getvalue(), "advisor")
    state = service.apply(principal(), state["plan_id"], ApplyRequest(expected_version=2, preview_id=preview["preview_id"]))
    response = client(service).post(f"{ROOT}/{state['plan_id']}/approvals", json={"expected_version": 3,
        "row_ids": ["r-1"], "reason": "never-echo-untrusted"})
    assert response.status_code == 422 and response.json()["detail"]["code"] == expected
    assert "untrusted" not in response.text


def test_screenshot_limits_still_enforced(monkeypatch):
    from app.sem_phase0 import screenshots

    out = io.BytesIO()
    Image.new("RGB", (8, 8)).save(out, format="PNG")
    item = Screenshot("page", "wrong.jpg", "image/jpeg", out.getvalue())
    for limit in ("MAX_IMAGE_BYTES", "MAX_PIXELS", "MAX_EDGE"):
        with monkeypatch.context() as patch:
            patch.setattr(screenshots, limit, 1)
            with pytest.raises(ValueError):
                clean_screenshot(item)


def test_structure_rechecks_negative_scope_after_keyword_move(env):
    from app.sem_phase1a.planning import negative_overlap_ok
    from app.sem_phase1a.contracts import PlanRow

    rows = [PlanRow(row_id="c", parent_id="root", kind="campaign", text="方案", source_refs=["s"],
                    verification="pending_verification", budget_cents=2),
            PlanRow(row_id="u1", parent_id="c", kind="unit", text="一", source_refs=["s"],
                    verification="pending_verification", budget_cents=1),
            PlanRow(row_id="u2", parent_id="c", kind="unit", text="二", source_refs=["s"],
                    verification="pending_verification", budget_cents=1),
            PlanRow(row_id="n", parent_id="u1", kind="negative_keyword", text="免费", source_refs=["s"],
                    verification="source_confirmed"),
            PlanRow(row_id="k", parent_id="u2", kind="keyword", text="免费", source_refs=["s"],
                    verification="pending_verification")]
    assert negative_overlap_ok(rows)
    rows[-1] = rows[-1].model_copy(update={"parent_id": "u1"})
    assert not negative_overlap_ok(rows)


def test_demo_outputs_actual_persistence_evidence(tmp_path, monkeypatch):
    from app.sem_phase1a.demo_slice2 import run

    monkeypatch.setattr(socket, "create_connection", lambda *a, **kw: pytest.fail("network forbidden"))
    output = tmp_path / "samples"
    names = run(output)
    assert len(names) == 4
    evidence = json.loads((output / "slice2-persistence.internal.json").read_text(encoding="utf-8"))
    assert evidence["restart_equal"] and evidence["apply_audit_count"] == 1 and evidence["replay_code"] == "VERSION_CONFLICT"
    auth = json.loads((output / "slice2-auth.internal.json").read_text(encoding="utf-8"))
    assert all(auth["suspended_denied"].values()) and auth["customer_writable_accounts"] == []
    assert not list(output.glob("*.sqlite*"))


def test_replaceable_store_and_concurrent_structure_versions(env):
    submissions, service = env
    state = generated(service)
    class StoreAdapter:
        def __init__(self, delegate):
            self.delegate = delegate
            self.transactions = 0
        def transaction(self):
            self.transactions += 1
            return self.delegate.transaction()
        def cleanup_previews(self, now):
            return self.delegate.cleanup_previews(now)
    store = StoreAdapter(service.store)
    services = [ShadowService(submissions, store), ShadowService(submissions, SQLiteShadowStore(service.store.path))]
    def change(svc):
        try:
            edit(svc, state, {"action": "update", "row_id": "r-2", "text": "合成并发改名"})
            return "edited"
        except RevisionConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(change, services)) == ["conflict", "edited"]
    assert store.transactions > 0 and service.read(principal(), state["plan_id"])["version"] == 3
