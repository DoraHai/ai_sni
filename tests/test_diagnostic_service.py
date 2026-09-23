import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

for key, value in {
    "DATABASE_URL": "postgresql+asyncpg://test:test@localhost/test",
    "BAIDU_APP_ID": "test", "BAIDU_SECRET_KEY": "test",
    "BAIDU_DEFAULT_USERNAME": "test", "BAIDU_DEFAULT_UCID": "0",
    "BAIDU_SELF_ACCESS_TOKEN": "test", "BAIDU_SELF_TOKEN_EXPIRES_AT": "2099-01-01T00:00:00Z",
    "CRYPTO_MASTER_KEY_B64": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "ADMIN_API_KEY": "test-admin-key",
}.items():
    os.environ.setdefault(key, value)

import pytest
from fastapi.testclient import TestClient
from app.diagnostic_main import app
from app.diagnostic import routes
from app.database import get_session
from app.security.auth import AuthContext, require_auth


@pytest.fixture
def context():
    return AuthContext(1, "diagnostic-test", "operator", 7, {"geo.diagnosis": "edit"})


@pytest.fixture
def db():
    return SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(id=7)),
                           commit=AsyncMock(), refresh=AsyncMock())


@pytest.fixture
def client(context, db):
    app.dependency_overrides[require_auth] = lambda: context
    app.dependency_overrides[get_session] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_route_surface_is_isolated():
    paths = {r.path for r in app.routes}
    assert "/api/v1/diagnostic/assets/brand/discover" in paths
    assert "/api/v1/diagnostic/assets/brand" in paths
    assert "/api/v1/diagnostic/audits" in paths
    assert "/api/v1/diagnostic/pagespeed" in paths
    assert not any(p.startswith("/api/v1/geo/") for p in paths)


def test_discovery_rejects_cross_tenant_before_fetch(client, monkeypatch):
    fetch = AsyncMock()
    monkeypatch.setattr(routes, "discover_brand_profile", fetch)
    response = client.post("/api/v1/diagnostic/assets/brand/discover",
                           json={"tenant_id": 8, "website": "https://example.com"})
    assert response.status_code == 403
    fetch.assert_not_awaited()


def test_discovery_returns_candidate_and_preserves_fetch_error(client, monkeypatch):
    fetch = AsyncMock(return_value={"brand": {"name": "Example"}, "ai_used": False})
    monkeypatch.setattr(routes, "discover_brand_profile", fetch)
    payload = {"tenant_id": 7, "website": "https://example.com"}
    assert client.post("/api/v1/diagnostic/assets/brand/discover", json=payload).json()["brand"]["name"] == "Example"
    fetch.side_effect = routes.GeoAuditError("网站访问失败：HTTP 403")
    response = client.post("/api/v1/diagnostic/assets/brand/discover", json=payload)
    assert response.status_code == 400
    assert "HTTP 403" in response.json()["detail"]


def test_readonly_user_cannot_save_brand(client, context):
    context.permissions = {"geo.diagnosis": "view"}
    assert client.put("/api/v1/diagnostic/assets/brand",
                      json={"tenant_id": 7, "name": "Example"}).status_code == 403


def test_brand_save_preserves_other_domains_and_tenant_master(client, db, monkeypatch):
    monkeypatch.setattr(routes, "_diagnosis_brand_store", AsyncMock(return_value={
        "active_key": "old.example", "profiles": {"old.example": {"name": "Old"}}}))
    upsert = AsyncMock()
    monkeypatch.setattr(routes, "_upsert_memory", upsert)
    response = client.put("/api/v1/diagnostic/assets/brand", json={
        "tenant_id": 7, "name": "Example", "website": "https://example.com",
        "industry": "Manufacturing", "core_products": ["Motors"]})
    assert response.status_code == 200
    saved = upsert.await_args.kwargs["data"]
    assert saved["profiles"]["old.example"]["name"] == "Old"
    assert saved["profiles"]["example.com"]["name"] == "Example"
    assert vars(db.get.return_value) == {"id": 7}


def test_audit_attaches_chinaz_and_keeps_existing_schema(client, db, monkeypatch):
    monkeypatch.setattr(routes, "_diagnosis_brand_store", AsyncMock(return_value={
        "active_key": "example.com", "profiles": {"example.com": {
            "name": "Example", "website": "https://example.com",
            "industry": "Manufacturing", "core_products": ["Motors"]}}}))
    scan = {"url": "https://example.com", "final_url": "https://example.com",
            "score": 80, "title": "Example", "description": "Example company",
            "snapshot": {}, "checks": []}
    monkeypatch.setattr(routes, "audit_site", AsyncMock(return_value=scan))
    monkeypatch.setattr(routes, "fetch_chinaz_seo_metrics", AsyncMock(return_value={
        "baidu_index": {"status": "available", "site_count": 12}}))
    inserted = []
    db.add = inserted.append
    response = client.post("/api/v1/diagnostic/audits", json={
        "tenant_id": 7, "url": "https://example.com", "scope": "site"})
    assert response.status_code == 200
    assert response.json()["snapshot"]["external_metrics"]["baidu_index"]["site_count"] == 12
    assert inserted[0].__tablename__ == "geo_audit_runs"


