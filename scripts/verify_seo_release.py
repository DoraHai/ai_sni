"""Fail-closed consistency checks for SEO-only source and release changes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


SOURCE_ALLOWED_EXACT = {
    "app/seo_demo_fixture_loader.py",
    "scripts/load_seo_demo_fixture.py",
    "tests/test_seo_demo_fixture_loader.py",
    "docs/SEO_DEMO_FIXTURE_LOADER.md",
    "app/seo_qa_batches.py",
    "migrations/versions/20260906_0094_seo_qa_batches.py",
    "migrations/versions/20260909_0095_adopt_geo_ticket.py",
    "tests/test_geo_ticket_adoption_migration.py",
    "migrations/versions/20260909_0096_sem_tasks.py",
    "app/models/sem_task.py",
    "tests/test_sem_task_migration.py",
    "migrations/versions/20260909_0097_demo_tenant_bindings.py",
    "app/models/demo_tenant_binding.py",
    "tests/test_demo_tenant_binding_migration.py",
    "migrations/versions/20260909_0098_demo_binding_no_truncate.py",
    "tests/test_demo_binding_no_truncate_migration.py",
    "docs/DEMO_DATABASE_MIGRATION_0095.md",
    "app/seo_qa_documents.py",
    "tests/test_seo_qa_documents.py",
    "requirements.txt",
    "app/models/seo_qa.py",
    "app/api/seo_qa.py",
    "app/seo_qa.py",
    "migrations/versions/20260906_0093_seo_qa.py",
    "tests/test_seo_qa.py",
    "frontend/scripts/test-seo-qa.mjs",
    "docs/SEO_QA_WORKBENCH.md",
    "frontend/scripts/test-seo-video-workflow.mjs",
    "app/api/seo_video.py",
    "app/seo_video_platforms.py",
    "app/api/seo_backlink_workflow.py",
    "tests/test_seo_video_platforms.py",
    "tests/test_seo_backlink_workflow.py",
    "docs/SEO_DISTRIBUTION_ACCEPTANCE.md",
    "app/seo_backlink_opportunities.py",
    "tests/test_seo_backlink_opportunities.py",
    "tests/test_seo_publisher_runner.py",
    "app/models/seo_cockpit.py",
    "app/api/seo_cockpit.py",
    "app/seo_cockpit_metrics.py",
    "app/seo_image_verification.py",
    "app/security/auth.py",
    "app/rules/engine.py",
    "tests/test_seo_cockpit_auth.py",
    "tests/test_seo_cockpit.py",
    "docs/SEO_COCKPIT_CONTRACT.md",
    "migrations/versions/20260905_0092_seo_cockpit.py",
    "app/seo_backlink_sources.py",
    "app/seo_distribution_package.py",
    "tests/test_seo_backlink_sources.py",
    "tests/test_seo_distribution_package.py",
    "frontend/scripts/test-seo-backlinks.mjs",
    "app/seo_backlinks.py",
    "tests/test_seo_backlink_evidence.py",
    "migrations/versions/20260905_0091_seo_backlink_evidence.py",
    ".env.example",
    ".gitattributes",
    ".github/workflows/ci.yml",
    ".github/workflows/production-seo-deploy.yml",
    ".github/workflows/production-seo-frontend-deploy.yml",
    ".github/workflows/seo-baseline-check.yml",
    "app/api/__init__.py",
    "app/api/customer_modules.py",
    "app/api/seo.py",
    "app/api/seo_site_diagnostics.py",
    "app/api/seo_remediation.py",
    "app/seo_remediation.py",
    "app/seo_site_diagnostics.py",
    "app/seo_image_evidence.py",
    "app/seo_page_audit.py",
    "app/seo_image_alt_ai.py",
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
    "app/seo_demo_runtime.py",
    "app/seo_demo_source.py",
    "app/seo_static_demo.py",
    "app/fixtures/seo_demo_tenant16_v1.json",
    "app/seo_monitoring_jobs.py",
    "app/seo_rank_limits.py",
    "app/seo_rank_optimization.py",
    "app/seo_ranking_jobs.py",
    "app/seo_scheduler.py",
    "app/seo_snapshot_retention.py",
    "app/seo_serp.py",
    "app/seo_usage_limits.py",
    "app/seo_ai_operations.py",
    "app/seo_task_center.py",
    "tests/test_seo_task_center.py",
    "tests/test_seo_demo_source.py",
    "tests/test_seo_static_demo.py",
    "frontend/scripts/test-seo-task-center.mjs",
    "tests/test_seo_ai_operations.py",
    "migrations/versions/20260905_0090_seo_ai_operations.py",
    "frontend/src/api/seoAiRequests.js",
    "frontend/scripts/test-seo-ai-requests.mjs",
    "app/urlwords.py",
    "app/scheduler.py",
    "deploy/seo-service.service",
    "deploy/seo-frontend.nginx.conf",
    "docs/SEO_PRODUCTION_PIPELINE.md",
    "docs/SEO_DEMO_DUAL_SOURCE_HANDOFF.md",
    "docs/SEO_SESSION_SYNC_RELEASE_REVIEW.md",
    "docs/SEO_DIAGNOSTIC_TRUST.md",
    "docs/SEO_IMAGE_ALT_EVIDENCE.md",
    "docs/SEO_SINGLE_PAGE_IMAGE_EVIDENCE.md",
    "docs/SEO_IMAGE_REMEDIATION_WORKLIST.md",
    "docs/SEO_AI_REMEDIATION.md",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/.gitignore",
    "frontend/scripts/verify-seo-build.mjs",
    "frontend/tests/seoBatchOperations.test.mjs",
    "frontend/scripts/test-seo-diagnostics.mjs",
    "frontend/scripts/test-seo-image-evidence.mjs",
    "frontend/scripts/test-seo-remediation.mjs",
    "frontend/scripts/test-seo-workspace-access.mjs",
    "frontend/scripts/test-seo-editor.mjs",
    "frontend/scripts/test-session-storage.mjs",
    "frontend/scripts/test-session-store-integration.mjs",
    "frontend/src/api/moduleAssets.js",
    "frontend/src/api/seo.js",
    "frontend/src/api/client.js",
    "frontend/src/authContextRouting.js",
    "frontend/src/store/session.js",
    "frontend/src/store/sessionStorage.js",
    "frontend/seo/index.html",
    "frontend/seo/ai-remediation-acceptance.html",
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
    "migrations/versions/20260903_0085_seo_page_index_reviews.py",
    "migrations/versions/20260903_0087_seo_image_alt_evidence.py",
    "migrations/versions/20260904_0088_seo_image_alt_reviews.py",
    "migrations/versions/20260905_0089_seo_metric_partial_status.py",
    "tests/test_seo_site_diagnostics.py",
    "migrations/versions/20260903_0086_seo_index_review_merge.py",
    "tests/test_seo_remediation.py",
    "ops/platform-deploy/install-seo.sh",
    "ops/platform-deploy/install-seo-frontend.sh",
    "ops/platform-deploy/modules/seo",
    "ops/platform-deploy/modules/seo-frontend",
    "tests/test_module_workspaces.py",
    "tests/test_keyword_refresh.py",
    "tests/test_seo_crawler.py",
    "tests/test_seo_single_page_audit.py",
    "tests/test_seo_competitors.py",
    "tests/test_seo_automation_runs.py",
    "tests/test_seo_manual_automation.py",
    "tests/test_seo_distribution_import.py",
    "tests/test_seo_distribution.py",
    "tests/test_seo_domestic_distribution.py",
    "frontend/scripts/test-seo-publisher.mjs",
    "docs/SEO_DOMESTIC_DISTRIBUTION.md",
    "tests/fixtures/seo_editor_html_roundtrip.json",
    "tests/test_seo_foundation.py",
    "tests/test_seo_migration_merge.py",
    "tests/test_seo_rank_limits.py",
    "tests/test_seo_rank_optimization.py",
    "tests/test_seo_release_consistency.py",
    "tests/test_seo_scheduler.py",
    "tests/test_seo_snapshot_retention.py",
    "tests/test_seo_monitoring_jobs.py",
    "tests/test_seo_usage_limits.py",
    "tests/test_seo_site_association.py",
    "tests/test_seo_site_page_detail.py",
    "tests/test_seo_workbench_site_scope.py",
    "tests/test_seo_site_onboarding_contract.py",
    "docs/SEO_TIGER_SITE_ONBOARDING_HANDOFF.md",
    "tests/test_seo_workbench_publication_page_evidence.py",
    "docs/SEO_WORKBENCH_PUBLICATION_PAGE_EVIDENCE.md",
    "tests/test_seo_deploy_isolation.py",
    "tests/test_seo_demo_runtime.py",
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


def source_change_allowed(status: str, path: str) -> bool:
    normalized = path.replace("\\", "/")
    if not source_path_allowed(normalized):
        return False
    if normalized.startswith("migrations/versions/"):
        # A migration may enter the canonical history once. Once present in the
        # compared base, modifying, renaming or deleting it is always rejected.
        return status == "A"
    return True


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


def changed_source_entries(repo: Path, base_ref: str, head_ref: str) -> list[tuple[str, str]]:
    result = subprocess.run(
        ["git", "diff", "--name-status", "--find-renames=100%", f"{base_ref}..{head_ref}"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    entries = []
    for line in result.stdout.splitlines():
        parts = line.strip().split("\t")
        if len(parts) < 2:
            continue
        status = parts[0][0]
        entries.extend((status, path.replace("\\", "/")) for path in parts[1:])
    return entries


def changed_source_paths(repo: Path, base_ref: str, head_ref: str) -> list[str]:
    return [path for _, path in changed_source_entries(repo, base_ref, head_ref)]


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
        entries = changed_source_entries(args.repo, args.base, args.head)
        changed = [path for _, path in entries]
        problems = [path for status, path in entries if not source_change_allowed(status, path)]
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
