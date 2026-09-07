import asyncio
import os
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "1234567890abcdefsecret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.api import seo as api
from app.security.auth import AuthContext, _required


class Rows:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


def _ctx(*, tenant_id=7, permissions=None):
    return AuthContext(
        user_id=11,
        username="viewer",
        role_name="viewer",
        tenant_id=tenant_id,
        permissions=permissions or {"seo.content": "view"},
    )


def _page(page_id=31, url="https://example.com/article", **changes):
    values = {
        "id": page_id,
        "tenant_id": 7,
        "site_id": 9,
        "url": url,
        "status": "healthy",
        "http_status": 200,
        "last_checked_at": datetime(2026, 9, 7, 4, 0),
        "last_error": None,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _content(content_id=41, **changes):
    values = {
        "id": content_id,
        "tenant_id": 7,
        "site_id": 9,
        "content_type": "article",
        "title": "Example article",
        "status": "approved",
        "review_submitted_at": datetime(2026, 9, 6, 2, 0),
        "reviewed_at": datetime(2026, 9, 6, 3, 0),
        "published_at": datetime(2026, 9, 6, 4, 0),
        "created_at": datetime(2026, 9, 5, 1, 0),
        "updated_at": datetime(2026, 9, 6, 4, 0),
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _publication(publication_id=51, page_url="https://example.com/article", **changes):
    values = {
        "id": publication_id,
        "tenant_id": 7,
        "content_asset_id": 41,
        "platform_code": "zhihu",
        "platform_name": "知乎",
        "publish_mode": "assisted",
        "status": "published",
        "page_url": page_url,
        "external_id": "external-1",
        "published_at": datetime(2026, 9, 6, 4, 0),
        "last_synced_at": datetime(2026, 9, 6, 5, 0),
        "last_error": None,
        "created_at": datetime(2026, 9, 6, 1, 0),
        "updated_at": datetime(2026, 9, 6, 5, 0),
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _attempt(attempt_id=61, **changes):
    values = {
        "id": attempt_id,
        "tenant_id": 7,
        "publication_id": 51,
        "action": "publish",
        "status": "succeeded",
        "error": None,
        "started_at": datetime(2026, 9, 6, 3, 59),
        "completed_at": datetime(2026, 9, 6, 4, 0),
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _snapshot(**changes):
    values = {
        "id": 71,
        "tenant_id": 7,
        "site_id": 9,
        "crawl_run_id": 81,
        "url": "https://example.com/article",
        "final_url": "https://example.com/article",
        "fetch_error": None,
        "error_type": None,
        "status_code": 200,
        "content_type": "text/html",
        "content_length": 2000,
        "response_time_ms": 60,
        "main_content_extractable": True,
        "word_count": 500,
        "title": "Example article",
        "h1_count": 1,
        "robots_allowed": True,
        "indexable": True,
        "internal_links_count": 8,
        "external_links_count": 2,
        "images_count": 4,
        "images_missing_alt_count": 1,
        "image_alt_evidence": {
            "candidate_count": 1,
            "counts": {"missing": 1, "empty": 0, "whitespace": 0},
            "truncated": False,
        },
        "issue_codes": ["image_alt_missing", "thin_content"],
        "fetched_at": datetime(2026, 9, 7, 4, 0),
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _db(*, rows, attempts, pages, total=1):
    return SimpleNamespace(
        scalar=AsyncMock(return_value=total),
        execute=AsyncMock(return_value=Rows(rows)),
        scalars=AsyncMock(side_effect=[Rows(attempts), Rows(pages)]),
        commit=AsyncMock(),
        flush=AsyncMock(),
        refresh=AsyncMock(),
        rollback=AsyncMock(),
        add=MagicMock(),
        delete=AsyncMock(),
    )


def test_url_normalization_contract_is_conservative_and_deterministic():
    assert api._normalize_workbench_publication_url(
        "HTTPS://Example.COM:443/Article/?b=2&a=1&a=#section"
    ) == "https://example.com/Article?a=1&a=&b=2"
    assert api._normalize_workbench_publication_url(
        "https://example.com/Article?a=1&a=2"
    ) != api._normalize_workbench_publication_url(
        "https://example.com/Article?a=2&a=1"
    )
    assert api._normalize_workbench_publication_url("http://EXAMPLE.com:80") == "http://example.com/"
    assert api._normalize_workbench_publication_url("https://example.com:8443/a") == "https://example.com:8443/a"
    assert api._normalize_workbench_publication_url("https://example.com/Article") != (
        api._normalize_workbench_publication_url("https://example.com/article")
    )
    assert api._normalize_workbench_publication_url("ftp://example.com/a") is None
    assert api._normalize_workbench_publication_url("https://user:secret@example.com/a") is None
    assert api._normalize_workbench_publication_url("https://example.com/%zz") is None


def test_association_distinguishes_missing_no_match_unique_and_multiple():
    missing, selected = api._associate_workbench_publication_page(
        None, [], inventory_complete=True
    )
    assert missing["association_status"] == "publication_url_missing" and selected is None

    no_match, selected = api._associate_workbench_publication_page(
        "https://example.com/other", [_page()], inventory_complete=True
    )
    assert no_match["association_status"] == "no_match" and selected is None

    unique, selected = api._associate_workbench_publication_page(
        "HTTPS://EXAMPLE.COM:443/article/?b=2&a=1#x",
        [_page(url="https://example.com/article?a=1&b=2")],
        inventory_complete=True,
    )
    assert unique["association_status"] == "exact_unique"
    assert selected.id == 31

    candidates = [_page(page_id=index, url="https://example.com/article") for index in range(1, 8)]
    multiple, selected = api._associate_workbench_publication_page(
        "https://example.com/article/", candidates, inventory_complete=True
    )
    assert multiple["association_status"] == "multiple_matches"
    assert multiple["candidate_count"] == 7
    assert len(multiple["candidates"]) == api.WORKBENCH_ASSOCIATION_CANDIDATE_LIMIT
    assert selected is None


def test_incomplete_inventory_never_claims_a_unique_match():
    association, selected = api._associate_workbench_publication_page(
        "https://example.com/article", [_page()], inventory_complete=False
    )
    assert association["association_status"] == "page_inventory_incomplete"
    assert association["candidate_count"] is None
    assert selected is None


def test_page_check_keeps_crawl_http_body_link_and_image_evidence_separate():
    result = api._workbench_page_check_payload(_page(), _snapshot())
    assert result["coverage"] == "available"
    assert result["crawl"]["snapshot_id"] == 71
    assert result["http"]["status_code"] == 200
    assert result["body"]["main_content_extractable"] is True
    assert result["links"] == {
        "coverage": "counts_only",
        "reason": "snapshot_stores_link_counts;_edge_details_are_not_embedded",
        "internal_count": 8,
        "external_count": 2,
    }
    assert result["images"]["missing_alt_count"] == 1
    assert result["images"]["issue_codes"] == ["image_alt_missing"]

    failed = api._workbench_page_check_payload(
        _page(), _snapshot(fetch_error="timeout", error_type="timeout", status_code=None)
    )
    assert failed["coverage"] == "failed"
    assert failed["reason"] == "stored_crawl_failed"
    assert failed["crawl"]["fetch_error"] == "timeout"


def test_endpoint_returns_scoped_stored_evidence_and_has_no_write_side_effect(monkeypatch):
    publication = _publication()
    content = _content()
    page = _page()
    snapshot = _snapshot()
    db = _db(rows=[(publication, content)], attempts=[_attempt()], pages=[page])
    module_guard = AsyncMock()
    tenant_guard = AsyncMock(return_value=SimpleNamespace(id=7))
    site_guard = AsyncMock(return_value=SimpleNamespace(id=9, tenant_id=7))
    snapshot_lookup = AsyncMock(return_value=snapshot)
    crawl = AsyncMock(side_effect=AssertionError("GET must not crawl"))
    publish = AsyncMock(side_effect=AssertionError("GET must not publish"))
    save_snapshot = AsyncMock(side_effect=AssertionError("GET must not save snapshots"))
    monkeypatch.setattr(api, "ensure_module_access", module_guard)
    monkeypatch.setattr(api, "_tenant", tenant_guard)
    monkeypatch.setattr(api, "_seo_site", site_guard)
    monkeypatch.setattr(api, "_latest_workbench_page_snapshot", snapshot_lookup)
    monkeypatch.setattr(api, "crawl_site", crawl)
    monkeypatch.setattr(api, "publish_content", publish)
    monkeypatch.setattr(api, "save_page_snapshot", save_snapshot)

    ctx = _ctx()
    result = asyncio.run(
        api.list_workbench_publication_page_evidence(
            tenant_id=7,
            site_id=9,
            content_id=41,
            publication_id=51,
            page=2,
            page_size=2,
            session=db,
            ctx=ctx,
        )
    )

    assert result["read_only"] is True
    assert result["tenant_id"] == 7 and result["site_id"] == 9
    assert result["filters"] == {"content_id": 41, "publication_id": 51}
    assert result["page"] == 2 and result["page_size"] == 2
    assert result["items"][0]["publication"]["status"] == "published"
    assert result["items"][0]["latest_attempt"]["status"] == "succeeded"
    assert result["items"][0]["page_association"]["association_status"] == "exact_unique"
    assert result["items"][0]["page_check"]["coverage"] == "available"
    assert "request_summary" not in result["items"][0]["latest_attempt"]
    module_guard.assert_awaited_once_with(db, ctx, 7, "seo")
    tenant_guard.assert_awaited_once_with(db, 7)
    site_guard.assert_awaited_once_with(db, 7, 9)
    snapshot_lookup.assert_awaited_once_with(
        db, tenant_id=7, site_id=9, page_url="https://example.com/article"
    )

    count_sql = str(db.scalar.await_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    page_sql = str(db.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    inventory_sql = str(db.scalars.await_args_list[1].args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "seo_content_publications.tenant_id = 7" in count_sql
    assert "seo_content_assets.site_id = 9" in count_sql
    assert "seo_content_publications.content_asset_id = 41" in count_sql
    assert "seo_content_publications.id = 51" in count_sql
    assert "LIMIT 2 OFFSET 2" in page_sql
    assert "seo_site_pages.tenant_id = 7" in inventory_sql
    assert "seo_site_pages.site_id = 9" in inventory_sql
    db.add.assert_not_called()
    db.commit.assert_not_awaited()
    db.flush.assert_not_awaited()
    db.refresh.assert_not_awaited()
    db.rollback.assert_not_awaited()
    db.delete.assert_not_awaited()
    crawl.assert_not_awaited()
    publish.assert_not_awaited()
    save_snapshot.assert_not_awaited()


def test_authorized_empty_result_does_not_scan_attempts_or_pages(monkeypatch):
    db = _db(rows=[], attempts=[], pages=[], total=0)
    monkeypatch.setattr(api, "ensure_module_access", AsyncMock())
    monkeypatch.setattr(api, "_tenant", AsyncMock(return_value=SimpleNamespace(id=7)))
    monkeypatch.setattr(
        api, "_seo_site", AsyncMock(return_value=SimpleNamespace(id=9, tenant_id=7))
    )

    result = asyncio.run(
        api.list_workbench_publication_page_evidence(
            tenant_id=7,
            site_id=9,
            content_id=None,
            publication_id=None,
            page=1,
            page_size=20,
            session=db,
            ctx=_ctx(),
        )
    )

    assert result["total"] == 0 and result["total_pages"] == 0
    assert result["items"] == []
    assert result["coverage"]["state"] == "complete"
    db.scalars.assert_not_awaited()
    db.commit.assert_not_awaited()


def test_endpoint_rejects_cross_tenant_and_missing_permissions_before_database(monkeypatch):
    module_guard = AsyncMock()
    monkeypatch.setattr(api, "ensure_module_access", module_guard)
    db = SimpleNamespace(scalar=AsyncMock(), execute=AsyncMock(), scalars=AsyncMock())

    with pytest.raises(HTTPException) as cross_tenant:
        asyncio.run(
            api.list_workbench_publication_page_evidence(
                tenant_id=8,
                site_id=9,
                content_id=None,
                publication_id=None,
                page=1,
                page_size=20,
                session=db,
                ctx=_ctx(tenant_id=7),
            )
        )
    assert cross_tenant.value.status_code == 403

    with pytest.raises(HTTPException) as no_permission:
        asyncio.run(
            api.list_workbench_publication_page_evidence(
                tenant_id=7,
                site_id=9,
                content_id=None,
                publication_id=None,
                page=1,
                page_size=20,
                session=db,
                ctx=_ctx(permissions={"seo.dashboard": "view"}),
            )
        )
    assert no_permission.value.status_code == 403
    module_guard.assert_not_awaited()
    db.scalar.assert_not_awaited()
    db.execute.assert_not_awaited()
    db.scalars.assert_not_awaited()


def test_endpoint_stops_when_seo_module_is_unavailable(monkeypatch):
    module_guard = AsyncMock(side_effect=HTTPException(403, "SEO module unavailable"))
    tenant_guard = AsyncMock()
    site_guard = AsyncMock()
    monkeypatch.setattr(api, "ensure_module_access", module_guard)
    monkeypatch.setattr(api, "_tenant", tenant_guard)
    monkeypatch.setattr(api, "_seo_site", site_guard)
    db = SimpleNamespace(scalar=AsyncMock(), execute=AsyncMock(), scalars=AsyncMock())

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            api.list_workbench_publication_page_evidence(
                tenant_id=7,
                site_id=9,
                content_id=None,
                publication_id=None,
                page=1,
                page_size=20,
                session=db,
                ctx=_ctx(),
            )
        )

    assert error.value.status_code == 403
    tenant_guard.assert_not_awaited()
    site_guard.assert_not_awaited()
    db.scalar.assert_not_awaited()
    db.execute.assert_not_awaited()
    db.scalars.assert_not_awaited()


def test_endpoint_rejects_a_site_outside_the_tenant_before_evidence_queries(monkeypatch):
    monkeypatch.setattr(api, "ensure_module_access", AsyncMock())
    monkeypatch.setattr(api, "_tenant", AsyncMock(return_value=SimpleNamespace(id=7)))
    monkeypatch.setattr(
        api,
        "_seo_site",
        AsyncMock(side_effect=HTTPException(404, "SEO site does not exist for this tenant")),
    )
    db = SimpleNamespace(scalar=AsyncMock(), execute=AsyncMock(), scalars=AsyncMock())

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            api.list_workbench_publication_page_evidence(
                tenant_id=7,
                site_id=99,
                content_id=None,
                publication_id=None,
                page=1,
                page_size=20,
                session=db,
                ctx=_ctx(),
            )
        )

    assert error.value.status_code == 404
    db.scalar.assert_not_awaited()
    db.execute.assert_not_awaited()
    db.scalars.assert_not_awaited()


def test_route_has_exact_read_permission_and_page_size_maximum():
    assert _required(
        "/api/v1/seo/workbench/publication-page-evidence", "GET"
    ) == ({"seo.content", "seo.site"}, False)
    assert _required(
        "/api/v1/seo/workbench/publication-page-evidence", "POST"
    ) == ({"seo.content", "seo.site"}, False)

    route = next(
        item
        for item in api.router.routes
        if item.path == "/api/v1/seo/workbench/publication-page-evidence"
    )
    page_size = next(field for field in route.dependant.query_params if field.name == "page_size")
    page_number = next(field for field in route.dependant.query_params if field.name == "page")
    size_limits = {type(item).__name__: item for item in page_size.field_info.metadata}
    page_limits = {type(item).__name__: item for item in page_number.field_info.metadata}
    assert size_limits["Le"].le == 100 and size_limits["Ge"].ge == 1
    assert page_limits["Ge"].ge == 1
