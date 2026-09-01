"""Fail-closed consistency checks for SEO-only source and release changes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


SOURCE_ALLOWED_EXACT = {
    ".env.example",
    ".gitattributes",
    ".github/workflows/ci.yml",
    ".github/workflows/production-seo-deploy.yml",
    ".github/workflows/production-seo-frontend-deploy.yml",
    ".github/workflows/seo-baseline-check.yml",
    "app/api/__init__.py",
    "app/api/customer_modules.py",
    "app/api/seo.py",
    "app/config.py",
    "app/main.py",
    "app/models/__init__.py",
    "app/models/module_workspace.py",
    "app/models/seo.py",
    "app/module_scope.py",
    "app/permissions.py",
    "app/seo_crawler.py",
    "app/seo_automation_runs.py",
    "app/seo_manual_automation.py",
    "app/seo_competitor.py",
    "app/seo_distribution.py",
    "app/seo_distribution_import.py",
    "app/seo_main.py",
    "app/seo_monitoring_jobs.py",
    "app/seo_rank_limits.py",
    "app/seo_ranking_jobs.py",
    "app/seo_scheduler.py",
    "app/seo_serp.py",
    "app/seo_usage_limits.py",
    "app/urlwords.py",
    "app/scheduler.py",
    "deploy/seo-service.service",
    "deploy/seo-frontend.nginx.conf",
    "docs/SEO_PRODUCTION_PIPELINE.md",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/.gitignore",
    "frontend/scripts/verify-seo-build.mjs",
    "frontend/tests/seoBatchOperations.test.mjs",
    "frontend/src/api/moduleAssets.js",
    "frontend/src/api/seo.js",
    "frontend/seo/index.html",
    "frontend/src/SeoApp.vue",
    "frontend/src/seo-main.js",
    "frontend/src/seo-router.js",
    "frontend/src/router/index.js",
    "frontend/vite.seo.config.js",
    "migrations/versions/20260817_0065_seo_rewrite_schema_repair.py",
    "migrations/versions/20260817_0066_module_workspaces.py",
    "migrations/versions/20260818_0067_seo_site_metrics_foundation.py",
    "migrations/versions/20260818_0068_seo_crawler_foundation.py",
    "migrations/versions/20260818_0069_writeback_approvals.py",
    "migrations/versions/20260819_0070_seo_content_multi_keywords.py",
    "migrations/versions/20260819_0071_seo_distribution_publishing.py",
    "migrations/versions/20260819_0071_login_lockout.py",
    "migrations/versions/20260819_0072_merge_login_seo.py",
    "migrations/versions/20260819_0073_seo_distribution_variants.py",
    "migrations/versions/20260819_0073_geo_schema_repair.py",
    "migrations/versions/20260822_0074_merge_geo_seo_heads.py",
    "migrations/versions/20260822_0074_suggestion_workflow.py",
    "migrations/versions/20260822_0075_sem_asset_sync_state.py",
    "migrations/versions/20260825_0076_oauth_rebind_intent.py",
    "migrations/versions/20260829_0075_seo_content_source_page.py",
    "migrations/versions/20260829_0077_merge_sem_seo_heads.py",
    "migrations/versions/20260829_0078_seo_site_data_repairs.py",
    "migrations/versions/20260829_0079_seo_content_review_workflow.py",
    "migrations/versions/20260831_0080_seo_content_review_history.py",
    "migrations/versions/20260831_0081_seo_monitor_tenant_cascade.py",
    "migrations/versions/20260901_0082_seo_automation_runs.py",
    "migrations/versions/20260901_0083_seo_manual_rerun.py",
    "migrations/versions/20260901_0084_seo_crawl_queued_status.py",
    "ops/platform-deploy/install-seo.sh",
    "ops/platform-deploy/install-seo-frontend.sh",
    "ops/platform-deploy/modules/seo",
    "ops/platform-deploy/modules/seo-frontend",
    "tests/test_module_workspaces.py",
    "tests/test_keyword_refresh.py",
    "tests/test_seo_crawler.py",
    "tests/test_seo_competitors.py",
    "tests/test_seo_automation_runs.py",
    "tests/test_seo_manual_automation.py",
    "tests/test_seo_distribution_import.py",
    "tests/test_seo_distribution.py",
    "tests/test_seo_foundation.py",
    "tests/test_seo_migration_merge.py",
    "tests/test_seo_rank_limits.py",
    "tests/test_seo_release_consistency.py",
    "tests/test_seo_scheduler.py",
    "tests/test_seo_monitoring_jobs.py",
    "tests/test_seo_usage_limits.py",
    "tests/test_seo_site_association.py",
    "tests/test_seo_deploy_isolation.py",
    "tests/test_seo_serp.py",
    "tests/test_urlwords.py",
    "scripts/verify_seo_release.py",
}
SOURCE_ALLOWED_PREFIXES = ("frontend/src/views/seo/",)
SEO_ASSET_RE = re.compile(r"^(?:Seo[^/]*|seo-[^/]*)\.(?:js|css)$")
SEO_TOKEN_RE = re.compile(
    rb"(?P<logical>Seo[A-Za-z]+View|SeoWorkspaceShell|seo)-[A-Za-z0-9_-]+(?P<ext>\.(?:js|css))"
)


def source_path_allowed(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized in SOURCE_ALLOWED_EXACT or normalized.startswith(SOURCE_ALLOWED_PREFIXES)


def _files(root: Path) -> dict[str, Path]:
    return {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file()
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_entry(path: Path) -> bytes:
    return SEO_TOKEN_RE.sub(lambda match: match.group("logical") + match.group("ext"), path.read_bytes())


def check_release_diff(base: Path, candidate: Path, entry_asset: str) -> list[str]:
    base_files, candidate_files = _files(base), _files(candidate)
    problems: list[str] = []
    for relative in sorted(base_files.keys() | candidate_files.keys()):
        before, after = base_files.get(relative), candidate_files.get(relative)
        if before is None:
            if not (relative.startswith("assets/") and SEO_ASSET_RE.match(relative[7:])):
                problems.append(f"unexpected added file: {relative}")
            continue
        if after is None:
            problems.append(f"deleted file: {relative}")
            continue
        if _sha256(before) == _sha256(after):
            continue
        if relative == entry_asset:
            if _normalized_entry(before) != _normalized_entry(after):
                problems.append(f"entry asset changed beyond SEO chunk tokens: {relative}")
            continue
        if relative.startswith("assets/") and SEO_ASSET_RE.match(relative[7:]):
            continue
        problems.append(f"unexpected modified file: {relative}")
    return problems


def changed_source_paths(repo: Path, base_ref: str, head_ref: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}..{head_ref}"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


def build_manifest(root: Path, paths: list[str]) -> dict[str, object]:
    files = {}
    for relative in sorted(set(paths)):
        path = root / relative
        if not path.is_file():
            raise FileNotFoundError(relative)
        files[relative] = {"sha256": _sha256(path), "size": path.stat().st_size}
    return {"schema": 1, "files": files}


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    source = sub.add_parser("source-diff")
    source.add_argument("--repo", type=Path, default=Path.cwd())
    source.add_argument("--base", required=True)
    source.add_argument("--head", default="HEAD")
    release = sub.add_parser("release-diff")
    release.add_argument("--base-dir", type=Path, required=True)
    release.add_argument("--candidate-dir", type=Path, required=True)
    release.add_argument("--entry-asset", required=True)
    manifest = sub.add_parser("manifest")
    manifest.add_argument("--root", type=Path, default=Path.cwd())
    manifest.add_argument("paths", nargs="+")
    args = parser.parse_args()

    if args.command == "source-diff":
        changed = changed_source_paths(args.repo, args.base, args.head)
        problems = [path for path in changed if not source_path_allowed(path)]
        print(json.dumps({"changed": changed, "rejected": problems}, ensure_ascii=False, indent=2))
        return 1 if problems else 0
    if args.command == "release-diff":
        problems = check_release_diff(args.base_dir, args.candidate_dir, args.entry_asset)
        print(json.dumps({"rejected": problems}, ensure_ascii=False, indent=2))
        return 1 if problems else 0
    print(json.dumps(build_manifest(args.root, args.paths), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
