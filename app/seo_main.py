"""Independent SEO API process.

This application mounts only SEO routes and owns only the SEO scheduler.
Deploying or restarting it does not restart the shared SEM backend or GEO.
"""

from contextlib import asynccontextmanager
import json

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text, BigInteger, Integer, SmallInteger
from sqlalchemy.dialects.postgresql import JSONB

from app.api.customer_modules import seo_sites_router
from app.api.seo import router as seo_router
from app.config import get_settings
from app.database import engine
from app.http_errors import register_infra_handlers
from app.security.prod_guard import enforce_production_secrets
from app.seo_scheduler import shutdown_seo_scheduler, start_seo_scheduler
from app.seo_demo_runtime import (
    demo_request_is_allowed,
    seo_scheduler_may_start,
    validate_seo_demo_runtime_settings,
)
from app.seo_demo_source import SeoDataSourceDecision, hide_demo_tenant_ids

settings = get_settings()
enforce_production_secrets(settings, hard_fail=True)
validate_seo_demo_runtime_settings(settings)
SEO_REQUIRED_SCHEMA_REVISION = "0099_demo_fixture_registry"
# Runtime compatibility supports code-first rollout; it never authorizes the
# separately reviewed migration operation.
SEO_COMPATIBLE_SCHEMA_REVISIONS = frozenset(
    {"0094_seo_qa_batches", "0095_adopt_geo_ticket", "0096_sem_tasks", "0097_demo_tenant_bindings", "0098_demo_binding_no_truncate", SEO_REQUIRED_SCHEMA_REVISION}
)
SEO_GEO_TICKET_REQUIRED_REVISIONS = frozenset(
    {"0095_adopt_geo_ticket", "0096_sem_tasks", "0097_demo_tenant_bindings", "0098_demo_binding_no_truncate", SEO_REQUIRED_SCHEMA_REVISION}
)
SEO_GEO_TICKET_SHAPE = {
    "owner_name": ("character varying(100)", False, None, "", "", "b", None, True),
    "due_date": ("date", False, None, "", "", "b", None, True),
}
SEO_DEMO_BINDING_COLUMNS = {
    "demo_tenant_bindings": {
        "tenant_id": ("bigint", True), "demo_tenant_id": ("bigint", True),
        "dataset_key": ("character varying(64)", True), "dataset_version": ("character varying(40)", True),
        "status": ("character varying(16)", True), "bound_by_user_id": ("bigint", True),
        "bound_at": ("timestamp with time zone", True), "updated_by_user_id": ("bigint", True),
        "updated_at": ("timestamp with time zone", True), "disabled_at": ("timestamp with time zone", False),
        "version": ("integer", True), "notes": ("character varying(500)", False),
    },
    "demo_tenant_binding_history": {
        "id": ("bigint", True), "tenant_id": ("bigint", True), "binding_version": ("integer", True),
        "operation": ("character varying(16)", True), "before_snapshot": ("jsonb", False),
        "after_snapshot": ("jsonb", True), "actor_user_id": ("bigint", True),
        "reason": ("character varying(500)", True), "created_at": ("timestamp with time zone", True),
    },
}
SEO_DEMO_BINDING_CONSTRAINTS = {
    "demo_tenant_bindings": {
        "pk_demo_tenant_bindings", "fk_demo_tenant_bindings_tenant", "fk_demo_tenant_bindings_bound_by",
        "fk_demo_tenant_bindings_updated_by", "uq_demo_tenant_bindings_demo_tenant",
        "uq_demo_tenant_bindings_dataset_key", "ck_demo_tenant_bindings_demo_tenant_positive",
        "ck_demo_tenant_bindings_version_positive", "ck_demo_tenant_bindings_dataset_key_format",
        "ck_demo_tenant_bindings_dataset_version_format", "ck_demo_tenant_bindings_status",
        "ck_demo_tenant_bindings_disabled_state", "ck_demo_tenant_bindings_updated_time",
        "ck_demo_tenant_bindings_disabled_time", "ck_demo_tenant_bindings_disabled_updater",
    },
    "demo_tenant_binding_history": {
        "pk_demo_tenant_binding_history", "fk_demo_tenant_binding_history_tenant",
        "fk_demo_tenant_binding_history_actor", "uq_demo_tenant_binding_history_tenant_version",
        "ck_demo_tenant_binding_history_version_positive", "ck_demo_tenant_binding_history_operation",
        "ck_demo_tenant_binding_history_before", "ck_demo_tenant_binding_history_after",
        "ck_demo_tenant_binding_history_reason", "ck_demo_tenant_binding_history_links",
        "ck_demo_tenant_binding_history_transition",
    },
}
SEO_DEMO_BINDING_DEFAULTS = {
    ("demo_tenant_bindings", "bound_at"): "now()",
    ("demo_tenant_bindings", "updated_at"): "now()",
    ("demo_tenant_bindings", "version"): "1",
    ("demo_tenant_binding_history", "id"): "nextval('demo_tenant_binding_history_id_seq'::regclass)",
    ("demo_tenant_binding_history", "created_at"): "now()",
}
SEO_DEMO_BINDING_CONSTRAINT_RULES = {
    "pk_demo_tenant_bindings": ("primary key", "tenant_id"),
    "fk_demo_tenant_bindings_tenant": ("foreign key", "tenant_id", "references tenants", "on delete restrict"),
    "fk_demo_tenant_bindings_bound_by": ("foreign key", "bound_by_user_id", "references users", "on delete restrict"),
    "fk_demo_tenant_bindings_updated_by": ("foreign key", "updated_by_user_id", "references users", "on delete restrict"),
    "uq_demo_tenant_bindings_demo_tenant": ("unique", "demo_tenant_id"),
    "uq_demo_tenant_bindings_dataset_key": ("unique", "dataset_key"),
    "ck_demo_tenant_bindings_demo_tenant_positive": ("check", "demo_tenant_id", "> 0"),
    "ck_demo_tenant_bindings_version_positive": ("check", "version", "> 0"),
    "ck_demo_tenant_bindings_dataset_key_format": ("check", "dataset_key", "a-z0-9"),
    "ck_demo_tenant_bindings_dataset_version_format": ("check", "dataset_version", "a-z0-9"),
    "ck_demo_tenant_bindings_status": ("check", "status", "active", "disabled"),
    "ck_demo_tenant_bindings_disabled_state": ("check", "status", "disabled_at", "is null", "is not null"),
    "ck_demo_tenant_bindings_updated_time": ("check", "updated_at", "bound_at"),
    "ck_demo_tenant_bindings_disabled_time": ("check", "disabled_at", "bound_at"),
    "ck_demo_tenant_bindings_disabled_updater": ("check", "disabled", "updated_by_user_id"),
    "pk_demo_tenant_binding_history": ("primary key", "id"),
    "fk_demo_tenant_binding_history_tenant": ("foreign key", "tenant_id", "references tenants", "on delete restrict"),
    "fk_demo_tenant_binding_history_actor": ("foreign key", "actor_user_id", "references users", "on delete restrict"),
    "uq_demo_tenant_binding_history_tenant_version": ("unique", "tenant_id", "binding_version"),
    "ck_demo_tenant_binding_history_version_positive": ("check", "binding_version", "> 0"),
    "ck_demo_tenant_binding_history_operation": ("check", "operation", "create", "disable", "replace"),
    "ck_demo_tenant_binding_history_before": ("check", "before_snapshot", "binding_version", "jsonb_typeof", "dataset_key", "updated_by_user_id"),
    "ck_demo_tenant_binding_history_after": ("check", "after_snapshot", "binding_version", "jsonb_typeof", "dataset_key", "updated_by_user_id"),
    "ck_demo_tenant_binding_history_reason": ("check", "btrim", "reason"),
    "ck_demo_tenant_binding_history_links": ("check", "tenant_id", "actor_user_id", "updated_by_user_id"),
    "ck_demo_tenant_binding_history_transition": ("check", "operation", "create", "replace", "disable", "active", "disabled"),
}

