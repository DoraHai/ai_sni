-- Execute as the existing object owner after the reviewed additive schema.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '15s';
REVOKE ALL ON api_control_settings, api_control_bindings,
    api_control_credentials, api_control_audit FROM PUBLIC, sem_runtime;
GRANT SELECT, INSERT, UPDATE ON api_control_settings, api_control_bindings,
    api_control_credentials TO sem_runtime;
-- Append-only audit for the service role; no DELETE/UPDATE grants.
GRANT SELECT, INSERT ON api_control_audit TO sem_runtime;
COMMIT;
