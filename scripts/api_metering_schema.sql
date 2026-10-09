-- Review and run this additive migration once, before enabling API_METERING_ENABLED.
-- Independent of the SEM/SEO/GEO Alembic heads. No existing table is modified.
BEGIN;
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
COMMIT;
