"""Actual native APIs against a hash-bound private TEMP customer snapshot."""
import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
import httpx
import pytest
from sqlalchemy import Date, DateTime, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateTable

from app.database import get_session
from app.geo.content import routes
from app.geo.distribution_sources import load_intake_candidate, load_source
from app.geo.project_scope import set_binding
from app.geo.project_workflows import save_plan
from app.models import (Tenant, TenantModule, GeoProject, GeoFact, GeoPrompt, GeoContentTask,
    GeoArticleVersion, GeoChannelVariant, GeoChannelAsset, GeoTaskFact, GeoPublication,
    GeoOptimizationBusiness, GeoOptimizationUnit, GeoPublishingChannel, GeoAsyncJob)
from app.models.role import Role
from app.models.user import User
from app.permissions import CUSTOMER_ROLE
from app.security.auth import hash_password
from test_geo_distribution_control_integration_postgres import auth_api, PASSWORD, bearer, login
from geo_manual_revision_fixture import revised_body, FACT4_TRANSLATION

SNAPSHOT = Path(os.getenv("GEO_MANUAL_SNAPSHOT", r"C:/Users/ADMINI~1/AppData/Local/Temp/distribution-existing-customers-f1183d33e40f4002b7c5667fd029b179/existing-customer-drafts-with-fact-metadata.json"))
SNAPSHOT_SHA = "f75d382a54ec33f0c892cc4c6afcc17b082c130cc1b58236fb4dde48e383f609"
SOURCE_URL = "https://www.nord.com/en/campaign/products/industrial-gear-units-maxxdrive-xd-2.jsp"
SOURCE_QUOTE = "it is well suited for belt conveyor systems."
TRANSLATION = "MAXXDRIVE XT适用于带式输送系统"
BASE = "/api/v1/geo/content-tasks/12"
FINAL = BASE + "/variants/wechat/manual-finalization"
pytestmark = pytest.mark.skipif(not os.getenv("GEO_MANUAL_POSTGRES_URL"), reason="owned manual PG required")


def snapshot():
    raw = SNAPSHOT.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SNAPSHOT_SHA
    return json.loads(raw)["collections"]