@pytest.mark.parametrize('robots_ok,text,passed,deduction', [
    (False, '', None, 0),
    (True, '<html><body>Login required</body></html>', None, 0),
    (True, 'User-agent: *\nAllow: /\n' + '# padding\n' * 2500, None, 0),
    (True, 'User-agent: GPTBot\nDisallow: /', False, 6),
    (True, 'User-agent: *\nDisallow: /', False, 6),
    (True, 'User-agent: GPTBot\nDisallow: /private/', True, 0),
    (True, 'User-agent: *\nAllow: /', True, 0),
    (True, '', True, 0),
])
def test_crawler_tri_state_and_problem_contract(monkeypatch, robots_ok, text, passed, deduction):
    import asyncio
    from app.diagnostic import audit as rules
    from app.diagnostic.generate import deterministic_advice
    doc = rules.PageDocument('https://example.com/', 'https://example.com/',
                             '<html lang="zh"><title>Example company website</title><h1>Example</h1></html>', 'text/html')
    monkeypatch.setattr(rules, 'safe_fetch', AsyncMock(return_value=doc))
    async def optional(url):
        return (robots_ok, text) if url.endswith('/robots.txt') else (False, '')
    monkeypatch.setattr(rules, '_optional_text', optional)
    result = asyncio.run(rules.audit_url('https://example.com/'))
    crawler = next(row for row in result['checks'] if row['code'] == 'ai_crawlers')
    assert crawler['passed'] is passed
    assert crawler['status'] == ('unavailable' if passed is None else 'passed' if passed else 'failed')
    assert crawler['deduction'] == deduction
    assert result['score'] == max(0, 100 - sum(row['deduction'] for row in result['checks']))
    assert result['rule_version'] == '1.1.1'
    assert result['snapshot']['total'] == len(result['checks']) - (passed is None)
    result['checks'] = [crawler]
    assert bool(routes._preview_payload(result, 7)['problems']) is (passed is False)
    assert bool(deterministic_advice([crawler])) is (passed is False)
    if passed is None:
        assert result['snapshot']['ai_crawlers']['agents'] == []
        assert '无法确认' in crawler['title']
        assert '未满足' not in crawler['reason']


@pytest.mark.parametrize('states,expected,deduction', [
    ([None, None], None, 0), ([None, True], True, 0),
    ([True, None], True, 0), ([None, False], False, 6),
    ([True, False, None], False, 2.4),
])
def test_site_crawler_ignores_unavailable_pages(states, expected, deduction):
    from app.diagnostic.audit import _finding
    from app.diagnostic.site_audit import aggregate_site_results
    urls = ['https://example.com/', 'https://example.com/products/a', 'https://example.com/about']
    rows = []
    for passed, url in zip(states, urls):
        check = _finding('ai_crawlers', '主流 AI 爬虫未被整站拦截', 'AI 可访问性', 'high', passed,
                         'robots.txt 不可读，无法审计 AI 爬虫 UA' if passed is None else '已读取规则', '核查规则', 6)
        rows.append(dict(final_url=url, url=url, title=url, rule_version='1.1.1', score=100-check['deduction'],
                         checks=[check], snapshot={'passed': int(passed is True), 'total': int(passed is not None)}))
    result = aggregate_site_results(rows, discovery_source='sitemap', requested_count=len(rows))
    check = result['checks'][0]
    assert check['passed'] is expected
    assert check['deduction'] == deduction
    assert check['status'] == ('unavailable' if expected is None else 'passed' if expected else 'failed')
    assert [row['passed'] for row in check['page_evidence']] == states
    assert result['score'] == round(100-deduction)
    assert result['snapshot']['total'] == int(expected is not None)
    assert all('未满足' not in row['reason'] for row in check['page_evidence'] if row['passed'] is None)


def test_saved_payload_preserves_recorded_rule_version_and_unknown_state():
    run = SimpleNamespace(id=1, tenant_id=7, url='https://example.com', final_url='https://example.com',
                          status='completed', score=94, page_title='Example', page_description='',
                          snapshot={'rule_version': '1.1.1'}, findings=[{'code': 'ai_crawlers', 'passed': None, 'status': 'unavailable', 'deduction': 0}],
                          advice=[], advice_source='', json_ld={}, llms_text='', created_at=None, updated_at=None)
    assert routes._payload(run)['problems'] == []
    assert routes._payload(run)['rule_version'] == '1.1.1'
    run.snapshot = {}
    assert routes._payload(run)['rule_version'] is None


def test_ai_advice_never_receives_unknown_crawler(monkeypatch):
    import asyncio
    from app.diagnostic import ai_client
    from app.diagnostic.generate import ai_advice
    chat = AsyncMock(return_value={'recommendations': []})
    monkeypatch.setattr(ai_client, 'is_enabled', lambda: True)
    monkeypatch.setattr(ai_client, 'chat_json', chat)
    findings = [{'code':'ai_crawlers', 'passed':None, 'severity':'high', 'deduction':0}]
    assert asyncio.run(ai_advice(tenant_name='Example', url='https://example.com', score=100,
                                title='', description='', findings=findings)) == ([], 'rules')
    assert 'ai_crawlers' not in chat.await_args.args[1]
