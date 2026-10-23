-- 待审核，只读后检；仅供迁移刚结束、功能尚未启用时使用。
\set ON_ERROR_STOP on
BEGIN READ ONLY;
SET LOCAL search_path = public;
WITH expected_columns(table_name,column_name) AS (VALUES ('geo_visibility_patrol_settings', 'schedule_mode'),
('geo_visibility_patrol_settings', 'self_service_enabled'),
('geo_visibility_patrol_settings', 'owner_user_id'),
('geo_visibility_patrol_settings', 'owner_grant_id'),
('geo_visibility_patrol_settings', 'owner_scope'),
('geo_visibility_patrol_settings', 'revision'),
('geo_visibility_patrol_settings', 'admin_locked'),
('geo_visibility_patrol_settings', 'lock_reason'),
('geo_visibility_patrol_settings', 'opened_at'),
('geo_visibility_patrol_settings', 'opened_by'),
('geo_visibility_patrol_settings', 'last_changed_by'),
('geo_visibility_patrol_settings', 'last_changed_at'),
('geo_visibility_patrol_settings', 'blocked_reason'),
('geo_visibility_patrol_settings', 'manual_daily_limit'),
('geo_visibility_patrol_settings', 'manual_limit_revision'),
('geo_visibility_patrol_runs','auto_day'),('geo_visibility_patrol_runs','last_progress_at')),
checks(name,ok) AS (
VALUES ('expected_migrator',current_user='sem_app'),
('expected_database',current_database()='sem_prod'),
('public_schema',current_schema()='public'),
('single_0111_version',(SELECT count(*)=1 AND min(version_num)='0111_geo_autopatrol' FROM public.alembic_version)),
('all_new_columns_present',(SELECT count(*)=17 FROM expected_columns e JOIN information_schema.columns c ON c.table_schema='public' AND c.table_name=e.table_name AND c.column_name=e.column_name)),
('both_new_tables_ordinary',(SELECT count(*)=2 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='r' AND c.relname IN ('geo_visibility_patrol_setting_events','geo_visibility_patrol_daily_budget'))),
('auto_day_unique_partial',EXISTS(SELECT 1 FROM pg_index i WHERE i.indexrelid=to_regclass('public.uq_geo_patrol_tenant_auto_day') AND i.indrelid='public.geo_visibility_patrol_runs'::regclass AND i.indisunique AND i.indisvalid AND i.indisready AND pg_get_expr(i.indpred,i.indrelid)='(auto_day IS NOT NULL)' AND (SELECT array_agg(a.attname::text ORDER BY k.n) FROM unnest(i.indkey) WITH ORDINALITY k(attnum,n) JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum)=ARRAY['tenant_id','auto_day'])),
('events_index',EXISTS(SELECT 1 FROM pg_indexes WHERE schemaname='public' AND tablename='geo_visibility_patrol_setting_events' AND indexname='ix_geo_patrol_events_tenant_id' AND indexdef LIKE '%(tenant_id, id)')),
('both_primary_keys',(SELECT count(*)=2 FROM pg_constraint WHERE contype='p' AND conrelid IN ('public.geo_visibility_patrol_setting_events'::regclass,'public.geo_visibility_patrol_daily_budget'::regclass))),
('runtime_events_dml',has_table_privilege('sem_runtime','public.geo_visibility_patrol_setting_events','SELECT') AND has_table_privilege('sem_runtime','public.geo_visibility_patrol_setting_events','INSERT') AND has_table_privilege('sem_runtime','public.geo_visibility_patrol_setting_events','UPDATE') AND has_table_privilege('sem_runtime','public.geo_visibility_patrol_setting_events','DELETE')),
('runtime_budget_dml',has_table_privilege('sem_runtime','public.geo_visibility_patrol_daily_budget','SELECT') AND has_table_privilege('sem_runtime','public.geo_visibility_patrol_daily_budget','INSERT') AND has_table_privilege('sem_runtime','public.geo_visibility_patrol_daily_budget','UPDATE') AND has_table_privilege('sem_runtime','public.geo_visibility_patrol_daily_budget','DELETE')),
('runtime_event_sequence',has_sequence_privilege('sem_runtime',pg_get_serial_sequence('public.geo_visibility_patrol_setting_events','id'),'USAGE') AND has_sequence_privilege('sem_runtime',pg_get_serial_sequence('public.geo_visibility_patrol_setting_events','id'),'SELECT') AND has_sequence_privilege('sem_runtime',pg_get_serial_sequence('public.geo_visibility_patrol_setting_events','id'),'UPDATE')),
('legacy_settings_preserved',NOT EXISTS(SELECT 1 FROM public.geo_visibility_patrol_settings WHERE schedule_mode IS DISTINCT FROM 'legacy' OR self_service_enabled IS DISTINCT FROM false)),
('historical_claims_not_inferred',NOT EXISTS(SELECT 1 FROM public.geo_visibility_patrol_runs WHERE auto_day IS NOT NULL))
)
SELECT name,ok,1/CASE WHEN coalesce(ok,false) THEN 1 ELSE 0 END AS assert_pass FROM checks;
COMMIT;
