"""Opt-in local acceptance runner; never uses the application's .env.

No command runs on import. prepare/graph are offline. Database commands accept
only the named local test instance and keep a lifecycle manifest outside Git.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from uuid import uuid4
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = Path.home() / ".secrets" / "seo12-local"
CREDENTIAL_FILE = Path.home() / ".secrets" / "seo_workflow_test.env"
IDENTITY = ("127.0.0.1", 55432, "seo_workflow_test", "seo_workflow_tester")
BASE = "0104_seo_page_ai_tdk"
HEAD = "0105_seo_content_confirmations"
PORT = 8031


def validate_target(fields):
    try:
        target = (fields["PGHOST"], int(fields["PGPORT"]), fields["PGDATABASE"], fields["PGUSER"])
    except (KeyError, ValueError, TypeError):
        raise ValueError("Dedicated test database target is incomplete") from None
    if target != IDENTITY or not fields.get("PGPASSWORD"):
        raise ValueError("Only the designated local test database and ordinary test role are allowed")
    return URL.create("postgresql+asyncpg", username=target[3], password=fields["PGPASSWORD"],
                      host=target[0], port=target[1], database=target[2])


def database_url():
    from dotenv import dotenv_values
    # Never use DATABASE_URL from the shell, application .env, or file as fallback.
    return validate_target(dotenv_values(CREDENTIAL_FILE))


def read_state():
    return json.loads((STATE_DIR / "manifest.json").read_text(encoding="utf-8"))


def write_state(state):
    path = STATE_DIR / "manifest.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)


def prepare():
    if STATE_DIR.exists():
        raise ValueError("Lifecycle directory already exists; do not overwrite a previous run")
    # Parent is the operator's existing restricted secrets directory.
    if not STATE_DIR.parent.is_dir():
        raise ValueError("Restricted secrets parent directory must already exist")
    STATE_DIR.mkdir(mode=0o700)
    if os.name == "nt":
        user = subprocess.check_output(["whoami"], text=True).strip()
        locked = subprocess.run(["icacls", str(STATE_DIR), "/inheritance:r", "/grant:r",
                                 f"{user}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"], capture_output=True)
        if locked.returncode:
            raise ValueError("Could not restrict the new lifecycle directory; no identities written")
    credentials = {"jwt_secret": secrets.token_urlsafe(48),
                   "crypto_key": base64.b64encode(secrets.token_bytes(32)).decode(),
                   "accounts": {name: {"username": "seo12_" + name, "password": secrets.token_urlsafe(24)}
                                for name in ("customer", "advisor", "other_customer", "unassigned_advisor")}}
    fd = os.open(STATE_DIR / "identities.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(credentials, stream, ensure_ascii=False, indent=2)
    state = {"run_id": secrets.token_hex(12), "phase": "prepared",
             "created_at": datetime.now(timezone.utc).isoformat(), "target": list(IDENTITY),
             "migration_hashes": migration_hashes(), "external_actions": "disabled", "scheduler": "disabled"}
    write_state(state)
    print(json.dumps({"phase": "prepared", "state_directory": str(STATE_DIR), "database_connected": False}))


def migration_hashes():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "migrations" / "versions").glob("*.py"))}


def configure(url):
    """Only settings are supplied; auth/session dependencies remain real."""
    sys.path.insert(0, str(ROOT))
    from app import config
    values = {name: field.get_default(call_default_factory=True)
              for name, field in config.Settings.model_fields.items() if not field.is_required()}
    credentials = json.loads((STATE_DIR / "identities.json").read_text(encoding="utf-8"))
    values.update(database_url=url.render_as_string(hide_password=False), app_env="test",
                  app_host="127.0.0.1", app_port=PORT, app_base_url=f"http://127.0.0.1:{PORT}",
                  baidu_app_id="isolated", baidu_secret_key="", baidu_default_username="isolated",
                  baidu_default_ucid=1, baidu_self_access_token="", baidu_self_token_expires_at="2000-01-01T00:00:00Z",
                  crypto_master_key_b64=credentials["crypto_key"], admin_api_key="",
                  admin_api_key_query_enabled=False, jwt_secret=credentials["jwt_secret"],
                  seo_scheduler_enabled=False, seo_rank_scheduler_enabled=False,
                  seo_external_actions_enabled=False, seo_page_capture_enabled=False,
                  seo_demo_mode=False, seo_demo_data_source_enabled=False, chinaz_api_enabled=False)
    # Every Settings field has an explicit value, so inherited environment keys
    # cannot silently configure a provider or redirect the database.
    settings = config.Settings(_env_file=None, **values)
    config.get_settings = lambda: settings
    return settings


async def inventory(conn):
    queries = {
        "relations": """SELECT n.nspname AS schema,c.relname AS name,c.relkind::text AS kind,
          pg_get_userbyid(c.relowner) AS owner FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg_%' ORDER BY 1,2""",
        "functions": """SELECT n.nspname AS schema,p.proname AS name,
          pg_get_function_identity_arguments(p.oid) AS arguments,pg_get_userbyid(p.proowner) AS owner
          FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
          WHERE n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg_%' ORDER BY 1,2,3""",
        "types": """SELECT n.nspname AS schema,t.typname AS name,t.typtype::text AS kind,pg_get_userbyid(t.typowner) AS owner
          FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE t.typtype IN ('e','d')
          AND n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg_%' ORDER BY 1,2""",
        "extensions": "SELECT extname AS name,extversion AS version FROM pg_extension ORDER BY 1",
        "foreign_keys": """SELECT n.nspname AS schema,c.relname AS table_name,k.conname AS name,
          pg_get_constraintdef(k.oid) AS definition FROM pg_constraint k
          JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace
          WHERE k.contype='f' AND n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg_%' ORDER BY 1,2,3""",
    }
    return {key: [dict(row) for row in (await conn.execute(text(sql))).mappings()] for key, sql in queries.items()}


