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
    assert source_path_allowed("frontend/package-lock.json")
    assert source_path_allowed("frontend/scripts/test-seo-editor.mjs")
    assert source_path_allowed("tests/fixtures/seo_editor_html_roundtrip.json")
    assert not source_path_allowed("frontend/scripts/test-sem-editor.mjs")
    assert not source_path_allowed("tests/fixtures/sem_editor_html_roundtrip.json")
    assert source_path_allowed(".gitattributes")
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
    assert source_path_allowed(".github/workflows/production-seo-frontend-deploy.yml")
    assert source_path_allowed("ops/platform-deploy/install-seo-frontend.sh")
    assert source_path_allowed("ops/platform-deploy/modules/seo-frontend")
    assert source_path_allowed("frontend/src/views/seo/SeoDashboardView.vue")
    assert source_path_allowed("app/api/customer_modules.py")
    assert not source_path_allowed("app/security/auth.py")
    assert not source_path_allowed("app/api/geo.py")
    assert not source_path_allowed("app/baidu/writeback.py")
    assert not source_path_allowed("app/api/auth.py")
    assert not source_path_allowed("frontend/src/views/monitor/DashboardView.vue")
    assert not source_path_allowed("frontend/src/views/LoginView.vue")


def test_seo_workflows_run_site_association_and_traffic_regressions() -> None:
    root = Path(__file__).parents[1]
    for relative in (
        ".github/workflows/seo-baseline-check.yml",
        ".github/workflows/production-seo-deploy.yml",
    ):
        workflow = (root / relative).read_text(encoding="utf-8")
        assert "tests/test_seo_site_association.py" in workflow
        assert "tests/test_seo_traffic.py" in workflow


def test_seo_baseline_uses_authoritative_production_history_not_main() -> None:
    root = Path(__file__).parents[1]
    workflow = (root / ".github/workflows/seo-baseline-check.yml").read_text(
        encoding="utf-8"
    )

    assert 'expected_branch="codex/production-seo"' in workflow
    assert 'test "$PR_BASE_REF" = "$expected_branch"' in workflow
    assert 'test "$REF_NAME" = "$expected_branch"' in workflow
    assert 'git merge-base --is-ancestor "$PUSH_BEFORE_SHA" HEAD' in workflow
    assert "origin/main" not in workflow
    assert "git fetch --no-tags origin main" not in workflow


def test_standalone_seo_entry_does_not_import_shared_application() -> None:
    frontend = Path(__file__).parents[1] / "frontend"
    entry = (frontend / "src/seo-main.js").read_text(encoding="utf-8")
    router = (frontend / "src/seo-router.js").read_text(encoding="utf-8")
    config = (frontend / "vite.seo.config.js").read_text(encoding="utf-8")

    assert "./App.vue" not in entry
    assert "./router" not in entry
    assert "import ElementPlus from 'element-plus'" not in entry
    assert "elementComponents" in entry
    assert "provideGlobalConfig({ locale: zhCn }, app, true)" in entry
    used_element_components = {
        "El" + "".join(part.capitalize() for part in tag.split("-"))
        for view in (frontend / "src/views/seo").glob("*.vue")
        for tag in re.findall(r"<el-([a-z0-9-]+)", view.read_text(encoding="utf-8"))
    }
    registered_element_components = set(re.findall(r"\bEl[A-Z][A-Za-z]+", entry))
    assert used_element_components <= registered_element_components
    assert "base: '/seo/'" in config
    view_imports = re.findall(r"import\('([^']+)'\)", router)
    assert view_imports
    assert all(path.startswith("./views/seo/") for path in view_imports)
    for forbidden in ("/geo/", "/monitor/", "/diagnostic-center", "LoginView", "../router"):
        assert forbidden not in router


def test_seo_dashboard_title_is_not_duplicated() -> None:
    root = Path(__file__).parents[1]
    standalone_router = (root / "frontend/src/seo-router.js").read_text(encoding="utf-8")

    assert "to.meta.title === productName" in standalone_router


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


