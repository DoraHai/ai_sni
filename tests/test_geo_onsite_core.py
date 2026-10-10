"""No-network tests of approval invalidation, real evidence and final acceptance."""
import asyncio
from datetime import datetime, timezone, timedelta
import pytest
from fastapi import HTTPException
from app import onsite_workflow as w

def fixture(module="seo"):
    kind = "title" if module == "seo" else "structured_content"
    return w.new_workflow(module, "monthly", "2026-10", "example.com",
        [dict(id="a", kind=kind, target_url="https://example.com/page", expected="审核文字", instruction="核对事实")], 7, "网站维护人员")

def change(value, action, **fields):
    return w.prepare_change(value, w.Change(action=action, expected_revision=value["revision"], **fields),
                            value["module"], "example.com", 7)

def implementation(value):
    value = change(value, "save_proposal", items=value["items"])
    value = change(value, "approve", note="已核对事实与适用条件")
    return change(value, "implement", note="已修改官网对应页面")

@pytest.mark.parametrize("module", ["seo", "geo"])
def test_delivery_requires_review_implementation_live_match_and_acceptance(module):
    value = fixture(module)
    with pytest.raises(HTTPException):
        change(value, "accept", note="不能跳过步骤")
    value = implementation(value)
    async def fetch(url, kind):
        return dict(url=url, body="<html><head><title>审核文字</title></head><body>审核文字</body></html>")
    value = asyncio.run(w.recheck(change(value, "recheck"), fetch))
    assert value["phase"] == "acceptance" and value["recheck"]["passed"]
    assert value.get("acceptance") is None
    value = change(value, "accept", note="人工核对业务质量和事实")
    assert value["phase"] == "done" and value["acceptance"]["actor"] == 7

def test_editing_any_proposal_clears_old_review_implementation_and_evidence():
    value = implementation(fixture())
    value["recheck"] = {"passed": True}
    items = [dict(value["items"][0], expected="新版本")]
    result = change(value, "save_proposal", items=items)
    assert result["phase"] == "review"
    assert not any(k in result for k in ("approval", "implementation", "recheck", "acceptance"))
    assert value["items"][0]["expected"] == "审核文字"
    with pytest.raises(HTTPException):
        change(result, "implement", note="旧审核无效")

def test_stale_versions_foreign_urls_and_removed_or_changed_checklist_are_rejected():
    value = fixture()
    with pytest.raises(HTTPException) as error:
        w.prepare_change(value, w.Change(action="save_proposal", expected_revision=99, items=value["items"]), "seo", "example.com", 7)
    assert error.value.status_code == 409
    for url in ("https://evil.example/page", "https://user@example.com/page", "https://example.com:8080/p",
                "https://example.com/page#fragment", "https://example.com.evil/p"):
        with pytest.raises(HTTPException):
            w.scoped_url(url, "example.com")
    with pytest.raises(HTTPException):
        change(value, "save_proposal", items=[dict(value["items"][0], id="removed")])
    with pytest.raises(HTTPException):
        change(value, "save_proposal", items=[dict(value["items"][0], kind="keyword")])

def test_failed_or_foreign_page_is_not_evidence_and_cannot_complete():
    value = implementation(fixture())
    async def fetch(url, kind):
        return dict(url="https://another.example/page", body="<title>审核文字</title>")
    value = asyncio.run(w.recheck(change(value, "recheck"), fetch))
    assert value["phase"] == "recheck" and not value["recheck"]["passed"]
    assert value["recheck"]["results"][0]["reason"]
    with pytest.raises(HTTPException):
        change(value, "accept", note="伪造完成")

def test_old_or_modified_recheck_cannot_be_accepted():
    value = implementation(fixture())
    value["phase"] = "acceptance"
    value["recheck"] = dict(passed=True, hash=w.proposal_hash(value["items"]),
                            at=(datetime.now(timezone.utc)-timedelta(hours=25)).isoformat())
    with pytest.raises(HTTPException):
        change(value, "accept", note="证据过期")
    value["recheck"].update(at=w.now(), hash="0"*64)
    with pytest.raises(HTTPException):
        change(value, "accept", note="不是当前版本")

def test_review_requires_explicit_values_and_implementation_note():
    value = fixture()
    value = change(value, "save_proposal", items=[dict(value["items"][0], expected="")])
    with pytest.raises(HTTPException):
        change(value, "approve", note="空预期不能审核")
    value = change(value, "save_proposal", items=fixture()["items"])
    with pytest.raises(HTTPException):
        change(value, "approve", note="")

def test_matches_visible_copy_json_subset_canonical_and_xml_without_confusing_drafts():
    def check(kind, expected, body):
        return w.check_item(dict(id="x", kind=kind, expected=expected, target_url="https://example.com/p"),
                            dict(url="https://example.com/p", body=body))["passed"]
    assert not check("keyword", "重点词", '<script>重点词</script><body>空白</body>')
    assert not check("title", "标题", '<title>标题</title><title>标题</title>')
    assert check("internal_link", "https://example.com/faq", '<a href="/faq">问题</a>')
    assert not check("canonical", "https://example.com/p", '<link rel="canonical" href="/wrong">')
    assert check("schema", '{"@type":"Organization","name":"客户"}',
                 '<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization","name":"客户","url":"https://example.com"}</script>')
    assert not check("schema", '{"@type":"Organization","name":"客户"}',
                     '<script type="application/ld+json">{"@type":"Organization","name":"别人"}</script>')
    assert not check("sitemap", "/page", "<html>/page</html>")
    assert check("sitemap", "/page", '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://example.com/page</loc></url></urlset>')

def test_quota_is_daily_bounded_and_preserves_other_settings():
    result = {"other": "kept"}
    for _ in range(20):
        result = w.reserve_recheck(result)
    assert result["other"] == "kept"
    with pytest.raises(HTTPException) as error:
        w.reserve_recheck(result)
    assert error.value.status_code == 429
    result["onsite_recheck_quota"]["day"] = "2020-01-01"
    assert w.reserve_recheck(result)["onsite_recheck_quota"]["count"] == 1

def test_geo_reader_rejects_foreign_host_before_dns_or_http(monkeypatch):
    from unittest.mock import AsyncMock
    from app.geo import audit
    guard = AsyncMock()
    monkeypatch.setattr(audit, "_ensure_public_host", guard)
    with pytest.raises(audit.GeoAuditError):
        asyncio.run(audit.safe_fetch("https://another.example/page", allowed_hosts=frozenset({"example.com"})))
    guard.assert_not_awaited()