@asynccontextmanager
async def fixture():
    url = make_url(os.environ["GEO_MANUAL_POSTGRES_URL"])
    assert url.drivername == "postgresql+asyncpg" and url.host == "127.0.0.1" and url.port == 55527
    assert (url.database, url.username) == ("geo_manual_ci", "geo_manual_ci") and not url.query
    schema = "geo_manual_test_" + uuid4().hex
    engine = create_async_engine(url, pool_size=5, connect_args={"server_settings": {
        "search_path": schema, "timezone": "UTC", "lock_timeout": "5000", "statement_timeout": "15000"}},
        execution_options={"schema_translate_map": {"public": schema}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    models = (Tenant, TenantModule, GeoProject, GeoFact, GeoPrompt, GeoContentTask,
        GeoArticleVersion, GeoChannelVariant, GeoChannelAsset, GeoTaskFact, GeoPublication,
        GeoOptimizationBusiness, GeoOptimizationUnit, GeoPublishingChannel, GeoAsyncJob, Role, User)
    collections = snapshot()
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            for model in models:
                await connection.execute(CreateTable(model.__table__, include_foreign_key_constraints=[]))
            await connection.execute(text("CREATE TABLE demo_tenant_bindings (tenant_id bigint,demo_tenant_id bigint,dataset_key varchar(64),dataset_version varchar(40),status varchar(16),version integer)"))
            await connection.execute(text("CREATE TABLE IF NOT EXISTS public.demo_tenant_bindings (tenant_id bigint,demo_tenant_id bigint,dataset_key varchar(64),dataset_version varchar(40),status varchar(16),version integer)"))
        async with sessions() as db:
            for model in models:
                for original in collections.get(model.__tablename__, []):
                    if model is TenantModule and original.get("module_code") != "geo": continue
                    values = {}
                    for column in model.__table__.columns:
                        if column.name not in original: continue
                        value = original[column.name]
                        if value is not None and isinstance(column.type, DateTime):
                            value = datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
                        elif value is not None and isinstance(column.type, Date): value = date.fromisoformat(value)
                        values[column.name] = value
                    db.add(model(**values))
            db.add(Role(id=8001, name="isolated manual advisor", permissions={"geo.diagnosis": "view", "geo.assets": "edit", "geo.content": "edit"}))
            db.add(Role(id=8002, name=CUSTOMER_ROLE, permissions={"geo.diagnosis": "view", "geo.content": "view"}))
            for ident, role, tenant in ((8001, 8001, None), (8002, 8002, 1), (8003, 8001, None)):
                db.add(User(id=ident, username=f"geo-manual-{ident}", role_id=role, tenant_id=tenant,
                    password_hash=hash_password(PASSWORD), is_active=True))
            module_id=next(row["id"] for row in collections["tenant_modules"] if row["tenant_id"]==1 and row["module_code"]=="geo")
            db.add(GeoProject(id=9001, tenant_id=1, tenant_module_id=module_id, name="isolated manual acceptance",
                primary_domain="manual-acceptance.invalid", canonical_domain="manual-acceptance.invalid", status="active"))
            await db.commit()
            await set_binding(db, 1, 9001, [13], 0, 8001)
            await save_plan(db, 1, 9001, {"enabled": False, "status": "active",
                "prompt_ids": [row["prompt_id"] for row in collections['geo_content_tasks'] if row["id"] == 12],
                "interval_days": 7, "advisor_user_id": 8001}, 0, 8001)
            for model in (GeoChannelVariant, GeoArticleVersion):
                table = model.__tablename__
                await db.execute(text(f"SELECT setval(pg_get_serial_sequence('{table}','id'),(SELECT max(id) FROM {table}))"))
            await db.commit()
        app = FastAPI()
        app.include_router(auth_api.router)
        app.include_router(routes.router, prefix="/api/v1/geo")
        async def local_session():
            async with sessions() as db: yield db
        app.dependency_overrides[get_session] = local_session
        app.dependency_overrides[routes.geo_read_session] = local_session
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            tokens = {key: await login(client, f"geo-manual-{ident}") for key, ident in (("advisor",8001),("customer",8002),("other",8003))}
            yield sessions, client, tokens, collections
    finally:
        try:
            async with engine.begin() as connection:
                assert schema.startswith("geo_manual_test_") and len(schema) == 48
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        finally: await engine.dispose()


async def call(client, token, method, path, **kwargs):
    return await client.request(method, path, headers=bearer(token), params={"tenant_id":1}, **kwargs)


async def verify(client, token, collections):
    fact = next(row for row in collections["geo_facts"] if row["id"] == 6)
    response = await call(client, token, "POST", "/api/v1/geo/facts/6/verify", json={
        "excerpt": fact["statement"], "excerpt_locator": "Official MAXXDRIVE XT page: Built for Bulk Material Conveyor Applications",
        "source_url": SOURCE_URL, "note": "Isolated advisor test; official current quote: " + SOURCE_QUOTE,
        "verified_translation": TRANSLATION, "expected_source_statement": fact["statement"],
        "expected_source_name": fact["source_name"], "expected_source_url": fact["source_url"], "public_use_allowed": True})
    assert response.status_code == 200, response.text
    assert response.json()["meta"]["verified_translations"][0]["verified_by"] == 8001
    fact = next(row for row in collections["geo_facts"] if row["id"] == 4)
    response = await call(client, token, "POST", "/api/v1/geo/facts/4/verify", json={
        "excerpt":fact["statement"], "excerpt_locator":"Official MAXXDRIVE page: opening paragraph",
        "source_url":fact["source_url"], "note":"Isolated advisor test; current official quote: engineered for continuous operation in demanding environments",
        "verified_translation":FACT4_TRANSLATION, "expected_source_statement":fact["statement"],
        "expected_source_name":fact["source_name"], "expected_source_url":fact["source_url"], "public_use_allowed":True})
    assert response.status_code==200,response.text
    assert response.json()["meta"]["verified_translations"][0]["verified_by"]==8001


async def request(client, token):
    response = await client.get(FINAL, headers=bearer(token), params={"tenant_id":1,"scope_id":9001})
    assert response.status_code == 200, response.text
    data = response.json()
    req = {"scope_id":9001,"expected_variant_id":data["variant_id"],"expected_article_id":data["article_id"],
        "expected_revision":data["revision"],"request_id":str(uuid4()),
        "confirm_title_body":True,"confirm_layout":True,"confirm_facts":True,"confirm_brand_author":True,"confirm_platform":True}
    return req, data


async def approve(client, token, task):
    return await call(client, token, "POST", BASE+"/review", json={"decision":"approved",
        "expected_article_id":task["article"]["id"],"expected_updated_at":task["updated_at"],"note":"Isolated test customer confirmation, not real client approval"})


async def prepare_revision(client, tokens, collections):
    await verify(client, tokens["advisor"], collections)
    # A genuine remaining evidence gap must not be waived. Save a separately
    # identified LOCAL manual revision using the real editor APIs instead.
    _, raw = await request(client, tokens["advisor"])
    assert not raw["quality_passed"] and "sentence_evidence" in " ".join(raw["issues"])
    original = next(row for row in collections["geo_channel_variants"] if row["id"] == 2)
    body = revised_body(collections)
    saved = await call(client, tokens["advisor"], "PUT", BASE+"/article", json={
        "expected_article_id":17, "title":original["title"], "body_markdown":body,
        "outline":{}})
    assert saved.status_code == 200, saved.text
    assert saved.json()["article"]["id"] != 17
    saved = await call(client, tokens["advisor"], "PATCH", BASE+"/variants/wechat", json={
        "title":original["title"], "body_markdown":body})
    assert saved.status_code == 200, saved.text
    req, context = await request(client, tokens["advisor"])
    assert context["quality_passed"] is True, context["issues"]
    assert context["requires_master_rebase"] is True
    return req


async def completed(client, tokens, collections):
    req=await prepare_revision(client,tokens,collections)
    response = await call(client, tokens["advisor"], "POST", FINAL, json=req)
    assert response.status_code == 200, response.text
    return req, response.json()


def test_original_real_snapshot_requires_translation_and_customer_approval_alone_cannot_finalize():
    async def run():
        async with fixture() as (sessions, client, tokens, collections):
            req, context = await request(client, tokens["advisor"])
            assert context["quality_passed"] is False and context["issues"]
            assert (await call(client, tokens["advisor"], "POST", FINAL, json=req)).status_code == 409
            task = (await call(client, tokens["advisor"], "GET", BASE)).json()
            response = await approve(client, tokens["customer"], task)
            assert response.status_code == 200, response.text
            async with sessions() as db:
                assert await db.scalar(select(func.count()).select_from(GeoChannelVariant)) == len(collections["geo_channel_variants"])
                assert (await load_intake_candidate(db,8001,1,9001,2,"wechat-article"))["readiness"] == "awaiting-adaptation"
                with pytest.raises(HTTPException): await load_source(db,8001,1,9001,2,"wechat-article")
    asyncio.run(run())


def test_real_fact_verify_finalize_pending_native_customer_review_and_exact_source_handoff():
    async def run():
        async with fixture() as (sessions, client, tokens, collections):
            original = next(row for row in collections["geo_channel_variants"] if row["id"] == 2)
            req, pending = await completed(client, tokens, collections)
            new_id = pending["manual_finalize_result"]["variant_id"]
            assert new_id != 2 and pending["review_status"] == "pending"
            assert pending["manual_finalize_result"]["publishing_authorized"] is False
            assert next(v for v in pending["variant_history"] if v["id"] == 2)["body_markdown"] == original["body_markdown"]
            async with sessions() as db:
                old = await db.get(GeoChannelVariant,2)
                assert old.adapt_meta == original["adapt_meta"] and old.body_markdown == original["body_markdown"]
                assert (await load_intake_candidate(db,8001,1,9001,new_id,"wechat-article"))["readiness"] == "awaiting-review"
                with pytest.raises(HTTPException): await load_source(db,8001,1,9001,new_id,"wechat-article")
            advisor = await approve(client,tokens["advisor"],pending)
            assert advisor.status_code == 403
            response = await approve(client,tokens["customer"],pending)
            assert response.status_code == 200,response.text
            approved = response.json()
            async with sessions() as db:
                meta = await load_intake_candidate(db,8001,1,9001,new_id,"wechat-article")
                source = await load_source(db,8001,1,9001,new_id,"wechat-article")
                assert meta["readiness"] == "ready" and meta["source_revision"] == source["source_revision"]
                assert source["content"]["body"] == revised_body(collections).strip()
                assert (await db.get(GeoArticleVersion,17)).body_markdown == next(row for row in collections["geo_article_versions"] if row["id"]==17)["body_markdown"]
                assert await db.scalar(select(func.count()).select_from(GeoPublication)) == 0
            response = await call(client,tokens["advisor"],"POST",FINAL,json=req)
            assert response.status_code == 200,response.text
            assert response.json()["manual_finalize_result"]["idempotent"] is True
            assert response.json()["review_status"] == approved["review_status"] == "approved"
    asyncio.run(run())


@pytest.mark.parametrize("actor",["customer","other"])
def test_customer_and_unassigned_advisor_cannot_finalize(actor):
    async def run():
        async with fixture() as (_,client,tokens,collections):
            await verify(client,tokens["advisor"],collections)
            req,_ = await request(client,tokens["advisor"])
            assert (await call(client,tokens[actor],"POST",FINAL,json=req)).status_code == 403
    asyncio.run(run())


@pytest.mark.parametrize("field,value,status",[("expected_revision","0"*64,409),
    ("expected_variant_id",999,409),("expected_article_id",999,409),("confirm_facts",False,422),
    ("confirm_layout",1,422),("publishable",True,422),("scope_id",999,404)])
def test_stale_version_missing_confirmation_and_client_flags_rejected(field,value,status):
    async def run():
        async with fixture() as (sessions,client,tokens,collections):
            await verify(client,tokens["advisor"],collections)
            req,_=await request(client,tokens["advisor"])
            req[field]=value
            response=await call(client,tokens["advisor"],"POST",FINAL,json=req)
            assert response.status_code == status,response.text
            async with sessions() as db:
                assert await db.scalar(select(func.count()).select_from(GeoChannelVariant)) == len(collections["geo_channel_variants"])
    asyncio.run(run())


def test_editing_finalized_text_or_inline_image_preserves_history_and_invalidates_current():
    async def run():
        async with fixture() as (sessions,client,tokens,collections):
            _,pending=await completed(client,tokens,collections)
            response=await approve(client,tokens["customer"],pending)
            assert response.status_code == 200,response.text
            approved=response.json(); old_id=approved["manual_finalize_result"]["variant_id"] if "manual_finalize_result" in approved else next(v["id"] for v in approved["variants"] if v["channel"]=="wechat")
            old=next(v for v in approved["variants"] if v["id"]==old_id)
            response=await call(client,tokens["advisor"],"PATCH",BASE+"/variants/wechat",json={"body_markdown":old["body_markdown"]+"\n![本地测试配图](https://image.invalid/local.png)\n"})
            assert response.status_code == 200,response.text
            edited=response.json(); current=next(v for v in edited["variants"] if v["channel"]=="wechat")
            assert current["id"]!=old_id and edited["review_status"]=="none"
            async with sessions() as db:
                assert (await db.get(GeoChannelVariant,old_id)).body_markdown==old["body_markdown"]
                assert (await load_intake_candidate(db,8001,1,9001,current["id"],"wechat-article"))["readiness"]=="awaiting-adaptation"
    asyncio.run(run())


def test_customer_rejection_invalidates_manual_record_and_cannot_be_restored_by_approval_alone():
    async def run():
        async with fixture() as (sessions,client,tokens,collections):
            _,pending=await completed(client,tokens,collections)
            new_id=pending["manual_finalize_result"]["variant_id"]
            response=await call(client,tokens["customer"],"POST",BASE+"/review",json={"decision":"rejected","expected_article_id":pending["article"]["id"],"expected_updated_at":pending["updated_at"]})
            assert response.status_code==200,response.text
            response=await call(client,tokens["advisor"],"POST",BASE+"/submit-review",json={})
            assert response.status_code==200,response.text
            response=await approve(client,tokens["customer"],response.json())
            assert response.status_code==200,response.text
            async with sessions() as db:
                assert (await load_intake_candidate(db,8001,1,9001,new_id,"wechat-article"))["readiness"]=="awaiting-adaptation"
                with pytest.raises(HTTPException):await load_source(db,8001,1,9001,new_id,"wechat-article")
    asyncio.run(run())


def test_same_request_concurrent_replay_creates_only_one_finalized_variant():
    async def run():
        async with fixture() as (sessions,client,tokens,collections):
            req,pending=await completed(client,tokens,collections)
            responses=await asyncio.gather(*[call(client,tokens["advisor"],"POST",FINAL,json=req) for _ in range(3)])
            assert all(response.status_code==200 for response in responses)
            assert len({response.json()["manual_finalize_result"]["variant_id"] for response in responses})==1
            assert all(response.json()["manual_finalize_result"]["idempotent"] for response in responses)
            async with sessions() as db:
                assert await db.scalar(select(func.count()).select_from(GeoChannelVariant))==len(collections["geo_channel_variants"])+2
    asyncio.run(run())


@pytest.mark.parametrize("same_uuid",[True,False])
def test_two_cold_first_calls_serialize_without_duplicate_finalization(same_uuid):
    async def run():
        async with fixture() as (sessions,client,tokens,collections):
            req=await prepare_revision(client,tokens,collections)
            second={**req,"request_id":req["request_id"] if same_uuid else str(uuid4())}
            gate=asyncio.Event()
            async def start(body):
                await gate.wait()
                return await call(client,tokens["advisor"],"POST",FINAL,json=body)
            requests=[asyncio.create_task(start(body)) for body in (req,second)]
            gate.set()
            replies=await asyncio.gather(*requests)
            assert sorted(r.status_code for r in replies)==([200,200] if same_uuid else [200,409])
            if same_uuid:
                assert sorted(r.json()["manual_finalize_result"]["idempotent"] for r in replies)==[False,True]
                assert len({r.json()["manual_finalize_result"]["variant_id"] for r in replies})==1
            else:
                assert next(r for r in replies if r.status_code==409).json()["detail"]["code"]=="geo_manual_version_stale"
            async with sessions() as db:
                assert await db.scalar(select(func.count()).select_from(GeoChannelVariant))==len(collections["geo_channel_variants"])+2
                assert (await db.get(GeoContentTask,12)).review_status=="pending"
    asyncio.run(run())


@pytest.mark.parametrize("change",["master","facts","rendered","review"])
def test_later_master_fact_rendered_content_or_review_change_cannot_use_old_finalization(change):
    async def run():
        async with fixture() as (sessions,client,tokens,collections):
            _,pending=await completed(client,tokens,collections)
            approved=await approve(client,tokens["customer"],pending)
            assert approved.status_code==200,approved.text
            task=approved.json(); variant=next(v for v in task["variants"] if v["channel"]=="wechat")
            assert variant["manual_finalization_current"] is True
            if change=="master":
                response=await call(client,tokens["advisor"],"PUT",BASE+"/article",json={
                    "expected_article_id":task["article"]["id"],"title":task["article"]["title"],
                    "body_markdown":task["article"]["body_markdown"]+"\n请保留新的资料核对记录。","outline":{}})
                assert response.status_code==200,response.text
            elif change=="facts":
                response=await call(client,tokens["advisor"],"PATCH","/api/v1/geo/facts/6",json={"status":"archived"})
                assert response.status_code==200,response.text
            else:
                # Persistence-integrity and withdrawn-review negatives; no gate
                # is mocked, and the real adapter reads the committed PG row.
                async with sessions() as db:
                    if change=="rendered":
                        row=await db.get(GeoChannelVariant,variant["id"])
                        row.adapt_meta={**row.adapt_meta,"body_html":row.adapt_meta["body_html"]+"<p>changed</p>"}
                    else:
                        row=await db.get(GeoContentTask,12); row.review_status="none";row.reviewed_by=None;row.reviewed_at=None
                    await db.commit()
            async with sessions() as db:
                meta=await load_intake_candidate(db,8001,1,9001,variant["id"],"wechat-article")
                assert meta["readiness"]=="awaiting-adaptation" and meta["source_revision"] is None
                with pytest.raises(HTTPException): await load_source(db,8001,1,9001,variant["id"],"wechat-article")
            current=await call(client,tokens["advisor"],"GET",BASE)
            assert current.status_code==200
            assert next(v for v in current.json()["variants"] if v["id"]==variant["id"])["manual_finalization_current"] is False
    asyncio.run(run())


def test_current_actor_revocation_rejects_still_valid_jwt_and_native_scope():
    async def run():
        async with fixture() as (sessions,client,tokens,collections):
            req,_=await request(client,tokens["advisor"])
            async with sessions() as db:
                user=await db.get(User,8001);user.is_active=False;await db.commit()
            response=await call(client,tokens["advisor"],"POST",FINAL,json=req)
            assert response.status_code in {401,403}
            async with sessions() as db:
                with pytest.raises(HTTPException) as denied: await load_intake_candidate(db,8001,1,9001,2,"wechat-article")
                assert denied.value.status_code==403
    asyncio.run(run())


def test_other_tenant_project_and_task_scope_cannot_finalize():
    async def run():
        async with fixture() as (sessions,client,tokens,collections):
            req,_=await request(client,tokens["advisor"])
            async with sessions() as db:
                db.add(GeoProject(id=9002,tenant_id=1,tenant_module_id=2,name="other project",primary_domain="other.invalid",canonical_domain="other.invalid",status="active"))
                await db.commit()
                await save_plan(db,1,9002,{"enabled":False,"status":"active","prompt_ids":[],"interval_days":7,"advisor_user_id":8001},0,8001)
                await db.commit()
            response=await call(client,tokens["advisor"],"POST",FINAL,json={**req,"scope_id":9002})
            assert response.status_code==403,response.text
            response=await client.post(FINAL,headers=bearer(tokens["advisor"]),params={"tenant_id":15},json=req)
            assert response.status_code in {403,404},response.text
    asyncio.run(run())