async def preflight(engine, *, empty=False):
    async with engine.connect() as conn:
        row = (await conn.execute(text("""SELECT current_database() AS db,current_user AS usr,
          inet_server_addr()::text AS host,inet_server_port() AS port,
          has_schema_privilege(current_user,'public','USAGE') AS can_use,
          has_schema_privilege(current_user,'public','CREATE') AS can_create,
          r.rolsuper,r.rolcreatedb,r.rolcreaterole FROM pg_roles r WHERE r.rolname=current_user"""))).mappings().one()
        if (row["host"], row["port"], row["db"], row["usr"]) != ("127.0.0.1/32", *IDENTITY[1:]):
            raise ValueError("Actual database identity does not match the approved local target")
        if any(row[k] for k in ("rolsuper", "rolcreatedb", "rolcreaterole")):
            raise ValueError("High-privilege roles are not allowed")
        if not row["can_use"] or not row["can_create"]:
            raise ValueError("Missing public USAGE/CREATE; no grant will be attempted")
        objects = await inventory(conn)
        if empty and any(objects[k] for k in ("relations", "functions", "types")):
            raise ValueError("Initial migration requires a dedicated empty database")
        return {"identity": dict(row), "objects": objects}


def engine_for(url):
    return create_async_engine(url, connect_args={"server_settings": {
        "search_path": "public", "lock_timeout": "5000", "statement_timeout": "120000"}})


async def inspect_database(url, *, empty=False):
    engine = engine_for(url)
    try:
        return await preflight(engine, empty=empty)
    finally:
        await engine.dispose()


def graph():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    scripts = ScriptDirectory.from_config(cfg)
    if scripts.get_heads() != [HEAD] or scripts.get_revision(HEAD).down_revision != BASE:
        raise ValueError("Unexpected migration graph")
    return {"head": HEAD, "parent": BASE, "revisions": len(list(scripts.walk_revisions(base="base", head=HEAD)))}


def upgrade(target):
    from alembic import command
    from alembic.config import Config
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(cfg, target)  # Actual env.py and all canonical revisions.


