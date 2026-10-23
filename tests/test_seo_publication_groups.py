"""Synthetic SQLite executes actual SELECTs; HTTP tests use actual JWT/RBAC.

SQLite cannot establish PostgreSQL isolation semantics; snapshot SQL/order is
asserted separately. No provider, remote DB or migration is used.
"""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import event, select
from starlette.requests import Request

from app.database import Base, get_session
from app import seo_publication_groups as g
from app.api import seo_publication_groups as api
from app.models.distribution_inbox import DistributionInboxReceipt as R
from app.models.seo import SeoContentAsset as C, SeoContentPublication as P, SeoSiteAdvisorAssignment as A, SeoDistributionConnection as D, SeoDistributionVariant as V
from app.security.auth import AuthContext
from app.distribution_inbox_protocol import match_inbox_business_route
from test_advisor_tenant_auth import LocalSession, local_db, claims, token  # noqa: F401

SECRET = "synthetic-groups-key-at-least-32-bytes"
STAMP = datetime(2026, 10, 22, 1, 2, 3, tzinfo=timezone.utc)


def receipt(number, article=None, **changes):
    values = dict(id=str(UUID(int=number)), owner_user_id=1, device_id=str(UUID(int=999)),
                  event_id=str(UUID(int=number)), payload_digest="f" * 64, received_at=STAMP,
                  occurred_at=STAMP, platform="示例平台", title="相同标题", result="success",
                  public_url="https://example.test/same", content_bytes=1, state="active", label_state="active",
                  tenant_id=1, module="seo", scope_id=1, article_id=article,
                  article_version=1 if article else None, verification_status="unavailable", revision=0, history=[])
    values.update(changes)
    return R(**values)


@pytest.fixture
def groups_db(local_db):
    db, adapter = local_db
    Base.metadata.create_all(db.bind, tables=[m.__table__ for m in (C, P, R, D, V)])
    db.add(A(id=1, tenant_id=1, site_id=1, advisor_user_id=1, active=True))
    db.add_all([C(id=i, tenant_id=tid, site_id=site, title="相同标题", version_count=3, status="ready")
                for i, tid, site in [(10, 1, 1), (11, 1, 1), (12, 1, 1), (20, 2, 2)]])
    db.add_all([P(id=i, tenant_id=tid, content_asset_id=article, platform_code="official", platform_name="官网",
                  status=status, source_version=1, page_url="https://example.test/second" if i == 2 else "https://example.test/same", published_at=STAMP)
                for i, tid, article, status in [(1, 1, 10, "published"), (2, 1, 10, "published"),
                                               (3, 1, 11, "published"), (4, 1, 12, "preparing"),
                                               (5, 2, 20, "published")]])
    db.add_all([receipt(1, 10), receipt(2, 10, result="failed"), receipt(3, 12), receipt(4),
                receipt(5, 404), receipt(6, 20), receipt(7, 10, scope_id=2), receipt(8, scope_id=None),
                receipt(9, 10, module="geo"), receipt(10, 20, tenant_id=2, scope_id=2),
                receipt(11, state="deleted", label_state="pending", tenant_id=None, module=None, scope_id=None),
                receipt(12, state="pending", label_state="revoked", tenant_id=None, module=None, scope_id=None)])
    db.commit()
    return db, adapter


def args(**changes):
    return {**dict(tenant=1, scope=1, bucket="linked", article=None, limit=50, cursor=None), **changes}


def read(store, values=None, *, customer=False, auth="rev1"):
    ctx = AuthContext(1, "fixture", "advisor", 1, {"seo.content": "edit", "seo.site": "edit"})
    return asyncio.run(g.read_groups(store[1], ctx, values or args(), customer=customer,
                                    authorization_revision=auth, secret=SECRET))


def test_exact_ids_keep_all_sources_and_do_not_complete_native(groups_db):
    result = read(groups_db)
    assert [r["group_article_id"] for r in result["items"]] == [12, 11, 10]
    assert result["counts"] == dict(native=3, external=6, articles=3, unlinked=1, invalid=2, loaded=3)
    row = result["items"][-1]
    assert (row["native_count"], row["external_count"], row["current_version_no"]) == (2, 2, 3)
    detail = read(groups_db, args(article=10))["items"]
    assert len(detail) == 4 and len({r["key"] for r in detail}) == 4
    assert sum(r["url"] == "https://example.test/same" for r in detail) == 3  # same URL across sources is retained
    assert detail[-1]["status"] == "failed" and detail[-1]["verification"] == "unavailable"
    assert all(r["article_version_no"] == 1 for r in detail)
    assert groups_db[0].get(P, 4).status == "preparing"