SEO_DEMO_BINDING_COLUMNS_SQL = text("""
    SELECT c.relname, a.attname, pg_catalog.format_type(a.atttypid, a.atttypmod), a.attnotnull,
           pg_catalog.pg_get_expr(d.adbin, d.adrelid)
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
    JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid
    LEFT JOIN pg_catalog.pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
    WHERE n.nspname='public' AND c.relkind='r'
      AND c.relname IN ('demo_tenant_bindings','demo_tenant_binding_history')
      AND a.attnum > 0 AND NOT a.attisdropped
    ORDER BY c.relname, a.attnum
""")
SEO_DEMO_BINDING_CONSTRAINTS_SQL = text("""
    SELECT c.relname, con.conname, pg_catalog.pg_get_constraintdef(con.oid, true)
    FROM pg_catalog.pg_constraint con
    JOIN pg_catalog.pg_class c ON c.oid=con.conrelid
    JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='public' AND c.relname IN ('demo_tenant_bindings','demo_tenant_binding_history')
    ORDER BY c.relname, con.conname
""")
SEO_DEMO_BINDING_TRIGGER_SQL = text("""
    SELECT c.relname, t.tgname, pg_catalog.pg_get_triggerdef(t.oid, true)
    FROM pg_catalog.pg_trigger t
    JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid
    JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='public' AND c.relname IN ('demo_tenant_bindings','demo_tenant_binding_history')
      AND NOT t.tgisinternal AND t.tgenabled <> 'D'
""")
SEO_DEMO_BINDING_SEQUENCE_SQL = text("""
    SELECT pg_catalog.pg_get_serial_sequence('public.demo_tenant_binding_history', 'id')
""")