async def baseline_seed():
    from app.database import async_session_factory, engine
    from app.models.tenant import Tenant
    from app.models.role import Role
    from app.models.user import User
    from app.models.module_workspace import TenantModule, SeoSite
    from app.models.seo import SeoContentAsset, SeoKeywordAsset, SeoSitePage
    from app.models.seo_qa import SeoQaFact
    from app.security.auth import hash_password
    keys = ("seo.site", "seo.content", "seo.keywords", "seo.links", "seo.overview")
    secrets_file = json.loads((STATE_DIR / "identities.json").read_text(encoding="utf-8"))
    scope = {}
    async with async_session_factory() as session:
        customer_role = Role(name="SEO12 isolated customer", permissions={k: "view" for k in keys})
        advisor_role = Role(name="SEO12 isolated advisor", permissions={k: "edit" for k in keys})
        session.add_all([customer_role, advisor_role])
        await session.flush()
        for label in ("primary", "foreign"):
            tenant = Tenant(name=f"SEO12 合成客户 {label}", industry="仅本地验收", business_desc="合成资料，不代表真实客户")
            session.add(tenant)
            await session.flush()
            module = TenantModule(tenant_id=tenant.id, module_code="seo", status="active")
            session.add(module)
            await session.flush()
            site = SeoSite(tenant_id=tenant.id, tenant_module_id=module.id, name=f"合成站点 {label}",
                           domain=f"seo12-{label}.invalid", canonical_domain=f"seo12-{label}.invalid", status="active",
                           site_settings={"seo_service_plan": {"revision": 1, "status": "active",
                             "optimization_directions": ["核对合成资料"], "content_topics": ["合成选型指南"],
                             "content_ai_enabled": False, "content_cycle_enabled": False,
                             "website_cycle_enabled": False, "monitoring_cycle_enabled": False, "report_cycle_enabled": False}})
            session.add(site)
            await session.flush()
            scope[label] = {"tenant_id": tenant.id, "site_id": site.id}
        scope["users"] = {}
        for label, account in secrets_file["accounts"].items():
            customer = label in {"customer", "other_customer"}
            user = User(username=account["username"], password_hash=hash_password(account["password"]),
                        role_id=customer_role.id if customer else advisor_role.id, is_active=True,
                        tenant_id=scope["foreign" if label == "other_customer" else "primary"]["tenant_id"])
            session.add(user)
            await session.flush()
            scope["users"][label] = user.id
        target = scope["primary"]
        keyword = SeoKeywordAsset(**target, keyword="合成选型", status="active", source="manual")
        fact = SeoQaFact(**target, title="合成测试资料", statement="本资料仅用于本机验收，不含真实产品参数。",
                         source_name="SEO12 synthetic fixture", status="active")
        page = SeoSitePage(**target, url="https://seo12-primary.invalid/selection", status="needs_fix",
                           issue_codes=["h1_missing"], title="合成待检查页面")
        session.add_all([keyword, fact, page])
        await session.flush()
        content = SeoContentAsset(**target, title="合成选型指南", draft="<p>仅本地测试稿，等待顾问审核。</p>",
                                  outline="合成资料核对", content_type="article", status="drafting",
                                  keyword_id=keyword.id, keyword_ids=[keyword.id], version_count=1)
        session.add(content)
        await session.flush()
        scope.update(content_id=content.id, keyword_id=keyword.id, fact_id=fact.id, page_id=page.id,
                     report_period="2026-09", report_data="not_seeded_no_traffic_or_effect_claim")
        await session.commit()
    await engine.dispose()
    return scope


def quote_ident(value):
    return '"' + str(value).replace('"', '""') + '"'


async def table_fingerprints(conn, table_names):
    result = {}
    for table in table_names:
        rows = (await conn.execute(text(f"SELECT row_to_json(t)::text FROM public.{quote_ident(table)} t"))).scalars().all()
        encoded = json.dumps(sorted(rows), ensure_ascii=False).encode()
        result[table] = {"rows": len(rows), "sha256": hashlib.sha256(encoded).hexdigest()}
    return result


