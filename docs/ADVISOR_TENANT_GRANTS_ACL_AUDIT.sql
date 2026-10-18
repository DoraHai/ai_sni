-- REVIEW ONLY: run before/after the independently approved migration, never in deploy.
-- Exclude only the new table; identity sequence ACL must not add a diff.
-- SNAPSHOT-BEGIN
WITH me AS (SELECT oid FROM pg_roles WHERE rolname = 'sem_runtime')
SELECT 'relation' AS kind, n.nspname || '.' || c.relname AS obj, a.privilege_type AS priv
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
CROSS JOIN LATERAL aclexplode(c.relacl) a, me
WHERE a.grantee = me.oid AND c.relname <> 'advisor_tenant_grants'
UNION ALL
SELECT 'column', n.nspname || '.' || c.relname || '.' || att.attname, a.privilege_type
FROM pg_attribute att JOIN pg_class c ON c.oid = att.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
CROSS JOIN LATERAL aclexplode(att.attacl) a, me
WHERE a.grantee = me.oid AND c.relname <> 'advisor_tenant_grants'
UNION ALL
SELECT 'schema', n.nspname, a.privilege_type
FROM pg_namespace n CROSS JOIN LATERAL aclexplode(n.nspacl) a, me WHERE a.grantee = me.oid
UNION ALL
SELECT 'function', p.oid::regprocedure::text, a.privilege_type
FROM pg_proc p CROSS JOIN LATERAL aclexplode(p.proacl) a, me WHERE a.grantee = me.oid
UNION ALL
SELECT 'database', d.datname, a.privilege_type
FROM pg_database d CROSS JOIN LATERAL aclexplode(d.datacl) a, me
WHERE a.grantee = me.oid AND d.datname = current_database()
UNION ALL
SELECT 'member_of', r.rolname, CASE WHEN m.admin_option THEN 'ADMIN' ELSE 'MEMBER' END
FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.roleid, me WHERE m.member = me.oid
UNION ALL
SELECT 'default_acl', pg_get_userbyid(d.defaclrole) || ':' || d.defaclobjtype::text, a.privilege_type
FROM pg_default_acl d CROSS JOIN LATERAL aclexplode(d.defaclacl) a, me WHERE a.grantee = me.oid
UNION ALL
SELECT 'role_attr', 'sem_runtime',
       concat_ws(',', CASE WHEN rolsuper THEN 'SUPERUSER' END, CASE WHEN rolcreaterole THEN 'CREATEROLE' END,
                 CASE WHEN rolcreatedb THEN 'CREATEDB' END, CASE WHEN rolbypassrls THEN 'BYPASSRLS' END)
FROM pg_roles WHERE rolname = 'sem_runtime'
ORDER BY 1, 2, 3;
-- SNAPSHOT-END

-- TABLE-BEGIN
SELECT p AS privilege, has_table_privilege('sem_runtime', 'public.advisor_tenant_grants', p) AS granted
FROM unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER']) AS p;
-- TABLE-END

SELECT pg_get_userbyid(relowner) AS owner FROM pg_class
WHERE oid='public.advisor_tenant_grants'::regclass;