SEO_FIXTURE_REGISTRY_COLUMNS = {
    "module_code": ("character varying(3)", True, None),
    "demo_tenant_id": ("bigint", True, None),
    "dataset_key": ("character varying(64)", True, None),
    "dataset_version": ("character varying(40)", True, None),
    "fixture_namespace": ("character varying(128)", True, None),
    "manifest_sha256": ("character(64)", True, None),
    "schema_revision": ("character varying(64)", True, None),
    "loader_name": ("character varying(80)", True, None),
    "loader_version": ("character varying(80)", True, None),
    "row_counts": ("jsonb", True, None),
    "source_summary": ("jsonb", True, None),
    "sealed_at": ("timestamp with time zone", True, None),
    "status": ("character varying(16)", True, None),
}
SEO_FIXTURE_REGISTRY_CONSTRAINTS = {
    "pk_demo_fixture_registry",
    "uq_demo_fixture_registry_manifest",
    "ck_demo_fixture_registry_module",
    "ck_demo_fixture_registry_tenant_positive",
    "ck_demo_fixture_registry_dataset_key_format",
    "ck_demo_fixture_registry_dataset_version_format",
    "ck_demo_fixture_registry_namespace_nonempty",
    "ck_demo_fixture_registry_manifest_sha256",
    "ck_demo_fixture_registry_schema_revision",
    "ck_demo_fixture_registry_loader_name_nonempty",
    "ck_demo_fixture_registry_loader_version_nonempty",
    "ck_demo_fixture_registry_row_counts",
    "ck_demo_fixture_registry_source_summary",
    "ck_demo_fixture_registry_status",
}
SEO_FIXTURE_REGISTRY_CONSTRAINT_RULES = {
    "pk_demo_fixture_registry": ("primary key", "module_code", "demo_tenant_id", "dataset_key", "dataset_version"),
    "uq_demo_fixture_registry_manifest": ("unique", "manifest_sha256"),
    "ck_demo_fixture_registry_module": ("check", "module_code", "sem", "seo", "geo"),
    "ck_demo_fixture_registry_tenant_positive": ("check", "demo_tenant_id", "> 0"),
    "ck_demo_fixture_registry_dataset_key_format": ("check", "dataset_key", "a-z0-9"),
    "ck_demo_fixture_registry_dataset_version_format": ("check", "dataset_version", "a-z0-9"),
    "ck_demo_fixture_registry_namespace_nonempty": ("check", "btrim", "fixture_namespace"),
    "ck_demo_fixture_registry_manifest_sha256": ("check", "manifest_sha256", "0-9a-f", "64"),
    "ck_demo_fixture_registry_schema_revision": ("check", "schema_revision", "0099_demo_fixture_registry"),
    "ck_demo_fixture_registry_loader_name_nonempty": ("check", "btrim", "loader_name"),
    "ck_demo_fixture_registry_loader_version_nonempty": ("check", "btrim", "loader_version"),
    "ck_demo_fixture_registry_row_counts": ("check", "is_nonnegative_integer_object", "row_counts"),
    "ck_demo_fixture_registry_source_summary": ("check", "jsonb_typeof", "source_summary", "object"),
    "ck_demo_fixture_registry_status": ("check", "status", "sealed"),
}
SEO_FIXTURE_REGISTRY_COLUMNS_SQL = text("""
    SELECT a.attname, pg_catalog.format_type(a.atttypid, a.atttypmod), a.attnotnull,
           pg_catalog.pg_get_expr(d.adbin, d.adrelid)
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
    JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid
    LEFT JOIN pg_catalog.pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
    WHERE n.nspname='demo_control' AND c.relname='fixture_registry' AND c.relkind='r'
      AND a.attnum > 0 AND NOT a.attisdropped
    ORDER BY a.attnum
""")
SEO_FIXTURE_REGISTRY_CONSTRAINTS_SQL = text("""
    SELECT con.conname, pg_catalog.pg_get_constraintdef(con.oid, true)
    FROM pg_catalog.pg_constraint con
    JOIN pg_catalog.pg_class c ON c.oid=con.conrelid
    JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='demo_control' AND c.relname='fixture_registry' AND c.relkind='r'
    ORDER BY con.conname
""")
SEO_FIXTURE_REGISTRY_TRIGGER_SQL = text("""
    SELECT t.tgname, pg_catalog.pg_get_triggerdef(t.oid, true)
    FROM pg_catalog.pg_trigger t
    JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid
    JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='demo_control' AND c.relname='fixture_registry' AND c.relkind='r'
      AND NOT t.tgisinternal AND t.tgenabled <> 'D'
    ORDER BY t.tgname
""")
SEO_FIXTURE_REGISTRY_FUNCTION_SQL = text("""
    SELECT p.proname, pg_catalog.pg_get_functiondef(p.oid), p.provolatile::text,
           p.proisstrict, p.proparallel::text
    FROM pg_catalog.pg_proc p
    JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
    WHERE n.nspname='demo_control'
      AND p.proname IN ('is_nonnegative_integer_object','reject_fixture_registry_mutation')
    ORDER BY p.proname, p.oid
""")


