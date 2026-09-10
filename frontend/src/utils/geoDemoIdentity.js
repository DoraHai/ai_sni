export const GEO_DEMO_TENANT_ID = 16
export const GEO_DEMO_USER_ID = 5
export const GEO_DEMO_USERNAME = 'workbench_test_readonly'
export const GEO_DEMO_HOME = '/geo/demo/overview'

export function isGeoDemoIdentity(user, tenantId) {
  return Number(user?.id) === GEO_DEMO_USER_ID
    && user?.username === GEO_DEMO_USERNAME
    && Number(user?.tenant_id) === GEO_DEMO_TENANT_ID
    && Number(tenantId) === GEO_DEMO_TENANT_ID
}