def test_customer_counts_hide_invalid_and_dto_is_safe(groups_db):
    result = read(groups_db, customer=True)
    assert result["counts"] == dict(native=3, external=4, articles=3, unlinked=1, loaded=3)
    for values in [args(article=10), args(bucket="unlinked")]:
        for row in read(groups_db, values, customer=True)["items"]:
            assert not {"owner_user_id", "device_id", "event_id", "attempt_id", "history", "payload_digest",
                        "article_digest", "reported_account", "published_account", "can_link"} & set(row)
    invalid = read(groups_db, args(bucket="invalid"))["items"]
    assert len(invalid) == 2 and all(r["title"] is None and r["group_article_id"] is None for r in invalid)


def test_default_twenty_articles_sorted_by_latest_time_across_sources(groups_db):
    from datetime import timedelta
    db, _ = groups_db
    db.add_all([C(id=i, tenant_id=1, site_id=1, title="分页样本", status="ready") for i in range(100, 121)])
    # Newer timestamps deliberately have smaller article IDs.
    db.add_all([receipt(1000 + i, i, occurred_at=STAMP + timedelta(minutes=200 - i))
                for i in range(100, 121)])
    db.get(P, 1).published_at = STAMP + timedelta(days=1)
    db.commit()
    values = g.query(request(), customer=False)
    assert values["limit"] == 20
    first = read(groups_db, values)
    assert [r["group_article_id"] for r in first["items"]] == [10, *range(100, 119)]
    assert first["has_more"] and first["counts"]["articles"] == 24
    second = read(groups_db, {**values, "cursor": first["next_cursor"]})
    assert [r["group_article_id"] for r in second["items"]] == [119, 120, 12, 11]
    assert not second["has_more"]
    assert [r["latest_at"] for r in first["items"]] == sorted(
        [r["latest_at"] for r in first["items"]], reverse=True)


@pytest.mark.parametrize("bucket,article", [("linked", None), ("linked", 10), ("unlinked", None), ("invalid", None)])
def test_typed_pagination_no_omissions(groups_db, bucket, article):
    values = args(bucket=bucket, article=article, limit=1)
    found = []
    while True:
        page = read(groups_db, values)
        found.extend(r.get("key", r["group_article_id"]) for r in page["items"])
        if not page["has_more"]:
            break
        values["cursor"] = page["next_cursor"]
    expected = {("linked", None): 3, ("linked", 10): 4, ("unlinked", None): 1, ("invalid", None): 2}[(bucket, article)]
    assert len(found) == len(set(found)) == expected


def test_5101_plus_articles_and_101_plus_details(groups_db):
    db, _ = groups_db
    db.add_all([C(id=i, tenant_id=1, site_id=1, title="分页样本", status="ready") for i in range(100, 5203)])
    db.add_all([receipt(100 + i, i) for i in range(100, 5203)])
    db.add_all([receipt(10000 + i, 10) for i in range(103)])
    db.commit()
    result = read(groups_db, args(limit=100))
    assert result["counts"]["articles"] == 5106
    seen = []
    values = args(limit=100)
    while True:
        result = read(groups_db, values)
        seen.extend(r["group_article_id"] for r in result["items"])
        if not result["has_more"]:
            break
        values["cursor"] = result["next_cursor"]
    assert len(seen) == len(set(seen)) == 5106
    first = read(groups_db, args(article=10, limit=100))
    second = read(groups_db, args(article=10, limit=100, cursor=first["next_cursor"]))
    assert len(first["items"]) == 100 and len(second["items"]) == 7 and not second["has_more"]


@pytest.mark.parametrize("change", ["add", "delete", "relabel", "move", "version", "permission"])
def test_cursor_detects_collection_and_authorization_changes(groups_db, change):
    page = read(groups_db, args(limit=1))
    db, _ = groups_db
    if change == "add":
        db.add(receipt(99, 10))
    elif change == "delete":
        db.delete(db.get(R, str(UUID(int=1))))
    elif change == "relabel":
        db.get(R, str(UUID(int=1))).article_id = 11
        db.get(R, str(UUID(int=1))).revision += 1
    elif change == "move":
        db.get(C, 10).site_id = 2
    elif change == "version":
        db.get(C, 10).version_count += 1
        db.get(C, 10).updated_at = STAMP
    db.commit()
    with pytest.raises(HTTPException) as caught:
        read(groups_db, args(limit=1, cursor=page["next_cursor"]), auth="rev2" if change == "permission" else "rev1")
    assert caught.value.status_code == 409