def _required_schema_columns():
    from app.models.seo import SeoContentAsset, SeoAiOperation, SeoMetricSnapshot, SeoImageAltReview
    from app.models.seo_cockpit import SeoTask, SeoImageVerification
    from app.models.seo_qa import SeoQuestion, SeoQaFact, SeoQaAnswer, SeoQaPlacement, SeoQaBatch
    from app.models.module_workspace import SeoSite
    models = (SeoSite, SeoContentAsset, SeoAiOperation, SeoMetricSnapshot, SeoImageAltReview,
              SeoTask, SeoImageVerification, SeoQuestion, SeoQaFact, SeoQaAnswer, SeoQaPlacement, SeoQaBatch)
    required = {}
    for model in models:
        for column in model.__table__.columns:
            kind = ('int8' if isinstance(column.type, BigInteger) else 'int2' if isinstance(column.type, SmallInteger)
                    else 'int4' if isinstance(column.type, Integer)
                    else 'jsonb' if isinstance(column.type, JSONB) else None)
            required[(model.__tablename__, column.name)] = kind
    return required


SEO_REQUIRED_COLUMNS = _required_schema_columns()
SEO_SCHEMA_COLUMNS_SQL = text("""
    SELECT requested.name, a.attname, t.typname
    FROM unnest(CAST(:tables AS text[])) AS requested(name)
    JOIN pg_catalog.pg_class c ON c.oid = to_regclass(requested.name)
    JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
    JOIN pg_catalog.pg_type t ON t.oid = a.atttypid
    WHERE c.relkind IN ('r', 'p') AND a.attnum > 0 AND NOT a.attisdropped
""")

