import client from './client'
const prefix = '/api/v1/geo/distribution/v1'
const config = (tenantId, projectId) => ({ params: { tenant_id: tenantId, project_id: projectId } })
export const reportSettings = (tenantId, projectId) => client.get(`${prefix}/settings`, config(tenantId, projectId))
export const setReportSettings = (tenantId, projectId, body) => client.put(`${prefix}/settings`, body, config(tenantId, projectId))
export const pairReportDevice = (tenantId, projectId, body) => client.post(`${prefix}/device-pairings`, body, config(tenantId, projectId))
export const revokeReportDevice = (tenantId, projectId, id, revision) => client.post(`${prefix}/devices/${encodeURIComponent(id)}/revoke`, { expected_revision: revision }, config(tenantId, projectId))
export const dispatchReportTask = (tenantId, projectId, body) => client.post(`${prefix}/tasks`, body, config(tenantId, projectId))
export const fetchReportTask = (tenantId, projectId, id) => client.get(`${prefix}/tasks/${encodeURIComponent(id)}`, config(tenantId, projectId))
export const setReportPublishAccount = (tenantId, projectId, id, body) => client.post(`${prefix}/tasks/${encodeURIComponent(id)}/publish-account`, body, config(tenantId, projectId))
