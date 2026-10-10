-- Additive platform controls. Review together with api_controls_permissions.sql.
-- Existing tenant/account/business rows are not modified. No Alembic stamp.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '15s';
ALTER TABLE api_usage_events ADD COLUMN reserved_amount numeric(24,12)
    CHECK (reserved_amount >= 0);
CREATE TABLE api_control_settings (
    key varchar(260) PRIMARY KEY,
    kind varchar(16) NOT NULL CHECK (kind IN ('budget','provider','rate','connection')),
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
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
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
COMMIT;
