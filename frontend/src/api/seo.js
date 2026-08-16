import client from './client'

export function fetchSeoKeywords({ tenantId, q, priority, intent, status = 'active', engine = 'baidu', device = 'desktop', page = 1, pageSize = 50 }) {
  return client.get('/api/v1/seo/keywords', {
    params: {
      tenant_id: tenantId,
      q: q || undefined,
      priority: priority || undefined,
      intent: intent || undefined,
      status: status || undefined,
      engine,
      device,
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

export function fetchSeoKeywordDetail({ keywordId, tenantId, engine = 'baidu', device = 'desktop', days = 90 }) {
  return client.get(`/api/v1/seo/keywords/${keywordId}`, {
    params: { tenant_id: tenantId, engine, device, days },
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

export function fetchSeoOverview({ tenantId, engine = 'baidu', device = 'desktop' }) {
  return client.get('/api/v1/seo/overview', { params: { tenant_id: tenantId, engine, device } })
}

export function collectSeoRankSerp(payload) {
  return client.post('/api/v1/seo/rank-serp/collect', payload, { timeout: 180000 })
}

export function fetchSeoSerpResults({ tenantId, device = 'desktop', ownershipType, keywordId, limit = 200 }) {
  return client.get('/api/v1/seo/rank-serp/results', { params: { tenant_id: tenantId, device, ownership_type: ownershipType || undefined, keyword_id: keywordId || undefined, limit } })
}

export function updateSeoSerpOwnership({ resultId, tenantId, ownershipType, createAsset = true }) {
  return client.patch(`/api/v1/seo/rank-serp/results/${resultId}`, { tenant_id: tenantId, ownership_type: ownershipType, create_asset: createAsset })
}

export function fetchSeoBrandAssets({ tenantId }) {
  return client.get('/api/v1/seo/rank-serp/brand-assets', { params: { tenant_id: tenantId } })
}

export function createSeoBrandAsset(payload) {
  return client.post('/api/v1/seo/rank-serp/brand-assets', payload)
}

export function fetchSeoAlerts({ tenantId, engine = 'baidu' }) {
  return client.get('/api/v1/seo/alerts', { params: { tenant_id: tenantId, engine } })
}

export function fetchSeoContentAssets({ tenantId, status, contentType }) {
  return client.get('/api/v1/seo/content-assets', { params: { tenant_id: tenantId, status: status || undefined, content_type: contentType || undefined } })
}

export function createSeoContentAsset(payload) {
  return client.post('/api/v1/seo/content-assets', payload)
}

export function updateSeoContentAsset({ contentId, tenantId, payload }) {
  return client.patch(`/api/v1/seo/content-assets/${contentId}`, payload, { params: { tenant_id: tenantId } })
}

export function assistSeoContent(payload) {
  return client.post('/api/v1/seo/content-ai/assist', payload, { timeout: 100000 })
}

export function fetchSeoInternalLinks({ tenantId }) {
  return client.get('/api/v1/seo/internal-links', { params: { tenant_id: tenantId } })
}

export function crawlSeoInternalLinks({ tenantId, pageId }) {
  return client.post('/api/v1/seo/internal-links/crawl', null, { params: { tenant_id: tenantId, page_id: pageId }, timeout: 60000 })
}

export function fetchSeoBacklinks({ tenantId, status }) {
  return client.get('/api/v1/seo/backlinks', { params: { tenant_id: tenantId, status: status || undefined } })
}

export function createSeoBacklink(payload) {
  return client.post('/api/v1/seo/backlinks', payload)
}

export function fetchSeoCompetitors({ tenantId }) {
  return client.get('/api/v1/seo/competitors', { params: { tenant_id: tenantId } })
}

export function createSeoCompetitor(payload) {
  return client.post('/api/v1/seo/competitors', payload)
}

export function createSeoCompetitorEvent(payload) {
  return client.post('/api/v1/seo/competitors/events', payload)
}
