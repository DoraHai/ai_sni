"""Generate JSON-only local synthetic evidence, with all SQLite files in TEMP."""
from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from app.sem_phase0.contracts import LandingSubmission
from app.sem_phase0.store import AdvisorPrincipal, RevisionConflict, ScopeDenied, SubmissionStore
from app.sem_phase1a.contracts import ApplyRequest, BatchCreateRequest, RulingRequest, StructureRequest
from app.sem_phase1a.principals import LocalGrantPrincipalAdapter, SessionIdentity
from app.sem_phase1a.service import ShadowService
from app.sem_phase1a.sources import FIXTURES
from app.sem_phase1a.store import SQLiteShadowStore


def run(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    fixture = json.loads((FIXTURES / "slice2-pages.internal.json").read_text(encoding="utf-8"))
    principal = AdvisorPrincipal("synthetic-advisor", "advisor", frozenset({(101, 201)}))
    with TemporaryDirectory(prefix="sem-slice2-") as temp:
        temp = Path(temp)
        submissions = SubmissionStore(temp / "phase0.sqlite")
        for page in fixture["pages"]:
            submissions.submit(principal, LandingSubmission.model_validate(page), [])
        store = SQLiteShadowStore(temp / "shadow.sqlite")
        service = ShadowService(submissions, store)
        state = service.create(principal, BatchCreateRequest(tenant_id=101, account_id=201, pages=[
            {"page_id": p["landing_page_id"], "submission_revision": 1, "fixture_id": "fallback"} for p in fixture["pages"]]))
        state = service.rule(principal, state["plan_id"], RulingRequest(expected_version=1, reason="合成多页逐字段来源裁定"))
        multi = state
        campaign = next(r for r in state["rows"] if r["kind"] == "campaign")
        units = [r for r in state["rows"] if r["parent_id"] == campaign["row_id"] and r["kind"] == "unit"]
        keyword = next(r for r in state["rows"] if r["parent_id"] == units[0]["row_id"] and r["kind"] == "keyword")
        state = service.edit_structure(principal, state["plan_id"], StructureRequest(expected_version=2,
            reason="仅合成结构演练，正式客户确认仍待定", operations=[
                {"action": "update", "row_id": campaign["row_id"], "text": "合成甲乙产品线顾问改名"},
                {"action": "move_keyword", "row_id": keyword["row_id"], "parent_id": units[1]["row_id"]}]))
        structure = state
        restarted = ShadowService(SubmissionStore(submissions.path), SQLiteShadowStore(store.path))
        restart_equal = restarted.read(principal, state["plan_id"]) == state
        preview = restarted.preview(principal, state["plan_id"], restarted.export(principal, state["plan_id"], "advisor"), "advisor")
        applied = service.apply(principal, state["plan_id"], ApplyRequest(expected_version=3, preview_id=preview["preview_id"]))
        try:
            restarted.apply(principal, state["plan_id"], ApplyRequest(expected_version=3, preview_id=preview["preview_id"]))
            replay = "unexpected"
        except RevisionConflict:
            replay = "VERSION_CONFLICT"
        persistence = {"synthetic": True, "restart_equal": restart_equal, "preview": preview,
                       "applied_version": applied["version"], "replay_code": replay,
                       "apply_audit_count": sum(e["action"] == "advisor_preview_applied" for e in applied["audit"]),
                       "customer_confirmation": applied["customer_confirmation"],
                       "execution_export_enabled": applied["execution_export_enabled"]}
        auth_path = temp / "synthetic-auth.sqlite"
        with closing(sqlite3.connect(auth_path)) as db, db:
            db.executescript("""
                CREATE TABLE tenants(id INTEGER PRIMARY KEY);
                CREATE TABLE users(id INTEGER PRIMARY KEY,is_active INTEGER,locked_until TEXT,tenant_id INTEGER,role TEXT);
                CREATE TABLE advisor_tenant_grants(id INTEGER PRIMARY KEY,user_id INTEGER,tenant_id INTEGER,revoked_at TEXT);
                CREATE TABLE tenant_modules(tenant_id INTEGER,module_code TEXT,status TEXT,expires_at TEXT);
                CREATE TABLE baidu_accounts(id INTEGER PRIMARY KEY,tenant_id INTEGER,status TEXT);
                CREATE TABLE sem_phase1a_account_grants(user_id INTEGER,tenant_id INTEGER,account_id INTEGER,
                    advisor_grant_id INTEGER,revoked_at TEXT);
                INSERT INTO sem_phase1a_account_grants VALUES(1,101,201,10,NULL),(2,101,201,NULL,NULL);
                INSERT INTO tenants VALUES(101);
                INSERT INTO users VALUES(1,1,NULL,NULL,'advisor'),(2,1,NULL,101,'customer');
                INSERT INTO advisor_tenant_grants VALUES(10,1,101,NULL);
                INSERT INTO tenant_modules VALUES(101,'sem','active',NULL);
                INSERT INTO baidu_accounts VALUES(201,101,'active');
            """)
        adapter = LocalGrantPrincipalAdapter(auth_path, clock=lambda: datetime(2026, 10, 29, tzinfo=timezone.utc))
        auth = {"synthetic": True, "advisor_writable_accounts": sorted(adapter.resolve(SessionIdentity(1, "advisor", 101, 10)).writable_accounts),
                "customer_writable_accounts": sorted(adapter.resolve(SessionIdentity(2, "customer", 101)).writable_accounts),
                "customer_readable_accounts": sorted(adapter.resolve(SessionIdentity(2, "customer", 101)).readable_accounts)}
        with closing(sqlite3.connect(auth_path)) as db, db:
            db.execute("UPDATE tenant_modules SET status='suspended'")
        auth["suspended_denied"] = {}
        for role, identity in (("advisor", SessionIdentity(1, "advisor", 101, 10)), ("customer", SessionIdentity(2, "customer", 101))):
            try:
                adapter.resolve(identity)
                auth["suspended_denied"][role] = False
            except ScopeDenied:
                auth["suspended_denied"][role] = True
        samples = {"slice2-multi-plan.internal.json": multi, "slice2-structure.internal.json": structure,
                   "slice2-persistence.internal.json": persistence, "slice2-auth.internal.json": auth}
        for filename, value in samples.items():
            (output / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return sorted(samples)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    print("\n".join(run(parser.parse_args().output)))
