-- Optional isolated acceptance migration. Never execute on production in this task.
-- Only digests and public lifecycle metadata; no plaintext code or credential.
CREATE TABLE IF NOT EXISTS distribution_device_pairings (
 id uuid PRIMARY KEY,
 device_id varchar(100) NOT NULL UNIQUE REFERENCES distribution_devices(id),
 created_by bigint NOT NULL CHECK(created_by>0),
 request_id uuid NOT NULL,
 fingerprint char(64) NOT NULL,
 code_hash char(64) NOT NULL UNIQUE,
 state varchar(12) NOT NULL CHECK(state IN ('pending','claimed','revoked')),
 created_at bigint NOT NULL,
 expires_at bigint NOT NULL CHECK(expires_at>created_at),
 claimed_at bigint,
 claim_request_id uuid,
 revoked_at bigint,
 revoked_by bigint,
 UNIQUE(created_by,request_id),
 CHECK((claimed_at IS NULL)=(claim_request_id IS NULL)),
 CHECK(state<>'claimed' OR claimed_at IS NOT NULL),
 CHECK(state<>'revoked' OR revoked_at IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS distribution_pairing_recent
 ON distribution_device_pairings(created_at DESC,id DESC);