async def validate_upgrade(url, state):
    engine = engine_for(url)
    try:
        await preflight(engine)
        async with engine.connect() as conn:
            revision = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalars().all()
            if revision != [HEAD]:
                raise ValueError("Upgrade did not reach the exact expected head")
            if not state["baseline_data"] or state["baseline_data"].get("seo_content_assets", {}).get("rows", 0) < 1:
                raise ValueError("A populated 0104 data fingerprint is required")
            preserved = await table_fingerprints(conn, state["baseline_data"].keys())
            if preserved != state["baseline_data"]:
                raise ValueError("Pre-existing table data changed during 0105 migration")
            constraints = [dict(r) for r in (await conn.execute(text("""SELECT c.relname AS table_name,
              k.conname AS name,k.contype::text AS kind,pg_get_constraintdef(k.oid) AS definition
              FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace
              WHERE n.nspname='public' AND c.relname IN ('seo_site_advisor_assignments','seo_content_confirmations')
              ORDER BY 1,2"""))).mappings()]
            expected_names = {"ck_seo_content_confirmation_version", "ck_seo_content_confirmation_decision",
                              "ck_seo_content_confirmation_actor_mode", "uq_seo_site_advisor_assignment_scope_user"}
            if not expected_names <= {r["name"] for r in constraints}:
                raise ValueError("Expected CHECK/UNIQUE constraints missing")
            for table in ("seo_site_advisor_assignments", "seo_content_confirmations"):
                if sum(r["table_name"] == table and r["kind"] == "f" for r in constraints) != 4:
                    raise ValueError("Expected foreign keys missing")
            from sqlalchemy import inspect
            assignment_fks = await conn.run_sync(lambda c: inspect(c).get_foreign_keys("seo_site_advisor_assignments", schema="public"))
            confirmation_fks = await conn.run_sync(lambda c: inspect(c).get_foreign_keys("seo_content_confirmations", schema="public"))
            common = {("tenant_id", "tenants", "id", "CASCADE"), ("site_id", "seo_sites", "id", "CASCADE")}
            for found, expected in ((assignment_fks, common | {("advisor_user_id", "users", "id", "RESTRICT"),
                                                             ("assigned_by", "users", "id", "SET NULL")}),
                                    (confirmation_fks, common | {("content_asset_id", "seo_content_assets", "id", "CASCADE"),
                                                               ("actor_user_id", "users", "id", "RESTRICT")})):
                shapes = {(f["constrained_columns"][0], f["referred_table"], f["referred_columns"][0],
                           f["options"].get("ondelete")) for f in found}
                if shapes != expected or any(f.get("referred_schema") != "public" for f in found):
                    raise ValueError("Foreign-key targets or delete actions differ from reviewed 0105 contract")
            await conn.rollback()
            scope = state["seed"]
            params = {**scope["primary"], "advisor": scope["users"]["advisor"], "content": scope["content_id"]}
            # Every probe is rolled back, including successful inserts.
            probes = [("bad_assignment_fk", """INSERT INTO seo_site_advisor_assignments
                       (tenant_id,site_id,advisor_user_id) VALUES (:tenant_id,:site_id,-1)""", "23503")]
            base = """INSERT INTO seo_content_confirmations
                (tenant_id,site_id,content_asset_id,content_version,content_hash,decision,actor_mode,actor_user_id,actor_role_name)
                VALUES (:tenant_id,:site_id,:content,:version,:hash,:decision,:mode,:advisor,'isolated')"""
            for label, changes, expected in (
                ("valid_confirmation", {}, None), ("bad_version", {"version": 0}, "23514"),
                ("bad_decision", {"decision": "unknown"}, "23514"), ("bad_actor_mode", {"mode": "unknown"}, "23514"),
                ("bad_content_fk", {"content": -1}, "23503"), ("bad_user_fk", {"advisor": -1}, "23503"),
                ("bad_site_fk", {"site_id": -1}, "23503"), ("bad_tenant_fk", {"tenant_id": -1}, "23503")):
                values = {**params, "version": 1, "hash": "a" * 64, "decision": "approve", "mode": "advisor_proxy", **changes}
                tx = await conn.begin()
                code = None
                try:
                    await conn.execute(text(base), values)
                except Exception as exc:
                    code = getattr(getattr(exc, "orig", None), "sqlstate", None)
                    if code is None:
                        raise
                finally:
                    await tx.rollback()
                if code != expected:
                    raise ValueError(f"Constraint probe {label} unexpected SQLSTATE")
            for label, statement, expected in probes:
                tx = await conn.begin()
                code = None
                try:
                    await conn.execute(text(statement), params)
                except Exception as exc:
                    code = getattr(getattr(exc, "orig", None), "sqlstate", None)
                    if code is None:
                        raise
                finally:
                    await tx.rollback()
                if code != expected:
                    raise ValueError(f"Constraint probe {label} unexpected SQLSTATE")
            tx = await conn.begin()
            duplicate_code = None
            try:
                statement = text("""INSERT INTO seo_site_advisor_assignments
                    (tenant_id,site_id,advisor_user_id) VALUES (:tenant_id,:site_id,:advisor)""")
                await conn.execute(statement, params)
                await conn.execute(statement, params)
            except Exception as exc:
                duplicate_code = getattr(getattr(exc, "orig", None), "sqlstate", None)
                if duplicate_code is None:
                    raise
            finally:
                await tx.rollback()
            if duplicate_code != "23505":
                raise ValueError("Duplicate advisor scope was not rejected")
            # Keep one real assignment for API tests; no approval is pre-filled.
            await conn.execute(text("""INSERT INTO seo_site_advisor_assignments
                (tenant_id,site_id,advisor_user_id,assigned_by) VALUES (:tenant_id,:site_id,:advisor,:advisor)"""), params)
            await conn.commit()
            return {"constraints": constraints, "preserved_tables": len(preserved),
                    "probe_count": 10, "confirmation_rows": 0, "status": "verified"}
    finally:
        await engine.dispose()


