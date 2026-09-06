"""Draft controlled SemTask entry. Deployment and production execution require approval.

No application imports, no environment DATABASE_URL, no credentials in argv.
Approval files are externally approved attestations, not cryptographic authorization.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import ssl
import stat
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location("sem_pinned_bundle", HERE / "bundle.py")
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)
TARGETS = {"sem_tasks", "sem_tasks_id_seq", "sem_tasks_pkey", "ix_sem_tasks_action", "ix_sem_tasks_queue"}
CATALOG_KEYS = ("relations", "columns", "constraints", "indexes")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def structural(report, without_tasks=False):
    return {key: [row for row in report[key]
                  if not without_tasks or row["relname"] not in TARGETS]
            for key in CATALOG_KEYS}


def check_window(a, now=None):
    now = now or datetime.now(timezone.utc)
    start = datetime.fromisoformat(a["not_before"])
    end = datetime.fromisoformat(a["expires_at"])
    if start.utcoffset() is None or end.utcoffset() is None:
        raise ValueError("Timezone required")
    if not start <= now < end or not 0 < (end - start).total_seconds() <= 3600:
        raise ValueError("Expired, future or overlong approval window")


def validate_approval(a):
    if (a["confirmation"] != "MIGRATE_SEM_TASKS_0095" or a["schema"] != "public"
            or a["start_revision"] != bundle.START or a["target_revision"] != bundle.TARGET):
        raise ValueError("Wrong migration contract")
    for key in ("checkout_commit", "seo_release_commit", "seo_rollback_commit"):
        if not re.fullmatch("[0-9a-f]{40}", a[key]):
            raise ValueError("Full reviewed commit required")
    for key in ("manifest_sha256", "baseline_sha256", "schema_sha256",
                "seo_release_sha256", "seo_rollback_sha256", "ca_bundle_sha256"):
        if not re.fullmatch("[0-9a-f]{64}", a[key]):
            raise ValueError("Reviewed SHA-256 required")
    for key in ("change_id", "operator", "reviewer", "backup_evidence", "restore_evidence",
                "pause_evidence", "seo_compatibility_evidence", "schema_review_evidence"):
        if not isinstance(a[key], str) or not a[key].strip() or a[key].upper() in {"TODO", "UNKNOWN", "TBD"}:
            raise ValueError("Missing external approval evidence")
    d = a["database"]
    if a["application_role"] != d["role"]:
        raise ValueError("Separate execution/application roles need a separately reviewed grant design")
    if set(d) != {"host", "port", "name", "role", "server_address", "server_port"}:
        raise ValueError("Explicit database identity required")
    if any(not isinstance(d[k], str) or not d[k].strip() for k in ("host", "name", "role", "server_address")):
        raise ValueError("Missing identity")
    if any(type(d[k]) is not int or not 1 <= d[k] <= 65535 for k in ("port", "server_port")):
        raise ValueError("Invalid port")
    check_window(a)


def checked_json(path, expected):
    raw = Path(path).read_bytes()
    if sha(raw) != expected:
        raise ValueError("Approval/baseline digest mismatch")
    return json.loads(raw)


def verify_checkout(commit):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT, stderr=subprocess.DEVNULL).decode().strip()
    if git("rev-parse", "HEAD") != commit or git("status", "--porcelain", "--untracked-files=all"):
        raise ValueError("Requires exact reviewed clean checkout")


def checked_baseline(a, report):
    if (report["read_only"] != "on" or report["isolation"] != "repeatable read"
            or report["inspected_schema"] != "public"):
        raise ValueError("Baseline must be a consistent read-only public snapshot")
    preconditions(a, report)
    if sha(canonical(structural(report))) != a["schema_sha256"]:
        raise ValueError("Baseline schema not approved")


def preconditions(a, report):
    d = a["database"]
    if (report["database"] != d["name"] or report["role"] != d["role"]
            or report["server_address"] != d["server_address"] or report["server_port"] != d["server_port"]):
        raise ValueError("Connected database identity mismatch")
    if report["version_tables"] != [{"schema_name": "public", "relkind": "r"}] or report["revisions"] != [bundle.START]:
        raise ValueError("Expected a unique physical version table and single 0094")
    if set(report["target_relations"]) != TARGETS or any(v is not False for v in report["target_relations"].values()):
        raise ValueError("Target object already exists or report incomplete")
    expected_privileges = {"schema_usage", "schema_create", "tenants_references", "version_select", "version_update"}
    if set(report["privileges"]) != expected_privileges or any(v is not True for v in report["privileges"].values()):
        raise ValueError("Required privilege missing")
    columns = [c for c in report["columns"] if c["relname"] == "tenants" and c["attname"] == "id"]
    pks = [c for c in report["constraints"] if c["relname"] == "tenants" and c["contype"] == "p"]
    if len(columns) != 1 or columns[0]["type"] != "bigint" or columns[0]["attnotnull"] is not True:
        raise ValueError("Tenant id must be nonnull bigint")
    if len(pks) != 1 or pks[0]["definition"] != "PRIMARY KEY (id)":
        raise ValueError("Tenant primary key mismatch")


def postconditions(a, before, after):
    if after["revisions"] != [bundle.TARGET] or structural(after, True) != structural(before):
        raise ValueError("Unexpected schema/revision after migration")
    if set(after["target_relations"]) != TARGETS or not all(v is True for v in after["target_relations"].values()):
        raise ValueError("Target objects incomplete")
    expected = dict(id="bigint", tenant_id="bigint", module="character varying(8)",
                    action_type="character varying(64)", title="character varying(300)",
                    params="jsonb", status="character varying(20)", created_by="character varying(80)",
                    assignee_role="character varying(64)", baseline_snapshot="jsonb", completion_evidence="jsonb",
                    created_at="timestamp with time zone", updated_at="timestamp with time zone")
    cols = [c for c in after["columns"] if c["relname"] == "sem_tasks"]
    if {c["attname"]: c["type"] for c in cols} != expected or any(
            c["attnotnull"] != (c["attname"] != "completion_evidence") for c in cols):
        raise ValueError("Task column contract mismatch")
    rows = [r for r in after["relations"] if r["relname"] in {"sem_tasks", "sem_tasks_id_seq"}]
    if len(rows) != 2 or any(r["owner"] != a["application_role"] or r["relrowsecurity"] for r in rows):
        raise ValueError("Task ownership/policy mismatch")
    cs = [c for c in after["constraints"] if c["relname"] == "sem_tasks"]
    checks = {"ck_sem_tasks_" + s for s in ("module","action","status","role","params","baseline","evidence","done")}
    if len(cs) != 10 or {c["conname"] for c in cs if c["contype"] == "c"} != checks or not all(c["convalidated"] for c in cs):
        raise ValueError("Task check constraints incomplete")
    if [c["definition"] for c in cs if c["contype"] == "p"] != ["PRIMARY KEY (id)"]:
        raise ValueError("Task primary key mismatch")
    if [c["definition"] for c in cs if c["contype"] == "f"] != ["FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT"]:
        raise ValueError("Task tenant FK mismatch")
    indexes = [i for i in after["indexes"] if i["relname"] == "sem_tasks"]
    if ({i["index_name"] for i in indexes} != {"sem_tasks_pkey","ix_sem_tasks_action","ix_sem_tasks_queue"}
            or not all(i["indisvalid"] and i["indisready"] for i in indexes)):
        raise ValueError("Task indexes incomplete/invalid")


def configuration(path):
    cfg = bundle.configuration(path)  # Validates inventory, digests and one-step graph.
    cfg.set_main_option("path_separator", "os")
    cfg.set_main_option("version_locations", str((Path(path) / "migrations/versions").resolve()).replace("%", "%%"))
    cfg.set_main_option("script_location", str(HERE / "controlled").replace("%", "%%"))
    return cfg


async def snapshot(conn):
    from sqlalchemy import text
    sql = (HERE / "preflight-readonly.psql").read_text(encoding="utf-8")
    query = sql[sql.index("WITH relations AS ("):sql.rindex("ROLLBACK;")].strip().rstrip(";")
    result = await conn.scalar(text(query))
    return json.loads(result) if isinstance(result, str) else result


async def migrate_transaction(conn, cfg, a, baseline):
    """Caller owns the transaction. Failure propagates, never retries/commits here."""
    from sqlalchemy import text
    from alembic import command
    check_window(a)
    await conn.execute(text("SET LOCAL search_path = pg_catalog, public, pg_temp"))
    await conn.execute(text("SET LOCAL lock_timeout = '1s'"))
    await conn.execute(text("SET LOCAL statement_timeout = '10s'"))
    await conn.execute(text("LOCK TABLE public.alembic_version IN EXCLUSIVE MODE"))
    before = await snapshot(conn)
    preconditions(a, before)
    if structural(before) != structural(baseline):
        raise ValueError("Schema changed since approved baseline")
    # Unqualified CREATE must target public, while catalog functions remain first
    # via PostgreSQL's implicit pg_catalog lookup. Explicit pg_temp LAST prevents
    # temporary relation shadowing. Refuse any preexisting temp relations anyway.
    if await conn.scalar(text("SELECT count(*) FROM pg_class WHERE relnamespace=pg_my_temp_schema()")):
        raise ValueError("Temporary objects forbidden")
    await conn.execute(text("SET LOCAL search_path = public, pg_temp"))
    check_window(a)
    def upgrade(sync):
        cfg.attributes.update(connection=sync, controlled_target=bundle.TARGET)
        command.upgrade(cfg, bundle.TARGET)
    await conn.run_sync(upgrade)
    await conn.execute(text("SET LOCAL search_path = pg_catalog, public, pg_temp"))
    after = await snapshot(conn)
    postconditions(a, before, after)
    if await conn.scalar(text("SELECT count(*) FROM public.sem_tasks")) != 0:
        raise ValueError("Unexpected task data")
    # Same execution and application role for this first implementation. Different
    # role/grant deployment is intentionally unsupported until separately designed.
    if not await conn.scalar(text("SELECT (SELECT bool_and(has_table_privilege(current_user,'public.sem_tasks',p)) FROM unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE']) p) AND (SELECT bool_and(has_sequence_privilege(current_user,'public.sem_tasks_id_seq',p)) FROM unnest(ARRAY['USAGE','SELECT']) p)")):
        raise ValueError("New objects not usable by application role")
    check_window(a)


def credential_url(path, a):
    # Initial production entry targets Unix operators only. No weak Windows ACL fallback.
    if os.name != "posix":
        raise ValueError("Production credential adapter requires reviewed Unix permissions")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as f:
        s = os.fstat(f.fileno())
        if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1 or s.st_uid != os.geteuid() or s.st_mode & 0o077:
            raise ValueError("Credential file must be owner-only regular file")
        raw = f.read(16385)
        if len(raw) > 16384:
            raise ValueError("Credential file too large")
    return validate_url(raw.strip(), a)


def validate_url(raw, a):
    from sqlalchemy.engine import make_url
    url = make_url(raw)
    d = a["database"]
    if (url.drivername != "postgresql+asyncpg" or url.query or not url.password
            or (url.host, url.port, url.database, url.username) != (d["host"], d["port"], d["name"], d["role"])):
        raise ValueError("Credential identity mismatch")
    return url


def tls_context(path, expected_sha256):
    """Trust only the approved PEM bundle; never ambient OS/environment roots."""
    if not re.fullmatch("[0-9a-f]{64}", expected_sha256):
        raise ValueError("Reviewed CA SHA-256 required")
    with Path(path).open("rb") as f:
        raw = f.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024 or sha(raw) != expected_sha256:
        raise ValueError("CA bundle size/digest mismatch")
    pem = raw.decode("ascii")
    certificate = r"-----BEGIN CERTIFICATE-----\s+[A-Za-z0-9+/=\s]+-----END CERTIFICATE-----"
    if not re.fullmatch(r"\s*(?:" + certificate + r"\s*)+", pem):
        raise ValueError("CA bundle must contain PEM certificates only")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.check_hostname = True
    # Load exactly the bytes hashed above, not a second read of a mutable path.
    ctx.load_verify_locations(cadata=pem)
    if not ctx.cert_store_stats()["x509_ca"]:
        raise ValueError("CA bundle has no CA certificates")
    return ctx


async def apply(a, baseline, cfg, url, receipt, tls):
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool
    engine = create_async_engine(url, poolclass=NullPool, hide_parameters=True,
                                 connect_args={"ssl": tls, "timeout": 10})
    try:
        # Total timeout includes connection, locks, migration and COMMIT. If it
        # fires during COMMIT, outcome is unknown: inspect, never retry blindly.
        async with asyncio.timeout(min(60, (datetime.fromisoformat(a["expires_at"]) - datetime.now(timezone.utc)).total_seconds())):
            async with engine.begin() as conn:
                receipt("transaction_started")
                await migrate_transaction(conn, cfg, a, baseline)
                receipt("ready_to_commit")
            receipt("commit_acknowledged")
    finally:
        await engine.dispose()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=["fingerprint", "check", "apply"])
    p.add_argument("--approval")
    p.add_argument("--approval-sha256")
    p.add_argument("--baseline", required=True)
    p.add_argument("--bundle")
    p.add_argument("--credential-file")
    p.add_argument("--ca-file")
    p.add_argument("--receipt")
    args = p.parse_args()
    if args.mode == "fingerprint":
        raw = Path(args.baseline).read_bytes()
        report = json.loads(raw)
        print(json.dumps({"baseline_sha256": sha(raw), "schema_sha256": sha(canonical(structural(report)))}))
        return
    if not args.approval or not args.approval_sha256 or not args.bundle or not args.ca_file:
        raise ValueError("Approval, externally verified approval digest, source bundle and CA file required")
    a = checked_json(args.approval, args.approval_sha256)
    validate_approval(a)
    tls = tls_context(args.ca_file, a["ca_bundle_sha256"])
    verify_checkout(a["checkout_commit"])
    baseline = checked_json(args.baseline, a["baseline_sha256"])
    checked_baseline(a, baseline)
    manifest = Path(args.bundle) / "MANIFEST.json"
    if sha(manifest.read_bytes()) != a["manifest_sha256"]:
        raise ValueError("Unapproved source manifest")
    cfg = configuration(args.bundle)
    if args.mode == "check":
        print("offline_contract=passed; production_readiness=requires_external_review")
        return
    if not args.credential_file or not args.receipt:
        raise ValueError("Credential adapter and exclusive audit receipt required")
    url = credential_url(args.credential_file, a)
    fd = os.open(args.receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as log:
        def receipt(phase):
            log.write(json.dumps({"phase": phase, "at": datetime.now(timezone.utc).isoformat(),
                                  "approval_sha256": args.approval_sha256,
                                  "commit": a["checkout_commit"], "target": bundle.TARGET}) + "\n")
            log.flush()
            os.fsync(log.fileno())
        receipt("validated")
        try:
            asyncio.run(apply(a, baseline, cfg, url, receipt, tls))
        except BaseException:
            receipt("not_confirmed_requires_readonly_reconciliation")
            raise
    print("migration=0095_sem_tasks; commit_acknowledged; keep_feature_disabled")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("controlled_entry_refused_or_failed=" + type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
