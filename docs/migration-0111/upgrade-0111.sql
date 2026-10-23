BEGIN;

-- Running upgrade 0110_distribution_inbox -> 0111_geo_autopatrol

DO $guard$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname=current_schema() AND c.relname='geo_visibility_patrol_settings' AND c.relkind='r')
     OR NOT EXISTS (SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname=current_schema() AND c.relname='geo_visibility_patrol_runs' AND c.relkind='r') THEN
    RAISE EXCEPTION '0111 requires ordinary settings and runs tables';
  END IF;
END $guard$;

LOCK TABLE geo_visibility_patrol_settings, geo_visibility_patrol_runs IN ACCESS EXCLUSIVE MODE;

DO $guard$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_catalog.pg_attribute a
    JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
    JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname=current_schema() AND a.attnum>0 AND NOT a.attisdropped
      AND ((c.relname='geo_visibility_patrol_settings' AND a.attname IN ('schedule_mode','self_service_enabled','owner_user_id','owner_grant_id','owner_scope','revision','admin_locked','lock_reason','opened_at','opened_by','last_changed_by','last_changed_at','blocked_reason','manual_daily_limit','manual_limit_revision'))
        OR (c.relname='geo_visibility_patrol_runs' AND a.attname IN ('auto_day','last_progress_at')))
  ) OR EXISTS (
    SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname=current_schema() AND c.relname IN (
      'geo_visibility_patrol_setting_events','geo_visibility_patrol_daily_budget',
      'geo_visibility_patrol_setting_events_id_seq','geo_visibility_patrol_setting_events_pkey',
      'geo_visibility_patrol_daily_budget_pkey','ix_geo_patrol_events_tenant_id','uq_geo_patrol_tenant_auto_day')
  ) THEN
    RAISE EXCEPTION '0111 refuses existing or partial autopatrol objects; no automatic adoption';
  END IF;
END $guard$;

ALTER TABLE geo_visibility_patrol_settings ADD COLUMN schedule_mode VARCHAR(32) DEFAULT 'legacy' NOT NULL;

ALTER TABLE geo_visibility_patrol_settings ADD COLUMN self_service_enabled BOOLEAN DEFAULT false NOT NULL;

ALTER TABLE geo_visibility_patrol_settings ADD COLUMN owner_user_id BIGINT;

ALTER TABLE geo_visibility_patrol_settings ADD COLUMN owner_grant_id BIGINT;

ALTER TABLE geo_visibility_patrol_settings ADD COLUMN owner_scope JSONB;

ALTER TABLE geo_visibility_patrol_settings ADD COLUMN revision INTEGER DEFAULT '0' NOT NULL;

ALTER TABLE geo_visibility_patrol_settings ADD COLUMN admin_locked BOOLEAN DEFAULT false NOT NULL;

ALTER TABLE geo_visibility_patrol_settings ADD COLUMN lock_reason VARCHAR(500);

ALTER TABLE geo_visibility_patrol_settings ADD COLUMN opened_at TIMESTAMP WITHOUT TIME ZONE;

ALTER TABLE geo_visibility_patrol_settings ADD COLUMN opened_by BIGINT;

ALTER TABLE geo_visibility_patrol_settings ADD COLUMN last_changed_by BIGINT;

ALTER TABLE geo_visibility_patrol_settings ADD COLUMN last_changed_at TIMESTAMP WITHOUT TIME ZONE;

ALTER TABLE geo_visibility_patrol_settings ADD COLUMN blocked_reason VARCHAR(64);

ALTER TABLE geo_visibility_patrol_settings ADD COLUMN manual_daily_limit INTEGER DEFAULT '10' NOT NULL;

ALTER TABLE geo_visibility_patrol_settings ADD COLUMN manual_limit_revision INTEGER DEFAULT '0' NOT NULL;

ALTER TABLE geo_visibility_patrol_runs ADD COLUMN auto_day DATE;

ALTER TABLE geo_visibility_patrol_runs ADD COLUMN last_progress_at TIMESTAMP WITHOUT TIME ZONE;

CREATE UNIQUE INDEX uq_geo_patrol_tenant_auto_day ON geo_visibility_patrol_runs (tenant_id, auto_day) WHERE auto_day IS NOT NULL;

CREATE TABLE geo_visibility_patrol_setting_events (
    id BIGSERIAL NOT NULL, 
    tenant_id BIGINT NOT NULL, 
    actor_user_id BIGINT, 
    actor_role VARCHAR(32) NOT NULL, 
    action VARCHAR(32) NOT NULL, 
    before JSONB NOT NULL, 
    after JSONB NOT NULL, 
    revision INTEGER NOT NULL, 
    reason VARCHAR(500), 
    request_id VARCHAR(64), 
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX ix_geo_patrol_events_tenant_id ON geo_visibility_patrol_setting_events (tenant_id, id);

CREATE TABLE geo_visibility_patrol_daily_budget (
    budget_day DATE NOT NULL, 
    attempts INTEGER DEFAULT '0' NOT NULL, 
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (budget_day)
);

UPDATE alembic_version SET version_num='0111_geo_autopatrol' WHERE alembic_version.version_num = '0110_distribution_inbox';

COMMIT;

