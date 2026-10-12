-- Candidate only: queue -> planning. No runtime DDL; suggestions never publish grants.
CREATE TABLE distribution_planner_scans (
 tenant_id bigint NOT NULL,module varchar(3) NOT NULL,scope_id bigint NOT NULL,
 checked_at bigint NOT NULL DEFAULT 0,binding_cursor uuid,
 PRIMARY KEY(tenant_id,module,scope_id)
);
CREATE TABLE distribution_plan_requests (
 id uuid PRIMARY KEY, tenant_id bigint NOT NULL, module varchar(3) NOT NULL, scope_id bigint NOT NULL,
 fingerprint char(64) NOT NULL, snapshot jsonb NOT NULL, actor_id bigint NOT NULL,
 state varchar(20) NOT NULL CHECK(state IN ('running','succeeded','failed','stale','unknown')), reason varchar(64) NOT NULL, attempts integer NOT NULL DEFAULT 1 CHECK(attempts BETWEEN 1 AND 3),
 created_at bigint NOT NULL, updated_at bigint NOT NULL, retry_at bigint,
 UNIQUE(tenant_id,module,scope_id,fingerprint)
);
CREATE TABLE distribution_plans (
 id uuid PRIMARY KEY, queue_id uuid NOT NULL REFERENCES distribution_queue(id),
 request_id uuid NOT NULL REFERENCES distribution_plan_requests(id),
 tenant_id bigint NOT NULL, module varchar(3) NOT NULL, scope_id bigint NOT NULL,
 platform varchar(60) NOT NULL, external_account_id varchar(100) NOT NULL,
 binding_id uuid NOT NULL, draft_version varchar(100) NOT NULL, source_revision varchar(100) NOT NULL,
 content_digest char(64) NOT NULL, planned_at bigint NOT NULL, basis varchar(20) NOT NULL CHECK(basis IN ('ai','rules')),
 state varchar(30) NOT NULL CHECK(state IN ('planned','blocked','superseded')), reason varchar(64) NOT NULL,
 created_at bigint NOT NULL, checked_at bigint NOT NULL,
 UNIQUE(request_id,queue_id)
);
CREATE UNIQUE INDEX distribution_live_plan ON distribution_plans(queue_id) WHERE state='planned';
CREATE INDEX distribution_plan_account ON distribution_plans(platform,external_account_id,planned_at) WHERE state='planned';