def migrate():
    state = read_state()
    if state["phase"] != "prepared" or state["migration_hashes"] != migration_hashes():
        raise ValueError("Run is not fresh or migration sources changed; stop for review")
    url = database_url()
    state["before"] = asyncio.run(inspect_database(url, empty=True))
    configure(url)
    graph()
    state["phase"] = "migrating"
    write_state(state)
    try:
        upgrade(BASE)
        state["phase"] = "baseline_0104"
        state["seed"] = asyncio.run(baseline_seed())
        async def snapshot():
            engine = engine_for(url)
            try:
                async with engine.connect() as conn:
                    objects = await inventory(conn)
                    tables = [r["name"] for r in objects["relations"]
                              if r["schema"] == "public" and r["kind"] == "r" and r["name"] != "alembic_version"]
                    return await table_fingerprints(conn, tables)
            finally:
                await engine.dispose()
        state["baseline_data"] = asyncio.run(snapshot())
        write_state(state)
        upgrade(HEAD)
        state["validation"] = asyncio.run(validate_upgrade(url, state))
        state["phase"] = "verified_0105"
    except Exception as exc:
        state["phase"] = "migration_failed"
        # No raw exception strings: database errors can include connection data.
        state["failure"] = {"type": type(exc).__name__,
                            "sqlstate": getattr(getattr(exc, "orig", None), "sqlstate", None)}
        raise
    finally:
        state["after"] = asyncio.run(inspect_database(url))
        write_state(state)
    print(json.dumps({"phase": state["phase"], "seed": state["seed"], "validation": state["validation"]}, ensure_ascii=False))


def network_audit(event, args):
    if event == "socket.connect":
        address = args[1]
        if not isinstance(address, tuple) or address[:2] != IDENTITY[:2]:
            raise PermissionError("SEO local acceptance blocks all outbound traffic except its test database")
    elif event == "socket.getaddrinfo" and args[0] not in ("127.0.0.1", b"127.0.0.1"):
        raise PermissionError("SEO local acceptance blocks external DNS")
    elif event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.spawn"}:
        raise PermissionError("SEO local acceptance blocks child processes and browser providers")


def allowed_request(method, path):
    if method in {"GET", "HEAD", "OPTIONS"}:
        return path.startswith(("/api/v1/seo/", "/api/v1/seo-sites", "/api/v1/auth/")) or path == "/health/seo"
    rules = {
        "POST": (r"/api/v1/auth/login", r"/api/v1/seo/content-assets/\d+/(submit-review|review)",
                 r"/api/v1/seo/workbench/content-assets/\d+/confirmations", r"/api/v1/seo/workbench/service-plan/run",
                 r"/api/v1/seo/workbench/content-workflows/\d+/advance",
                 r"/api/v1/seo/workbench/service-cycles/run", r"/api/v1/seo/content-distribution/publications/manual",
                 r"/api/v1/seo/content-distribution/publications/\d+/complete"),
        "PATCH": (r"/api/v1/seo/content-assets/\d+", r"/api/v1/seo/tasks/\d+"),
        "PUT": (r"/api/v1/seo/workbench/service-plan",),
    }
    return any(re.fullmatch(pattern, path) for pattern in rules.get(method, ()))


def build_app():
    from app.seo_main import app, settings
    from app.api.auth import router
    from fastapi.responses import JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
    from starlette.middleware.trustedhost import TrustedHostMiddleware
    if settings.seo_scheduler_enabled or settings.seo_external_actions_enabled or settings.admin_api_key:
        raise ValueError("Unsafe local backend settings")
    from seo_local_auth import router as session_catalog
    app.include_router(session_catalog)  # Before legacy /tenants; real auth/SQL.
    app.include_router(router)
    app.user_middleware = [m for m in app.user_middleware if m.cls is not CORSMiddleware]
    app.add_middleware(CORSMiddleware, allow_origin_regex=r"http://(127\.0\.0\.1|localhost):\d+",
                       allow_methods=["GET", "POST", "PUT", "PATCH", "OPTIONS"], allow_headers=["Authorization", "Content-Type"])
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    @app.middleware("http")
    async def local_actions(request, call_next):
        if request.headers.get("x-api-key") or not allowed_request(request.method, request.url.path):
            return JSONResponse(status_code=403, content={"code": "local_acceptance_action_disabled",
                "detail": "仅本机合成数据联调；真实生成、抓取、发布与账号连接均禁用"})
        response = await call_next(request)
        response.headers["X-SEO-Local-Acceptance"] = "synthetic-no-external-actions"
        return response
    return app