def test_seo_shell_filters_entitled_tenants_and_clears_cross_tenant_drafts() -> None:
    root = Path(__file__).parents[1]
    shell = (root / "frontend/src/views/seo/SeoWorkspaceShell.vue").read_text(encoding="utf-8")
    auth_api = (root / "frontend/src/api/auth.js").read_text(encoding="utf-8")

    assert "fetchTenants('seo')" in shell
    assert "params: module ? { module } : undefined" in auth_api
    assert 'href="/deal-sniper/portal"' in shell
    assert "https://gsnipers.snipers.com.cn/deal-sniper/portal" not in shell
    assert "https://sem.snipers.com.cn/deal-sniper/portal" not in shell
    assert "sessionStorage.removeItem('seo_pending_rewrite_source')" in shell
    assert "sessionStorage.removeItem('seo_pending_rewrite_options')" in shell
    assert "router.replace('/seo/keywords')" in shell
    assert "router.replace('/seo/content/qa')" in shell


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
    assert source_path_allowed("migrations/versions/20260822_0074_suggestion_workflow.py")
    assert source_path_allowed("migrations/versions/20260822_0075_sem_asset_sync_state.py")
    assert source_path_allowed("migrations/versions/20260825_0076_oauth_rebind_intent.py")
    assert source_path_allowed("migrations/versions/20260829_0075_seo_content_source_page.py")
    assert source_path_allowed("migrations/versions/20260829_0077_merge_sem_seo_heads.py")
    assert source_path_allowed("migrations/versions/20260829_0078_seo_site_data_repairs.py")
    assert source_path_allowed("migrations/versions/20260829_0079_seo_content_review_workflow.py")
    assert source_path_allowed("migrations/versions/20260831_0080_seo_content_review_history.py")


def test_content_review_ui_supports_rejected_draft_resubmission_and_audit_details() -> None:
    root = Path(__file__).parents[1]
    content = (root / "frontend/src/views/seo/SeoContentView.vue").read_text(encoding="utf-8")
    backend = (root / "app/api/seo.py").read_text(encoding="utf-8")

    assert "submitSeoContentReview" in content
    assert "保存并提交审核" in content
    assert "提交审核说明（选填）" in content
    assert "任务 #{{ row.id }}" in content
    assert "timeZone: 'Asia/Shanghai'" in content
    assert "review_submitted_by_name" in content
    assert "reviewed_by_name" in content
    assert "@compositionstart" in content
    assert ":disabled=\"isComposing\"" in content
    assert '"review_submitted_by_name"' in backend
    assert '"reviewed_by_name"' in backend
    assert "row.review_history_count" in content
    assert "fetchSeoContentReviewHistory" in content
    assert '@toggle="loadReviewHistory(row, $event)"' in content
    assert '"review_history"' in backend


def test_seo_editor_preserves_plain_text_handoff_and_browser_paragraphs() -> None:
    root = Path(__file__).parents[1]
    editor = (root / "frontend/src/views/seo/SeoContentEditorView.vue").read_text(encoding="utf-8")
    # Actual DOM/save/reopen behavior is covered by test-seo-editor.mjs.
    assert "return sanitizeSeoEditorHtml(value)" in editor
    # Preserve the existing IME-safe, one-way DOM read on input.
    sync = re.search(r"function syncDraft\(\) \{(.*?)\n\}", editor, re.S).group(1)
    assert "form.draft = editor.value?.innerHTML || ''" in sync
    assert not re.search(r"innerHTML\s*=(?!=)", sync)
    assert 'v-html="form.draft"' not in editor


def test_rewrite_library_keeps_original_source_types_when_content_api_is_paginated() -> None:
    root = Path(__file__).parents[1]
    content = (root / "frontend/src/views/seo/SeoRewriteView.vue").read_text(encoding="utf-8")

    assert "contentTypes:'rewrite,article,guide,landing,comparison,faq'" in content
    assert "pageSize:200" in content


