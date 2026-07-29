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

export function fetchGeoAssetProfile(tenantId) {
  return client.get('/api/v1/geo/assets/profile', { params: { tenant_id: tenantId } })
}

export function saveGeoBrand(payload) {
  return client.put('/api/v1/geo/assets/brand', payload)
}

export function saveGeoAudience(payload) {
  return client.put('/api/v1/geo/assets/audience', payload)
}

export function fetchGeoKnowledge({ tenantId, q = '', itemType = '' }) {
  return client.get('/api/v1/geo/assets/knowledge', {
    params: { tenant_id: tenantId, q, item_type: itemType },
  })
}

export function createGeoKnowledge(payload) {
  return client.post('/api/v1/geo/assets/knowledge', payload)
}

export function deleteGeoKnowledge({ tenantId, knowledgeId }) {
  return client.delete(`/api/v1/geo/assets/knowledge/${knowledgeId}`, {
    params: { tenant_id: tenantId },
  })
}
