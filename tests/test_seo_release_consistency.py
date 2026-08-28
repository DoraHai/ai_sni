from pathlib import Path
import re

from scripts.verify_seo_release import (
    build_manifest,
    check_release_diff,
    source_path_allowed,
)


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_source_allowlist_rejects_auth_and_other_modules() -> None:
    assert source_path_allowed("app/api/seo.py")
    assert source_path_allowed("app/seo_distribution_import.py")
    assert source_path_allowed("app/seo_distribution.py")
    assert source_path_allowed("app/seo_ranking_jobs.py")
    assert source_path_allowed("app/seo_rank_limits.py")
    assert source_path_allowed("app/seo_scheduler.py")
    assert source_path_allowed("app/config.py")
    assert source_path_allowed("app/scheduler.py")
    assert source_path_allowed("tests/test_seo_distribution_import.py")
    assert source_path_allowed("tests/test_seo_distribution.py")
    assert source_path_allowed("tests/test_keyword_refresh.py")
    assert source_path_allowed("tests/test_seo_scheduler.py")
    assert source_path_allowed("tests/test_seo_rank_limits.py")
    assert source_path_allowed("deploy/seo-frontend.nginx.conf")
    assert source_path_allowed("frontend/src/views/seo/SeoDashboardView.vue")
    assert source_path_allowed("app/api/customer_modules.py")
    assert not source_path_allowed("app/security/auth.py")
    assert not source_path_allowed("app/api/geo.py")
    assert not source_path_allowed("app/baidu/writeback.py")
    assert not source_path_allowed("app/api/auth.py")
    assert not source_path_allowed("frontend/src/views/monitor/DashboardView.vue")
    assert not source_path_allowed("frontend/src/views/LoginView.vue")


def test_standalone_seo_entry_does_not_import_shared_application() -> None:
    frontend = Path(__file__).parents[1] / "frontend"
    entry = (frontend / "src/seo-main.js").read_text(encoding="utf-8")
    router = (frontend / "src/seo-router.js").read_text(encoding="utf-8")
    config = (frontend / "vite.seo.config.js").read_text(encoding="utf-8")

    assert "./App.vue" not in entry
    assert "./router" not in entry
    assert "base: '/seo/'" in config
    view_imports = re.findall(r"import\('([^']+)'\)", router)
    assert view_imports
    assert all(path.startswith("./views/seo/") for path in view_imports)
    for forbidden in ("/geo/", "/monitor/", "/diagnostic-center", "LoginView", "../router"):
        assert forbidden not in router


def test_trends_are_scoped_by_site_and_selected_time_range() -> None:
    root = Path(__file__).parents[1]
    trends = (root / "frontend/src/views/seo/SeoTrendsView.vue").read_text(
        encoding="utf-8"
    )
    api = (root / "frontend/src/api/seo.js").read_text(encoding="utf-8")
    backend = (root / "app/api/seo.py").read_text(encoding="utf-8")

    assert "fetchSeoSites(currentTenantId.value)" in trends
    assert "siteId:siteId.value" in trends
    assert "days:range.value" in trends
    assert "watch([engine,range,siteId],load)" in trends
    assert "watch(currentTenantId,changeTenant)" in trends
    assert "siteId.value=null;overview.value={stats:{},trend:[]};keywords.value=[]" in trends
    assert "site_id: siteId || undefined" in api
    assert "days = 30" in api
    assert "days: int = Query(30, ge=1, le=366)" in backend
    assert "SeoRankSnapshot.checked_at >= trend_since" in backend
def test_rewrite_ui_connects_source_ai_save_and_publish_steps() -> None:
    frontend = Path(__file__).parents[1] / "frontend/src/views/seo"
    rewrite = (frontend / "SeoRewriteView.vue").read_text(encoding="utf-8")
    editor = (frontend / "SeoContentEditorView.vue").read_text(encoding="utf-8")

    assert "原创文章列表" in rewrite
    assert "直接粘贴" in rewrite
    assert "autoGenerate:true" in rewrite
    assert "await assist('rewrite')" in editor
    assert "await save('drafting', { quiet: true })" in editor
    assert "save('published'" in editor
    assert "发布地址必须使用 http 或 https" in editor
    assert "router.push('/seo/distribution')" in editor


def test_original_content_brief_supports_bounded_multi_keywords() -> None:
    root = Path(__file__).parents[1]
    editor = (root / "frontend/src/views/seo/SeoContentEditorView.vue").read_text(encoding="utf-8")
    content = (root / "frontend/src/views/seo/SeoContentView.vue").read_text(encoding="utf-8")
    migration = (root / "migrations/versions/20260819_0070_seo_content_multi_keywords.py").read_text(encoding="utf-8")

    assert 'v-model="form.keyword_ids"' in editor
    assert ':multiple-limit="5"' in editor
    assert "1 个品牌词" in editor
    assert "keyword_ids: form.keyword_ids" in editor
    assert 'v-model="form.keyword_ids"' in content
    assert 'revision: str = "0070_seo_content_keywords"' in migration
    assert 'down_revision: Union[str, None] = "0069_writeback_approvals"' in migration
    assert 'jsonb_build_array(keyword_id)' in migration
    assert source_path_allowed("migrations/versions/20260818_0069_writeback_approvals.py")
    assert source_path_allowed("migrations/versions/20260819_0070_seo_content_multi_keywords.py")
    assert source_path_allowed("migrations/versions/20260819_0071_seo_distribution_publishing.py")
    assert source_path_allowed("migrations/versions/20260819_0071_login_lockout.py")
    assert source_path_allowed("migrations/versions/20260819_0072_merge_login_seo.py")
    assert source_path_allowed("migrations/versions/20260819_0073_seo_distribution_variants.py")
    assert source_path_allowed("migrations/versions/20260819_0073_geo_schema_repair.py")
    assert source_path_allowed("migrations/versions/20260822_0074_merge_geo_seo_heads.py")