SEO_GEO_TICKET_SHAPE_SQL = text("""
    SELECT
        a.attname,
        pg_catalog.format_type(a.atttypid, a.atttypmod),
        a.attnotnull,
        pg_catalog.pg_get_expr(ad.adbin, ad.adrelid),
        a.attidentity::text,
        a.attgenerated::text,
        t.typtype::text,
        CASE WHEN t.typbasetype = 0 THEN NULL ELSE bt.typname END,
        a.attcollation = t.typcollation,
        EXISTS (
            SELECT 1
            FROM pg_catalog.pg_depend dep
            JOIN pg_catalog.pg_class index_class
              ON dep.classid = 'pg_catalog.pg_class'::pg_catalog.regclass
             AND index_class.oid = dep.objid
            JOIN pg_catalog.pg_index i
              ON i.indexrelid = index_class.oid AND i.indrelid = c.oid
            WHERE dep.refclassid = 'pg_catalog.pg_class'::pg_catalog.regclass
              AND dep.refobjid = c.oid AND dep.refobjsubid = a.attnum
        ),
        EXISTS (
            SELECT 1
            FROM pg_catalog.pg_depend dep
            JOIN pg_catalog.pg_constraint con
              ON dep.classid = 'pg_catalog.pg_constraint'::pg_catalog.regclass
             AND con.oid = dep.objid
            WHERE dep.refclassid = 'pg_catalog.pg_class'::pg_catalog.regclass
              AND dep.refobjid = c.oid AND dep.refobjsubid = a.attnum
        )
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
    JOIN pg_catalog.pg_type t ON t.oid = a.atttypid
    LEFT JOIN pg_catalog.pg_type bt ON bt.oid = t.typbasetype
    LEFT JOIN pg_catalog.pg_attrdef ad ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
    WHERE n.nspname = 'public'
      AND c.relname = 'geo_action_tickets'
      AND c.relkind = 'r'
      AND a.attname IN ('owner_name', 'due_date')
      AND a.attnum > 0 AND NOT a.attisdropped
    ORDER BY a.attname
""")


async def _check_seo_structure(conn):
    rows = await conn.execute(SEO_SCHEMA_COLUMNS_SQL,
                              {'tables': sorted({table for table, _ in SEO_REQUIRED_COLUMNS})})
    actual = {(table, column): kind for table, column, kind in rows}
    incompatible = [f'{table}.{column}' for (table, column), kind in SEO_REQUIRED_COLUMNS.items()
                    if (table, column) not in actual or (kind and actual[(table, column)] != kind)]
    if incompatible:
        raise RuntimeError('SEO required columns missing or incompatible: ' + ', '.join(sorted(incompatible)))


async def _check_geo_ticket_adoption(conn):
    rows = await conn.execute(SEO_GEO_TICKET_SHAPE_SQL)
    actual = {}
    for row in rows:
        name, *shape = row
        actual[name] = tuple(shape)
    expected = {name: shape + (False, False) for name, shape in SEO_GEO_TICKET_SHAPE.items()}
    if actual != expected:
        raise RuntimeError(
            "0095 GEO ticket assignment columns missing or incompatible: "
            f"found {sorted(actual)}"
        )


async def _check_demo_binding_structure(conn, *, require_current_truncate: bool = False):
    column_rows = await conn.execute(SEO_DEMO_BINDING_COLUMNS_SQL)
    columns = {table: {} for table in SEO_DEMO_BINDING_COLUMNS}
    defaults = {}
    for table, name, kind, not_null, default in column_rows:
        if table in columns:
            columns[table][name] = (kind, not_null)
            if default is not None:
                defaults[(table, name)] = " ".join(default.lower().split())
    constraint_rows = await conn.execute(SEO_DEMO_BINDING_CONSTRAINTS_SQL)
    constraints = {table: set() for table in SEO_DEMO_BINDING_CONSTRAINTS}
    definitions = {}
    for table, name, definition in constraint_rows:
        if table in constraints:
            constraints[table].add(name)
            definitions[name] = " ".join(definition.lower().replace("public.", "").split())
    trigger_rows = await conn.execute(SEO_DEMO_BINDING_TRIGGER_SQL)
    triggers = {(table, name): " ".join(definition.lower().replace("public.", "").split()) for table, name, definition in trigger_rows}
    definition_ok = all(
        name in definitions and all(fragment in definitions[name] for fragment in fragments)
        for name, fragments in SEO_DEMO_BINDING_CONSTRAINT_RULES.items()
    )
    expected_triggers = {
        ("demo_tenant_binding_history", "trg_demo_tenant_binding_history_append_only"): ("before", "update", "delete", "for each row", "reject_demo_tenant_binding_history_mutation"),
        ("demo_tenant_binding_history", "trg_demo_tenant_binding_history_no_truncate"): ("before", "truncate", "for each statement", "reject_demo_tenant_binding_history_mutation"),
        ("demo_tenant_bindings", "trg_demo_tenant_bindings_no_delete"): ("before", "delete", "for each row", "reject_demo_tenant_binding_delete"),
    }
    if require_current_truncate:
        expected_triggers[("demo_tenant_bindings", "trg_demo_tenant_bindings_no_truncate")] = (
            "before", "truncate", "for each statement", "reject_demo_tenant_binding_delete"
        )
    trigger_ok = set(triggers) == set(expected_triggers) and all(
        all(fragment in triggers[key] for fragment in fragments) for key, fragments in expected_triggers.items()
    )
    sequence_rows = await conn.execute(SEO_DEMO_BINDING_SEQUENCE_SQL)
    sequence = next(iter(sequence_rows.scalars()), None)
    sequence_ok = sequence is not None and sequence.removeprefix("public.") == "demo_tenant_binding_history_id_seq"
    if (columns != SEO_DEMO_BINDING_COLUMNS
            or constraints != SEO_DEMO_BINDING_CONSTRAINTS
            or defaults != SEO_DEMO_BINDING_DEFAULTS
            or not definition_ok or not trigger_ok or not sequence_ok):
        raise RuntimeError(
            "0097 demo binding control-plane objects missing or incompatible: "
            f"column_keys={{{', '.join(f'{table}:{sorted(values)}' for table, values in columns.items())}}}; "
            f"constraint_names={{{', '.join(f'{table}:{sorted(values)}' for table, values in constraints.items())}}}; "
            f"default_keys={sorted(defaults)}; definition_ok={definition_ok}; "
            f"trigger_names={sorted(triggers)}; trigger_ok={trigger_ok}; sequence_ok={sequence_ok}"
        )