def serve():
    state = read_state()
    if state["phase"] != "verified_0105" or state["migration_hashes"] != migration_hashes():
        raise ValueError("A verified real migration is required before backend startup")
    url = database_url()
    asyncio.run(inspect_database(url))
    configure(url)
    import uvicorn
    app = build_app()
    # Windows event loops can create a self-pipe via socketpair; initialize it
    # before locking network access, rather than permitting arbitrary loopback.
    loop = asyncio.new_event_loop()
    # Python audit hook is installed before lifespan/routes; auth is not mocked.
    sys.addaudithook(network_audit)
    async def run():
        from app.seo_main import seo_health
        from fastapi import Response
        health = await seo_health(Response())
        if health["schema"] != "ok" or health["schema_revision"] != HEAD:
            raise ValueError("Actual SEO health check failed; backend not started")
        print(json.dumps({"starting_on": f"http://127.0.0.1:{PORT}", "schema": "public", "seed": state["seed"],
                          "identities_file": str(STATE_DIR / "identities.json"), "stop": "Ctrl+C"}, ensure_ascii=False))
        await uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, workers=1,
                                           reload=False, access_log=False, loop="asyncio")).serve()
    try:
        loop.run_until_complete(run())
    finally:
        from app.database import engine
        loop.run_until_complete(engine.dispose())
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


def cleanup_plan():
    state = read_state()
    if "after" not in state or "before" not in state:
        raise ValueError("No owned database object inventory exists")
    current = asyncio.run(inspect_database(database_url()))["objects"]
    recorded = state["after"]["objects"]
    if current != recorded:
        raise ValueError("Object inventory changed; manual ownership review required before cleanup")
    if any(state["before"]["objects"][k] for k in ("relations", "functions", "types")):
        raise ValueError("Original database was not empty; refuse automated cleanup planning")
    for key in ("relations", "functions", "types"):
        if any(r["schema"] != "public" or r["owner"] != IDENTITY[3] for r in current[key]):
            raise ValueError("Objects outside owned public scope exist")
    # Only produce a manifest, never DROP DATABASE/SCHEMA/extensions/CASCADE.
    path = STATE_DIR / "cleanup-review.json"
    path.write_text(json.dumps({"run_id": state["run_id"], "objects": current,
        "steps": ["Stop the loopback backend and UI writes", "Recheck database identity and exact object inventory",
                  "Remove only inventoried foreign keys, then owned tables with RESTRICT",
                  "Remove remaining inventoried sequences/functions/enums with RESTRICT",
                  "Verify the original empty user-object baseline and unchanged extensions/schema/roles"],
        "requires_reviewed_executor": True}, ensure_ascii=False, indent=2), encoding="utf-8")
    sql = cleanup_sql(current)
    (STATE_DIR / "cleanup-review.sql").write_text(sql, encoding="utf-8")
    print(json.dumps({"cleanup_manifest": str(path), "cleanup_sql": str(STATE_DIR / "cleanup-review.sql"), "executed": False}))


def seed_ui():
    """Prepare the second article via actual authenticated business APIs."""
    import httpx
    state = read_state()
    if state["phase"] != "verified_0105":
        raise ValueError("Migration must be verified before UI fixtures")
    if state.get("ui_seed"):
        print(json.dumps(state["ui_seed"], ensure_ascii=False))

        return
    state.setdefault("ui_request_id", str(uuid4()))
    write_state(state)
    credentials = json.loads((STATE_DIR / "identities.json").read_text(encoding="utf-8"))
    scope = state["seed"]["primary"]
    with httpx.Client(base_url=f"http://127.0.0.1:{PORT}", trust_env=False, timeout=20) as client:
        def checked(response):
            if response.status_code != 200:
                raise ValueError(f"Local fixture API refused a step: HTTP {response.status_code}")
            return response.json()
        login = checked(client.post("/api/v1/auth/login", json=credentials["accounts"]["advisor"]))
        client.headers["Authorization"] = "Bearer " + login["token"]
        plan = checked(client.get("/api/v1/seo/workbench/service-plan", params=scope))
        task = checked(client.post("/api/v1/seo/workbench/service-plan/run", json={**scope,
            "expected_revision": plan["revision"], "request_id": state["ui_request_id"]}))["task"]
        ident = task["params"]["content_id"]
        route = f"/api/v1/seo/content-assets/{ident}"
        delivery = checked(client.get(f"/api/v1/seo/workbench/content-assets/{ident}/delivery", params=scope))
        content = delivery["content"]
        if content["status"] == "planned":
            content = checked(client.patch(route, params={"tenant_id": scope["tenant_id"]}, json={
                "version_count": content["version_count"], "title": "SEO12 合成待客户确认稿",
                "draft": "<p>仅用于本机工作台联调的合成稿件，不含真实业务事实。</p>",
                "outline": "测试稿件确认与版本冲突", "keyword_ids": [state["seed"]["keyword_id"]], "status": "drafting"}))
        if content["status"] == "drafting":
            content = checked(client.post(route + "/submit-review", params={"tenant_id": scope["tenant_id"]},
                json={"version_count": content["version_count"], "note": "仅合成联调稿"}))
        if content["status"] == "review":
            content = checked(client.post(route + "/review", params={"tenant_id": scope["tenant_id"]},
                json={"version_count": content["version_count"], "decision": "approve", "note": "普通文章合成审核记录"}))
        if content["status"] != "ready":
            raise ValueError("UI fixture article is not ready; do not overwrite user changes")
        checked(client.post(f'/api/v1/seo/workbench/content-workflows/{task["id"]}/advance', json=scope))
        state["ui_seed"] = {"drafting_content_id": state["seed"]["content_id"], "ready_content_id": ident,
                            "task_id": task["id"], "ready_version": content["version_count"],
                            "synthetic_publication_url": f"https://seo12-primary.invalid/fixture/{ident}",
                            "customer_confirmation": "pending"}
        write_state(state)
        print(json.dumps(state["ui_seed"], ensure_ascii=False))


