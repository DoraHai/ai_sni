-- Apply with the existing object owner after the reviewed table creation.
-- Affect only this new ledger. Default privileges must not grant DELETE.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '15s';
REVOKE ALL PRIVILEGES ON public.api_usage_events FROM PUBLIC, sem_runtime;
GRANT SELECT, INSERT, UPDATE ON public.api_usage_events TO sem_runtime;
COMMIT;