async def _check_fixture_registry_structure(conn):
    column_rows = list(await conn.execute(SEO_FIXTURE_REGISTRY_COLUMNS_SQL))
    columns = {
        name: (kind, not_null, None if default is None else " ".join(default.lower().split()))
        for name, kind, not_null, default in column_rows
    }
    constraint_rows = list(await conn.execute(SEO_FIXTURE_REGISTRY_CONSTRAINTS_SQL))
    constraints = {name for name, _definition in constraint_rows}
    definitions = {
        name: " ".join(definition.lower().replace("demo_control.", "").split())
        for name, definition in constraint_rows
    }
    constraint_ok = all(
        name in definitions and all(fragment in definitions[name] for fragment in fragments)
        for name, fragments in SEO_FIXTURE_REGISTRY_CONSTRAINT_RULES.items()
    )

    trigger_rows = list(await conn.execute(SEO_FIXTURE_REGISTRY_TRIGGER_SQL))
    triggers = {
        name: " ".join(definition.lower().replace("demo_control.", "").split())
        for name, definition in trigger_rows
    }
    expected_triggers = {
        "trg_fixture_registry_no_update": ("before update", "for each row", "reject_fixture_registry_mutation"),
        "trg_fixture_registry_no_delete": ("before delete", "for each row", "reject_fixture_registry_mutation"),
        "trg_fixture_registry_no_truncate": ("before truncate", "for each statement", "reject_fixture_registry_mutation"),
    }
    trigger_ok = len(trigger_rows) == len(expected_triggers) and set(triggers) == set(expected_triggers) and all(
        all(fragment in triggers[name] for fragment in fragments)
        for name, fragments in expected_triggers.items()
    )

    function_rows = list(await conn.execute(SEO_FIXTURE_REGISTRY_FUNCTION_SQL))
    functions = {
        name: (" ".join(definition.lower().split()), volatility, strict, parallel)
        for name, definition, volatility, strict, parallel in function_rows
    }
    validator = functions.get("is_nonnegative_integer_object")
    rejector = functions.get("reject_fixture_registry_mutation")
    function_ok = (
        len(function_rows) == 2
        and validator is not None
        and validator[1:] == ("i", True, "s")
        and all(fragment in validator[0] for fragment in (
            "returns boolean", "language sql", "jsonb_typeof", "jsonb_each",
            "not exists", "0-9", "value <> '{}'::jsonb",
        ))
        and rejector is not None
        and rejector[1] == "v"
        and all(fragment in rejector[0] for fragment in (
            "returns trigger", "language plpgsql", "raise exception",
            "demo_control.fixture_registry is immutable",
        ))
    )

    if (columns != SEO_FIXTURE_REGISTRY_COLUMNS
            or constraints != SEO_FIXTURE_REGISTRY_CONSTRAINTS
            or not constraint_ok or not trigger_ok or not function_ok):
        raise RuntimeError(
            "0099 demo fixture registry objects missing or incompatible: "
            f"column_keys={sorted(columns)}; constraint_names={sorted(constraints)}; "
            f"constraint_ok={constraint_ok}; trigger_names={sorted(triggers)}; "
            f"trigger_ok={trigger_ok}; function_names={sorted(functions)}; function_ok={function_ok}"
        )



