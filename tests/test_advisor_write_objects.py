"""Real local SQL + HTTP object/assignment boundary tests (no remote services)."""
import asyncio
import io
import json
from types import SimpleNamespace
from urllib.parse import urlencode

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, insert, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable
from starlette.datastructures import UploadFile

from app.models.module_workspace import SeoSite
from app.models.seo import (
    SeoBrandAsset, SeoContentAsset, SeoKeywordAsset, SeoSiteAdvisorAssignment, SeoSitePage,
)
from app.models.seo_qa import SeoQaFact
from app.models.tenant import Tenant
from app.security.advisor_write_objects import (
    _file_references, check_write_objects, ensure_advisor_assignment,
)
from app.security.auth import AuthContext


@compiles(JSONB, "sqlite")
def sqlite_json(_type, _compiler, **_kw):
    return "JSON"


class LocalSession:
    def __init__(self, sync):
        self.sync = sync

    async def execute(self, *args, **kwargs):
        return self.sync.execute(*args, **kwargs)

    async def scalar(self, *args, **kwargs):
        return self.sync.scalar(*args, **kwargs)


@pytest.fixture
def db(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "objects.sqlite"))
    models = [Tenant, SeoSite, SeoQaFact, SeoBrandAsset, SeoContentAsset,
              SeoKeywordAsset, SeoSitePage, SeoSiteAdvisorAssignment]
    with engine.begin() as connection:
        for model in models:
            connection.execute(CreateTable(model.__table__, include_foreign_key_constraints=[]))
    with Session(engine, expire_on_commit=False) as sync:
        sync.add_all([Tenant(id=tid, name=f"test-{tid}") for tid in (1, 2, 3)])
        # Site 12 is the same tenant, other site. Tenant 2 is granted but unselected;
        # tenant 3 is ungranted. All deliberately have valid DB objects.
        for site, tid in [(11, 1), (12, 1), (22, 2), (33, 3)]:
            sync.add(SeoSite(id=site, tenant_id=tid, tenant_module_id=site, name="test",
                            domain=f"site{site}.test", canonical_domain=f"site{site}.test"))
            sync.add(SeoQaFact(id=site, tenant_id=tid, site_id=site, title="fact",
                               statement="test", source_name="fixture"))
            sync.add(SeoBrandAsset(id=site, tenant_id=tid, site_id=site, asset_type="official_domain",
                                  name="brand", match_value="example.test"))
            sync.add(SeoKeywordAsset(id=site, tenant_id=tid, site_id=site, keyword="test"))
            sync.add(SeoSitePage(id=site, tenant_id=tid, site_id=site,
                                url="https://example.test", target_keyword_id=site))
            sync.add(SeoContentAsset(id=site, tenant_id=tid, site_id=site, title="draft",
                                    keyword_id=site, keyword_ids=[site], source_page_id=site))
            sync.add(SeoSiteAdvisorAssignment(id=site, tenant_id=tid, site_id=site,
                                              advisor_user_id=7, active=True))
        sync.commit()
        yield LocalSession(sync)
    engine.dispose()


@pytest.fixture
def ctx():
    return AuthContext(7, "test", "advisor", 1, {"seo.content": "edit"}, is_advisor=True,
                       scope_kind="advisor_tenant", grant_id=10, advisor_tenant_ids=frozenset({1, 2}))


RULE = SimpleNamespace(assignment="site")


def request(path=None, query=None, method="PATCH"):
    return Request({"type": "http", "method": method, "path": "/test", "headers": [],
                    "query_string": urlencode(query or [("tenant_id", 1)], doseq=True).encode(),
                    "path_params": path or {}})


def check(db, ctx, req=None, body=None, assignment=True):
    async def run():
        await check_write_objects(db, ctx, req or request({"content_id": 11}), body, RULE)
        if assignment:
            await ensure_advisor_assignment(db, ctx, req or request({"content_id": 11}), body, RULE)
    return asyncio.run(run())


def denied(code, status=403):
    class Denial:
        def __enter__(self):
            self.manager = pytest.raises(HTTPException)
            self.error = self.manager.__enter__()
            return self.error

        def __exit__(self, *exc):
            self.manager.__exit__(*exc)
            assert self.error.value.status_code == status
            assert self.error.value.detail["code"] == code
            return True
    return Denial()


