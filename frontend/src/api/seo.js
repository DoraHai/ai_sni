import client from './client'

export function fetchSeoKeywords({ tenantId, q, priority, intent, status = 'active', engine = 'baidu', page = 1, pageSize = 50 }) {
  return client.get('/api/v1/seo/keywords', {
    params: {
      tenant_id: tenantId,
      q: q || undefined,
      priority: priority || undefined,
      intent: intent || undefined,
      status: status || undefined,
      engine,
      page,
      page_size: pageSize,
    },
  })
}

export function createSeoKeyword(payload) {
  return client.post('/api/v1/seo/keywords', payload)
}

export function importSeoKeywords(payload) {
  return client.post('/api/v1/seo/keywords/import', payload)
}

export function updateSeoKeyword({ keywordId, tenantId, payload }) {
  return client.patch(`/api/v1/seo/keywords/${keywordId}`, payload, {
    params: { tenant_id: tenantId },
  })
}

export function fetchSeoKeywordDetail({ keywordId, tenantId, engine = 'baidu', days = 90 }) {
  return client.get(`/api/v1/seo/keywords/${keywordId}`, {
    params: { tenant_id: tenantId, engine, days },
  })
}

export function createSeoRankSnapshot(payload) {
  return client.post('/api/v1/seo/rank-snapshots', payload)
}

export function createSeoRankSnapshotBatch(payload) {
  return client.post('/api/v1/seo/rank-snapshots/batch', payload)
}

export function fetchSeoSitePages({ tenantId, q, status, page = 1, pageSize = 50 }) {
  return client.get('/api/v1/seo/site-pages', {
    params: {
      tenant_id: tenantId,
      q: q || undefined,
      status: status || undefined,
      page,
      page_size: pageSize,
    },
  })
}

export function createSeoSitePage(payload) {
  return client.post('/api/v1/seo/site-pages', payload)
}

export function importSeoSitePages(payload) {
  return client.post('/api/v1/seo/site-pages/import', payload)
}

export function updateSeoSitePage({ pageId, tenantId, payload }) {
  return client.patch(`/api/v1/seo/site-pages/${pageId}`, payload, {
    params: { tenant_id: tenantId },
  })
}

export function auditSeoSitePage({ pageId, tenantId }) {
  return client.post(`/api/v1/seo/site-pages/${pageId}/audit`, null, {
    params: { tenant_id: tenantId },
    timeout: 60000,
  })
}
