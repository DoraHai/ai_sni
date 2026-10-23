import client from './client'

const geo = '/api/v1/geo/visibility-patrol'
const seo = '/api/v1/seo/workbench'
export const fetchManualQuota = tenantId => client.get(`${geo}/self-service`, { params: { tenant_id: tenantId } })
export const saveManualQuota = body => client.put(`${geo}/manual-limit`, body)
export const fetchAssignmentSites = tenantId => client.get(`${seo}/sites`, { params: { tenant_id: tenantId } })
export const fetchSiteAssignments = (tenantId, siteId) => client.get(`${seo}/advisor-assignments`, { params: { tenant_id: tenantId, site_id: siteId } })
// Deactivation deliberately preserves the assignment row and its history.
export const saveSiteAssignment = body => client.put(`${seo}/advisor-assignments`, body)