@pytest.mark.parametrize("kind", ["fact_id", "asset_id", "content_id", "keyword_id", "source_page_id", "page_id", "site_id"])
@pytest.mark.parametrize("site", [22, 33])
def test_path_objects_other_selected_or_ungranted_tenant(db, ctx, kind, site):
    with denied("ADVISOR_TENANT_NOT_GRANTED"):
        check(db, ctx, request({kind: site}))


@pytest.mark.parametrize("body", [
    {"keyword_ids": [11, 22]}, {"keyword_id": 33}, {"source_page_id": 22},
    {"items": [{"source": {"fact_ids": [11, 22]}}]},
    [{"site_id": 11}, {"details": {"tenant_id": 2}}],
    {"tenant_ids": [1, 3]}, {"references": [{"asset_id": 33}]},
])
def test_nested_and_array_references_all_checked(db, ctx, body):
    with denied("ADVISOR_TENANT_NOT_GRANTED"):
        check(db, ctx, body=body)


@pytest.mark.parametrize("query", [
    [("tenant_id", 1), ("tenant_id", 2)],
    [("tenant_id", 1), ("keyword_ids", 11), ("keyword_ids", 22)],
    [("tenant_id", 1), ("source_page_id", 22)],
])
def test_all_duplicate_query_parameters_checked(db, ctx, query):
    with denied("ADVISOR_TENANT_NOT_GRANTED"):
        check(db, ctx, request({"content_id": 11}, query))


@pytest.mark.parametrize("key,value", [("owner_user_id", 7), ("mystery_ids", []),
    ("answer_id", 11), ("id", 11), ("project_id", None), ("connection_ids", [11])])
def test_unknown_ids_fail_closed_even_empty(db, ctx, key, value):
    with denied("ADVISOR_OBJECT_UNAVAILABLE"):
        check(db, ctx, body={"nested": [{key: value}]})
    with denied("ADVISOR_OBJECT_UNAVAILABLE"):
        check(db, ctx, request(query=[("tenant_id", 1), (key, "11")]))


@pytest.mark.parametrize("value", [True, False, 0, -1, "1.0", "١١", " 11", {}, [11], 1.1, 2**63, "9" * 50])
def test_bad_scalar_ids_rejected(db, ctx, value):
    with denied("ADVISOR_INVALID_OBJECT_ID", 422):
        check(db, ctx, body={"keyword_id": value})


@pytest.mark.parametrize("kind", ["fact_id", "content_id", "asset_id", "keyword_id", "page_id", "site_id", "tenant_id"])
def test_missing_objects_are_404(db, ctx, kind):
    with denied("ADVISOR_OBJECT_NOT_FOUND", 404):
        check(db, ctx, body={kind: 9999})


@pytest.mark.parametrize("kind", ["keyword_id", "source_page_id", "site_id", "fact_id"])
def test_same_tenant_other_site_rejected(db, ctx, kind):
    with denied("ADVISOR_TENANT_NOT_GRANTED"):
        check(db, ctx, body={kind: 12})


def test_stored_primary_scope_cannot_be_overridden_for_assignment(db, ctx):
    db.sync.get(SeoSiteAdvisorAssignment, 11).active = False
    db.sync.commit()
    with denied("ADVISOR_TENANT_NOT_GRANTED"):
        check(db, ctx, body={"site_id": 12})
    with denied("ADVISOR_ASSIGNMENT_REQUIRED"):
        check(db, ctx)


@pytest.mark.parametrize("change", ["inactive", "different_user", "different_tenant", "different_site", "deleted"])
def test_assignment_requires_exact_active_user_tenant_site(db, ctx, change):
    row = db.sync.get(SeoSiteAdvisorAssignment, 11)
    if change == "deleted":
        db.sync.delete(row)
    else:
        setattr(row, {"inactive": "active", "different_user": "advisor_user_id",
                      "different_tenant": "tenant_id", "different_site": "site_id"}[change],
                {"inactive": False, "different_user": 8, "different_tenant": 2, "different_site": 99}[change])
    db.sync.commit()
    with denied("ADVISOR_ASSIGNMENT_REQUIRED"):
        check(db, ctx)


def test_assignment_is_requeried_after_initial_check(db, ctx):
    check(db, ctx)
    db.sync.get(SeoSiteAdvisorAssignment, 11).active = False
    db.sync.commit()
    with denied("ADVISOR_ASSIGNMENT_REQUIRED"):
        asyncio.run(ensure_advisor_assignment(db, ctx, request({"content_id": 11}), None, RULE))