@pytest.mark.parametrize("values", [dict(bucket="unlinked"), dict(article=10), dict(scope=2), dict(tenant=2)])
def test_cursor_cannot_cross_buckets_articles_or_scope(groups_db, values):
    page = read(groups_db, args(limit=1))
    merged = args(limit=1, cursor=page["next_cursor"])
    merged.update(values)
    with pytest.raises(HTTPException):
        read(groups_db, merged)


def test_no_dml_no_commit_and_native_statistics_unchanged(groups_db):
    db, adapter = groups_db
    from app.seo_publication_export import publication_summary
    before = db.execute(select(P.__table__)).all()
    before_receipts = db.execute(select(R.__table__)).all()
    summary = publication_summary([dict(platform="官网", capture_kind="none") for _ in range(3)], "示例网站", "2026-10", STAMP)
    statements = []

    def select_only(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)
        assert statement.lstrip().upper().startswith("SELECT")
        assert "FOR UPDATE" not in statement.upper()

    event.listen(db.bind, "before_cursor_execute", select_only)
    try:
        for values in [args(), args(article=10), args(bucket="unlinked"), args(bucket="invalid")]:
            read(groups_db, values)
        assert db.execute(select(P.__table__)).all() == before
        assert db.execute(select(R.__table__)).all() == before_receipts
    finally:
        event.remove(db.bind, "before_cursor_execute", select_only)
    assert statements and not db.dirty and not db.new
    assert publication_summary([dict(platform="官网", capture_kind="none") for _ in range(3)], "示例网站", "2026-10", STAMP) == summary


def test_original_excel_and_monthly_report_ignore_external_rows(groups_db, monkeypatch):
    from io import BytesIO
    from openpyxl import load_workbook
    from app.api import seo_page_captures as exports
    from app.models.seo_page_capture import SeoPageCapture
    from app.models.seo_site_analytics import SeoSiteExportTemplate
    from app.seo_monthly_report import build_report_context, render_report_html
    db, adapter = groups_db
    Base.metadata.create_all(db.bind, tables=[m.__table__ for m in (SeoPageCapture, SeoSiteExportTemplate)])
    actor = AuthContext(2, "fixture", "customer", 1, {"seo.site": "view", "seo.content": "view"})
    rendered = []
    original = exports.build_publication_list_workbook
    def capture(rows, summary, **kw):
        context = build_report_context(site_name="示例网站", month="2026-10", rows=rows, generated_at=STAMP)
        rendered.append((rows, summary["total"], render_report_html(context)))
        return original(rows, summary, **kw)
    monkeypatch.setattr(exports, "build_publication_list_workbook", capture)
    def export():
        response = asyncio.run(exports.export_publication_list(1, 1, "2026-10", adapter, actor))
        book = load_workbook(BytesIO(response.body))
        return list(book["发布明细"].values)
    before = export()
    db.add_all([receipt(20001, 10), receipt(20002, 12), receipt(20003)])
    db.commit()
    result = read(groups_db)
    assert result["counts"]["native"] == 3 and result["counts"]["external"] == 9
    assert export() == before
    assert len(before) == 4 and rendered[0] == rendered[1]


def request(query="tenant_id=1&scope_id=1", *, customer=False, method="GET", raw=None):
    path = "/api/v1/seo/" + ("workbench" if customer else "distribution/v2") + "/publication-groups"
    return Request(dict(type="http", method=method, path=path, raw_path=raw or path.encode(),
                        query_string=query.encode(), headers=[], scheme="http", server=("test", 80)))


@pytest.mark.parametrize("extra", ["&site_id=1", "&tenant_id=1", "&scope_id=1", "&ownerUserId=1",
                                    "&offset=1", "&article_id=9007199254740992", "&limit=101", "&limit=0",
                                    "&bucket=unlinked&article_id=10", "&bucket=other", "&cursor="])
def test_strict_query(extra):
    with pytest.raises(HTTPException):
        g.query(request("tenant_id=1&scope_id=1" + extra), customer=False)


@pytest.mark.parametrize("method", ["HEAD", "POST", "PUT", "DELETE"])
def test_exact_method_and_raw_path(method):
    with pytest.raises(HTTPException):
        g.query(request(method=method), customer=False)
    assert not match_inbox_business_route(method, request().url.path)