@asynccontextmanager
async def lifespan(_app: FastAPI):
    scheduler_started = seo_scheduler_may_start(settings)
    if scheduler_started:
        start_seo_scheduler()
    try:
        yield
    finally:
        if scheduler_started:
            shutdown_seo_scheduler()


app = FastAPI(title="Growth Sniper SEO API", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def enforce_demo_runtime_read_only(request: Request, call_next):
    """Block mutations and every outbound-capable action before route dispatch."""
    if not demo_request_is_allowed(settings, request.method, request.url.path):
        return JSONResponse(
            status_code=403,
            content={
                "detail": "演示环境仅允许只读查询；抓取、生成、连接测试、发布和数据修改均已禁用",
                "code": "seo_demo_runtime_read_only",
            },
        )
    return await call_next(request)


@app.middleware("http")
async def keep_demo_tenant_mapping_private(request: Request, call_next):
    """Keep isolated tenant ids out of otherwise transparent JSON responses."""
    response = await call_next(request)
    decision = getattr(request.state, "seo_data_source_decision", None)
    if (
        not isinstance(decision, SeoDataSourceDecision)
        or decision.source != "demo"
        or decision.binding is None
        or "application/json" not in response.headers.get("content-type", "")
    ):
        return response
    body = b"".join([chunk async for chunk in response.body_iterator])
    if not body:
        return response
    try:
        payload = json.loads(body)
    except (UnicodeError, json.JSONDecodeError):
        return Response(
            body,
            status_code=response.status_code,
            headers=dict(response.headers),
            background=response.background,
        )
    rewritten = json.dumps(
        hide_demo_tenant_ids(payload, decision.binding),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    headers = dict(response.headers)
    headers.pop("content-length", None)
    return Response(
        rewritten,
        status_code=response.status_code,
        headers=headers,
        media_type="application/json",
        background=response.background,
    )


register_infra_handlers(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(seo_router)
app.include_router(seo_sites_router)


@app.get("/health/seo")
async def seo_health(response: Response) -> dict:
    """Fail closed when the database is unreachable or its schema is incompatible."""
    db_status = "ok"
    db_error: str | None = None
    schema_status = "unknown"
    schema_revision: str | None = None
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            revisions = list(
                (
                    await conn.execute(
                        text("SELECT version_num FROM alembic_version ORDER BY version_num")
                    )
                ).scalars()
            )
            schema_revision = ",".join(revisions) or None
            if len(revisions) != 1 or revisions[0] not in SEO_COMPATIBLE_SCHEMA_REVISIONS:
                schema_status = "error"
                raise RuntimeError(
                    "SEO database schema mismatch: "
                    f"expected {SEO_REQUIRED_SCHEMA_REVISION} or an explicitly reviewed compatible revision, "
                    f"found {schema_revision or 'none'}"
                )
            schema_status = "error"
            await _check_seo_structure(conn)
            if revisions[0] in SEO_GEO_TICKET_REQUIRED_REVISIONS:
                await _check_geo_ticket_adoption(conn)
            if revisions[0] in {"0097_demo_tenant_bindings", "0098_demo_binding_no_truncate", "0099_demo_fixture_registry"}:
                await _check_demo_binding_structure(
                    conn, require_current_truncate=revisions[0] in {"0098_demo_binding_no_truncate", "0099_demo_fixture_registry"}
                )
            if revisions[0] == "0099_demo_fixture_registry":
                await _check_fixture_registry_structure(conn)
            schema_status = "ok"
    except Exception as exc:  # noqa: BLE001 - health must report infra failure
        db_status = "error"
        db_error = str(exc)
        response.status_code = 503
    return {
        "service": "seo-api",
        "env": settings.app_env,
        "db": db_status,
        "db_error": db_error,
        "schema": schema_status,
        "schema_revision": schema_revision,
        "required_schema_revision": SEO_REQUIRED_SCHEMA_REVISION,
        "compatible_schema_revisions": sorted(SEO_COMPATIBLE_SCHEMA_REVISIONS),
    }
