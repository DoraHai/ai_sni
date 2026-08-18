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
    assert source_path_allowed("tests/test_seo_distribution_import.py")
    assert source_path_allowed("deploy/seo-frontend.nginx.conf")
    assert source_path_allowed("frontend/src/views/seo/SeoDashboardView.vue")
    assert source_path_allowed("app/api/customer_modules.py")
    assert not source_path_allowed("app/security/auth.py")
    assert not source_path_allowed("app/api/geo.py")
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
    migration = (root / "migrations/versions/20260819_0069_seo_content_multi_keywords.py").read_text(encoding="utf-8")

    assert 'v-model="form.keyword_ids"' in editor
    assert ':multiple-limit="5"' in editor
    assert "1 个品牌词" in editor
    assert "keyword_ids: form.keyword_ids" in editor
    assert 'v-model="form.keyword_ids"' in content
    assert 'down_revision: Union[str, None] = "0068_seo_crawler"' in migration
    assert 'jsonb_build_array(keyword_id)' in migration
    assert source_path_allowed("migrations/versions/20260819_0069_seo_content_multi_keywords.py")


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