def test_deployed_login_and_seo_distribution_heads_are_merged() -> None:
    root = Path(__file__).parents[1]
    login = (root / "migrations/versions/20260819_0071_login_lockout.py").read_text(encoding="utf-8")
    merge = (root / "migrations/versions/20260819_0072_merge_login_seo.py").read_text(encoding="utf-8")

    assert 'revision: str = "0071_login_lockout"' in login
    assert 'down_revision: Union[str, None] = "0070_seo_content_keywords"' in login
    assert 'revision: str = "0072_merge_login_seo"' in merge
    assert '"0071_login_lockout"' in merge
    assert '"0071_seo_distribution"' in merge


def test_seo_content_and_rank_views_are_site_scoped_and_html_safe() -> None:
    root = Path(__file__).parents[1]
    api = (root / "frontend/src/api/seo.js").read_text(encoding="utf-8")
    editor = (root / "frontend/src/views/seo/SeoContentEditorView.vue").read_text(encoding="utf-8")
    content = (root / "frontend/src/views/seo/SeoContentView.vue").read_text(encoding="utf-8")
    ranking = (root / "frontend/src/views/seo/SeoRankingMonitorView.vue").read_text(encoding="utf-8")
    rewrite = (root / "frontend/src/views/seo/SeoRewriteView.vue").read_text(encoding="utf-8")
    distribution = (root / "frontend/src/views/seo/SeoDistributionView.vue").read_text(encoding="utf-8")
    backend = (root / "app/api/seo.py").read_text(encoding="utf-8")

    assert "sanitizeEditorHtml(item.humanized_content||item.draft||'')" in editor
    assert 'site_id: siteId.value' in editor
    assert 'site_id: siteId.value' in content
    assert 'site_id: siteId.value' in ranking
    assert "if (!siteId.value) return ElMessage.warning('请先选择或创建 SEO 网站')" in ranking
    assert "if (!siteId.value) { ElMessage.warning('请先选择或创建 SEO 网站'); return }" in ranking
    assert '@click="openCollect"' in ranking
    assert "site_id: PositiveInt" in backend
    assert "? `采集部分完成" in ranking
    assert "Array.isArray(summary.errors)" in ranking
    assert "const collectOutcome = ref(null)" in ranking
    assert 'class="collect-outcome"' in ranking
    assert "失败请求已记录，本页面不会自动重试" in ranking
    assert "结果会保留在页面上，避免重复采集" in ranking
    assert '@click="showCollectedDevice"' in ranking
    assert "collectOutcome.value = {" in ranking
    assert 'v-model="collectForm.keyword_ids"' in ranking
    assert "keyword_ids: collectForm.keyword_ids" in ranking
    assert "formatSeoRankTime(serp.captured_at)" in ranking
    assert "timeZone: SEO_TIME_ZONE" in (root / "frontend/src/views/seo/seoRankTime.js").read_text(encoding="utf-8")
    assert 'siteId:siteId.value' in rewrite
    assert 'siteId: siteId.value' in distribution
    assert "site_id: siteId || undefined" in api
    assert "func.row_number()" in backend
    assert "all_ranks = list" not in backend


def test_release_diff_allows_only_seo_assets_and_hash_token_changes(tmp_path: Path) -> None:
    base, candidate = tmp_path / "base", tmp_path / "candidate"
    _write(base, "index.html", "<script src='/assets/index-old.js'></script>")
    _write(candidate, "index.html", "<script src='/assets/index-old.js'></script>")
    _write(base, "assets/index-old.js", 'import("SeoDashboardView-old.js")')
    _write(candidate, "assets/index-old.js", 'import("SeoDashboardView-new.js")')
    _write(candidate, "assets/SeoDashboardView-new.js", "new seo dashboard")
    assert check_release_diff(base, candidate, "assets/index-old.js") == []


def test_release_diff_rejects_shared_asset_or_index_changes(tmp_path: Path) -> None:
    base, candidate = tmp_path / "base", tmp_path / "candidate"
    _write(base, "index.html", "stable")
    _write(candidate, "index.html", "changed")
    _write(base, "assets/index-old.js", "stable")
    _write(candidate, "assets/index-old.js", "shared logic changed")
    problems = check_release_diff(base, candidate, "assets/index-old.js")
    assert "unexpected modified file: index.html" in problems
    assert "entry asset changed beyond SEO chunk tokens: assets/index-old.js" in problems


def test_manifest_is_deterministic(tmp_path: Path) -> None:
    _write(tmp_path, "app/api/seo.py", "seo")
    manifest = build_manifest(tmp_path, ["app/api/seo.py"])
    assert manifest["schema"] == 1
    assert manifest["files"]["app/api/seo.py"]["size"] == 3
    assert len(manifest["files"]["app/api/seo.py"]["sha256"]) == 64
