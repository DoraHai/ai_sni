-- REVIEW CANDIDATE ONLY. Do not run on production without separate approval.
-- Apply in the reviewed application schema as its owner; no role creation.
CREATE TABLE automation_projects (
    module varchar(3) NOT NULL CHECK (module IN ('seo','geo')),
    tenant_id bigint NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    scope_id bigint NOT NULL CHECK (scope_id > 0),
    version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
    generation bigint NOT NULL DEFAULT 1 CHECK (generation > 0),
    state varchar(24) NOT NULL DEFAULT 'not_started' CHECK (state IN
        ('not_started','active','pausing','paused','taking_over','taken_over','ending','idle')),
    owner_user_id bigint NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    configuration jsonb NOT NULL CHECK (jsonb_typeof(configuration)='object'),
    cycle_enabled boolean NOT NULL DEFAULT false,
    next_due_at timestamptz,
    current_run_id uuid,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (module,tenant_id,scope_id)
);
CREATE TABLE automation_project_runs (
    id uuid PRIMARY KEY,
    module varchar(3) NOT NULL,
    tenant_id bigint NOT NULL,
    scope_id bigint NOT NULL,
    generation bigint NOT NULL CHECK (generation > 0),
    state varchar(24) NOT NULL CHECK (state IN
        ('queued','running','waiting_input','waiting_human','pausing','paused','taking_over','taken_over','ending','ended','failed')),
    stop_requested boolean NOT NULL DEFAULT false,
    dispatch_count integer NOT NULL DEFAULT 0 CHECK (dispatch_count >= 0),
    configuration jsonb NOT NULL CHECK (jsonb_typeof(configuration)='object'),
    steps jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(steps)='array'),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at timestamptz,
    UNIQUE (module,tenant_id,scope_id,id),
    FOREIGN KEY(module,tenant_id,scope_id) REFERENCES automation_projects(module,tenant_id,scope_id) ON DELETE RESTRICT
);
ALTER TABLE automation_projects ADD CONSTRAINT fk_automation_current_run
    FOREIGN KEY(module,tenant_id,scope_id,current_run_id)
    REFERENCES automation_project_runs(module,tenant_id,scope_id,id) ON DELETE RESTRICT;
CREATE TABLE automation_project_commands (
    module varchar(3) NOT NULL,
    tenant_id bigint NOT NULL,
    scope_id bigint NOT NULL,
    request_id uuid NOT NULL,
    actor_user_id bigint NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    payload_hash varchar(64) NOT NULL CHECK (length(payload_hash)=64),
    action varchar(24) NOT NULL,
    applied_version bigint NOT NULL,
    run_id uuid,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (module,tenant_id,scope_id,request_id),
    FOREIGN KEY(module,tenant_id,scope_id) REFERENCES automation_projects(module,tenant_id,scope_id) ON DELETE RESTRICT
);
CREATE TABLE automation_project_events (
    id bigserial PRIMARY KEY,
    module varchar(3) NOT NULL,
    tenant_id bigint NOT NULL,
    scope_id bigint NOT NULL,
    run_id uuid,
    actor_kind varchar(8) NOT NULL CHECK (actor_kind IN ('human','system','ai')),
    actor_user_id bigint REFERENCES users(id) ON DELETE RESTRICT,
    step_key varchar(80),
    code varchar(80) NOT NULL CHECK (code ~ '^[a-z][a-z0-9_]*$'),
    request_id uuid,
    evidence_refs jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(evidence_refs)='array'),
    fee_state varchar(20) NOT NULL DEFAULT 'not_called' CHECK (fee_state IN ('not_called','recorded','unknown_charge','unverified')),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (actor_kind <> 'human' OR actor_user_id IS NOT NULL),
    FOREIGN KEY(module,tenant_id,scope_id) REFERENCES automation_projects(module,tenant_id,scope_id) ON DELETE RESTRICT,
    FOREIGN KEY(module,tenant_id,scope_id,run_id) REFERENCES automation_project_runs(module,tenant_id,scope_id,id) ON DELETE RESTRICT
);
CREATE INDEX ix_automation_project_due ON automation_projects(module,state,next_due_at);
CREATE INDEX ix_automation_runs_history ON automation_project_runs(module,tenant_id,scope_id,created_at DESC,id DESC);
CREATE INDEX ix_automation_events_scope ON automation_project_events(module,tenant_id,scope_id,run_id,id);
CREATE INDEX ix_automation_events_project ON automation_project_events(module,tenant_id,scope_id,id);
CREATE FUNCTION automation_project_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'automation audit rows are append only';
END;
$$;
CREATE TRIGGER automation_events_immutable BEFORE UPDATE OR DELETE ON automation_project_events
    FOR EACH ROW EXECUTE FUNCTION automation_project_immutable();
CREATE TRIGGER automation_commands_immutable BEFORE UPDATE OR DELETE ON automation_project_commands
    FOR EACH ROW EXECUTE FUNCTION automation_project_immutable();
CREATE TRIGGER automation_events_no_truncate BEFORE TRUNCATE ON automation_project_events
    FOR EACH STATEMENT EXECUTE FUNCTION automation_project_immutable();
CREATE TRIGGER automation_commands_no_truncate BEFORE TRUNCATE ON automation_project_commands
    FOR EACH STATEMENT EXECUTE FUNCTION automation_project_immutable();