def seed_revocation():
    """One extra fixture for the separately coordinated revoked-assignment run."""
    import httpx
    state = read_state()
    if state["phase"] != "verified_0105" or not state.get("ui_seed"):
        raise ValueError("Verified UI fixture scope is required")
    url = database_url()
    asyncio.run(inspect_database(url))
    configure(url)
    scope = state["seed"]["primary"]
    if not state.get("revocation_content_id"):
        async def insert():
            from app.database import async_session_factory, engine
            from app.models.seo import SeoContentAsset
            try:
                async with async_session_factory() as session:
                    row = SeoContentAsset(**scope, title="SEO12 合成撤权验收稿", content_type="article", status="drafting",
                        draft="<p>仅本机撤权验收，尚未发布。</p>", outline="合成撤权场景", version_count=1,
                        keyword_id=state["seed"]["keyword_id"], keyword_ids=[state["seed"]["keyword_id"]])
                    session.add(row)
                    await session.commit()
                    return row.id
            finally:
                await engine.dispose()
        state["revocation_content_id"] = asyncio.run(insert())
        write_state(state)
    credentials = json.loads((STATE_DIR / "identities.json").read_text(encoding="utf-8"))
    ident = state["revocation_content_id"]
    with httpx.Client(base_url=f"http://127.0.0.1:{PORT}", trust_env=False, timeout=20) as client:
        def checked(response):
            if response.status_code != 200:
                raise ValueError(f"Revocation fixture API refused a step: HTTP {response.status_code}")
            return response.json()
        token = checked(client.post("/api/v1/auth/login", json=credentials["accounts"]["advisor"]))["token"]
        client.headers["Authorization"] = "Bearer " + token
        content = checked(client.get(f"/api/v1/seo/workbench/content-assets/{ident}/delivery", params=scope))["content"]
        route = f"/api/v1/seo/content-assets/{ident}"
        if content["status"] == "drafting":
            content = checked(client.post(route + "/submit-review", params={"tenant_id": scope["tenant_id"]},
                                          json={"version_count": content["version_count"]}))
        if content["status"] == "review":
            content = checked(client.post(route + "/review", params={"tenant_id": scope["tenant_id"]},
                                          json={"version_count": content["version_count"], "decision": "approve"}))
        if content["status"] != "ready":
            raise ValueError("Revocation fixture is not ready; do not overwrite user changes")
    print(json.dumps({"revocation_content_id": ident, "status": "ready", "assignment_changed": False}))


def advisor_assignment(active):
    """Operator CLI only; run after coordinating the browser synchronization point."""
    state = read_state()
    if state["phase"] != "verified_0105" or not state.get("revocation_content_id"):
        raise ValueError("Revocation fixture must be prepared")
    async def update():
        engine = engine_for(database_url())
        try:
            await preflight(engine)
            async with engine.begin() as conn:
                params = {**state["seed"]["primary"], "user_id": state["seed"]["users"]["advisor"], "active": active}
                rows = (await conn.execute(text("""SELECT id FROM seo_site_advisor_assignments
                    WHERE tenant_id=:tenant_id AND site_id=:site_id AND advisor_user_id=:user_id FOR UPDATE"""), params)).scalars().all()
                if len(rows) != 1:
                    raise ValueError("Exactly one owned fixture assignment is required")
                await conn.execute(text("UPDATE seo_site_advisor_assignments SET active=:active,updated_at=now() WHERE id=:id"),
                                   {"active": active, "id": rows[0]})
        finally:
            await engine.dispose()
    asyncio.run(update())
    state.setdefault("assignment_history", []).append({"active": active, "at": datetime.now(timezone.utc).isoformat()})
    write_state(state)
    print(json.dumps({"advisor_assignment_active": active, "tenant_id": state["seed"]["primary"]["tenant_id"]}))


