-- Run as object owner only after reviewed schema. No extra ledger DELETE grant.
BEGIN;
SET LOCAL lock_timeout='3s';
SET LOCAL statement_timeout='15s';
REVOKE ALL ON api_usage_review_audit FROM PUBLIC, sem_runtime;
GRANT SELECT,INSERT ON api_usage_review_audit TO sem_runtime;
COMMIT;
