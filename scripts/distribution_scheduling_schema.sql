-- Additive local candidate. No runtime DDL and no production application.
-- Reconciled/revoked historical tasks can record late conflicting evidence.
-- Canonical-account locks and enqueue's duplicate check still fence unknowns.
DROP INDEX IF EXISTS distribution_task_intent;
CREATE UNIQUE INDEX distribution_task_intent
 ON distribution_tasks(tenant_id,module,scope_id,variant_id,binding_id,source_revision,action)
 WHERE status NOT IN ('failed','canceled') AND NOT revoked;
CREATE TABLE IF NOT EXISTS distribution_account_policies (
 platform varchar(30) NOT NULL, external_account_id varchar(100) NOT NULL,
 tenant_id bigint NOT NULL REFERENCES tenants(id), enabled boolean NOT NULL,
 timezone varchar(60) NOT NULL, min_interval_seconds integer NOT NULL CHECK(min_interval_seconds BETWEEN 0 AND 86400),
 daily_limit integer NOT NULL CHECK(daily_limit BETWEEN 1 AND 1000), windows jsonb NOT NULL,
 revision integer NOT NULL, paused_reason varchar(40), updated_at bigint NOT NULL,
 PRIMARY KEY(platform,external_account_id)
);
CREATE TABLE IF NOT EXISTS distribution_account_restrictions (
 binding_id uuid PRIMARY KEY REFERENCES distribution_bindings(id),
 min_interval_seconds integer NOT NULL CHECK(min_interval_seconds BETWEEN 0 AND 86400),
 daily_limit integer NOT NULL CHECK(daily_limit BETWEEN 1 AND 1000), revision integer NOT NULL,
 updated_by bigint NOT NULL, updated_at bigint NOT NULL
);
CREATE TABLE IF NOT EXISTS distribution_publish_reservations (
 task_id uuid PRIMARY KEY REFERENCES distribution_tasks(id),
 platform varchar(30) NOT NULL, external_account_id varchar(100) NOT NULL,
 tenant_id bigint NOT NULL, reserved_at bigint NOT NULL, policy_revision integer NOT NULL,
 state varchar(12) NOT NULL CHECK(state IN ('held','consumed','released')),
 completed_at bigint
);
CREATE INDEX IF NOT EXISTS distribution_account_reservations
 ON distribution_publish_reservations(platform,external_account_id,state,reserved_at);
CREATE TABLE IF NOT EXISTS distribution_task_resolutions (
 id bigserial PRIMARY KEY, task_id uuid NOT NULL REFERENCES distribution_tasks(id),
 outcome varchar(20) NOT NULL CHECK(outcome IN ('not-published','published')),
 actor_id bigint NOT NULL, checked_at bigint NOT NULL, public_url text
);
CREATE INDEX IF NOT EXISTS distribution_task_resolution_history ON distribution_task_resolutions(task_id,id DESC);
DROP TRIGGER IF EXISTS distribution_resolutions_append_only ON distribution_task_resolutions;
CREATE TRIGGER distribution_resolutions_append_only BEFORE UPDATE OR DELETE ON distribution_task_resolutions
 FOR EACH ROW EXECUTE FUNCTION distribution_append_only();
