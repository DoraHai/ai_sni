from pathlib import Path

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
    assert source_path_allowed("frontend/src/views/seo/SeoDashboardView.vue")
    assert source_path_allowed("app/api/customer_modules.py")
    assert not source_path_allowed("app/security/auth.py")
    assert not source_path_allowed("app/api/geo.py")
    assert not source_path_allowed("frontend/src/views/LoginView.vue")


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