def test_deployed_login_and_seo_distribution_heads_are_merged() -> None:
    root = Path(__file__).parents[1]
    login = (root / "migrations/versions/20260819_0071_login_lockout.py").read_text(encoding="utf-8")
    merge = (root / "migrations/versions/20260819_0072_merge_login_seo.py").read_text(encoding="utf-8")

    assert 'revision: str = "0071_login_lockout"' in login
    assert 'down_revision: Union[str, None] = "0070_seo_content_keywords"' in login
    assert 'revision: str = "0072_merge_login_seo"' in merge
    assert '"0071_login_lockout"' in merge
    assert '"0071_seo_distribution"' in merge


def test_seo_workflows_require_the_current_reviewed_migration_head() -> None:
    root = Path(__file__).parents[1]
    expected = "0085_seo_page_index_reviews (head)"
    baseline = (root / ".github/workflows/seo-baseline-check.yml").read_text(encoding="utf-8")
    production = (root / ".github/workflows/production-seo-deploy.yml").read_text(encoding="utf-8")
    assert expected in baseline
    assert expected in production
    assert "0078_seo_site_data_repairs (head)" not in baseline
    assert "0078_seo_site_data_repairs (head)" not in production


def test_seo_release_and_deploy_use_production_branch_authority() -> None:
    root = Path(__file__).parents[1]
    baseline = (root / ".github/workflows/seo-baseline-check.yml").read_text(encoding="utf-8")
    production = (root / ".github/workflows/production-seo-deploy.yml").read_text(encoding="utf-8")

    assert 'expected_branch="codex/production-seo"' in baseline
    assert 'test "$REF_NAME" = "$SEO_PRODUCTION_BRANCH"' in production
    assert "origin/main" not in baseline
    assert "origin/main" not in production


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
    assert "openKeywordDetail(row.id)" in ranking
    assert "query: { engine: engine.value, device: device.value }" in ranking
    keyword_detail = (root / "frontend/src/views/seo/SeoKeywordDetailView.vue").read_text(encoding="utf-8")
    assert "{k:'360',n:'360'}" in keyword_detail
    assert "{k:'sogou',n:'搜狗'}" in keyword_detail
    assert "device:device.value" in keyword_detail
    assert "const engine=computed(()=>" in keyword_detail
    assert "const device=computed(()=>" in keyword_detail
    assert "setRankContext(item.k,device)" in keyword_detail
    assert "setRankContext(engine,'mobile')" in keyword_detail
    assert "manual_import:'人工导入'" in keyword_detail
    assert "当前引擎和设备暂无记录" in keyword_detail
    assert 'query:{engine,device}' in keyword_detail
    assert 'rankEngines.has(String(route.query.engine))' in ranking
    assert "route.query.device === 'mobile'" in ranking
    assert "timeZone: SEO_TIME_ZONE" in (root / "frontend/src/views/seo/seoRankTime.js").read_text(encoding="utf-8")
    assert 'siteId:siteId.value' in rewrite
    assert 'siteId: siteId.value' in distribution
    assert "site_id: siteId || undefined" in api
    assert "func.row_number()" in backend
    assert "all_ranks = list" not in backend


def test_site_optimization_normalizes_issue_codes_and_only_links_drafts() -> None:
    view = (
        Path(__file__).parents[1]
        / "frontend/src/views/seo/SeoSiteOptimizationView.vue"
    ).read_text(encoding="utf-8")

    assert "title_missing:'缺少 Title'" in view
    assert "NO_DEFINITION:'缺少定义块'" in view
    assert "}[code] || '其他检测问题'" in view
    assert "['planned', 'drafting'].includes(item.status)" in view
    assert "{v:'content',n:'内容质量'}" in view


def test_site_optimization_has_success_feedback_and_contextual_empty_state() -> None:
    view = (
        Path(__file__).parents[1]
        / "frontend/src/views/seo/SeoSiteOptimizationView.vue"
    ).read_text(encoding="utf-8")

    assert "页面优化记录已保存" in view
    assert "个页面的 TDK 建议" in view
    assert "const emptyStateText = computed" in view
    assert "Number(stats.value.total || 0) > 0" in view
    assert "没有符合当前筛选条件的页面" in view
    assert ':empty-text="emptyStateText"' in view


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
