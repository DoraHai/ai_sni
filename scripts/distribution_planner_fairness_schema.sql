-- Existing second-batch planning databases: apply only this additive table.
-- New installations already receive it in distribution_planning_schema.sql.
-- Runtime never runs this SQL. Stop the worker before rollback to the previous code.
CREATE TABLE distribution_planner_scans (
 tenant_id bigint NOT NULL,module varchar(3) NOT NULL,scope_id bigint NOT NULL,
 checked_at bigint NOT NULL DEFAULT 0,binding_cursor uuid,
 PRIMARY KEY(tenant_id,module,scope_id)
);
