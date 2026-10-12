-- Candidate only: apply after distribution_planning_schema.sql. No runtime DDL.
CREATE TABLE distribution_handoff_permissions (
 tenant_id bigint NOT NULL,module varchar(3) NOT NULL,scope_id bigint NOT NULL,
 binding_id uuid NOT NULL REFERENCES distribution_bindings(id),actor_id bigint NOT NULL,
 enabled boolean NOT NULL,stage varchar(12) NOT NULL CHECK(stage IN ('preflight','handoff')),
 revision integer NOT NULL,updated_at bigint NOT NULL,
 PRIMARY KEY(tenant_id,module,scope_id,binding_id)
);
CREATE TABLE distribution_capability_attestations (
 device_id varchar(100) NOT NULL REFERENCES distribution_devices(id),
 digest char(64) NOT NULL,adapter_version varchar(100) NOT NULL,
 stages jsonb NOT NULL,expires_at bigint NOT NULL,recorded_at bigint NOT NULL,
 PRIMARY KEY(device_id,digest)
);
CREATE TABLE distribution_execution_intents (
 id uuid PRIMARY KEY,queue_id uuid NOT NULL REFERENCES distribution_queue(id),
 plan_id uuid NOT NULL REFERENCES distribution_plans(id),binding_id uuid NOT NULL REFERENCES distribution_bindings(id),
 tenant_id bigint NOT NULL,module varchar(3) NOT NULL,scope_id bigint NOT NULL,
 source_revision varchar(100) NOT NULL,draft_version varchar(100) NOT NULL,content_digest char(64) NOT NULL,
 platform varchar(30) NOT NULL,external_account_id varchar(100) NOT NULL,
 stage varchar(12) NOT NULL CHECK(stage IN ('preflight','handoff')),
 permission_revision integer NOT NULL,capability_digest char(64) NOT NULL,
 task_id uuid UNIQUE REFERENCES distribution_tasks(id),created_at bigint NOT NULL,
 attempt integer NOT NULL DEFAULT 1 CHECK(attempt BETWEEN 1 AND 3),
 UNIQUE(queue_id,source_revision,content_digest,stage,attempt)
);
CREATE TABLE distribution_handoff_slots (
 intent_id uuid PRIMARY KEY REFERENCES distribution_execution_intents(id),
 platform varchar(30) NOT NULL,external_account_id varchar(100) NOT NULL,
 state varchar(12) NOT NULL CHECK(state IN ('held','consumed','released')),
 reserved_at bigint NOT NULL,completed_at bigint
);
CREATE INDEX distribution_handoff_account ON distribution_handoff_slots(platform,external_account_id,state,reserved_at);
CREATE TABLE distribution_execution_scans (
 queue_id uuid PRIMARY KEY REFERENCES distribution_queue(id),
 checked_at bigint NOT NULL,reason varchar(64) NOT NULL
);
