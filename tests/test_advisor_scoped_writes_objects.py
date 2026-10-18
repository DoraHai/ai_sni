"""Real SQL object ownership, recursive IDs, and active site assignment."""
import asyncio
from io import BytesIO

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.database import Base
from app.models.module_workspace import SeoSite
from app.models.seo import (SeoBrandAsset, SeoContentAsset, SeoKeywordAsset,
                            SeoSiteAdvisorAssignment, SeoSitePage)
from app.models.seo_qa import SeoQaFact
from test_advisor_tenant_auth import LocalSession, local_db  # noqa: F401
from test_advisor_scoped_writes import (CASES, actor, denied, request_for,
    routes_contract, objects_contract)  # noqa: F401


class ObjectSession(LocalSession):
    async def execute(self, *args, **kwargs):
        return self.sync.execute(*args, **kwargs)


@pytest.fixture
def object_db(local_db):
    db, _ = local_db
    models = (SeoBrandAsset, SeoContentAsset, SeoKeywordAsset, SeoSiteAdvisorAssignment, SeoSitePage, SeoQaFact)
    Base.metadata.create_all(db.bind, tables=[model.__table__ for model in models])
    db.add(SeoSite(id=4, tenant_id=1, tenant_module_id=1, name="other same-tenant site",
                   domain="same-tenant.test", canonical_domain="same-tenant.test", status="active"))
    # A=selected; B=granted but unselected; C=not granted; D=same tenant, different site.
    for offset, tid, site in ((0, 1, 1), (100, 2, 2), (200, 3, 3), (300, 1, 4)):
        db.add_all([
            SeoQaFact(id=30+offset, tenant_id=tid, site_id=site, title="Fact", statement="Evidence", source_name="fixture"),
            SeoBrandAsset(id=40+offset, tenant_id=tid, site_id=site, asset_type="official_domain",
                          name="Rule", match_value=f"rule{offset}.test"),
            SeoSitePage(id=50+offset, tenant_id=tid, site_id=site, url=f"https://page{offset}.test/"),
            SeoKeywordAsset(id=20+offset, tenant_id=tid, site_id=site, keyword="manual"),
            SeoContentAsset(id=1+offset, tenant_id=tid, site_id=site, title="Draft", status="drafting"),
        ])
    db.add(SeoSiteAdvisorAssignment(id=1, tenant_id=1, site_id=1, advisor_user_id=1, active=True))
    db.commit()
    return db, ObjectSession(db)


def selected():
    return actor(user_id=1, tenant_id=1, advisor_tenant_ids=frozenset({1, 2}))


def test_sql_fixture_has_real_cross_tenant_and_cross_site_rows(object_db):
    db, _ = object_db
    assert db.get(SeoQaFact, 30).tenant_id == 1
    assert db.get(SeoQaFact, 130).tenant_id == 2
    assert db.get(SeoContentAsset, 301).site_id == 4
    assert db.get(SeoSiteAdvisorAssignment, 1).active


def rule(routes_contract, case=CASES[5]):
    return routes_contract.WRITE_ROUTES[(case.method, case.template)]


def request(body=None, query="tenant_id=1&site_id=1", case=CASES[5]):
    return request_for(case, body={} if body is None else body, query=query)


@pytest.mark.parametrize("case", [CASES[1], CASES[3], CASES[5], CASES[6]])
def test_path_object_uses_real_table_and_tenant(routes_contract, objects_contract, object_db, case):
    db, session = object_db
    req = request(case=case)
    asyncio.run(objects_contract.check_write_objects(session, selected(), req, {}, rule(routes_contract, case)))
    key = next(iter(req.path_params))
    original = req.path_params[key]
    for offset in (100, 200):
        req.path_params[key] = original + offset
        with pytest.raises(HTTPException) as caught:
            asyncio.run(objects_contract.check_write_objects(session, selected(), req, {}, rule(routes_contract, case)))
        denied(caught.value)
    assert db.get(SeoContentAsset, 1).title == "Draft"


@pytest.mark.parametrize("key,base", [("keyword_id", 20), ("source_page_id", 50),
    ("fact_id", 30), ("asset_id", 40), ("content_id", 1)])
@pytest.mark.parametrize("location", ["body", "nested", "array", "query"])
@pytest.mark.parametrize("offset", [100, 200, 300], ids=["unselected-granted", "ungranted", "wrong-site"])
def test_foreign_ids_rejected_in_every_location(routes_contract, objects_contract, object_db, key, base, location, offset):
    db, session = object_db
    value = base + offset
    body = {key: value}
    if location == "nested":
        body = {"metadata": {"references": {key: value}}}
    elif location == "array":
        body = {"items": [{key: base}, {key: value}]}
    req = request(body, query="tenant_id=1&site_id=1" + (f"&{key}={value}" if location == "query" else ""))
    with pytest.raises(HTTPException) as caught:
        asyncio.run(objects_contract.check_write_objects(session, selected(), req,
                    {} if location == "query" else body, rule(routes_contract)))
    denied(caught.value)
    assert db.get(SeoContentAsset, 1).title == "Draft"


