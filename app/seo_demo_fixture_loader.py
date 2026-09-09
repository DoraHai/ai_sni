"""Offline, single-use loader for an isolated SEO demonstration database."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
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
        "bundle_sha256",
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
REQUIRED_TABLES = frozenset({"tenants", "tenant_modules", "seo_sites"})
RUNNABLE_STATES = {
    "seo_ai_operations": frozenset({"pending", "queued", "running", "processing"}),
    "seo_automation_runs": frozenset({"pending", "queued", "running", "processing"}),
    "seo_crawl_runs": frozenset({"pending", "queued", "running", "processing"}),
    "seo_qa_batches": frozenset({"pending", "queued", "running", "processing"}),
    "seo_tasks": frozenset({"in_progress"}),
    "seo_content_publications": frozenset({"preparing", "publishing", "retrying"}),
    "seo_publish_attempts": frozenset({"pending", "queued", "running", "processing", "retrying"}),
}
SENSITIVE_KEYS = re.compile(r"(?:password|secret|token|cookie|credential)", re.I)
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
VERSION = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")
ROLE = re.compile(r"^[a-z_][a-z0-9_-]{0,62}$")


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
                datetime.fromisoformat(str(source["collected_at"]).replace("Z", "+00:00"))
            except ValueError as exc:
                raise SeoFixtureError("source provenance timestamp is invalid") from exc
        for field in ("generated_at",):
            try:
                datetime.fromisoformat(str(manifest[field]).replace("Z", "+00:00"))
            except ValueError as exc:
                raise SeoFixtureError(f"{field} is invalid") from exc
        if not isinstance(manifest["loader_version"], str) or not manifest["loader_version"].strip():
            raise SeoFixtureError("loader_version is invalid")
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
        seen_primary_keys: dict[str, set[object]] = {}
        for table, records in self.rows.items():
            for row in records:
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
                if table == "seo_sites":
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
                    if row.get("credentials_encrypted") not in (None, "") or row.get("has_credentials") is not False or row.get("enabled") is not False:
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


async def _verify_app_readonly(connection: AsyncConnection, role: str) -> None:
    identity = (await connection.execute(text(
        "SELECT count(*)=1, coalesce(bool_or(rolsuper),false), "
        "coalesce(bool_or(rolreplication),false), coalesce(bool_or(rolbypassrls),false), "
        "coalesce(bool_or(rolcreatedb),false), coalesce(bool_or(rolcreaterole),false), "
        "(SELECT count(*) FROM pg_auth_members m JOIN pg_roles child ON child.oid=m.member WHERE child.rolname=:role)=0 "
        "FROM pg_roles WHERE rolname=:role"
    ), {"role": role})).one()
    if identity != (True, False, False, False, False, False, True):
        raise SeoFixtureError("application read-only role identity is unsafe")
    for table in TABLE_ORDER:
        privileges = (await connection.execute(text(
            f"SELECT has_table_privilege(:role, 'public.{table}', 'SELECT'), "
            f"has_table_privilege(:role, 'public.{table}', 'INSERT'), "
            f"has_table_privilege(:role, 'public.{table}', 'UPDATE'), "
            f"has_table_privilege(:role, 'public.{table}', 'DELETE'), "
            f"has_table_privilege(:role, 'public.{table}', 'TRUNCATE')"
        ), {"role": role})).one()
        if privileges != (True, False, False, False, False):
            raise SeoFixtureError(f"application role privileges are unsafe for {table}")
    schema_privileges = (await connection.execute(text(
        "SELECT has_schema_privilege(:role, 'public', 'USAGE'), has_schema_privilege(:role, 'public', 'CREATE'), has_database_privilege(:role, current_database(), 'CREATE'), has_database_privilege(:role, current_database(), 'TEMP')"
    ), {"role": role})).one()
    if schema_privileges != (True, False, False, False):
        raise SeoFixtureError("application role schema or database privileges are unsafe")
    writable_sequences = (await connection.execute(text(
        "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relkind='S' AND "
        "(has_sequence_privilege(:role, c.oid, 'USAGE') OR has_sequence_privilege(:role, c.oid, 'UPDATE'))"
    ), {"role": role})).scalar_one()
    if int(writable_sequences) != 0:
        raise SeoFixtureError("application role has writable sequence privileges")


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
        unknown = set(row) - set(columns)
        if unknown:
            raise SeoFixtureError(f"table {table.name} contains unknown columns")
        item = dict(row)
        for name, value in tuple(item.items()):
            if value is None:
                continue
            kind = columns[name].type
            try:
                if isinstance(kind, DateTime) and isinstance(value, str):
                    item[name] = datetime.fromisoformat(value.replace("Z", "+00:00"))
                elif isinstance(kind, Date) and isinstance(value, str):
                    item[name] = date.fromisoformat(value)
                elif isinstance(kind, Numeric) and not isinstance(value, Decimal):
                    item[name] = Decimal(str(value))
            except (ValueError, ArithmeticError) as exc:
                raise SeoFixtureError(f"table {table.name} column {name} has an invalid value") from exc
        converted.append(item)
    return converted


async def load_fixture_transaction(
    connection: AsyncConnection,
    bundle: SeoFixtureBundle,
    *,
    expected_server_addresses: set[str],
) -> dict[str, Any]:
    identity = (await connection.execute(text(
        "SELECT current_database(), inet_server_addr()::text, current_user, "
        "current_setting('transaction_isolation'), r.rolsuper, r.rolreplication, "
        "r.rolbypassrls, r.rolcreatedb, r.rolcreaterole "
        "FROM pg_roles r WHERE r.rolname=current_user"
    ))).one()
    database, server_address, loader_role, isolation, superuser, replication, bypass_rls, create_db, create_role = identity
    if database != bundle.manifest["target_database"] or database == "sem_prod":
        raise SeoFixtureError("connected database identity is not the reviewed demo target")
    if server_address not in expected_server_addresses or isolation.lower() != "serializable":
        raise SeoFixtureError("server address or transaction isolation is unsafe")
    if superuser or replication or bypass_rls or create_db or create_role or loader_role == bundle.manifest["app_readonly_role"]:
        raise SeoFixtureError("loader role identity is unsafe")
    revisions = await _scalar_rows(connection, "SELECT version_num FROM alembic_version ORDER BY version_num")
    if revisions != [REQUIRED_REVISION]:
        raise SeoFixtureError(f"target must have exactly revision {REQUIRED_REVISION}")
    lock_key = int.from_bytes(hashlib.sha256(f"seo-fixture:{bundle.dataset_key}".encode()).digest()[:8], "big", signed=True)
    locked = (await connection.execute(
        text("SELECT pg_try_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key}
    )).scalar_one()
    if locked is not True:
        raise SeoFixtureError("another loader holds the dataset advisory lock")
    for table in (*TABLE_ORDER, "demo_tenant_bindings", "demo_tenant_binding_history"):
        if await _table_count(connection, table) != 0:
            raise SeoFixtureError(f"target is not empty: {table}")
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
    return {
        "schema_version": 1,
        "module": "seo",
        "target_revision": REQUIRED_REVISION,
        "target_database": database,
        "server_address": server_address,
        "loader_role": loader_role,
        "dataset_key": bundle.dataset_key,
        "dataset_version": bundle.dataset_version,
        "demo_tenant_id": bundle.demo_tenant_id,
        "manifest_sha256": bundle.digest,
        "row_counts": {name: count for name, count in actual_counts.items() if count},
        "validated_at": datetime.now().astimezone().isoformat(),
        "result": "committed",
    }


async def run_fixture_load(
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
            receipt = await load_fixture_transaction(connection, bundle, expected_server_addresses=expected_server_addresses)
        return receipt
    finally:
        if owned:
            await target.dispose()
