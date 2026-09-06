-- REVIEW ONLY. Not registered with Alembic or invoked by any deployment.
-- Based on operator's 2026-09-06 read-only report, not independent DB access.
-- Shared production revision: 0093_seo_qa; tenants.id BIGINT; sem_tasks absent.
-- Still REVIEW ONLY: migration lineage/installation require separate approval.
-- Candidate DDL matches SemTask metadata; no existing table/data is modified.
CREATE TABLE sem_tasks (
    id BIGSERIAL NOT NULL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    module VARCHAR(8) NOT NULL,
    action_type VARCHAR(64) NOT NULL,
    title VARCHAR(300) NOT NULL,
    params JSONB NOT NULL,
    status VARCHAR(20) NOT NULL,
    created_by VARCHAR(80) NOT NULL,
    assignee_role VARCHAR(64) NOT NULL,
    baseline_snapshot JSONB NOT NULL,
    completion_evidence JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT ck_sem_tasks_module CHECK (module = 'sem'),
    CONSTRAINT ck_sem_tasks_action CHECK (action_type = 'metric_target'),
    CONSTRAINT ck_sem_tasks_status CHECK (status IN ('open','in_progress','done','cancelled')),
    CONSTRAINT ck_sem_tasks_role CHECK (assignee_role IN ('operator','admin')),
    CONSTRAINT ck_sem_tasks_params CHECK (jsonb_typeof(params) = 'object'),
    CONSTRAINT ck_sem_tasks_baseline CHECK (jsonb_typeof(baseline_snapshot) = 'object'),
    CONSTRAINT ck_sem_tasks_evidence CHECK (completion_evidence IS NULL OR jsonb_typeof(completion_evidence) = 'object'),
    CONSTRAINT ck_sem_tasks_done CHECK ((status = 'done' AND completion_evidence IS NOT NULL) OR (status <> 'done' AND completion_evidence IS NULL))
);
CREATE INDEX ix_sem_tasks_action ON sem_tasks(tenant_id, action_type, id);
CREATE INDEX ix_sem_tasks_queue ON sem_tasks(tenant_id, status, id);
