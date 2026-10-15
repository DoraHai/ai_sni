-- READ ONLY. Run only through the approved DB review process; do not execute here.
-- Historical customer_direct approvals by accounts which do not meet the new rule.
SELECT c.id, c.tenant_id, c.content_asset_id, c.actor_user_id, c.created_at,
       u.is_active, u.tenant_id AS actor_tenant_id, r.name AS actor_role
FROM seo_content_confirmations AS c
LEFT JOIN users AS u ON u.id = c.actor_user_id
LEFT JOIN roles AS r ON r.id = u.role_id
WHERE c.actor_mode = 'customer_direct'
  AND (u.id IS NULL OR NOT u.is_active OR u.tenant_id IS DISTINCT FROM c.tenant_id
       OR r.is_system IS DISTINCT FROM TRUE OR r.name IS DISTINCT FROM '品牌方客户'
       OR COALESCE(r.permissions->>'seo.content', '') <> 'view'
       OR EXISTS (SELECT 1 FROM jsonb_each_text(COALESCE(r.permissions, '{}'::jsonb)) p
                  WHERE p.value = 'edit' AND (p.key LIKE 'settings.%' OR p.key LIKE '%.content'))
       OR EXISTS (SELECT 1 FROM seo_site_advisor_assignments a WHERE a.advisor_user_id = u.id)
       OR EXISTS (SELECT 1 FROM geo_projects g
                  WHERE (g.project_settings->'geo_service_plan'->>'advisor_user_id') ~ '^[0-9]+$'
                    AND (g.project_settings->'geo_service_plan'->>'advisor_user_id')::bigint = u.id));

-- Review affected content with the business owner and obtain a new customer confirmation.