def export_ui():
    """Copy only synthetic browser credentials, never database/JWT secrets."""
    import tempfile
    state = read_state()
    if state["phase"] != "verified_0105" or not state.get("ui_seed") or not state.get("revocation_content_id"):
        raise ValueError("All verified UI fixtures are required")
    folder = Path(tempfile.gettempdir()) / ("seo12-ui-" + state["run_id"])
    folder.mkdir(mode=0o700, exist_ok=True)
    if os.name == "nt":
        user = subprocess.check_output(["whoami"], text=True).strip()
        result = subprocess.run(["icacls", str(folder), "/inheritance:r", "/grant:r",
                                 f"{user}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"], capture_output=True)
        if result.returncode:
            raise ValueError("UI fixture folder ACL could not be restricted")
    identities = json.loads((STATE_DIR / "identities.json").read_text(encoding="utf-8"))
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    config = {"environment_kind": "isolated-local-pg", "backend_origin": f"http://127.0.0.1:{PORT}",
              "backend_commit": commit, "database": IDENTITY[2], "schema": "public", **state["seed"]["primary"],
              "advisor": identities["accounts"]["advisor"], "customer": identities["accounts"]["customer"],
              "external_operations_disabled": True,
              "external_adapters": {"ai": "disabled", "crawl": "disabled", "scheduler": "disabled",
                                    "publication": "synthetic_manual_record_only", "page_evidence": "not_generated"},
              "scenarios": {"draft_content_id": state["ui_seed"]["drafting_content_id"],
                            "proxy_content_id": state["ui_seed"]["ready_content_id"],
                            "task_ids": [state["ui_seed"]["task_id"]], "revocation_content_id": state["revocation_content_id"]},
              "publication": {"synthetic": True, "page_url": state["ui_seed"]["synthetic_publication_url"],
                              "platform_name": "SEO12合成发布事实",
                              "published_local_time": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%dT%H:%M")}}
    path = folder / "ui12-config.json"
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    state["ui_config_path"] = str(path)
    write_state(state)
    print(json.dumps({"ui_config_file": str(path), "backend_commit": commit, "secrets_printed": False}))


def cleanup_sql(objects):
    """RESTRICT-only plan. Must be regenerated/reviewed after stopping the app."""
    lines = ["-- Review inventory and ownership immediately before execution; no CASCADE.", "BEGIN;",
             "DO $$ BEGIN IF current_database() <> 'seo_workflow_test' OR current_user <> 'seo_workflow_tester' "
             "OR inet_server_addr() <> '127.0.0.1'::inet OR inet_server_port() <> 55432 "
             "THEN RAISE EXCEPTION 'Wrong cleanup target'; END IF; END $$;"]
    for row in objects["foreign_keys"]:
        lines.append(f'ALTER TABLE public.{quote_ident(row["table_name"])} DROP CONSTRAINT {quote_ident(row["name"])};')
    relations = objects["relations"]
    if any(r["kind"] not in {"r", "i", "S"} for r in relations):
        raise ValueError("Cleanup has unreviewed relation kinds")
    for row in relations:
        if row["kind"] == "r":
            lines.append(f'DROP TABLE public.{quote_ident(row["name"])} RESTRICT;')
    for row in relations:
        if row["kind"] == "S":
            lines.append(f'DROP SEQUENCE IF EXISTS public.{quote_ident(row["name"])} RESTRICT;')
    for row in objects["functions"]:
        lines.append(f'DROP FUNCTION public.{quote_ident(row["name"])}({row["arguments"]}) RESTRICT;')
    for row in objects["types"]:
        kind = "DOMAIN" if row["kind"] == "d" else "TYPE"
        lines.append(f'DROP {kind} public.{quote_ident(row["name"])} RESTRICT;')
    return "\n".join([*lines, "COMMIT;", ""])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["graph", "prepare", "preflight", "migrate", "serve", "seed-ui", "seed-revocation", "export-ui", "advisor-revoke", "advisor-restore", "cleanup-plan"])
    command = parser.parse_args().command
    if command == "graph":
        print(json.dumps(graph()))
    elif command == "prepare":
        prepare()
    elif command == "preflight":
        print(json.dumps(asyncio.run(inspect_database(database_url(), empty=True))))
    else:
        {"migrate": migrate, "serve": serve, "seed-ui": seed_ui, "seed-revocation": seed_revocation,
         "advisor-revoke": lambda: advisor_assignment(False), "advisor-restore": lambda: advisor_assignment(True),
         "export-ui": export_ui, "cleanup-plan": cleanup_plan}[command]()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "stopped", "error_type": type(error).__name__,
                          "message": str(error) if type(error) in (ValueError, PermissionError) else "Inspect local lifecycle state; raw database errors withheld"}))
        raise SystemExit(1)
