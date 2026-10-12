-- REVIEW CANDIDATE ONLY. Apply after reviewed v1 schema, in isolated tests only
-- until separately approved. Runtime roles must not own tables or DDL privileges.
ALTER TABLE automation_projects ADD COLUMN ended_at timestamptz;
ALTER TABLE automation_project_events ADD COLUMN safe_changes jsonb NOT NULL DEFAULT '[]'
    CHECK (jsonb_typeof(safe_changes)='array');
-- Existing table-level runtime grants cover added columns. Immutable event
-- UPDATE/DELETE/TRUNCATE triggers and runtime ACL must remain unchanged.
