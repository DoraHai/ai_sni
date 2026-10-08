"""UI15 opt-in helper for the existing, fixed local acceptance database only.

No action on import. Never resets schemas or replays the UI12/UI14 workflow.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import socket
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import text
import seo_local_acceptance as runner

MIGRATION = "20261008_0106_seo_content_messages.py"


async def snapshot(url, tables=None, revision=None):
    engine = runner.engine_for(url)
    try:
        await runner.preflight(engine)
        async with engine.connect() as conn:
            found = list((await conn.execute(text("SELECT version_num FROM alembic_version"))).scalars())
            if revision and found != [revision]:
                raise ValueError("Unexpected local database revision")
            objects = await runner.inventory(conn)
            if tables is None:
                tables = [r["name"] for r in objects["relations"]
                          if r["schema"] == "public" and r["kind"] == "r" and r["name"] != "alembic_version"]
            return await runner.table_fingerprints(conn, tables)
    finally:
        await engine.dispose()


def upgrade():
    state = runner.read_state()
    hashes = runner.migration_hashes()
    if state["phase"] != "verified_0105" or state.get("runtime_revision", runner.HEAD) != runner.HEAD:
        raise ValueError("Only the already verified 0105 local lifecycle may be upgraded")
    if {k:v for k,v in hashes.items() if k != MIGRATION} != state["migration_hashes"]:
        raise ValueError("Previously executed migration source changed; stop for review")
    if MIGRATION not in hashes:
        raise ValueError("Message migration is missing")
    with socket.socket() as probe:
        probe.settimeout(1)
        if probe.connect_ex(("127.0.0.1", runner.PORT)) == 0:
            raise ValueError("Stop the verified local backend before applying this local migration")
    url = runner.database_url()
    runner.configure(url)
    runner.graph()
    before = asyncio.run(snapshot(url, revision=runner.HEAD))
    state["ui15_upgrade"] = {"phase":"started", "before":before, "at":datetime.now(timezone.utc).isoformat()}
    runner.write_state(state)
    runner.upgrade(runner.MESSAGE_HEAD)
    after = asyncio.run(snapshot(url, before.keys(), runner.MESSAGE_HEAD))
    if before != after:
        raise ValueError("Existing local data changed; preserve database for investigation")

    async def health():
        from fastapi import Response
        from app.seo_main import seo_health
        from app.database import engine
        try:
            response = Response()
            result = await seo_health(response)
            if response.status_code != 200 or result["schema_revision"] != runner.MESSAGE_HEAD:
                raise ValueError("Real 0106 health check failed")
            return result
        finally:
            await engine.dispose()
    checked = asyncio.run(health())
    state["ui15_upgrade"].update(phase="verified", preserved_tables=len(before), after=after,
                                health=checked)
    state["runtime_revision"] = runner.MESSAGE_HEAD
    state["migration_hashes"] = hashes
    state["after"] = asyncio.run(runner.inspect_database(url))
    runner.write_state(state)
    print(json.dumps({"revision":runner.MESSAGE_HEAD,"preserved_tables":len(before),"health":"ok"}))


def seed():
    import httpx
    state = runner.read_state()
    if (state.get("runtime_revision") != runner.MESSAGE_HEAD
            or state["migration_hashes"] != runner.migration_hashes()
            or state.get("ui15_upgrade", {}).get("phase") != "verified"):
        raise ValueError("Verified local UI15 migration required")
    url = runner.database_url()
    runner.configure(url)
    scope = state["seed"]["primary"]

    async def prepare_content():
        from app.models.seo import SeoContentAsset
        from app.models.module_workspace import SeoSite
        from sqlalchemy.ext.asyncio import async_sessionmaker
        engine = runner.engine_for(url)
        try:
            await runner.preflight(engine)
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(text("SELECT pg_advisory_xact_lock(15082026)"))
                site = await session.get(SeoSite, scope["site_id"])
                if not site or site.tenant_id != scope["tenant_id"] or site.domain != "seo12-primary.invalid":
                    raise ValueError("UI15 requires the owned synthetic site")
                # A unique synthetic title allows safe recovery if writing the receipt was interrupted.
                title = "UI15 人工沟通专用合成稿 " + state["run_id"]
                from sqlalchemy import select
                content = await session.scalar(select(SeoContentAsset).where(
                    SeoContentAsset.tenant_id == scope["tenant_id"], SeoContentAsset.site_id == scope["site_id"],
                    SeoContentAsset.title == title))
                if content is None:
                    content = SeoContentAsset(**scope, title=title, status="drafting", version_count=1,
                        draft='<h2>UI15 本机沟通验收</h2><p>仅合成资料；人工消息不表示审核、确认或发布。</p>'
                              '<img src="/api/v1/seo/site/page-captures/1/image?tenant_id=1" alt="已有本机合成截图">',
                        created_by=state["seed"]["users"]["advisor"])
                    session.add(content)
                    await session.commit()
                return content.id
        finally:
            await engine.dispose()
    ident = asyncio.run(prepare_content())
    state.setdefault("ui15", {}).update(content_id=ident, scope=scope)
    runner.write_state(state)
    prefix = f"/api/v1/seo/workbench/content-assets/{ident}/conversation"
    accounts = json.loads((runner.STATE_DIR / "identities.json").read_text(encoding="utf-8"))["accounts"]
    protected = ["seo_content_assets","seo_content_confirmations","seo_content_review_events","seo_tasks","seo_content_publications"]
    before = asyncio.run(snapshot(url, protected, runner.MESSAGE_HEAD))
    with httpx.Client(base_url=f"http://127.0.0.1:{runner.PORT}", trust_env=False, timeout=20) as client:
        def checked(response, status=200):
            if response.status_code != status:
                raise ValueError(f"UI15 local API returned HTTP {response.status_code}, expected {status}")
            return response.json()
        tokens = {name: checked(client.post("/api/v1/auth/login",json=account))["token"]
                  for name,account in accounts.items()}
        def headers(name): return {"Authorization":"Bearer " + tokens[name]}
        checked(client.get(prefix,params=scope),401)
        for name in ("unassigned_advisor","other_customer"):
            checked(client.get(prefix,params=scope,headers=headers(name)),403)
        checked(client.get(prefix,params={**scope,"site_id":state["seed"]["foreign"]["site_id"]},headers=headers("customer")),404)
        first = None
        for index in range(25):
            actor = "customer" if index % 2 == 0 else "advisor"
            body = {**scope,"request_id":str(uuid5(NAMESPACE_URL,f'{state["run_id"]}/ui15/{index}')),
                    "body":f"UI15 合成历史 {index+1:02d}：仅用于本机分页和双身份沟通验收。"}
            result = checked(client.post(prefix+"/messages",json=body,headers=headers(actor)))
            replay = checked(client.post(prefix+"/messages",json=body,headers=headers(actor)))
            if not replay["replayed"] or replay["message"] != result["message"]:
                raise ValueError("Real HTTP idempotency failed")
            if first is None: first = result["message"]["id"]
        newest = checked(client.get(prefix+"/messages",params={**scope,"limit":20},headers=headers("customer")))
        older = checked(client.get(prefix+"/messages",params={**scope,"limit":20,"before_id":newest["next_before_id"]},headers=headers("customer")))
        # Subsequent manual browser messages are preserved; this helper never deletes them.
        if len(newest["items"]) != 20 or not newest["has_more"] or len(older["items"]) < 5:
            raise ValueError("Real HTTP pagination failed")
        state["ui15"].update(seed_messages=25,first_message_id=first,
            latest_message_id=newest["read_state"]["latest_message_id"],
            customer_read_state=newest["read_state"],http_checks="passed")
    if before != asyncio.run(snapshot(url, protected, runner.MESSAGE_HEAD)):
        raise ValueError("Messaging changed protected workflow data")
    state["ui15"]["protected_workflows_unchanged"] = True
    runner.write_state(state)
    print(json.dumps(state["ui15"],ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["upgrade", "seed"])
    args = parser.parse_args()
    try:
        {"upgrade":upgrade,"seed":seed}[args.command]()
    except Exception as exc:
        # Do not expose raw connection/SQL exceptions or secrets in operator logs.
        print(json.dumps({"status":"stopped", "error_type":type(exc).__name__,
                          "message":str(exc) if type(exc) in (ValueError, PermissionError)
                          else "Inspect the local lifecycle receipt; raw database error withheld"}))
        raise SystemExit(1)
