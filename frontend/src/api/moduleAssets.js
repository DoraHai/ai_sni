import client from './client'

export const fetchCustomers = () => client.get('/api/v1/admin/customers')
export const createCustomer = (body) => client.post('/api/v1/admin/customers', body)
export const updateCustomer = (tenantId, body) => client.patch(`/api/v1/admin/customers/${tenantId}`, body)
export const setCustomerModule = (tenantId, moduleCode, body) => (
  client.put(`/api/v1/admin/customers/${tenantId}/modules/${moduleCode}`, body)
)

export const fetchSemAccounts = (tenantId) => client.get('/api/v1/sem/assets/accounts', { params: { tenant_id: tenantId } })
export const repairSemAccountAssets = (tenantId, accountId, dimension = null) => client.post(
  `/api/v1/sem/assets/accounts/${accountId}/repair-sync`, null,
  { params: { tenant_id: tenantId, dimension: dimension || undefined } },
)

export const fetchSeoSites = (tenantId) => client.get('/api/v1/seo/sites', { params: { tenant_id: tenantId } })
export const createSeoSite = (body) => client.post('/api/v1/seo/sites', body)
export const updateSeoSite = (siteId, tenantId, body) => client.patch(`/api/v1/seo/sites/${siteId}`, body, { params: { tenant_id: tenantId } })

export const fetchGeoProjects = (tenantId) => client.get('/api/v1/geo/projects', { params: { tenant_id: tenantId } })
export const createGeoProject = (body) => client.post('/api/v1/geo/projects', body)
export const updateGeoProject = (projectId, tenantId, body) => client.patch(`/api/v1/geo/projects/${projectId}`, body, { params: { tenant_id: tenantId } })
