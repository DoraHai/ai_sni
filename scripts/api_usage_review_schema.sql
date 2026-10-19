-- Human-reviewed, additive migration. All three admission runtimes must first
-- install api_usage_review_basis.py and its api_controls.usage integration.
-- Keep API_USAGE_REVIEW_ENABLED=false until schema/ACL and all runtimes pass.
BEGIN;
SET LOCAL lock_timeout='3s';
SET LOCAL statement_timeout='15s';
ALTER TABLE api_usage_events
    ADD COLUMN review_version integer NOT NULL DEFAULT 0 CHECK (review_version>=0),
    ADD COLUMN verified_amount numeric(24,12) CHECK (verified_amount>=0),
    ADD COLUMN verified_currency varchar(3) CHECK (verified_currency='CNY'),
    ADD COLUMN reviewed_at timestamptz,
    ADD CONSTRAINT api_usage_review_money_pair CHECK ((verified_amount IS NULL)=(verified_currency IS NULL)),
    ADD CONSTRAINT api_usage_review_terminal CHECK (review_version=0 OR
        (state IN ('succeeded','error') AND reviewed_at IS NOT NULL));
CREATE TABLE api_usage_review_audit (
    request_id uuid PRIMARY KEY,
    event_id uuid NOT NULL REFERENCES api_usage_events(id),
    actor_id bigint NOT NULL,
    request_hash varchar(64) NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    review_version integer NOT NULL CHECK (review_version>0),
    evidence jsonb NOT NULL CHECK (jsonb_typeof(evidence)='object'),
    before_value jsonb NOT NULL,
    after_value jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(event_id,review_version)
);
CREATE INDEX ix_api_usage_review_event ON api_usage_review_audit(event_id,created_at);
COMMENT ON TABLE api_usage_review_audit IS 'Human attestation and proof index, not an independently verified provider invoice; append-only runtime ACL';
COMMIT;