@pytest.mark.parametrize("key,values", [("keyword_ids", [20, 120]), ("fact_ids", [30, 130]),
    ("page_ids", [50, 150]), ("tenant_ids", [1, 2]), ("site_ids", [1, 2])])
def test_plural_ids_inspect_every_element(routes_contract, objects_contract, object_db, key, values):
    body = {"items": [{key: values}]}
    with pytest.raises(HTTPException) as caught:
        asyncio.run(objects_contract.check_write_objects(object_db[1], selected(), request(body), body, rule(routes_contract)))
    denied(caught.value)


@pytest.mark.parametrize("body", [{"tenant_id": 2}, {"tenant_id": 3},
    {"items": [{"tenant_id": 1}, {"tenant_id": 2}]}, [{"keyword_id": 20}, {"keyword_id": 120}]])
def test_nested_and_top_level_array_scope_cannot_override_selection(routes_contract, objects_contract, object_db, body):
    with pytest.raises(HTTPException) as caught:
        asyncio.run(objects_contract.check_write_objects(object_db[1], selected(), request(body), body, rule(routes_contract)))
    denied(caught.value)


@pytest.mark.parametrize("key,value", [("future_id", 20), ("future_ids", [20])])
def test_unknown_object_ids_fail_closed(routes_contract, objects_contract, object_db, key, value):
    body = {"nested": [{key: value}]}
    with pytest.raises(HTTPException) as caught:
        asyncio.run(objects_contract.check_write_objects(object_db[1], selected(), request(body), body, rule(routes_contract)))
    denied(caught.value, code="ADVISOR_OBJECT_UNAVAILABLE")


@pytest.mark.parametrize("key", ["keyword_id", "fact_id", "asset_id", "source_page_id", "content_id"])
def test_missing_known_object_is_404(routes_contract, objects_contract, object_db, key):
    body = {key: 99999}
    with pytest.raises(HTTPException) as caught:
        asyncio.run(objects_contract.check_write_objects(object_db[1], selected(), request(body), body, rule(routes_contract)))
    denied(caught.value, status=404)


def test_local_nested_ids_and_arrays_can_pass(routes_contract, objects_contract, object_db):
    body = {"tenant_id": 1, "site_id": 1, "keyword_ids": [20],
            "references": [{"fact_id": 30}, {"asset_id": 40}, {"source_page_id": 50}]}
    asyncio.run(objects_contract.check_write_objects(object_db[1], selected(), request(body), body, rule(routes_contract)))


@pytest.mark.parametrize("change", ["missing", "inactive", "other-user", "wrong-site"])
def test_assignment_must_be_active_for_current_site_and_actor(routes_contract, objects_contract, object_db, change):
    db, session = object_db
    assignment = db.get(SeoSiteAdvisorAssignment, 1)
    if change == "missing":
        db.delete(assignment)
    elif change == "inactive":
        assignment.active = False
    elif change == "other-user":
        assignment.advisor_user_id = 3
    else:
        assignment.site_id = 4
    db.commit()
    with pytest.raises(HTTPException) as caught:
        asyncio.run(objects_contract.ensure_advisor_assignment(session, selected(), request(), {}, rule(routes_contract)))
    denied(caught.value, code="ADVISOR_ASSIGNMENT_REQUIRED")


@pytest.mark.parametrize("case", [CASES[0], CASES[1], CASES[3], CASES[5], CASES[6]])
def test_assignment_resolves_body_or_path_object_site(routes_contract, objects_contract, object_db, case):
    body = {"tenant_id": 1, "site_id": 1} if case in (CASES[0], CASES[1]) else {}
    asyncio.run(objects_contract.ensure_advisor_assignment(object_db[1], selected(),
                request(body, query="tenant_id=1", case=case), body, rule(routes_contract, case)))


@pytest.mark.parametrize("filename,payload", [("ids.csv", b"keyword_id\n20\n120\n"),
    ("ids.json", b'[{"keyword_id":20},{"keyword_id":120}]')])
def test_upload_cannot_hide_foreign_second_row(routes_contract, objects_contract, object_db, filename, payload):
    # No SEO upload route is allowlisted. The generic object checker must still
    # reject a foreign ID or reject unsupported multipart altogether (403).
    encoded = httpx.Request("POST", "http://local.test/", files={"file": (filename, BytesIO(payload))})
    raw = encoded.read()
    req = request()
    req.scope["headers"] = list(encoded.headers.raw)
    req.scope["method"] = "POST"
    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}
    req._receive = receive
    with pytest.raises(HTTPException) as caught:
        asyncio.run(objects_contract.check_write_objects(object_db[1], selected(), req, None, rule(routes_contract)))
    denied(caught.value)
    assert object_db[0].scalar(select(SeoContentAsset.title).where(SeoContentAsset.id == 1)) == "Draft"
