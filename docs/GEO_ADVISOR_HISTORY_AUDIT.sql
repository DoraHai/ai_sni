-- READ ONLY. Run only through the approved DB review process; do not execute here.
SELECT id AS project_id, tenant_id,
       project_settings->'geo_service_plan'->>'advisor_user_id' AS advisor_user_id,
       project_settings->'geo_service_plan'->>'updated_by' AS updated_by,
       project_settings->'geo_service_plan'->>'updated_at' AS updated_at
FROM geo_projects
WHERE project_settings->'geo_service_plan'->>'advisor_user_id' IS NOT NULL
  AND project_settings->'geo_service_plan'->>'advisor_user_id'
      = project_settings->'geo_service_plan'->>'updated_by';
-- A match is a review candidate, not proof of self-assignment: later edits overwrite updated_by.
-- Review the project history with the business owner and reassign any unauthorized advisor.

-- READ ONLY: existing plans assigned to built-in administrators or accounts
-- with settings edit rights. This is an inventory; runtime access is preserved.
SELECT g.id AS project_id, g.tenant_id, u.id AS advisor_user_id,
       r.name AS advisor_role, r.is_system,
       (r.is_system AND r.name = '管理员') AS built_in_admin,
       EXISTS (SELECT 1 FROM jsonb_each_text(COALESCE(r.permissions, '{}'::jsonb)) p
               WHERE p.key LIKE 'settings.%' AND p.value = 'edit') AS settings_editor
FROM geo_projects g
JOIN users u ON u.id = CASE
    WHEN (g.project_settings->'geo_service_plan'->>'advisor_user_id') ~ '^[0-9]{1,18}$'
    THEN (g.project_settings->'geo_service_plan'->>'advisor_user_id')::bigint END
JOIN roles r ON r.id = u.role_id
WHERE (g.project_settings->'geo_service_plan'->>'advisor_user_id') ~ '^[0-9]{1,18}$'
  AND ((r.is_system AND r.name = '管理员')
       OR EXISTS (SELECT 1 FROM jsonb_each_text(COALESCE(r.permissions, '{}'::jsonb)) p
                  WHERE p.key LIKE 'settings.%' AND p.value = 'edit'));
