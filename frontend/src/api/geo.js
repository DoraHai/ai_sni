import client from './client'

export function runGeoAudit({ tenantId, url }) {
  return client.post('/api/v1/geo/audits', { tenant_id: tenantId, url }, { timeout: 45000 })
}

export function fetchLatestGeoAudit(tenantId) {
  return client.get('/api/v1/geo/audits/latest', { params: { tenant_id: tenantId } })
}

export function generateGeoAdvice({ tenantId, auditId }) {
  return client.post(`/api/v1/geo/audits/${auditId}/advice`, null, {
    params: { tenant_id: tenantId },
    timeout: 65000,
  })
}

export function generateGeoAssets({ tenantId, auditId }) {
  return client.post(`/api/v1/geo/audits/${auditId}/assets`, null, {
    params: { tenant_id: tenantId },
  })
}