@pytest.mark.parametrize("field,value", [("keyword_ids", [22]), ("keyword_id", 12), ("source_page_id", 22)])
def test_unchanged_stored_content_links_are_checked(db, ctx, field, value):
    setattr(db.sync.get(SeoContentAsset, 11), field, value)
    db.sync.commit()
    with pytest.raises(HTTPException) as error:
        check(db, ctx, body={"title": "new title"})
    assert error.value.status_code == 403


def test_stored_page_keyword_scope_checked(db, ctx):
    db.sync.get(SeoSitePage, 11).target_keyword_id = 12
    db.sync.commit()
    with denied("ADVISOR_TENANT_NOT_GRANTED"):
        check(db, ctx)


@pytest.mark.parametrize("model", [SeoBrandAsset, SeoContentAsset, SeoKeywordAsset, SeoSitePage])
def test_unscoped_legacy_objects_fail_closed(db, ctx, model):
    db.sync.get(model, 11).site_id = None
    db.sync.commit()
    key = {SeoBrandAsset: "asset_id", SeoContentAsset: "content_id",
           SeoKeywordAsset: "keyword_id", SeoSitePage: "page_id"}[model]
    with denied("ADVISOR_OBJECT_UNAVAILABLE"):
        check(db, ctx, request({key: 11}))


def test_post_requires_actual_body_site_and_assignment(db, ctx):
    with denied("ADVISOR_ASSIGNMENT_REQUIRED"):
        check(db, ctx, request(query=[("tenant_id", 1), ("site_id", 11)], method="POST"), {"name": "brand"})
    check(db, ctx, request(method="POST"), {"tenant_id": 1, "site_id": 11})


def test_non_advisor_and_admin_unchanged(db, ctx):
    ctx.is_advisor = False
    check(db, ctx, body={"unknown_id": 999, "site_id": 22})


def test_identity_or_empty_grants_cannot_use_helpers(db, ctx):
    ctx.advisor_tenant_ids = frozenset()
    with denied("ADVISOR_NO_TENANT"):
        check(db, ctx)
    ctx.advisor_tenant_ids = frozenset({1})
    ctx.scope_kind = "advisor_identity"
    with denied("ADVISOR_TENANT_SELECTION_REQUIRED", 409):
        check(db, ctx)


ROUTES = [
    ("POST", "/api/v1/seo/qa/facts", {}, {"tenant_id": 1, "site_id": 11, "title": "new"}),
    ("PATCH", "/api/v1/seo/qa/facts/{fact_id}", {"fact_id": 11}, {"tenant_id": 1, "site_id": 11, "version": 1}),
    ("POST", "/api/v1/seo/rank-serp/brand-assets", {}, {"tenant_id": 1, "site_id": 11, "name": "brand"}),
    ("PATCH", "/api/v1/seo/rank-serp/brand-assets/{asset_id}", {"asset_id": 11}, {"name": "brand"}),
    ("POST", "/api/v1/seo/content-assets", {}, {"tenant_id": 1, "site_id": 11, "keyword_ids": [11]}),
    ("PATCH", "/api/v1/seo/content-assets/{content_id}", {"content_id": 11}, {"keyword_ids": [11], "version_count": 1}),
    ("PUT", "/api/v1/seo/content-assets/{content_id}/source-page", {"content_id": 11}, {"source_page_id": 11, "version_count": 1}),
]


@pytest.mark.parametrize("method,template,path,body", ROUTES)
@pytest.mark.parametrize("attack", [None, "body", "assignment"])
def test_each_seven_route_boundaries_and_atomic_rejection(db, ctx, method, template, path, body, attack):
    """HTTP dependency contract with a real local SQL write after both checks.

    This tests the B boundary, not production handlers or A's route/field gates.
    """
    metadata = MetaData()
    writes = Table("boundary_writes", metadata, Column("id", Integer, primary_key=True))
    metadata.create_all(db.sync.bind)
    payload = dict(body)
    if attack == "body":
        payload["nested"] = [{"keyword_ids": [11, 22]}]
    elif attack == "assignment":
        db.sync.get(SeoSiteAdvisorAssignment, 11).active = False
        db.sync.commit()
    app = FastAPI()

    async def endpoint(req: Request):
        value = await req.json()
        await check_write_objects(db, ctx, req, value, RULE)
        await ensure_advisor_assignment(db, ctx, req, value, RULE)
        db.sync.execute(insert(writes).values(id=1))
        db.sync.commit()
        return {"saved": True, "body_preserved": await req.json() == payload}

    app.add_api_route(template, endpoint, methods=[method])

    async def send():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, template.format(**path), params={"tenant_id": 1}, json=payload)

    response = asyncio.run(send())
    assert response.status_code == (200 if attack is None else 403)
    if attack is None:
        assert response.json() == {"saved": True, "body_preserved": True}
    assert db.sync.scalar(select(writes.c.id)) == (1 if attack is None else None)


