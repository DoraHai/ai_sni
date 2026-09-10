export const SEM_DEMO_TENANT_ID = 16
export const SEM_DEMO_USERNAME = 'workbench_test_readonly'
export const SEM_DEMO_REVISION = 'sem-demo-tenant16-v1'

export const SEM_DEMO_ACCOUNTS = Object.freeze([
  Object.freeze({ id: 160001, username: '演示账户 A', ucid: 'demo-160001', status: 'active', demo: true }),
  Object.freeze({ id: 160002, username: '演示账户 B', ucid: 'demo-160002', status: 'active', demo: true }),
])

export function isSemDemoIdentity(user, tenantId) {
  return user?.username === SEM_DEMO_USERNAME
    && Number(user?.tenant_id) === SEM_DEMO_TENANT_ID
    && Number(tenantId) === SEM_DEMO_TENANT_ID
}