def test_customer_bucket_and_alias_rejected():
    for q in ["tenant_id=1&scope_id=1", "tenant_id=1&site_id=1&bucket=invalid", "tenant_id=1&site_id=1&scope_id=1"]:
        with pytest.raises(HTTPException):
            g.query(request(q, customer=True), customer=True)
    with pytest.raises(HTTPException):
        g.query(request(raw=b"/api/v1/seo/distribution/v2/%70ublication-groups"), customer=False)


def test_budget_failure_is_not_partial_success(groups_db, monkeypatch):
    monkeypatch.setattr(g, "REVISION_BUDGET", 2)
    with pytest.raises(HTTPException) as caught:
        read(groups_db)
    assert caught.value.status_code == 503


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/plain,hi", "https://u:p@example.test/", "https://example.test:bad/", "https://example.test/\nq", "//example.test/"])
def test_dangerous_links_not_clickable(url):
    assert g.safe_url(url) is None


def test_snapshot_is_first_read_and_uses_read_only_repeatable_read():
    class Session:
        def __init__(self):
            self.statements = []
        def in_transaction(self):
            return False
        async def execute(self, statement):
            self.statements.append(str(statement))
    s = Session()
    asyncio.run(api.snapshot(s))
    assert s.statements[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    assert len(s.statements) == 3


def test_http_real_auth_customer_internal_denied_and_revoked_assignment(groups_db, monkeypatch):
    from app.security import auth
    from app.config import get_settings
    db, adapter = groups_db
    # Customer retains both workbench view permissions, without becoming an advisor.
    from app.models.role import Role
    db.get(Role, 2).permissions = {"seo.content": "view", "seo.site": "view"}
    db.commit()
    monkeypatch.setattr(auth, "_jwt_secret", lambda: SECRET)
    monkeypatch.setattr(api, "_jwt_secret", lambda: SECRET)
    monkeypatch.setattr(get_settings(), "advisor_multi_tenant_enabled", True)
    app = FastAPI()
    app.include_router(api.router)

    async def session_override():
        yield adapter
    async def snapshot_override():
        return adapter
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[api.snapshot] = snapshot_override

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            customer = {"Authorization": "Bearer " + token({"sub": "2", "exp": 4102444800})}
            advisor = {"Authorization": "Bearer " + token(claims())}
            url = "/api/v1/seo/workbench/publication-groups?tenant_id=1&site_id=1"
            response = await client.get(url, headers=customer)
            assert response.status_code == 200, response.text
            assert response.headers["cache-control"] == "private, no-store"
            assert response.json()["counts"]["external"] == 4
            response = await client.get("/api/v1/seo/distribution/v2/publication-groups?tenant_id=1&scope_id=1", headers=customer)
            assert response.status_code == 403
            response = await client.get(url + "&article_id=10", headers=advisor)
            assert response.status_code == 200, response.text
            db.get(A, 1).active = False
            db.commit()
            assert (await client.get(url, headers=advisor)).status_code == 403
    asyncio.run(run())


def test_fastapi_starts_snapshot_before_auth_using_same_session(groups_db, monkeypatch):
    from fastapi import Depends
    calls = []
    class Recording(LocalSession):
        def in_transaction(self):
            return False
        async def execute(self, statement, *a, **kw):
            sql = str(statement)
            if sql.startswith("SET "):
                calls.append(sql)
                return None
            return await super().execute(statement, *a, **kw)
    adapter = Recording(groups_db[0])
    async def session_override():
        yield adapter
    async def authenticate(session=Depends(get_session)):
        assert session is adapter
        calls.append("AUTH")
        return AuthContext(2, "fixture", "customer", 1, {"seo.site": "view", "seo.content": "view"})
    monkeypatch.setattr(api, "_jwt_secret", lambda: SECRET)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[api.require_scoped_auth] = authenticate
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            result = await client.get("/api/v1/seo/workbench/publication-groups?tenant_id=1&site_id=1")
            assert result.status_code == 200, result.text
    asyncio.run(run())
    assert calls[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    assert calls[3] == "AUTH"

def test_single_table_exact_id_url_dedup_and_unlinked_stays_visible(groups_db):
    result = read(groups_db, args(bucket="records", limit=20))
    rows = result["items"]
    assert result["counts"]["total"] == 7
    native = next(r for r in rows if r["native_publication_id"] == 1)
    assert native["also_reported"] is True and native["source"] == "native"
    assert not any(r["external_receipt_id"] in {str(UUID(int=1)), str(UUID(int=2))} for r in rows)
    # Unlinked and a different exact article remain separate even with identical titles/URLs.
    assert any(r["external_receipt_id"] == str(UUID(int=4)) and r["group_article_id"] is None for r in rows)
    assert any(r["external_receipt_id"] == str(UUID(int=3)) and r["group_article_id"] == 12 for r in rows)
    assert all(r["title"] is None for r in rows if r["invalid"])
    assert groups_db[0].get(P, 4).status == "preparing"


def test_single_table_filters_beijing_month_and_accounts(groups_db):
    from datetime import timedelta
    db, _ = groups_db
    db.add_all([receipt(30, occurred_at=datetime(2026, 9, 30, 15, 59, tzinfo=timezone.utc), reported_account="示例旧账号"),
                receipt(31, occurred_at=datetime(2026, 9, 30, 16, 0, tzinfo=timezone.utc), reported_account="示例回传账号"),
                receipt(32, occurred_at=datetime(2026, 10, 31, 16, 0, tzinfo=timezone.utc), published_account="示例指定账号")])
    db.commit()
    october = read(groups_db, args(bucket="records", month="2026-10", source="external_report"))
    assert october["counts"]["total"] == 6  # includes native row marked also-reported
    assert any(r["account"] == "示例回传账号" for r in october["items"])
    assert all(r["account"] != "示例旧账号" and r["account"] != "示例指定账号" for r in october["items"])
    native = read(groups_db, args(bucket="records", month="2026-10", source="native"))
    assert len(native["items"]) == 3 and all(r["source"] == "native" for r in native["items"])
    with pytest.raises(HTTPException):
        read(groups_db, args(bucket="records", month="2026-09", source="native", cursor=read(groups_db, args(bucket="records", limit=1))["next_cursor"]))


def test_single_table_default_twenty_descending_no_missing_rows(groups_db):
    from datetime import timedelta
    db, _ = groups_db
    db.add_all([receipt(100 + i, occurred_at=STAMP + timedelta(minutes=i + 1)) for i in range(23)])
    db.commit()
    values = g.query(request("tenant_id=1&scope_id=1&bucket=records"), customer=False)
    assert values["limit"] == 20
    first = read(groups_db, values)
    second = read(groups_db, {**values, "cursor": first["next_cursor"]})
    assert len(first["items"]) == 20 and len(second["items"]) == 10 and not second["has_more"]
    rows = first["items"] + second["items"]
    assert len({r["key"] for r in rows}) == 30
    assert [r["event_at"] for r in rows] == sorted([r["event_at"] for r in rows], reverse=True)
    assert rows[0]["external_receipt_id"] == str(UUID(int=122))


def test_records_query_filters_internal_only_and_select_only(groups_db):
    for extra in ["&bucket=records&month=2026-13", "&bucket=records&source=unknown", "&month=2026-10", "&bucket=records&article_id=10"]:
        with pytest.raises(HTTPException):
            g.query(request("tenant_id=1&scope_id=1" + extra), customer=False)
    with pytest.raises(HTTPException):
        g.query(request("tenant_id=1&site_id=1&bucket=records", customer=True), customer=True)
    db, _ = groups_db
    before = db.execute(select(P.__table__)).all()
    statements = []
    def select_only(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)
        assert statement.lstrip().upper().startswith("SELECT") and "FOR UPDATE" not in statement.upper()
    event.listen(db.bind, "before_cursor_execute", select_only)
    try:
        read(groups_db, args(bucket="records"))
        assert db.execute(select(P.__table__)).all() == before
    finally:
        event.remove(db.bind, "before_cursor_execute", select_only)
    assert statements and not db.dirty and not db.new


def test_records_postgres_event_and_month_cursor_binds_are_aware_utc(groups_db):
    from sqlalchemy.dialects import postgresql
    expression = g._UtcNativeTime(g.func.coalesce(P.published_at, P.updated_at))
    assert expression.type.timezone is True
    assert "AT TIME ZONE 'UTC'" in str(expression.compile(dialect=postgresql.dialect()))
    adapter = groups_db[1]
    original = adapter.execute
    statements = []
    async def capture(statement, *a, **kw):
        statements.append(statement)
        return await original(statement, *a, **kw)
    adapter.execute = capture
    try:
        first = read(groups_db, args(bucket="records", month="2026-10", limit=1))
        read(groups_db, args(bucket="records", month="2026-10", limit=1, cursor=first["next_cursor"]))
    finally:
        adapter.execute = original
    binds = [bind for statement in statements for bind in statement.compile(dialect=postgresql.dialect()).binds.values()
             if isinstance(bind.value, datetime)]
    assert binds and all(bind.type.timezone and bind.value.tzinfo is not None for bind in binds)
