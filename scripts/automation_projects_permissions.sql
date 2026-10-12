-- REVIEW CANDIDATE ONLY. psql: provide reviewed existing runtime_role and schema.
-- No login/role creation, no public grants, no access to other module tables.
GRANT USAGE ON SCHEMA :"schema" TO :"runtime_role";
GRANT SELECT, INSERT, UPDATE ON :"schema".automation_projects,
    :"schema".automation_project_runs TO :"runtime_role";
GRANT SELECT, INSERT ON :"schema".automation_project_events,
    :"schema".automation_project_commands TO :"runtime_role";
REVOKE UPDATE, DELETE, TRUNCATE ON :"schema".automation_project_events,
    :"schema".automation_project_commands FROM :"runtime_role";
REVOKE DELETE, TRUNCATE ON :"schema".automation_projects,
    :"schema".automation_project_runs FROM :"runtime_role";
GRANT USAGE, SELECT ON SEQUENCE :"schema".automation_project_events_id_seq TO :"runtime_role";
