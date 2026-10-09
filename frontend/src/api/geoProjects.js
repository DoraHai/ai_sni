import client from './client'

export const fetchGeoProjects = (tenantId) =>
  client.get('/api/v1/geo/projects', { params: { tenant_id: tenantId } })

export const createGeoProject = (body) => client.post('/api/v1/geo/projects', body)

export const updateGeoProject = (projectId, tenantId, body) =>
  client.patch(`/api/v1/geo/projects/${projectId}`, body, { params: { tenant_id: tenantId } })

export const updateGeoBusinessScope = (projectId, tenantId, body) =>
  client.put(`/api/v1/geo/projects/${projectId}/business-scope`, body, { params: { tenant_id: tenantId } })

export const fetchGeoProjectExecutions = (projectId, tenantId) =>
  client.get(`/api/v1/geo/projects/${projectId}/executions`, { params: { tenant_id: tenantId } })

export const saveGeoProjectPlan = (projectId, tenantId, body) =>
  client.put(`/api/v1/geo/projects/${projectId}/service-plan`, body, { params: { tenant_id: tenantId } })
