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

export function fetchSeoOverview({ tenantId, siteId, engine = 'baidu', device = 'desktop' }) {
  return client.get('/api/v1/seo/overview', { params: { tenant_id: tenantId, site_id: siteId || undefined, engine, device } })
}

export function collectSeoOverviewMetrics(payload) {
  return client.post('/api/v1/seo/overview/collect-metrics', payload, { timeout: 180000 })
}

export function crawlSeoSite(payload) {
  return client.post('/api/v1/seo/site/crawl-runs', payload, { timeout: 300000 })
}

export function fetchSeoCrawlRuns({ tenantId, siteId, runId, limit = 10 }) {
  return client.get('/api/v1/seo/site/crawl-runs', {
    params: { tenant_id: tenantId, site_id: siteId, run_id: runId || undefined, limit },
  })
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

export function fetchSeoBrandProfile({ tenantId }) {
  return client.get('/api/v1/seo/rank-serp/brand-profile', { params: { tenant_id: tenantId } })
}

export function updateSeoBrandProfile(payload) {
  return client.patch('/api/v1/seo/rank-serp/brand-profile', payload)
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

export function importSeoPublishedLinks({ tenantId, file, dryRun = true }) {
  const form = new FormData()
  form.append('file', file)
  return client.post('/api/v1/seo/content-assets/import-published-links', form, {
    params: { tenant_id: tenantId, dry_run: dryRun },
    timeout: 60000,
  })
}

export function downloadSeoPublishedLinksTemplate() {
  return client.get('/api/v1/seo/content-assets/published-links-template', { responseType: 'blob' })
}

export function fetchSeoDistributionCatalog() {
  return client.get('/api/v1/seo/content-distribution/catalog')
}

export function fetchSeoDistributionConnections({ tenantId }) {
  return client.get('/api/v1/seo/content-distribution/connections', { params: { tenant_id: tenantId } })
}

export function createSeoDistributionConnection(payload) {
  return client.post('/api/v1/seo/content-distribution/connections', payload)
}

export function updateSeoDistributionConnection({ connectionId, tenantId, payload }) {
  return client.patch(`/api/v1/seo/content-distribution/connections/${connectionId}`, payload, { params: { tenant_id: tenantId } })
}

export function testSeoDistributionConnection({ connectionId, tenantId }) {
  return client.post(`/api/v1/seo/content-distribution/connections/${connectionId}/test`, null, { params: { tenant_id: tenantId }, timeout: 30000 })
}

export function fetchSeoContentPublications({ tenantId, contentId, status }) {
  return client.get('/api/v1/seo/content-distribution/publications', { params: { tenant_id: tenantId, content_id: contentId || undefined, status: status || undefined } })
}

export function createSeoManualPublication(payload) {
  return client.post('/api/v1/seo/content-distribution/publications/manual', payload)
}

export function preflightSeoDistribution(payload) {
  return client.post('/api/v1/seo/content-distribution/preflight', payload)
}

export function publishSeoDistribution(payload) {
  return client.post('/api/v1/seo/content-distribution/publish', payload, { timeout: 360000 })
}

export function completeSeoManualPublication({ publicationId, payload }) {
  return client.post(`/api/v1/seo/content-distribution/publications/${publicationId}/complete`, payload)
}

export function syncSeoContentPublication({ publicationId, tenantId }) {
  return client.post(`/api/v1/seo/content-distribution/publications/${publicationId}/sync`, null, { params: { tenant_id: tenantId }, timeout: 30000 })
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
