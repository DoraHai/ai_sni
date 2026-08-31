import client from './client'

export function runGeoAudit({ tenantId, url }) {
  return client.post('/api/v1/geo/audits', { tenant_id: tenantId, url }, { timeout: 45000 })
}

export function fetchLatestGeoAudit(tenantId) {
  return client.get('/api/v1/geo/audits/latest', { params: { tenant_id: tenantId } })
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

export function createGeoTaskFromDiagnosis({ tenantId, auditId, adviceCode }) {
  return client.post('/api/v1/geo/content-tasks/from-diagnosis', {
    tenant_id: tenantId,
    audit_id: auditId,
    advice_code: adviceCode || null,
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
