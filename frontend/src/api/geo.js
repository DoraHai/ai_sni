import client from './client'

export function fetchGeoTenants() {
  return client.get('/api/v1/geo/tenants')
}

export function runGeoAudit({ tenantId, url, scope = 'single' }) {
  return client.post('/api/v1/geo/audits', { tenant_id: tenantId, url, scope }, {
    timeout: scope === 'site' ? 120000 : 45000,
  })
}

export function runCompetitorAudit({ tenantId, url, scope = 'single' }) {
  return client.post('/api/v1/geo/audits/competitor-preview', { tenant_id: tenantId, url, scope }, {
    timeout: scope === 'site' ? 120000 : 45000,
  })
}

export function fetchLatestGeoAudit(tenantId) {
  return client.get('/api/v1/geo/audits/latest', { params: { tenant_id: tenantId } })
}

export function fetchGeoAuditHistory(tenantId, limit = 12) {
  return client.get('/api/v1/geo/audits/history', { params: { tenant_id: tenantId, limit } })
}

export function fetchGeoAudit({ tenantId, auditId }) {
  return client.get(`/api/v1/geo/audits/${auditId}`, { params: { tenant_id: tenantId } })
}

export function fetchPageSpeedInsights({ tenantId, url, strategy = 'mobile' }) {
  return client.get('/api/v1/geo/pagespeed', {
    params: { tenant_id: tenantId, url, strategy },
    timeout: 65000,
  })
}

export function generateGeoAdvice({ tenantId, auditId }) {
  return client.post(`/api/v1/geo/audits/${auditId}/advice`, null, {
    params: { tenant_id: tenantId },
    timeout: 65000,
  })
}

export function runDeepSeekSample({ tenantId, auditId, questions = [] }) {
  return client.post(`/api/v1/geo/audits/${auditId}/ai-sample`, {
    tenant_id: tenantId,
    questions,
  }, { timeout: 90000 })
}

export function generateGeoAssets({ tenantId, auditId }) {
  return client.post(`/api/v1/geo/audits/${auditId}/assets`, null, {
    params: { tenant_id: tenantId },
  })
}

export function fetchGeoAssetProfile(tenantId, website = '') {
  return client.get('/api/v1/geo/assets/profile', {
    params: { tenant_id: tenantId, website: website || undefined },
  })
}

export function discoverGeoBrand({ tenantId, website }) {
  return client.post('/api/v1/geo/assets/brand/discover', {
    tenant_id: tenantId,
    website,
  }, { timeout: 45000 })
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

export function createGeoTaskFromDiagnosis({ tenantId, auditId, adviceCode }) {
  return client.post('/api/v1/geo/content-tasks/from-diagnosis', {
    tenant_id: tenantId,
    audit_id: auditId,
    advice_code: adviceCode || null,
  })
}

export function fetchLatestGeoStructureScan(tenantId) {
  return client.get('/api/v1/geo/structure-scan/latest', { params: { tenant_id: tenantId } })
}

export function runGeoStructureScan(tenantId, websiteUrl) {
  return client.post('/api/v1/geo/structure-scan', null, {
    params: { tenant_id: tenantId, website_url: websiteUrl || undefined },
    timeout: 120000,
  })
}

export function listGeoActionTickets(tenantId, params = {}) {
  return client.get('/api/v1/geo/action-tickets', {
    params: { tenant_id: tenantId, ...params },
  })
}

export function createGeoActionTicket(tenantId, body) {
  return client.post('/api/v1/geo/action-tickets', body, {
    params: { tenant_id: tenantId },
  })
}

export function patchGeoActionTicket(tenantId, ticketId, body) {
  return client.patch(`/api/v1/geo/action-tickets/${ticketId}`, body, {
    params: { tenant_id: tenantId },
  })
}

export function verifyGeoActionTicket(tenantId, ticketId, recrawl = true) {
  return client.post(`/api/v1/geo/action-tickets/${ticketId}/verify`, null, {
    params: { tenant_id: tenantId, recrawl: !!recrawl },
    timeout: 90000,
  })
}

export function materializeGeoAuditTickets(tenantId, auditId, replaceOpen = false) {
  return client.post(`/api/v1/geo/audits/${auditId}/tickets`, null, {
    params: { tenant_id: tenantId, replace_open: !!replaceOpen },
  })
}

export function verifyGeoAuditTickets(tenantId, auditId, recrawl = true) {
  return client.post(`/api/v1/geo/audits/${auditId}/verify`, null, {
    params: { tenant_id: tenantId, recrawl: !!recrawl },
    timeout: 120000,
  })
}
