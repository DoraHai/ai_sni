"""GEO customer switcher: enabled-only list, bound isolation, single top-bar control."""

from pathlib import Path


ROOT = Path(__file__).parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_switcher_lists_enabled_geo_tenants_and_scopes_bound_accounts():
    scope = _read("app/geo/tenant_scope.py")
    routes = _read("app/geo/routes.py")
    auth = _read("app/security/auth.py")

    assert "async def list_geo_tenants_for_auth" in scope
    assert "if bound_tenant_id is None:" in scope
    assert "return [tenant for tenant in tenants if tenant.id == bound_tenant_id]" in scope
    assert 'module_code == "geo"' in scope
    assert '("active", "trial")' in scope
    assert "list_geo_tenants_for_auth(session, bound_tenant_id=ctx.tenant_id)" in routes
    assert "if self.tenant_id is not None and self.tenant_id != tenant_id:" in auth
    assert 'raise HTTPException(403, "无权访问该客户的数据")' in auth


def test_geo_topbar_keeps_one_customer_select():
    shell = _read("frontend/src/views/geo/GeoWorkspaceShell.vue")
    page = _read("frontend/src/components/GeoWorkbenchPage.vue")
    header = _read("frontend/src/components/GeoPrototypePageHeader.vue")
    app = _read("frontend/geo-frontend/src/App.vue")

    assert "GeoPrototypePageHeader" in page
    assert 'class="geo-tenant-switcher"' in header
    assert "当前客户" in header
    assert 'v-if="session.tenants.length"' not in header
    assert 'class="geo-side-foot"' not in shell
    assert 'class="geo-tenant"' not in shell
    assert "geo-tenant-switcher" not in page
    assert "fetchGeoTenants()" in app
    assert "session.isLoggedIn ? fetchMe() : Promise.resolve(null)" in app
    assert "fetchTenants" not in app


def test_sem_and_seo_customer_switchers_are_untouched():
    sem_app = _read("frontend/src/App.vue")
    seo_shell = _read("frontend/src/views/seo/SeoWorkspaceShell.vue")

    assert "fetchTenants" in sem_app
    assert "fetchGeoTenants" not in sem_app
    assert 'class="tenant-select"' in seo_shell
    assert "geo-tenant-switcher" not in seo_shell
