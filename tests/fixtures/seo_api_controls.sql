-- Frozen shared API schema from 41d7c72d; used ONLY inside an isolated test schema.
-- Review and run this additive migration once, before enabling API_METERING_ENABLED.
-- Independent of the SEM/SEO/GEO Alembic heads. No existing table is modified.
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '15s';
CREATE TABLE api_usage_events (
    id uuid PRIMARY KEY,
    tenant_id bigint,
    user_id bigint,
    origin varchar(24) NOT NULL,
    module varchar(12) NOT NULL,
    operation varchar(200) NOT NULL,
    job_ref varchar(80),
    provider varchar(80) NOT NULL,
    credential_ref varchar(64),
    model varchar(120),
    endpoint varchar(200) NOT NULL,
    state varchar(24) NOT NULL CHECK (state IN ('requested','succeeded','error','unknown')),
    status_code integer,
    provider_request_id varchar(100),
    latency_ms integer CHECK (latency_ms >= 0),
    prompt_tokens bigint CHECK (prompt_tokens >= 0),
    cached_tokens bigint CHECK (cached_tokens >= 0 AND cached_tokens <= prompt_tokens),
    completion_tokens bigint CHECK (completion_tokens >= 0),
    currency varchar(3),
    estimated_amount numeric(24,12) CHECK (estimated_amount >= 0),
    pricing_version varchar(80),
    rate_quote jsonb,
    started_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at timestamptz,
    CHECK (estimated_amount IS NULL OR currency IS NOT NULL)
);
CREATE INDEX ix_api_usage_started ON api_usage_events (started_at);
CREATE INDEX ix_api_usage_tenant_started ON api_usage_events (tenant_id, started_at);
CREATE INDEX ix_api_usage_user_started ON api_usage_events (user_id, started_at);
COMMENT ON TABLE api_usage_events IS 'Per outbound provider attempt; no prompts, keys, bodies, or historical reconstruction';
-- Additive platform controls. Review together with api_controls_permissions.sql.
-- Existing tenant/account/business rows are not modified. No Alembic stamp.
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '15s';
ALTER TABLE api_usage_events ADD COLUMN reserved_amount numeric(24,12)
    CHECK (reserved_amount >= 0);
CREATE TABLE api_control_settings (
    key varchar(260) PRIMARY KEY,
    kind varchar(16) NOT NULL CHECK (kind IN ('budget','provider','rate')),
    value jsonb NOT NULL CHECK (jsonb_typeof(value) = 'object'),
    revision integer NOT NULL CHECK (revision > 0),
    updated_by bigint NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE api_control_bindings (
    id varchar(64) NOT NULL, module varchar(12) NOT NULL,
    label varchar(100) NOT NULL, host varchar(200) NOT NULL,
    model varchar(200), configured boolean NOT NULL,
    can_rotate boolean NOT NULL,
    seen_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (module, label)
);
CREATE TABLE api_control_credentials (
    id varchar(64) PRIMARY KEY,
    ciphertext text, revision integer NOT NULL CHECK (revision > 0),
    updated_by bigint NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE api_control_audit (
    id uuid PRIMARY KEY,
    actor_id bigint NOT NULL,
    resource varchar(260) NOT NULL, action varchar(32) NOT NULL,
    request_hash varchar(64) NOT NULL,
    before_value jsonb, after_value jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX api_control_audit_created_idx ON api_control_audit(created_at DESC);
