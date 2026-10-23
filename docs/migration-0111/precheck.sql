-- 待审核，不自动执行。只读前检；任何 false/NULL 使最后断言失败。
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
('single_0110_version',(SELECT count(*)=1 AND min(version_num)='0110_distribution_inbox' FROM public.alembic_version)),
('settings_is_table',EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relname='geo_visibility_patrol_settings' AND c.relkind='r')),
('runs_is_table',EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relname='geo_visibility_patrol_runs' AND c.relkind='r')),
('all_new_columns_absent',NOT EXISTS(SELECT 1 FROM expected_columns e JOIN information_schema.columns c ON c.table_schema='public' AND c.table_name=e.table_name AND c.column_name=e.column_name)),
('all_new_objects_absent',NOT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relname IN ('geo_visibility_patrol_setting_events','geo_visibility_patrol_daily_budget','geo_visibility_patrol_setting_events_id_seq','geo_visibility_patrol_setting_events_pkey','geo_visibility_patrol_daily_budget_pkey','ix_geo_patrol_events_tenant_id','uq_geo_patrol_tenant_auto_day')))
)
SELECT name,ok,1/CASE WHEN coalesce(ok,false) THEN 1 ELSE 0 END AS assert_pass FROM checks;
SELECT 'settings_rows' AS name,count(*) FROM public.geo_visibility_patrol_settings
UNION ALL SELECT 'runs_rows',count(*) FROM public.geo_visibility_patrol_runs;
COMMIT;
