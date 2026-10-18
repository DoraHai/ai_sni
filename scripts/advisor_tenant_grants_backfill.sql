-- REVIEW ONLY. Execute separately ONLY in the user-approved first-import window.
-- Freeze role/user/grant administration; use the approved migration owner.
-- No automatic deployment or scheduled self-healing may run this script.
BEGIN;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM roles WHERE permissions IS NOT NULL
               AND jsonb_typeof(permissions::jsonb) <> 'object') THEN
        RAISE EXCEPTION 'invalid role permissions: stop backfill for manual review';
    END IF;
END $$;

WITH eligible AS (
    SELECT u.id AS user_id, u.tenant_id
    FROM users u JOIN roles r ON r.id = u.role_id
    JOIN tenants t ON t.id = u.tenant_id
    WHERE jsonb_typeof(COALESCE(r.permissions::jsonb, '{}'::jsonb)) = 'object'
      AND NOT (r.is_system IS TRUE AND r.name = '管理员')
      AND NOT EXISTS (
          SELECT 1 FROM jsonb_each_text(
              CASE WHEN jsonb_typeof(r.permissions::jsonb) = 'object'
                   THEN r.permissions::jsonb ELSE '{}'::jsonb END
          ) p
          WHERE p.key LIKE 'settings.%' AND p.value = 'edit'
      )
      AND (
          (r.permissions::jsonb ->> 'seo.site' = 'edit'
           AND r.permissions::jsonb ->> 'seo.content' = 'edit')
          OR (r.permissions::jsonb ->> 'geo.assets' = 'edit'
              AND r.permissions::jsonb ->> 'geo.content' = 'edit')
      )
)
INSERT INTO advisor_tenant_grants (user_id, tenant_id, granted_by, grant_source)
SELECT e.user_id, e.tenant_id, NULL, 'backfill'
FROM eligible e
WHERE NOT EXISTS (
    SELECT 1 FROM advisor_tenant_grants g WHERE g.user_id = e.user_id
)
ON CONFLICT (user_id, tenant_id) WHERE revoked_at IS NULL DO NOTHING;

COMMIT;
