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
