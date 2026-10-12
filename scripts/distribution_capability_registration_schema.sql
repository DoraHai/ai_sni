-- Candidate only; after distribution_execution_schema.sql. No runtime DDL.
-- Upgrade existing candidate intents without deleting any attempt history.
ALTER TABLE distribution_execution_intents ADD COLUMN IF NOT EXISTS attempt integer NOT NULL DEFAULT 1 CHECK(attempt BETWEEN 1 AND 3);
DO $$ DECLARE old_constraint text; BEGIN
 SELECT conname INTO old_constraint FROM pg_constraint
 WHERE conrelid='distribution_execution_intents'::regclass AND contype='u'
 AND pg_get_constraintdef(oid)='UNIQUE (queue_id, source_revision, content_digest, stage)';
 IF old_constraint IS NOT NULL THEN
  EXECUTE format('ALTER TABLE distribution_execution_intents DROP CONSTRAINT %I',old_constraint);
  ALTER TABLE distribution_execution_intents ADD UNIQUE(queue_id,source_revision,content_digest,stage,attempt);
 END IF;
END $$;
CREATE TABLE distribution_device_capability_registrations (
 device_id varchar(100) PRIMARY KEY REFERENCES distribution_devices(id),
 registration_id uuid NOT NULL,revision integer NOT NULL,
 digest char(64) NOT NULL,manifest_digest char(64) NOT NULL,
 bindings jsonb NOT NULL,active boolean NOT NULL,expires_at bigint NOT NULL,
 updated_at bigint NOT NULL
);
CREATE TABLE distribution_capability_requests (
 device_id varchar(100) NOT NULL REFERENCES distribution_devices(id),
 request_id uuid NOT NULL,fingerprint char(64) NOT NULL,response jsonb NOT NULL,
 PRIMARY KEY(device_id,request_id)
);
CREATE TABLE distribution_handoff_resolutions (
 id uuid PRIMARY KEY,task_id uuid NOT NULL UNIQUE REFERENCES distribution_tasks(id),
 actor_id bigint NOT NULL,source_revision varchar(100) NOT NULL,content_digest char(64) NOT NULL,
 outcome varchar(20) NOT NULL CHECK(outcome='not-published'),checked_at bigint NOT NULL
);
CREATE TRIGGER distribution_handoff_resolutions_append_only BEFORE UPDATE OR DELETE
 ON distribution_handoff_resolutions FOR EACH ROW EXECUTE FUNCTION distribution_append_only();
CREATE TABLE distribution_handoff_retry_links (
 previous_intent_id uuid PRIMARY KEY REFERENCES distribution_execution_intents(id),
 new_intent_id uuid NOT NULL UNIQUE REFERENCES distribution_execution_intents(id),
 actor_id bigint NOT NULL,created_at bigint NOT NULL
);
CREATE TRIGGER distribution_handoff_retry_links_append_only BEFORE UPDATE OR DELETE
 ON distribution_handoff_retry_links FOR EACH ROW EXECUTE FUNCTION distribution_append_only();