@pytest.mark.parametrize("extension,source", [
    ("csv", "tenant_id,site_id,keyword_ids\n1,11,[11]\n2,22,[22]\n"),
    ("json", json.dumps([{"tenant_id": 1, "site_id": 11}, {"nested": {"fact_id": 22}}])),
])
def test_file_every_row_foreign_ids_rejected_and_cursor_preserved(db, ctx, extension, source):
    app = FastAPI()

    @app.put("/upload/{content_id}")
    async def endpoint(req: Request):
        form = await req.form()
        upload = form["file"]
        await upload.seek(2)
        try:
            await check_write_objects(db, ctx, req, None, RULE)
        finally:
            assert upload.file.tell() == 2
        pytest.fail("foreign row must prevent handler execution")

    async def send():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.put("/upload/11?tenant_id=1", files={"file": (f"test.{extension}", source)})

    assert asyncio.run(send()).status_code == 403


@pytest.mark.parametrize("name,source,status,code", [
    ("ok.csv", "tenant_id,site_id,keyword_ids\n1,11,[11]\n", None, None),
    ("ok.json", '[{"site_id":11,"links":[{"fact_id":11}]}]', None, None),
    ("bad.csv", "tenant_id,mystery_id\n1,\n", 403, "ADVISOR_OBJECT_UNAVAILABLE"),
    ("bad.json", '[{"owner_user_id":null}]', 403, "ADVISOR_OBJECT_UNAVAILABLE"),
    ("bad.csv", "site_id,site_id\n11,22\n", 422, "ADVISOR_INVALID_OBJECT_FILE"),
    ("bad.csv", "site_id\n11,22\n", 422, "ADVISOR_INVALID_OBJECT_FILE"),
    ("bad.json", "broken", 422, "ADVISOR_INVALID_OBJECT_FILE"),
    ("bad.json", '[{"site_id":22,"site_id":11}]', 422, "ADVISOR_INVALID_OBJECT_FILE"),
    ("bad.xlsx", "unknown format", 403, "ADVISOR_OBJECT_UNAVAILABLE"),
    ("large.json", " " * (2 * 1024 * 1024 + 1), 413, "ADVISOR_OBJECT_FILE_TOO_LARGE"),
], ids=["csv-ok", "json-ok", "unknown-csv-id", "unknown-json-id", "duplicate-header",
        "extra-column", "bad-json", "duplicate-json-key", "unsupported", "oversized"])
def test_upload_parser_is_bounded_closed_and_non_destructive(name, source, status, code):
    upload = UploadFile(file=io.BytesIO(source.encode()), filename=name)
    upload.file.seek(1)
    refs = []
    if status:
        with denied(code, status):
            asyncio.run(_file_references(upload, refs))
    else:
        asyncio.run(_file_references(upload, refs))
        assert ("site_id", 11) in refs
    assert upload.file.tell() == 1


def test_allowed_multipart_form_and_files_remain_readable(db, ctx):
    app = FastAPI()
    source = '[{"site_id":11,"keyword_ids":[11]}]'

    @app.put("/upload/{content_id}")
    async def endpoint(req: Request):
        form = await req.form()
        upload = form["file"]
        await upload.seek(2)
        await check_write_objects(db, ctx, req, None, RULE)
        await ensure_advisor_assignment(db, ctx, req, None, RULE)
        assert upload.file.tell() == 2
        assert (await upload.read()).decode() == source[2:]
        assert (await req.form())["keyword_ids"] == "[11]"
        return {"ok": True}

    async def send():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.put("/upload/11?tenant_id=1", data={"keyword_ids": "[11]"},
                                    files={"file": ("rows.json", source)})

    assert asyncio.run(send()).json() == {"ok": True}
