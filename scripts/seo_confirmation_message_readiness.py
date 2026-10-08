"""Offline generator of read-only psql checks; never connects or loads app settings.

Reuse the canonical 0105/0106 Alembic definitions as the object inventory.
The emitted SQL is an acceptance check, never a migration or grant script.
"""
import argparse
import importlib.util
import json
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

ROOT = Path(__file__).resolve().parents[1]
REVISIONS = ("0104_seo_page_ai_tdk", "0105_seo_content_confirmations", "0106_seo_content_messages")
SOURCES = ("20261007_0105_seo_content_confirmations.py", "20261008_0106_seo_content_messages.py")


class Inventory:
    def __init__(self):
        self.metadata = sa.MetaData()
        self.tables = {}
        self.indexes = {}
        self.sql = []

    def create_table(self, name, *columns):
        table = sa.Table(name, self.metadata, *columns)
        self.tables[name] = table
        return table

    def create_index(self, name, table, columns):
        self.indexes[name] = (table, columns)

    def execute(self, sql):
        self.sql.append(sql)


def inventory(level):
    result = Inventory()
    for index, name in enumerate(SOURCES[:level]):
        path = ROOT / "migrations" / "versions" / name
        spec = importlib.util.spec_from_file_location("readiness_" + str(index), path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if module.revision != REVISIONS[index + 1] or module.down_revision != REVISIONS[index]:
            raise ValueError("Reviewed revision chain changed")
        module.op = result  # Collector only: no Alembic connection/environment is loaded.
        module.upgrade()
    return result


def literal(value):
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def sequence_names(inv):
    return [name + "_id_seq" for name, table in inv.tables.items() if len(table.primary_key.columns) == 1]


def render(revision, database, runtime_role, migration_role):
    if revision not in REVISIONS:
        raise ValueError("Only reviewed 0104/0105/0106 snapshots are supported")
    level = REVISIONS.index(revision)
    inv, complete = inventory(level), inventory(2)
    qrole, qmigration = literal(runtime_role), literal(migration_role)
    checks = []
    def check(name, expression): checks.append((name, expression))
    check("database_identity", f"current_database()={literal(database)}")
    check("migration_identity", f"current_user={qmigration}")
    check("public_search_path", "current_schemas(false)=ARRAY['public']::name[]")
    check("single_expected_revision", f"(SELECT array_agg(version_num::text) FROM public.alembic_version)=ARRAY[{literal(revision)}]")
    check("runtime_role_is_separate", f"{qrole}<>{qmigration} AND EXISTS(SELECT 1 FROM pg_roles WHERE rolname={qrole} AND NOT (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls))")
    check("runtime_database_connect", f"has_database_privilege({qrole},current_database(),'CONNECT')")
    check("migration_schema_rights", f"has_schema_privilege({qmigration},'public','USAGE') AND has_schema_privilege({qmigration},'public','CREATE')")
    check("runtime_no_schema_create", f"has_schema_privilege({qrole},'public','USAGE') AND NOT has_schema_privilege({qrole},'public','CREATE')")
    check("migration_version_rights", f"has_table_privilege({qmigration},'public.alembic_version','SELECT') AND has_table_privilege({qmigration},'public.alembic_version','UPDATE')")
    check("migration_role_is_bounded", f"EXISTS(SELECT 1 FROM pg_roles WHERE rolname={qmigration} AND NOT (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls))")
    check("migration_timeouts_bounded", ":'migration_timeouts_bounded'::boolean")
    for name in ("tenants", "users", "seo_sites", "seo_content_assets"):
        check("parent_" + name, f"to_regclass('public.{name}') IS NOT NULL AND has_table_privilege({qmigration},to_regclass('public.{name}'),'REFERENCES')")
    # Existing authorization reads and row locks are required in addition to new-table grants.
    for name in ("users", "roles", "tenants", "tenant_modules", "seo_sites", "seo_content_assets", "alembic_version"):
        check("runtime_read_" + name, f"has_table_privilege({qrole},to_regclass('public.{name}'),'SELECT')")
    for name in ("users", "seo_content_assets"):
        check("runtime_lock_" + name, f"has_any_column_privilege({qrole},to_regclass('public.{name}'),'UPDATE')")
    expected_relations = set(complete.tables) | set(sequence_names(complete)) | set(complete.indexes)
    for name, table in complete.tables.items():
        expected_relations.add(name + "_pkey")
        expected_relations.update(c.name for c in table.constraints if isinstance(c, sa.UniqueConstraint))
    present = set(inv.tables) | set(sequence_names(inv)) | set(inv.indexes)
    for name, table in inv.tables.items():
        present.add(name + "_pkey")
        present.update(c.name for c in table.constraints if isinstance(c, sa.UniqueConstraint))
    for name in sorted(expected_relations - present):
        check("absent_future_" + name, f"to_regclass('public.{name}') IS NULL")
    for name in sorted(present):
        check("present_" + name, f"to_regclass('public.{name}') IS NOT NULL")
    for name, table in inv.tables.items():
        check("table_owner_" + name, f"EXISTS(SELECT 1 FROM pg_class WHERE oid=to_regclass('public.{name}') AND relkind='r' AND NOT relrowsecurity AND pg_get_userbyid(relowner)={qmigration} AND NOT pg_has_role({qrole},relowner,'USAGE'))")
        check("column_count_" + name, f"(SELECT count(*) FROM pg_attribute WHERE attrelid=to_regclass('public.{name}') AND attnum>0 AND NOT attisdropped)={len(table.columns)}")
        check("constraint_count_" + name, f"(SELECT count(*) FROM pg_constraint WHERE conrelid=to_regclass('public.{name}'))={len(table.constraints)}")
        for column in table.columns:
            typ = column.type.compile(dialect=postgresql.dialect()).lower().replace("varchar", "character varying")
            if typ == "timestamp": typ = "timestamp without time zone"
            default = str(column.server_default.arg).lower() if column.server_default is not None else None
            if column.primary_key and len(table.primary_key.columns) == 1:
                default_check = f"pg_get_serial_sequence('public.{name}',{literal(column.name)})='public.{name}_id_seq'"
            elif default is None:
                default_check = "d.oid IS NULL"
            elif default == "0":
                default_check = "pg_get_expr(d.adbin,d.adrelid) IN ('0', '''0''::bigint')"
            else:
                default_check = f"pg_get_expr(d.adbin,d.adrelid)={literal(default)}"
            check("column_" + name + "." + column.name,
                  f"EXISTS(SELECT 1 FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum WHERE a.attrelid=to_regclass('public.{name}') AND a.attname={literal(column.name)} AND NOT a.attisdropped AND format_type(a.atttypid,a.atttypmod)={literal(typ)} AND a.attnotnull={'false' if column.nullable else 'true'} AND ({default_check}))")
        for constraint in table.constraints:
            if isinstance(constraint, (sa.PrimaryKeyConstraint, sa.UniqueConstraint)):
                cname = constraint.name or name + "_pkey"
                columns = ",".join(c.name for c in constraint.columns)
                kind = "p" if isinstance(constraint, sa.PrimaryKeyConstraint) else "u"
                check("key_" + cname, f"EXISTS(SELECT 1 FROM pg_constraint k JOIN pg_index i ON i.indexrelid=k.conindid WHERE k.conrelid=to_regclass('public.{name}') AND k.conname={literal(cname)} AND k.contype='{kind}' AND k.convalidated AND NOT k.condeferrable AND i.indisvalid AND i.indisready AND (SELECT string_agg(a.attname,',' ORDER BY u.ord) FROM unnest(k.conkey) WITH ORDINALITY u(attnum,ord) JOIN pg_attribute a ON a.attrelid=k.conrelid AND a.attnum=u.attnum)={literal(columns)})")
            elif isinstance(constraint, sa.CheckConstraint):
                check("check_" + constraint.name, f"EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid=to_regclass('public.{name}') AND conname={literal(constraint.name)} AND contype='c' AND convalidated)")
            elif isinstance(constraint, sa.ForeignKeyConstraint):
                local = ",".join(e.parent.name for e in constraint.elements)
                remote = [e.target_fullname.split(".") for e in constraint.elements]
                action = {"RESTRICT":"r", "CASCADE":"c", "SET NULL":"n"}[constraint.ondelete]
                check("fk_" + name + "." + local, f"EXISTS(SELECT 1 FROM pg_constraint k WHERE conrelid=to_regclass('public.{name}') AND contype='f' AND confrelid=to_regclass('public.{remote[0][-2]}') AND confdeltype='{action}' AND confupdtype='a' AND convalidated AND NOT condeferrable AND (SELECT string_agg(a.attname,',' ORDER BY u.ord) FROM unnest(k.conkey) WITH ORDINALITY u(attnum,ord) JOIN pg_attribute a ON a.attrelid=k.conrelid AND a.attnum=u.attnum)={literal(local)} AND (SELECT string_agg(a.attname,',' ORDER BY u.ord) FROM unnest(k.confkey) WITH ORDINALITY u(attnum,ord) JOIN pg_attribute a ON a.attrelid=k.confrelid AND a.attnum=u.attnum)={literal(','.join(r[-1] for r in remote))})")
        check("runtime_read_insert_" + name, f"has_table_privilege({qrole},to_regclass('public.{name}'),'SELECT') AND has_table_privilege({qrole},to_regclass('public.{name}'),'INSERT')")
        check("runtime_no_delete_" + name, f"NOT has_table_privilege({qrole},to_regclass('public.{name}'),'DELETE') AND NOT has_table_privilege({qrole},to_regclass('public.{name}'),'TRUNCATE') AND NOT has_table_privilege({qrole},to_regclass('public.{name}'),'TRIGGER')")
        if name in ("seo_content_confirmations", "seo_content_messages"):
            check("runtime_append_only_" + name, f"NOT has_any_column_privilege({qrole},to_regclass('public.{name}'),'UPDATE')")
        else:
            columns = {"seo_site_advisor_assignments":["active","assigned_by","updated_at"],
                       "seo_content_conversations":["id"], "seo_conversation_participants":["last_read_message_id"]}[name]
            for col in columns:
                check("runtime_update_"+name+"."+col, f"has_column_privilege({qrole},'public.{name}',{literal(col)},'UPDATE')")
    for name in sequence_names(inv):
        check("sequence_" + name, f"EXISTS(SELECT 1 FROM pg_class WHERE oid=to_regclass('public.{name}') AND relkind='S' AND pg_get_userbyid(relowner)={qmigration}) AND has_sequence_privilege({qrole},to_regclass('public.{name}'),'USAGE') AND NOT has_sequence_privilege({qrole},to_regclass('public.{name}'),'UPDATE')")
        check("sequence_shape_" + name, f"EXISTS(SELECT 1 FROM pg_sequence WHERE seqrelid=to_regclass('public.{name}') AND seqtypid='bigint'::regtype AND seqincrement=1 AND seqstart=1 AND NOT seqcycle)")
    for name, (table, columns) in inv.indexes.items():
        check("index_" + name, f"EXISTS(SELECT 1 FROM pg_index i WHERE i.indexrelid=to_regclass('public.{name}') AND i.indrelid=to_regclass('public.{table}') AND i.indisvalid AND i.indisready AND NOT i.indisunique AND i.indpred IS NULL AND i.indexprs IS NULL AND (SELECT string_agg(a.attname,',' ORDER BY u.ord) FROM unnest(i.indkey) WITH ORDINALITY u(attnum,ord) JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=u.attnum)={literal(','.join(columns))})")
    if level < 2:
        check("future_function_absent", "NOT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.proname='seo_reject_message_mutation')")
    else:
        body = " ".join(inv.sql[0].split("$$")[1].split())
        check("message_trigger_function", f"EXISTS(SELECT 1 FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('public.seo_reject_message_mutation()') AND l.lanname='plpgsql' AND p.prorettype='trigger'::regtype AND NOT p.prosecdef AND p.proconfig IS NULL AND pg_get_userbyid(p.proowner)={qmigration} AND btrim(regexp_replace(p.prosrc,'\\s+',' ','g'))={literal(body)})")
        for name, bits in (("trg_seo_messages_append_only",27),("trg_seo_messages_no_truncate",34)):
            check(name, f"EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid=to_regclass('public.seo_content_messages') AND tgname='{name}' AND NOT tgisinternal AND tgenabled='O' AND tgtype={bits} AND tgfoid=to_regprocedure('public.seo_reject_message_mutation()') AND tgqual IS NULL)")
    # One materialized snapshot of catalog checks, fail closed without DDL/DO/functions.
    union = "\nUNION ALL\n".join(f"SELECT {literal(name)} AS check_name, COALESCE(({sql}),false) AS ok" for name,sql in checks)
    tables = ",".join(literal(x) for x in complete.tables)
    counts = "\nUNION ALL\n".join(f"SELECT {literal(name)} AS table_name,count(*) AS row_count FROM public.{name}" for name in inv.tables)
    if counts:
        counts += ";\n"
    return f"""-- Generated offline from canonical 0105/0106 migrations. No migration/grant/seed commands.
\\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL standard_conforming_strings=on;
SELECT current_setting('lock_timeout') AS migration_lock_timeout,
       current_setting('statement_timeout') AS migration_statement_timeout;
SELECT (SELECT setting::bigint BETWEEN 1 AND 10000 FROM pg_settings WHERE name='lock_timeout')
   AND (SELECT setting::bigint BETWEEN 1 AND 300000 FROM pg_settings WHERE name='statement_timeout') AS migration_timeouts_bounded \\gset
SET LOCAL statement_timeout='15s';
SET LOCAL lock_timeout='3s';
SELECT current_database(),current_user,current_setting('transaction_read_only') AS read_only,
       current_setting('search_path') AS search_path,version();
SELECT version_num FROM public.alembic_version ORDER BY version_num;
WITH checks AS ({union})
SELECT coalesce(bool_and(ok),false) AS readiness_ok,
       coalesce(jsonb_agg(check_name) FILTER (WHERE NOT ok),'[]'::jsonb)::text AS failed_checks
FROM checks \\gset
\\echo readiness_ok=:readiness_ok failed_checks=:failed_checks
-- CHECK expressions and all defaults are printed for DBA comparison with reviewed source.
SELECT c.relname,k.conname,k.contype::text,k.convalidated,pg_get_constraintdef(k.oid)
FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
WHERE c.relnamespace='public'::regnamespace AND c.relname IN ({tables}) ORDER BY 1,2;
SELECT c.relname,a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,pg_get_expr(d.adbin,d.adrelid)
FROM pg_class c JOIN pg_attribute a ON a.attrelid=c.oid
LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
WHERE c.relnamespace='public'::regnamespace AND c.relname IN ({tables}) AND a.attnum>0 AND NOT a.attisdropped ORDER BY 1,a.attnum;
SELECT schemaname,tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='public' AND tablename IN ({tables}) ORDER BY 2,3;
{counts}
-- Defaults missing means off. Existing opt-ins/work in flight require separate authorization review.
SELECT count(*) AS sites_with_any_new_opt_in FROM public.seo_sites
WHERE site_settings->'seo_service_plan' @> '{{"content_cycle_enabled":true}}'::jsonb
   OR site_settings->'seo_service_plan' @> '{{"content_ai_enabled":true}}'::jsonb
   OR site_settings->'seo_service_plan' @> '{{"website_cycle_enabled":true}}'::jsonb
   OR site_settings->'seo_service_plan' @> '{{"monitoring_cycle_enabled":true}}'::jsonb
   OR site_settings->'seo_service_plan' @> '{{"report_cycle_enabled":true}}'::jsonb;
SELECT action_type,status,count(*) FROM public.seo_tasks WHERE status IN ('open','in_progress')
 AND action_type IN ('content_delivery','site_diagnosis','ranking_followup','monthly_report') GROUP BY 1,2 ORDER BY 1,2;
SELECT relation::regclass,mode,granted,pid FROM pg_locks WHERE relation IN
 (to_regclass('public.alembic_version'),to_regclass('public.users'),to_regclass('public.tenants'),to_regclass('public.seo_sites'),to_regclass('public.seo_content_assets')) ORDER BY relation,pid;
\\if :readiness_ok
COMMIT;
\\else
-- ON_ERROR_STOP terminates; connection closure rolls back this read-only transaction.
SELECT 1/0 AS readiness_failed;
\\endif
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", choices=REVISIONS, required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--runtime-role", required=True)
    parser.add_argument("--migration-role", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sql = render(args.revision,args.database,args.runtime_role,args.migration_role)
    # Never overwrite acceptance evidence or another operator's output.
    with args.output.open("x",encoding="utf-8") as target:
        target.write(sql)
    print(json.dumps({"output":str(args.output),"revision":args.revision,"connected":False}))


if __name__ == "__main__":
    main()
