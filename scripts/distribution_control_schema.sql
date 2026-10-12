-- Local candidate only. Apply to production only after migration review.
CREATE TABLE IF NOT EXISTS distribution_devices (
 id varchar(100) PRIMARY KEY, label varchar(80) NOT NULL,
 credential_hash char(64) NOT NULL, active boolean NOT NULL DEFAULT true,
 created_by bigint NOT NULL, last_seen_at bigint, created_at bigint NOT NULL
);
CREATE TABLE IF NOT EXISTS distribution_bindings (
 id uuid PRIMARY KEY, tenant_id bigint NOT NULL REFERENCES tenants(id),
 module varchar(3) NOT NULL CHECK(module IN ('seo','geo')), scope_id bigint NOT NULL,
 device_id varchar(100) NOT NULL REFERENCES distribution_devices(id),
 account_id varchar(100) NOT NULL, external_account_id varchar(100) NOT NULL,
 platform varchar(30) NOT NULL CHECK(platform IN ('wechat-article','xiaohongshu-image')),
 active boolean NOT NULL DEFAULT true, created_by bigint NOT NULL,
 UNIQUE(device_id,account_id,module,tenant_id,scope_id,platform)
);
CREATE TABLE IF NOT EXISTS distribution_controls (
 tenant_id bigint NOT NULL REFERENCES tenants(id), module varchar(3) NOT NULL,
 scope_id bigint NOT NULL, owner_user_id bigint NOT NULL,
 state varchar(10) NOT NULL DEFAULT 'paused' CHECK(state IN ('running','paused','ended')),
 revision integer NOT NULL DEFAULT 1, PRIMARY KEY(tenant_id,module,scope_id)
);
CREATE TABLE IF NOT EXISTS distribution_tasks (
 id uuid PRIMARY KEY, tenant_id bigint NOT NULL REFERENCES tenants(id), module varchar(3) NOT NULL,
 scope_id bigint NOT NULL, variant_id bigint NOT NULL, binding_id uuid NOT NULL REFERENCES distribution_bindings(id),
 device_id varchar(100) NOT NULL REFERENCES distribution_devices(id), account_id varchar(100) NOT NULL,
 platform varchar(30) NOT NULL, advisor_user_id bigint NOT NULL,
 source_revision varchar(100) NOT NULL, content jsonb NOT NULL, content_digest char(64) NOT NULL,
 action varchar(10) NOT NULL CHECK(action IN ('preflight','handoff','publish')),
 grant_id uuid NOT NULL UNIQUE, publication_grant_id uuid UNIQUE, grant_expires_at bigint NOT NULL, revoked boolean NOT NULL DEFAULT false,
 lease_id uuid NOT NULL UNIQUE, lease_expires_at bigint NOT NULL,
 status varchar(20) NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','leased','running','awaiting-human','succeeded','failed','unknown','canceled')),
 receipt_at bigint, receipt_sequence bigint NOT NULL DEFAULT 0, receipt jsonb, created_at bigint NOT NULL,
 request_id uuid NOT NULL, request_fingerprint char(64) NOT NULL,
 UNIQUE(tenant_id,module,scope_id,advisor_user_id,request_id)
);
-- One live intent per canonical platform account, reviewed source and action,
-- including across devices. Terminal unknown is deliberately not retryable.
CREATE UNIQUE INDEX IF NOT EXISTS distribution_task_intent
 ON distribution_tasks(tenant_id,module,scope_id,variant_id,binding_id,source_revision,action)
 WHERE status NOT IN ('failed','canceled');
CREATE INDEX IF NOT EXISTS distribution_device_pending ON distribution_tasks(device_id,created_at,id)
 WHERE status NOT IN ('succeeded','failed','unknown','canceled');
CREATE INDEX IF NOT EXISTS distribution_advisor_tasks ON distribution_tasks(tenant_id,module,scope_id,advisor_user_id,created_at DESC);
CREATE TABLE IF NOT EXISTS distribution_events (
 id bigserial PRIMARY KEY, at bigint NOT NULL, actor varchar(120) NOT NULL,
 action varchar(40) NOT NULL, task_id uuid, target jsonb NOT NULL, result varchar(64) NOT NULL
);
CREATE TABLE IF NOT EXISTS distribution_receipts (
 receipt_id uuid PRIMARY KEY,
 task_id uuid NOT NULL REFERENCES distribution_tasks(id), lease_id uuid NOT NULL,
 sequence bigint NOT NULL, status varchar(20) NOT NULL, at bigint NOT NULL, fingerprint char(64) NOT NULL,
 payload jsonb NOT NULL, UNIQUE(task_id,lease_id,sequence)
);
CREATE INDEX IF NOT EXISTS distribution_project_events ON distribution_events
 ((target->>'module'),(target->>'tenant_id'),(target->>'scope_id'),id DESC);
CREATE TABLE IF NOT EXISTS distribution_requests (
 actor_id bigint NOT NULL, request_id uuid NOT NULL, fingerprint char(64) NOT NULL,
 result jsonb NOT NULL, PRIMARY KEY(actor_id,request_id)
);
CREATE OR REPLACE FUNCTION distribution_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'distribution audit is append only'; END;
$$;
DROP TRIGGER IF EXISTS distribution_events_append_only ON distribution_events;
CREATE TRIGGER distribution_events_append_only BEFORE UPDATE OR DELETE ON distribution_events
 FOR EACH ROW EXECUTE FUNCTION distribution_append_only();
DROP TRIGGER IF EXISTS distribution_receipts_append_only ON distribution_receipts;
CREATE TRIGGER distribution_receipts_append_only BEFORE UPDATE OR DELETE ON distribution_receipts
 FOR EACH ROW EXECUTE FUNCTION distribution_append_only();
