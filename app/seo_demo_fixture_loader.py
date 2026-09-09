"""Offline, single-use loader for an isolated SEO demonstration database."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import Date, DateTime, Numeric, insert, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncConnection, create_async_engine


REQUIRED_REVISION = "0098_demo_binding_no_truncate"
MANIFEST_FIELDS = frozenset(
    {
        "schema_version", "module", "target_revision", "target_database",
        "dataset_key", "dataset_version", "demo_tenant_id", "generated_at",
        "loader_version", "app_readonly_role", "sites", "sources", "tables",
        "bundle_sha256", "text_policy",
    }
)
TABLE_ENTRY_FIELDS = frozenset({"path", "size", "sha256", "row_count"})
TABLE_ORDER = (
    "tenants", "tenant_modules", "seo_sites", "seo_ai_operations",
    "seo_distribution_connections", "seo_automation_runs", "seo_backlinks",
    "seo_brand_assets", "seo_competitors", "seo_crawl_runs",
    "seo_keyword_assets", "seo_metric_snapshots", "seo_qa_batches",
    "seo_qa_facts", "seo_questions", "seo_tasks", "seo_competitor_events",
    "seo_page_snapshots", "seo_rank_snapshots", "seo_serp_results",
    "seo_site_pages", "seo_content_assets", "seo_image_alt_reviews",
    "seo_internal_links", "seo_page_index_reviews", "seo_content_review_events",
    "seo_distribution_variants", "seo_image_verifications", "seo_qa_answers",
    "seo_content_publications", "seo_qa_placements", "seo_publish_attempts",
)
ALLOWED_TABLES = frozenset(TABLE_ORDER)
TABLE_COLUMN_ALLOWLISTS = {
    'tenants': frozenset('id name strategy monthly_budget contract_start contract_end brand_terms industry business_desc profile_summary profile_generated_at created_at'.split()),
    'tenant_modules': frozenset('id tenant_id module_code status opened_at expires_at module_settings created_at updated_at'.split()),
    'seo_sites': frozenset('id tenant_id tenant_module_id name domain canonical_domain default_url status site_settings created_at updated_at'.split()),
    'seo_ai_operations': frozenset('id tenant_id site_id request_key request_hash kind charged_on status result expires_at completed_at created_at actor'.split()),
    'seo_distribution_connections': frozenset('id tenant_id platform_code name mode base_url config capabilities has_credentials enabled status last_error last_tested_at created_at updated_at'.split()),
    'seo_automation_runs': frozenset('id tenant_id site_id job_type trigger_type status planned_count success_count failed_count skipped_count error_summary started_at completed_at created_at'.split()),
    'seo_backlinks': frozenset('id tenant_id site_id source_url target_url source_domain anchor_text authority_score toxic_score status first_seen_at last_seen_at last_checked_at verification missing_checks created_at updated_at'.split()),
    'seo_brand_assets': frozenset('id tenant_id site_id asset_type name match_value platform status created_at updated_at'.split()),
    'seo_competitors': frozenset('id tenant_id site_id name domain notes status last_checked_at created_at updated_at'.split()),
    'seo_crawl_runs': frozenset('id tenant_id site_id status seed_url max_urls discovered_count fetched_count failed_count blocked_count issue_count error_summary started_at completed_at created_at'.split()),
    'seo_keyword_assets': frozenset('id tenant_id site_id keyword cluster intent monthly_volume difficulty priority landing_page status source notes created_at updated_at'.split()),
    'seo_metric_snapshots': frozenset('id tenant_id site_id metric_type dimension numeric_value text_value unit source data_quality status error_message raw_payload observed_at collected_at created_at'.split()),
    'seo_qa_batches': frozenset('request_key request_hash status items id tenant_id site_id created_at updated_at actor'.split()),
    'seo_qa_facts': frozenset('title statement source_name source_url expires_at status version id tenant_id site_id created_at updated_at'.split()),
    'seo_questions': frozenset('title fingerprint topic intent status relevance sources version id tenant_id site_id created_at updated_at'.split()),
    'seo_tasks': frozenset('id tenant_id site_id module action_type title params status assignee_role completion_evidence baseline created_at updated_at created_by'.split()),
    'seo_competitor_events': frozenset('id tenant_id site_id competitor_id event_type title url source_url summary event_at detected_at'.split()),
    'seo_page_snapshots': frozenset('id tenant_id site_id crawl_run_id url final_url discovery_source click_depth status_code redirect_chain fetch_error error_type content_type content_length response_time_ms raw_html_hash robots_allowed meta_robots x_robots_tag canonical_url indexable title title_length meta_description description_length h1_texts h1_count html_lang main_content_extractable main_content_hash word_count schema_types schema_jsonld_count schema_parse_error internal_links_count external_links_count images_count images_missing_alt_count image_alt_evidence hreflang_tags issue_codes fetched_at created_at'.split()),
    'seo_rank_snapshots': frozenset('id tenant_id site_id keyword_id engine device region domain subject_type rank result_url source checked_at created_at'.split()),
    'seo_serp_results': frozenset('id tenant_id site_id keyword_id engine device region rank rank_label title description result_url domain ownership_type match_method confidence matched_asset_id is_confirmed provider captured_at created_at'.split()),
    'seo_site_pages': frozenset('id tenant_id site_id url page_type target_keyword_id title meta_description meta_keywords h1 canonical indexable http_status content_units audit_score issue_codes title_suggestion description_suggestion status last_error last_checked_at created_at updated_at'.split()),
    'seo_content_assets': frozenset('id tenant_id site_id source_page_id keyword_id keyword_ids content_type title outline draft humanized_content source_text rewrite_progress originality_score target_platforms version_count status page_url published_at review_submitted_at review_note reviewed_at created_at updated_at'.split()),
    'seo_image_alt_reviews': frozenset('id tenant_id site_id page_id snapshot_id position source_url observed_alt_state decision alt_suggestion note review_status reviewed_at updated_at actor_id actor_name'.split()),
    'seo_internal_links': frozenset('id tenant_id site_id source_page_id target_page_id anchor_text discovered_at'.split()),
    'seo_page_index_reviews': frozenset('id tenant_id site_id page_id intent reason evidence created_at actor_id actor_name'.split()),
    'seo_content_review_events': frozenset('id tenant_id site_id content_asset_id action from_status to_status note created_at'.split()),
    'seo_distribution_variants': frozenset('id tenant_id content_asset_id connection_id platform_code source_version revision_number status title excerpt content content_chars keyword_checks warnings ai_generated generation_instruction feedback review_note reviewed_at created_at updated_at'.split()),
    'seo_image_verifications': frozenset('id tenant_id site_id page_id review_id status approved_at checked_at available_at evidence result_snapshot_id created_at'.split()),
    'seo_qa_answers': frozenset('question_id content_id format fact_snapshots evidence_hash id tenant_id site_id created_at updated_at'.split()),
    'seo_content_publications': frozenset('id tenant_id content_asset_id connection_id variant_id platform_code platform_name publish_mode status source_version adapted_title adapted_excerpt adapted_content external_id page_url handoff_url idempotency_key last_error published_at link_discovery last_synced_at created_at updated_at'.split()),
    'seo_qa_placements': frozenset('answer_id platform question_url answer_url status scheduled_at content_version body observations reported_metrics version id tenant_id site_id created_at updated_at'.split()),
    'seo_publish_attempts': frozenset('id tenant_id publication_id action status request_summary response_summary error started_at completed_at'.split()),
}
REQUIRED_TABLES = frozenset({"tenants", "tenant_modules", "seo_sites"})
FIXED_LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"gsnipers:seo:demo-fixture-loader:v1").digest()[:8],
    "big",
    signed=True,
)
RECEIPT_REGISTRY_TABLE = "seo_fixture_load_receipts"
RECEIPT_REJECT_FUNCTION = "public.reject_seo_fixture_receipt_mutation()"
SYNTHETIC_ACTOR_TEXT = "fixture:synthetic"
SYNTHETIC_ACTOR_ID = 0
SYNTHETIC_ACTOR_NAME = "Synthetic Fixture"
EMPTY_GUARD_TABLES = (
    "roles", "users", *TABLE_ORDER,
    "demo_tenant_bindings", "demo_tenant_binding_history",
)
RUNNABLE_STATES = {
    "seo_ai_operations": frozenset({"pending", "queued", "running", "processing"}),
    "seo_automation_runs": frozenset({"pending", "queued", "running", "processing"}),
    "seo_crawl_runs": frozenset({"pending", "queued", "running", "processing"}),
    "seo_qa_batches": frozenset({"pending", "queued", "running", "processing"}),
    "seo_tasks": frozenset({"in_progress"}),
    "seo_content_publications": frozenset({"preparing", "publishing", "retrying"}),
    "seo_publish_attempts": frozenset({"pending", "queued", "running", "processing", "retrying"}),
    "seo_image_verifications": frozenset({"pending", "checking"}),
}
SENSITIVE_KEYS = re.compile(
    r"(?:authorization|password|secret|token|cookie|credential|private[_-]?key|"
    r"access[_-]?key|api[_-]?key|oauth|client[_-]?secret|session)",
    re.I,
)
SENSITIVE_TEXT = re.compile(
    r"(?:\bBearer\s+[A-Za-z0-9._~+/=-]+|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"\bAKIA[0-9A-Z]{16}\b|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b|"
    r"\b(?:sk-|ya29\.)[A-Za-z0-9._-]{8,}|"
    r"\b(?:authorization|private[_-]?key|access[_-]?key|api[_-]?key|oauth|client[_-]?secret|session)\s*[:=])",
    re.I,
)
PII_TEXT = re.compile(
    r"(?:\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b|"
    r"(?<!\d)1[3-9]\d{9}(?!\d)|"
    r"(?<!\d)\d{17}[\dXx](?!\d))",
    re.I,
)
LABELED_PII_TEXT = re.compile(
    r"(?:联系人|姓名|收件人)\s*[:：]\s*[\u4e00-\u9fff]{2,6}|"
    r"(?:地址|住址|联系地址)\s*[:：]\s*[^\s,，;；]{4,}|"
    r"(?:座机|电话|联系电话)\s*[:：]\s*(?:0\d{2,3}[- ]?)?\d{7,8}",
)
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
VERSION = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")
ROLE = re.compile(r"^[a-z_][a-z0-9_-]{0,62}$")

# Every relation that can carry site-scoped data.  The validation below follows
# these edges and requires all resolved parents to belong to one manifest site.
SITE_RELATIONS = {
    "tenant_module_id": "tenant_modules",
    "site_id": "seo_sites",
    "crawl_run_id": "seo_crawl_runs",
    "keyword_id": "seo_keyword_assets",
    "target_keyword_id": "seo_keyword_assets",
    "competitor_id": "seo_competitors",
    "matched_asset_id": "seo_brand_assets",
    "source_page_id": "seo_site_pages",
    "target_page_id": "seo_site_pages",
    "page_id": "seo_site_pages",
    "snapshot_id": "seo_page_snapshots",
    "result_snapshot_id": "seo_page_snapshots",
    "content_asset_id": "seo_content_assets",
    "content_id": "seo_content_assets",
    "review_id": "seo_image_alt_reviews",
    "question_id": "seo_questions",
    "answer_id": "seo_qa_answers",
    "variant_id": "seo_distribution_variants",
    "publication_id": "seo_content_publications",
    "connection_id": "seo_distribution_connections",
}


class SeoFixtureError(RuntimeError):
    """The fixture or target failed a mandatory safety check."""


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def manifest_digest(manifest: dict[str, Any]) -> str:
    unsigned = {key: value for key, value in manifest.items() if key != "bundle_sha256"}
    return hashlib.sha256(_canonical(unsigned)).hexdigest()


def _strict_json(payload: str) -> object:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise SeoFixtureError(f"duplicate JSON key: {key}")
            value[key] = item
        return value

    return json.loads(payload, object_pairs_hook=object_pairs)


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SeoFixtureError(f"{field} must be a positive integer")
    return value


def _safe_relative_path(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise SeoFixtureError("fixture path must be a normalized relative POSIX path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise SeoFixtureError("fixture path escapes the bundle")
    if path.suffix != ".jsonl":
        raise SeoFixtureError("fixture table files must use .jsonl")
    return path


def _contains_sensitive_value(value: object, path: str = "") -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            name = str(key)
            empty = item is None or item == "" or item is False or item == [] or item == {}
            if SENSITIVE_KEYS.search(name) and not empty:
                return True
            if _contains_sensitive_value(item, f"{path}.{name}"):
                return True
    elif isinstance(value, list):
        return any(_contains_sensitive_value(item, path) for item in value)
    elif isinstance(value, str):
        return bool(SENSITIVE_TEXT.search(value) or PII_TEXT.search(value) or LABELED_PII_TEXT.search(value))
    return False


@dataclass(frozen=True)
class SeoFixtureBundle:
    root: Path
    manifest: dict[str, Any]
    rows: dict[str, tuple[dict[str, Any], ...]]
    digest: str

    @property
    def dataset_key(self) -> str:
        return self.manifest["dataset_key"]

    @property
    def dataset_version(self) -> str:
        return self.manifest["dataset_version"]

    @property
    def demo_tenant_id(self) -> int:
        return self.manifest["demo_tenant_id"]

    @classmethod
    def open(cls, root: Path) -> "SeoFixtureBundle":
        if root.is_symlink():
            raise SeoFixtureError("fixture bundle root cannot be a symlink")
        root = root.resolve(strict=True)
        manifest_path = root / "manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise SeoFixtureError("manifest.json must be a regular file")
        try:
            manifest = _strict_json(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SeoFixtureError("manifest.json is unreadable") from exc
        if not isinstance(manifest, dict) or set(manifest) != MANIFEST_FIELDS:
            raise SeoFixtureError("manifest fields do not match the reviewed contract")
        cls._validate_manifest(manifest)
        if _contains_sensitive_value(manifest):
            raise SeoFixtureError("manifest contains credential or personal data")
        tables = manifest["tables"]
        declared_paths: set[str] = set()
        rows: dict[str, tuple[dict[str, Any], ...]] = {}
        for table_name, entry in tables.items():
            if table_name not in ALLOWED_TABLES:
                raise SeoFixtureError(f"table {table_name} is outside the SEO fixture allowlist")
            if not isinstance(entry, dict) or set(entry) != TABLE_ENTRY_FIELDS:
                raise SeoFixtureError(f"table {table_name} manifest entry is invalid")
            if (
                isinstance(entry["size"], bool) or not isinstance(entry["size"], int) or entry["size"] < 0
                or isinstance(entry["row_count"], bool) or not isinstance(entry["row_count"], int) or entry["row_count"] < 0
                or not isinstance(entry["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
            ):
                raise SeoFixtureError(f"table {table_name} size, hash or row count is invalid")
            rel = _safe_relative_path(entry["path"])
            rel_text = rel.as_posix()
            if rel_text in declared_paths:
                raise SeoFixtureError("fixture path is declared more than once")
            declared_paths.add(rel_text)
            candidate = root.joinpath(*rel.parts)
            if candidate.is_symlink() or not candidate.is_file() or root not in candidate.resolve().parents:
                raise SeoFixtureError("fixture file must be a regular file inside the bundle")
            payload = candidate.read_bytes()
            if len(payload) != entry["size"] or hashlib.sha256(payload).hexdigest() != entry["sha256"]:
                raise SeoFixtureError(f"table {table_name} hash or size mismatch")
            parsed: list[dict[str, Any]] = []
            try:
                for line in payload.decode("utf-8").splitlines():
                    if not line.strip():
                        raise SeoFixtureError("blank JSONL records are forbidden")
                    row = _strict_json(line)
                    if not isinstance(row, dict):
                        raise SeoFixtureError("every JSONL record must be an object")
                    parsed.append(row)
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise SeoFixtureError(f"table {table_name} JSONL is invalid") from exc
            if len(parsed) != entry["row_count"]:
                raise SeoFixtureError(f"table {table_name} row count mismatch")
            rows[table_name] = tuple(parsed)
        actual_files: set[str] = set()
        for item in root.rglob("*"):
            if item.is_symlink():
                raise SeoFixtureError("symlinks are forbidden in fixture bundles")
            if item.is_file():
                actual_files.add(item.relative_to(root).as_posix())
        if actual_files != declared_paths | {"manifest.json"}:
            raise SeoFixtureError("fixture bundle contains missing or undeclared files")
        digest = manifest_digest(manifest)
        if manifest["bundle_sha256"] != digest:
            raise SeoFixtureError("fixture bundle manifest hash mismatch")
        bundle = cls(root=root, manifest=manifest, rows=rows, digest=digest)
        bundle._validate_rows()
        return bundle

    @staticmethod
    def _validate_manifest(manifest: dict[str, Any]) -> None:
        if manifest["schema_version"] != 1 or manifest["module"] != "seo":
            raise SeoFixtureError("fixture is not an SEO schema v1 bundle")
        if manifest["target_revision"] != REQUIRED_REVISION:
            raise SeoFixtureError(f"fixture requires {REQUIRED_REVISION}")
        database = manifest["target_database"]
        if not isinstance(database, str) or database.lower() == "sem_prod" or database != "gsnipers_demo":
            raise SeoFixtureError("fixture target must be the reviewed gsnipers_demo database")
        if not isinstance(manifest["dataset_key"], str) or not IDENTIFIER.fullmatch(manifest["dataset_key"]):
            raise SeoFixtureError("dataset_key is invalid")
        if not isinstance(manifest["dataset_version"], str) or not VERSION.fullmatch(manifest["dataset_version"]):
            raise SeoFixtureError("dataset_version is invalid")
        _positive_int(manifest["demo_tenant_id"], "demo_tenant_id")
        if not isinstance(manifest["app_readonly_role"], str) or not ROLE.fullmatch(manifest["app_readonly_role"]):
            raise SeoFixtureError("app_readonly_role is invalid")
        if not isinstance(manifest["sites"], list) or not manifest["sites"]:
            raise SeoFixtureError("manifest requires at least one site")
        if not isinstance(manifest["sources"], list) or not manifest["sources"]:
            raise SeoFixtureError("manifest requires source provenance")
        for source in manifest["sources"]:
            if not isinstance(source, dict) or set(source) != {"url", "collected_at", "content_sha256"}:
                raise SeoFixtureError("source provenance entry is invalid")
            parsed_url = urlsplit(source["url"]) if isinstance(source["url"], str) else None
            if (
                parsed_url is None or parsed_url.scheme not in {"https", "http"}
                or not parsed_url.hostname or parsed_url.username or parsed_url.password
            ):
                raise SeoFixtureError("source provenance URL is invalid")
            if not isinstance(source["content_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", source["content_sha256"]):
                raise SeoFixtureError("source provenance hash is invalid")
            try:
                collected_at = datetime.fromisoformat(str(source["collected_at"]).replace("Z", "+00:00"))
            except ValueError as exc:
                raise SeoFixtureError("source provenance timestamp is invalid") from exc
            if collected_at.tzinfo is None:
                raise SeoFixtureError("source provenance timestamp must include a timezone")
        for field in ("generated_at",):
            try:
                parsed_time = datetime.fromisoformat(str(manifest[field]).replace("Z", "+00:00"))
            except ValueError as exc:
                raise SeoFixtureError(f"{field} is invalid") from exc
            if parsed_time.tzinfo is None:
                raise SeoFixtureError(f"{field} must include a timezone")
        if not isinstance(manifest["loader_version"], str) or not manifest["loader_version"].strip():
            raise SeoFixtureError("loader_version is invalid")
        if manifest["text_policy"] != {
            "synthetic": True,
            "redacted": True,
            "policy_version": "seo-fixture-text-v1",
        }:
            raise SeoFixtureError("manifest text_policy must declare synthetic, redacted fixture text")
        tables = manifest["tables"]
        if not isinstance(tables, dict) or not REQUIRED_TABLES.issubset(tables):
            raise SeoFixtureError("manifest is missing required fixture tables")
        if not isinstance(manifest["bundle_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", manifest["bundle_sha256"]):
            raise SeoFixtureError("bundle_sha256 is invalid")

    def _validate_rows(self) -> None:
        tenant_id = self.demo_tenant_id
        sites = self.manifest["sites"]
        expected_sites: dict[int, str] = {}
        for site in sites:
            if not isinstance(site, dict) or set(site) != {"site_id", "canonical_domain"}:
                raise SeoFixtureError("site manifest entry is invalid")
            site_id = _positive_int(site["site_id"], "site_id")
            domain = site["canonical_domain"]
            if (
                site_id in expected_sites or not isinstance(domain, str) or not domain.strip()
                or any(character in domain for character in "/:@?#\\") or domain.startswith(".")
            ):
                raise SeoFixtureError("site manifest entry is duplicate or invalid")
            expected_sites[site_id] = domain.strip().lower()
        loaded_sites: dict[int, str] = {}
        tenant_module_ids = {row.get("id") for row in self.rows.get("tenant_modules", ())}
        seen_primary_keys: dict[str, set[object]] = {}
        for table, records in self.rows.items():
            for row in records:
                if set(row) - TABLE_COLUMN_ALLOWLISTS[table]:
                    raise SeoFixtureError(f"table {table} contains columns outside its explicit allowlist")
                if _contains_sensitive_value(row):
                    raise SeoFixtureError(f"table {table} contains credential material")
                if "tenant_id" in row and row["tenant_id"] != tenant_id:
                    raise SeoFixtureError(f"table {table} crosses the demo tenant boundary")
                if "site_id" in row and row["site_id"] is not None and row["site_id"] not in expected_sites:
                    raise SeoFixtureError(f"table {table} crosses the manifest site boundary")
                if table == "tenants" and row.get("id") != tenant_id:
                    raise SeoFixtureError("tenant fixture id does not match demo_tenant_id")
                if table == "tenant_modules" and row.get("module_code") != "seo":
                    raise SeoFixtureError("tenant_modules may contain SEO only")
                if table == "seo_tasks" and row.get("module") != "seo":
                    raise SeoFixtureError("seo_tasks must use module=seo")
                if table in {"seo_ai_operations", "seo_qa_batches"} and row.get("actor") != SYNTHETIC_ACTOR_TEXT:
                    raise SeoFixtureError(f"table {table} must use the synthetic actor contract")
                if table == "seo_tasks" and row.get("created_by") != SYNTHETIC_ACTOR_TEXT:
                    raise SeoFixtureError("seo_tasks must use the synthetic actor contract")
                if table in {"seo_image_alt_reviews", "seo_page_index_reviews"} and (
                    row.get("actor_id") != SYNTHETIC_ACTOR_ID
                    or row.get("actor_name") != SYNTHETIC_ACTOR_NAME
                ):
                    raise SeoFixtureError(f"table {table} must use the synthetic actor contract")
                if table == "seo_sites":
                    if row.get("tenant_module_id") not in tenant_module_ids:
                        raise SeoFixtureError(
                            "table seo_sites tenant_module_id does not reference a bundled parent"
                        )
                    settings = row.get("site_settings")
                    marker = {
                        "fixture_marker": self.dataset_key,
                        "dataset_version": self.dataset_version,
                        "synthetic": True,
                        "scheduler_excluded": True,
                        "external_actions_disabled": True,
                    }
                    if not isinstance(settings, dict) or any(settings.get(k) != v for k, v in marker.items()):
                        raise SeoFixtureError("SEO site safety markers do not match the manifest")
                    loaded_sites[row.get("id")] = str(row.get("canonical_domain") or "").lower()
                if table == "seo_distribution_connections":
                    if (
                        row.get("has_credentials") is not False
                        or row.get("enabled") is not False
                        or row.get("config") not in (None, {})
                        or row.get("capabilities") not in (None, [])
                    ):
                        raise SeoFixtureError("demo distribution connections must be inert and credential-free")
                if str(row.get("status") or "").strip().lower() in RUNNABLE_STATES.get(table, ()):
                    raise SeoFixtureError(f"table {table} contains a runnable state")
                if "id" in row:
                    values = seen_primary_keys.setdefault(table, set())
                    if row["id"] in values:
                        raise SeoFixtureError(f"table {table} contains duplicate ids")
                    values.add(row["id"])
        if loaded_sites != expected_sites:
            raise SeoFixtureError("loaded SEO sites do not match the manifest")
        self._validate_relations(expected_sites)

    def _validate_relations(self, expected_sites: dict[int, str]) -> None:
        by_table = {
            table: {row["id"]: row for row in rows if row.get("id") is not None}
            for table, rows in self.rows.items()
        }
        resolved: dict[tuple[str, object], int | None] = {
            ("seo_sites", site_id): site_id for site_id in expected_sites
        }
        pending = [
            (table, row) for table, rows in self.rows.items() for row in rows
            if row.get("id") is not None and table != "seo_sites"
        ]
        for _ in range(len(pending) + 1):
            changed = False
            for table, row in pending:
                key = (table, row["id"])
                candidates: set[int] = set()
                if isinstance(row.get("site_id"), int):
                    candidates.add(row["site_id"])
                unresolved = False
                for field, parent_table in SITE_RELATIONS.items():
                    parent_id = row.get(field)
                    if parent_id is None or field == "site_id":
                        continue
                    parent = by_table.get(parent_table, {}).get(parent_id)
                    if parent is None:
                        raise SeoFixtureError(
                            f"table {table} {field} does not reference a bundled parent"
                        )
                    parent_site = resolved.get((parent_table, parent_id))
                    if parent_site is None and parent_table != "tenant_modules" and parent_table != "seo_distribution_connections":
                        unresolved = True
                    elif parent_site is not None:
                        candidates.add(parent_site)
                keyword_ids = row.get("keyword_ids")
                if keyword_ids is not None:
                    if not isinstance(keyword_ids, list) or any(
                        isinstance(value, bool) or not isinstance(value, int) for value in keyword_ids
                    ):
                        raise SeoFixtureError(f"table {table} keyword_ids must be an integer list")
                    for parent_id in keyword_ids:
                        if parent_id not in by_table.get("seo_keyword_assets", {}):
                            raise SeoFixtureError(
                                f"table {table} keyword_ids does not reference a bundled parent"
                            )
                        parent_site = resolved.get(("seo_keyword_assets", parent_id))
                        if parent_site is None:
                            unresolved = True
                        else:
                            candidates.add(parent_site)
                if len(candidates) > 1:
                    raise SeoFixtureError(f"table {table} crosses site boundaries through its parent references")
                if not unresolved and key not in resolved:
                    resolved[key] = next(iter(candidates), None)
                    changed = True
            if not changed:
                break


def validate_target_url(database_url: str, bundle: SeoFixtureBundle, allowed_hosts: set[str]) -> None:
    try:
        url = make_url(database_url)
    except Exception as exc:
        raise SeoFixtureError("database URL is invalid") from exc
    if any(not host or "*" in host for host in allowed_hosts):
        raise SeoFixtureError("database host allowlist is invalid")
    hosts = {host.lower() for host in allowed_hosts}
    if url.drivername != "postgresql+asyncpg" or not url.host or url.host.lower() not in hosts:
        raise SeoFixtureError("database driver or host is not approved")
    if url.database != bundle.manifest["target_database"] or url.database == "sem_prod":
        raise SeoFixtureError("database URL does not target the reviewed demo database")


async def _scalar_rows(connection: AsyncConnection, sql: str, params: dict[str, Any] | None = None) -> list[Any]:
    return list((await connection.execute(text(sql), params or {})).scalars())


async def _verify_no_production_connect(connection: AsyncConnection, role: str) -> None:
    privilege = (await connection.execute(text(
        "SELECT CASE WHEN EXISTS (SELECT 1 FROM pg_database WHERE datname='sem_prod') "
        "THEN has_database_privilege(:role, 'sem_prod', 'CONNECT') ELSE NULL END"
    ), {"role": role})).scalar_one()
    if privilege is not False:
        raise SeoFixtureError("demo role production database CONNECT privilege is unsafe or unverifiable")


async def _verify_app_readonly(connection: AsyncConnection, role: str) -> None:
    identity = (await connection.execute(text(
        "SELECT count(*)=1, coalesce(bool_or(rolsuper),false), "
        "coalesce(bool_or(rolreplication),false), coalesce(bool_or(rolbypassrls),false), "
        "coalesce(bool_or(rolcreatedb),false), coalesce(bool_or(rolcreaterole),false), "
        "(SELECT count(*) FROM pg_auth_members m JOIN pg_roles child ON child.oid=m.member WHERE child.rolname=:role)=0, "
        "(SELECT count(*) FROM pg_auth_members m JOIN pg_roles parent ON parent.oid=m.roleid WHERE parent.rolname=:role)=0 "
        "FROM pg_roles WHERE rolname=:role"
    ), {"role": role})).one()
    if identity != (True, False, False, False, False, False, True, True):
        raise SeoFixtureError("application read-only role identity is unsafe")
    await _verify_no_production_connect(connection, role)
    readable_tables = (*TABLE_ORDER, "roles", "users", "demo_tenant_bindings", "demo_tenant_binding_history")
    for table in readable_tables:
        privileges = (await connection.execute(text(
            f"SELECT has_table_privilege(:role, 'public.{table}', 'SELECT'), "
            f"has_table_privilege(:role, 'public.{table}', 'INSERT'), "
            f"has_table_privilege(:role, 'public.{table}', 'UPDATE'), "
            f"has_table_privilege(:role, 'public.{table}', 'DELETE'), "
            f"has_table_privilege(:role, 'public.{table}', 'TRUNCATE')"
        ), {"role": role})).one()
        if privileges != (True, False, False, False, False):
            raise SeoFixtureError(f"application role privileges are unsafe for {table}")
    registry_privileges = (await connection.execute(text(
        f"SELECT has_table_privilege(:role, 'public.{RECEIPT_REGISTRY_TABLE}', 'SELECT'), "
        f"has_table_privilege(:role, 'public.{RECEIPT_REGISTRY_TABLE}', 'INSERT'), "
        f"has_table_privilege(:role, 'public.{RECEIPT_REGISTRY_TABLE}', 'UPDATE'), "
        f"has_table_privilege(:role, 'public.{RECEIPT_REGISTRY_TABLE}', 'DELETE'), "
        f"has_table_privilege(:role, 'public.{RECEIPT_REGISTRY_TABLE}', 'TRUNCATE')"
    ), {"role": role})).one()
    if registry_privileges != (False, False, False, False, False):
        raise SeoFixtureError("application role must not access the fixture receipt registry")
    schema_privileges = (await connection.execute(text(
        "SELECT has_schema_privilege(:role, 'public', 'USAGE'), has_schema_privilege(:role, 'public', 'CREATE'), "
        "has_database_privilege(:role, current_database(), 'CONNECT'), "
        "has_database_privilege(:role, current_database(), 'CREATE'), has_database_privilege(:role, current_database(), 'TEMP')"
    ), {"role": role})).one()
    if schema_privileges != (True, False, True, False, False):
        raise SeoFixtureError("application role schema or database privileges are unsafe")
    writable_sequences = (await connection.execute(text(
        "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relkind='S' AND "
        "(has_sequence_privilege(:role, c.oid, 'SELECT') OR has_sequence_privilege(:role, c.oid, 'USAGE') OR has_sequence_privilege(:role, c.oid, 'UPDATE'))"
    ), {"role": role})).scalar_one()
    if int(writable_sequences) != 0:
        raise SeoFixtureError("application role has writable sequence privileges")


async def _verify_loader_role(connection: AsyncConnection, role: str) -> None:
    memberships = (await connection.execute(text(
        "SELECT "
        "(SELECT count(*) FROM pg_auth_members m JOIN pg_roles child ON child.oid=m.member WHERE child.rolname=:role), "
        "(SELECT count(*) FROM pg_auth_members m JOIN pg_roles parent ON parent.oid=m.roleid WHERE parent.rolname=:role)"
    ), {"role": role})).one()
    if memberships != (0, 0):
        raise SeoFixtureError("loader role must not inherit or grant role memberships")
    await _verify_no_production_connect(connection, role)
    readonly_tables = {"roles", "users", "demo_tenant_bindings", "demo_tenant_binding_history"}
    for table in (*TABLE_ORDER, *sorted(readonly_tables)):
        privileges = (await connection.execute(text(
            f"SELECT has_table_privilege(:role, 'public.{table}', 'SELECT'), "
            f"has_table_privilege(:role, 'public.{table}', 'INSERT'), "
            f"has_table_privilege(:role, 'public.{table}', 'UPDATE'), "
            f"has_table_privilege(:role, 'public.{table}', 'DELETE'), "
            f"has_table_privilege(:role, 'public.{table}', 'TRUNCATE')"
        ), {"role": role})).one()
        expected = (True, table in TABLE_ORDER, False, False, False)
        if privileges != expected:
            raise SeoFixtureError(f"loader role privileges are unsafe for {table}")
    registry_privileges = (await connection.execute(text(
        f"SELECT has_table_privilege(:role, 'public.{RECEIPT_REGISTRY_TABLE}', 'SELECT'), "
        f"has_table_privilege(:role, 'public.{RECEIPT_REGISTRY_TABLE}', 'INSERT'), "
        f"has_table_privilege(:role, 'public.{RECEIPT_REGISTRY_TABLE}', 'UPDATE'), "
        f"has_table_privilege(:role, 'public.{RECEIPT_REGISTRY_TABLE}', 'DELETE'), "
        f"has_table_privilege(:role, 'public.{RECEIPT_REGISTRY_TABLE}', 'TRUNCATE')"
    ), {"role": role})).one()
    if registry_privileges != (True, True, False, False, False):
        raise SeoFixtureError("loader role receipt registry privileges are unsafe")
    environment = (await connection.execute(text(
        "SELECT has_schema_privilege(:role, 'public', 'USAGE'), has_schema_privilege(:role, 'public', 'CREATE'), "
        "has_database_privilege(:role, current_database(), 'CONNECT'), "
        "has_database_privilege(:role, current_database(), 'CREATE'), has_database_privilege(:role, current_database(), 'TEMP')"
    ), {"role": role})).one()
    if environment != (True, False, True, False, False):
        raise SeoFixtureError("loader role schema or database privileges are unsafe")
    sequence_privileges = (await connection.execute(text(
        "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relkind='S' AND "
        "(has_sequence_privilege(:role, c.oid, 'SELECT') OR has_sequence_privilege(:role, c.oid, 'USAGE') OR has_sequence_privilege(:role, c.oid, 'UPDATE'))"
    ), {"role": role})).scalar_one()
    if int(sequence_privileges) != 0:
        raise SeoFixtureError("loader role has sequence privileges")


async def _verify_receipt_registry(connection: AsyncConnection) -> None:
    relation = (await connection.execute(text(
        f"SELECT to_regclass('public.{RECEIPT_REGISTRY_TABLE}')::text"
    ))).scalar_one()
    if relation != RECEIPT_REGISTRY_TABLE:
        raise SeoFixtureError(
            "immutable fixture receipt registry is absent; revision 0098 is intentionally fail-closed"
        )
    columns = await _scalar_rows(connection,
        "SELECT column_name FROM information_schema.columns "
        f"WHERE table_schema='public' AND table_name='{RECEIPT_REGISTRY_TABLE}' ORDER BY ordinal_position"
    )
    expected = [
        "manifest_sha256", "dataset_key", "dataset_version", "demo_tenant_id",
        "target_revision", "target_database", "server_address", "loader_role",
        "loader_version", "row_counts", "committed_at",
    ]
    if columns != expected:
        raise SeoFixtureError("fixture receipt registry columns do not match the reviewed design")
    trigger_rows = (await connection.execute(text(
        "SELECT event_manipulation, action_timing, action_statement "
        "FROM information_schema.triggers "
        f"WHERE event_object_schema='public' AND event_object_table='{RECEIPT_REGISTRY_TABLE}'"
    ))).all()
    expected_triggers = {
        (event, "BEFORE", f"EXECUTE FUNCTION {RECEIPT_REJECT_FUNCTION}")
        for event in ("UPDATE", "DELETE", "TRUNCATE")
    }
    if set(trigger_rows) != expected_triggers:
        raise SeoFixtureError("fixture receipt registry is not protected by immutable triggers")


async def _table_count(connection: AsyncConnection, table: str) -> int:
    return int((await connection.execute(text(f"SELECT count(*) FROM public.{table}"))).scalar_one())


def _metadata_tables() -> dict[str, Any]:
    from app.database import Base
    import app.models  # noqa: F401
    return {name: Base.metadata.tables[name] for name in TABLE_ORDER}


def _coerce_rows(table: Any, rows: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    columns = {column.name: column for column in table.columns}
    converted: list[dict[str, Any]] = []
    for row in rows:
        unknown = set(row) - TABLE_COLUMN_ALLOWLISTS[table.name]
        if unknown:
            raise SeoFixtureError(f"table {table.name} contains unknown columns")
        item = dict(row)
        for name, value in tuple(item.items()):
            if value is None:
                continue
            kind = columns[name].type
            try:
                if isinstance(kind, DateTime) and isinstance(value, str):
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    if not kind.timezone and parsed.tzinfo is not None:
                        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
                    item[name] = parsed
                elif isinstance(kind, Date) and isinstance(value, str):
                    item[name] = date.fromisoformat(value)
                elif isinstance(kind, Numeric) and not isinstance(value, Decimal):
                    item[name] = Decimal(str(value))
            except (ValueError, ArithmeticError) as exc:
                raise SeoFixtureError(f"table {table.name} column {name} has an invalid value") from exc
        converted.append(item)
    return converted


async def _load_fixture_transaction_after_approved_registry(
    connection: AsyncConnection,
    bundle: SeoFixtureBundle,
    *,
    expected_server_addresses: set[str],
) -> dict[str, Any]:
    identity = (await connection.execute(text(
        "SELECT current_database(), inet_server_addr()::text, current_user, session_user, "
        "current_setting('transaction_isolation'), r.rolsuper, r.rolreplication, "
        "r.rolbypassrls, r.rolcreatedb, r.rolcreaterole "
        "FROM pg_roles r WHERE r.rolname=current_user"
    ))).one()
    database, server_address, loader_role, session_role, isolation, superuser, replication, bypass_rls, create_db, create_role = identity
    if database != bundle.manifest["target_database"] or database == "sem_prod":
        raise SeoFixtureError("connected database identity is not the reviewed demo target")
    if server_address not in expected_server_addresses or isolation.lower() != "serializable":
        raise SeoFixtureError("server address or transaction isolation is unsafe")
    if (
        session_role != loader_role or superuser or replication or bypass_rls
        or create_db or create_role or loader_role == bundle.manifest["app_readonly_role"]
    ):
        raise SeoFixtureError("loader role identity is unsafe")
    revisions = await _scalar_rows(connection, "SELECT version_num FROM alembic_version ORDER BY version_num")
    if revisions != [REQUIRED_REVISION]:
        raise SeoFixtureError(f"target must have exactly revision {REQUIRED_REVISION}")
    locked = (await connection.execute(
        text("SELECT pg_try_advisory_xact_lock(:lock_key)"), {"lock_key": FIXED_LOCK_KEY}
    )).scalar_one()
    if locked is not True:
        raise SeoFixtureError("another SEO fixture loader holds the database advisory lock")
    await _verify_receipt_registry(connection)
    for table in EMPTY_GUARD_TABLES:
        if await _table_count(connection, table) != 0:
            raise SeoFixtureError(f"target is not empty: {table}")
    if await _table_count(connection, RECEIPT_REGISTRY_TABLE) != 0:
        raise SeoFixtureError("target already has a fixture load receipt")
    await _verify_loader_role(connection, loader_role)
    await _verify_app_readonly(connection, bundle.manifest["app_readonly_role"])
    metadata = _metadata_tables()
    for table_name in TABLE_ORDER:
        rows = bundle.rows.get(table_name, ())
        if rows:
            await connection.execute(insert(metadata[table_name]), _coerce_rows(metadata[table_name], rows))
    actual_counts = {table: await _table_count(connection, table) for table in TABLE_ORDER}
    expected_counts = {table: len(bundle.rows.get(table, ())) for table in TABLE_ORDER}
    if actual_counts != expected_counts:
        raise SeoFixtureError("post-load row counts do not match the manifest")
    if await _table_count(connection, "demo_tenant_bindings") or await _table_count(connection, "demo_tenant_binding_history"):
        raise SeoFixtureError("loader must not create demo tenant bindings")
    await _verify_app_readonly(connection, bundle.manifest["app_readonly_role"])
    receipt = {
        "schema_version": 1,
        "module": "seo",
        "target_revision": REQUIRED_REVISION,
        "target_database": database,
        "server_address": server_address,
        "loader_role": loader_role,
        "loader_version": bundle.manifest["loader_version"],
        "dataset_key": bundle.dataset_key,
        "dataset_version": bundle.dataset_version,
        "demo_tenant_id": bundle.demo_tenant_id,
        "manifest_sha256": bundle.digest,
        "row_counts": {name: count for name, count in actual_counts.items() if count},
        "validated_at": datetime.now().astimezone().isoformat(),
        "result": "committed",
    }
    await connection.execute(text(
        f"INSERT INTO public.{RECEIPT_REGISTRY_TABLE} "
        "(manifest_sha256, dataset_key, dataset_version, demo_tenant_id, target_revision, "
        "target_database, server_address, loader_role, loader_version, row_counts) "
        "VALUES (:manifest_sha256, :dataset_key, :dataset_version, :demo_tenant_id, :target_revision, "
        ":target_database, :server_address, :loader_role, :loader_version, CAST(:row_counts AS jsonb))"
    ), {**receipt, "row_counts": json.dumps(receipt["row_counts"], sort_keys=True)})
    return receipt


async def load_fixture_transaction(
    connection: AsyncConnection,
    bundle: SeoFixtureBundle,
    *,
    expected_server_addresses: set[str],
) -> dict[str, Any]:
    del connection, bundle, expected_server_addresses
    raise SeoFixtureError(
        "revision 0098 cannot load fixtures; an approved 0099 receipt migration is required"
    )


async def _run_fixture_load_after_approved_registry(
    database_url: str,
    bundle: SeoFixtureBundle,
    *,
    allowed_hosts: set[str],
    expected_server_addresses: set[str],
    engine: AsyncEngine | None = None,
) -> dict[str, Any]:
    validate_target_url(database_url, bundle, allowed_hosts)
    owned = engine is None
    target = engine or create_async_engine(database_url, isolation_level="SERIALIZABLE", pool_pre_ping=True)
    try:
        async with target.begin() as connection:
            receipt = await _load_fixture_transaction_after_approved_registry(
                connection, bundle, expected_server_addresses=expected_server_addresses
            )
        return receipt
    finally:
        if owned:
            await target.dispose()


async def _recover_committed_receipt_after_approved_registry(
    database_url: str,
    bundle: SeoFixtureBundle,
    *,
    allowed_hosts: set[str],
    expected_server_addresses: set[str],
    engine: AsyncEngine | None = None,
) -> dict[str, Any]:
    """Recreate a lost local receipt from the immutable in-database record."""
    validate_target_url(database_url, bundle, allowed_hosts)
    owned = engine is None
    target = engine or create_async_engine(database_url, isolation_level="SERIALIZABLE", pool_pre_ping=True)
    try:
        async with target.begin() as connection:
            identity = (await connection.execute(text(
                "SELECT current_database(), inet_server_addr()::text, current_user, session_user, "
                "current_setting('transaction_isolation'), r.rolsuper, r.rolreplication, "
                "r.rolbypassrls, r.rolcreatedb, r.rolcreaterole "
                "FROM pg_roles r WHERE r.rolname=current_user"
            ))).one()
            (
                database, server_address, loader_role, session_role, isolation,
                superuser, replication, bypass_rls, create_db, create_role,
            ) = identity
            if (
                database != bundle.manifest["target_database"] or database == "sem_prod"
                or server_address not in expected_server_addresses
                or loader_role != session_role or isolation.lower() != "serializable"
                or superuser or replication or bypass_rls or create_db or create_role
            ):
                raise SeoFixtureError("receipt recovery target identity is unsafe")
            revisions = await _scalar_rows(connection, "SELECT version_num FROM alembic_version ORDER BY version_num")
            if revisions != [REQUIRED_REVISION]:
                raise SeoFixtureError(f"target must have exactly revision {REQUIRED_REVISION}")
            await _verify_receipt_registry(connection)
            await _verify_loader_role(connection, loader_role)
            result = (await connection.execute(text(
                f"SELECT dataset_key, dataset_version, demo_tenant_id, target_revision, target_database, "
                f"server_address::text, loader_role::text, loader_version, row_counts, committed_at "
                f"FROM public.{RECEIPT_REGISTRY_TABLE} WHERE manifest_sha256=:digest"
            ), {"digest": bundle.digest})).one_or_none()
            if result is None:
                raise SeoFixtureError("no committed receipt matches the reviewed bundle")
            (
                dataset_key, dataset_version, demo_tenant_id, target_revision,
                target_database, recorded_address, recorded_role, loader_version,
                row_counts, committed_at,
            ) = result
            if (
                dataset_key != bundle.dataset_key or dataset_version != bundle.dataset_version
                or demo_tenant_id != bundle.demo_tenant_id or target_revision != REQUIRED_REVISION
                or target_database != database or recorded_address != server_address
                or recorded_role != loader_role or loader_version != bundle.manifest["loader_version"]
            ):
                raise SeoFixtureError("stored receipt does not match the reviewed bundle or target")
            return {
                "schema_version": 1, "module": "seo", "target_revision": target_revision,
                "target_database": target_database, "server_address": recorded_address,
                "loader_role": recorded_role, "loader_version": loader_version,
                "dataset_key": dataset_key, "dataset_version": dataset_version,
                "demo_tenant_id": demo_tenant_id, "manifest_sha256": bundle.digest,
                "row_counts": row_counts,
                "validated_at": committed_at.isoformat() if hasattr(committed_at, "isoformat") else str(committed_at),
                "result": "committed",
            }
    finally:
        if owned:
            await target.dispose()


async def run_fixture_load(
    database_url: str,
    bundle: SeoFixtureBundle,
    *,
    allowed_hosts: set[str],
    expected_server_addresses: set[str],
    engine: AsyncEngine | None = None,
) -> dict[str, Any]:
    del database_url, bundle, allowed_hosts, expected_server_addresses, engine
    raise SeoFixtureError(
        "revision 0098 cannot load fixtures; an approved 0099 receipt migration is required"
    )


async def recover_committed_receipt(
    database_url: str,
    bundle: SeoFixtureBundle,
    *,
    allowed_hosts: set[str],
    expected_server_addresses: set[str],
    engine: AsyncEngine | None = None,
) -> dict[str, Any]:
    del database_url, bundle, allowed_hosts, expected_server_addresses, engine
    raise SeoFixtureError(
        "revision 0098 cannot recover fixture receipts; an approved 0099 receipt migration is required"
    )
