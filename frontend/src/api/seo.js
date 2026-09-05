import client from './client'
export const seoQaGet = (path, params) => client.get(`/api/v1/seo/qa/${path}`, { params })
export const seoQaPost = (path, payload) => client.post(`/api/v1/seo/qa/${path}`, payload, { timeout: 35000 })
export const seoQaPatch = (path, payload) => client.patch(`/api/v1/seo/qa/${path}`, payload)
export const fetchSeoWorkOrders = params => client.get('/api/v1/seo/tasks', {params})
export const createSeoWorkOrder = payload => client.post('/api/v1/seo/tasks', payload)
export const updateSeoWorkOrder = (id,payload) => client.patch(`/api/v1/seo/tasks/${id}`,payload)
export const fetchSeoBacklinkOutcomes = params => client.get('/api/v1/seo/backlinks/outcomes',{params})
export const saveSeoReferral = payload => client.post('/api/v1/seo/backlinks/referrals',payload)
export const seoVideoGet = (path,params) => client.get(`/api/v1/seo/content-distribution/video/${path}`,{params})
export const seoVideoPost = (path,payload) => client.post(`/api/v1/seo/content-distribution/video/${path}`,payload,{timeout:120000})
import { session } from '../store/session'
import { createSeoAiRequester } from './seoAiRequests'

const requestSeoAi = createSeoAiRequester(
  (path, payload, config) => client.post(path, payload, config),
  () => session.user?.id != null ? `user:${session.user.id}` : session.token || 'api_key',
  () => crypto.randomUUID(),
  { storage: () => sessionStorage },
)

export function fetchSeoTaskCenter(params) {
  return client.get('/api/v1/seo/overview/task-center', { params })
}

export function recoverSeoAiOperation(operationId, tenantId) {
  return client.get(`/api/v1/seo/content-ai/operations/${encodeURIComponent(operationId)}`, { params: { tenant_id: tenantId } })
}

export function retrySeoTask(runId, payload) {
  return client.post(`/api/v1/seo/overview/task-center/${runId}/retry`, payload)
}

export function fetchSeoSiteDiagnostics({ tenantId, siteId, q = '', reviewState = 'all', page = 1 }) {
  return client.get('/api/v1/seo/site-pages/diagnostics', {
    params: { tenant_id: tenantId, site_id: siteId, q, review_state: reviewState, page, page_size: 25 },
  })
}

export function saveSeoIndexReview(payload) {
  return client.post('/api/v1/seo/site-pages/index-reviews', payload)
}

export function fetchSeoIndexReviews({ tenantId, siteId, pageId, beforeId }) {
  return client.get('/api/v1/seo/site-pages/index-reviews', {
    params: { tenant_id: tenantId, site_id: siteId, page_id: pageId, before_id: beforeId },
  })
}

export function fetchSeoKeywords({ tenantId, siteId, q, priority, intent, status = 'active', engine = 'baidu', device = 'desktop', page = 1, pageSize = 50 }) {
  return client.get('/api/v1/seo/keywords', {
    params: {
      tenant_id: tenantId,
      site_id: siteId || undefined,
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

export function fetchSeoKeywordDetail({ keywordId, tenantId, engine = 'baidu', device = 'desktop', region = '全国', days = 90 }) {
  return client.get(`/api/v1/seo/keywords/${keywordId}`, {
    params: { tenant_id: tenantId, engine, device, region, days },
  })
}

export function createSeoRankSnapshot(payload) {
  return client.post('/api/v1/seo/rank-snapshots', payload)
}

export function createSeoRankSnapshotBatch(payload) {
  return client.post('/api/v1/seo/rank-snapshots/batch', payload)
}

export function fetchSeoSitePages({ tenantId, siteId, pageId, q, status, issueCode, page = 1, pageSize = 50 }) {
  return client.get('/api/v1/seo/site-pages', {
    params: {
      tenant_id: tenantId,
      site_id: siteId || undefined,
      page_id: pageId || undefined,
      q: q || undefined,
      status: status || undefined,
      issue_code: issueCode || undefined,
      page,
      page_size: pageSize,
    },
  })
}

export function fetchSeoSitePageIssues({ tenantId, siteId }) {
  return client.get('/api/v1/seo/site-pages/issues', {
    params: { tenant_id: tenantId, site_id: siteId },
  })
}

export function fetchSeoSitePageDetail({ pageId, tenantId }) {
  return client.get(`/api/v1/seo/site-pages/${pageId}/detail`, {
    params: { tenant_id: tenantId },
  })
}

export function fetchSeoBrokenLinkReport({ tenantId, siteId }) {
  return client.get('/api/v1/seo/site-pages/broken-link-report', {
    params: { tenant_id: tenantId, site_id: siteId },
  })
}

export function generateSeoSitePageSuggestions(payload) {
  return client.post('/api/v1/seo/site-pages/suggestions/generate', payload)
}

export function cleanupSeoNonHtmlSitePages(payload) {
  return client.post('/api/v1/seo/site-pages/non-html-assets/cleanup', payload)
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

export function auditSeoSitePage({ pageId, tenantId, siteId }) {
  return client.post(`/api/v1/seo/site-pages/${pageId}/audit`, null, {
    params: { tenant_id: tenantId, site_id: siteId },
    timeout: 60000,
  })
}

export function fetchSeoOverview({ tenantId, siteId, engine = 'baidu', device = 'desktop', days = 30 }) {
  return client.get('/api/v1/seo/overview', { params: { tenant_id: tenantId, site_id: siteId || undefined, engine, device, days } })
}

export function fetchSeoAutomationRuns({ tenantId, siteId, jobType, limit = 30 }) {
  return client.get('/api/v1/seo/automation-runs', {
    params: { tenant_id: tenantId, site_id: siteId || undefined, job_type: jobType || undefined, limit },
  })
}

export function triggerSeoAutomationRun(payload) {
  return client.post('/api/v1/seo/overview/automation-runs/trigger', payload, { timeout: 30000 })
}

export function collectSeoOverviewMetrics(payload) {
  return client.post('/api/v1/seo/overview/collect-metrics', payload, { timeout: 180000 })
}

export function crawlSeoSite(payload) {
  return client.post('/api/v1/seo/site/crawl-runs', payload, { timeout: 30000 })
}

export function fetchSeoCrawlRuns({ tenantId, siteId, runId, limit = 10 }) {
  return client.get('/api/v1/seo/site/crawl-runs', {
    params: { tenant_id: tenantId, site_id: siteId, run_id: runId || undefined, limit },
  })
}

export function collectSeoRankSerp(payload) {
  return client.post('/api/v1/seo/rank-serp/collect', payload, { timeout: 180000 })
}

export function fetchSeoRankCollectStatus({ tenantId, siteId, engine = 'baidu' }) {
  return client.get('/api/v1/seo/rank-serp/collect-status', {
    params: { tenant_id: tenantId, site_id: siteId, engine },
  })
}

export function fetchSeoRankProviders({ tenantId, siteId }) {
  return client.get('/api/v1/seo/rank-serp/providers', {
    params: { tenant_id: tenantId, site_id: siteId },
  })
}

export function fetchSeoSerpResults({ tenantId, siteId, engine = 'baidu', device = 'desktop', ownershipType, keywordId, limit = 200 }) {
  return client.get('/api/v1/seo/rank-serp/results', { params: { tenant_id: tenantId, site_id: siteId || undefined, engine, device, ownership_type: ownershipType || undefined, keyword_id: keywordId || undefined, limit } })
}

export function fetchSeoGscConnection({ tenantId, siteId }) {
  return client.get('/api/v1/seo/traffic/gsc', { params: { tenant_id: tenantId, site_id: siteId } })
}

export function updateSeoGscConnection(payload) {
  return client.put('/api/v1/seo/traffic/gsc', payload)
}

export function testSeoGscConnection(payload) {
  return client.post('/api/v1/seo/traffic/gsc/test', payload, { timeout: 60000 })
}

export function collectSeoGscTraffic(payload) {
  return client.post('/api/v1/seo/traffic/gsc/collect', payload, { timeout: 60000 })
}

export function updateSeoSerpOwnership({ resultId, tenantId, siteId, ownershipType, createAsset = true }) {
  return client.patch(`/api/v1/seo/rank-serp/results/${resultId}`, { tenant_id: tenantId, site_id: siteId || null, ownership_type: ownershipType, create_asset: createAsset })
}

export function fetchSeoBrandAssets({ tenantId, siteId }) {
  return client.get('/api/v1/seo/rank-serp/brand-assets', { params: { tenant_id: tenantId, site_id: siteId || undefined } })
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

export function updateSeoBrandAsset({ assetId, tenantId, payload }) {
  return client.patch(`/api/v1/seo/rank-serp/brand-assets/${assetId}`, payload, {
    params: { tenant_id: tenantId },
  })
}

export function fetchSeoAlerts({ tenantId, siteId, engine = 'baidu' }) {
  return client.get('/api/v1/seo/alerts', { params: { tenant_id: tenantId, site_id: siteId || undefined, engine } })
}

export function auditPendingSeoSitePages({ tenantId, siteId, maxPages = 10 }) {
  return client.post('/api/v1/seo/site-pages/audit-pending', null, {
    params: { tenant_id: tenantId, site_id: siteId || undefined, max_pages: maxPages },
    timeout: 180000,
  })
}

export function fetchSeoContentAssets({ tenantId, siteId, contentId, sourcePageId, status, contentType, contentTypes, query, page = 1, pageSize = 50 }) {
  return client.get('/api/v1/seo/content-assets', { params: { tenant_id: tenantId, site_id: siteId || undefined, content_id: contentId || undefined, source_page_id: sourcePageId || undefined, status: status || undefined, content_type: contentType || undefined, content_types: contentTypes || undefined, q: query || undefined, page, page_size: pageSize } })
}

export function fetchSeoContentReviewHistory({ contentId, tenantId }) {
  return client.get(`/api/v1/seo/content-assets/${contentId}/review-history`, { params: { tenant_id: tenantId } })
}

export function createSeoContentAsset(payload) {
  return client.post('/api/v1/seo/content-assets', payload)
}

export function updateSeoContentAsset({ contentId, tenantId, payload }) {
  return client.patch(`/api/v1/seo/content-assets/${contentId}`, payload, { params: { tenant_id: tenantId } })
}

export function bindSeoContentSourcePage({ contentId, tenantId, sourcePageId, versionCount }) {
  return client.put(`/api/v1/seo/content-assets/${contentId}/source-page`, {
    source_page_id: sourcePageId,
    version_count: versionCount,
  }, { params: { tenant_id: tenantId } })
}

export function submitSeoContentReview({ contentId, tenantId, note = null }) {
  return client.post(`/api/v1/seo/content-assets/${contentId}/submit-review`, { note }, { params: { tenant_id: tenantId } })
}

export function decideSeoContentReview({ contentId, tenantId, decision, note = null }) {
  return client.post(`/api/v1/seo/content-assets/${contentId}/review`, { decision, note }, { params: { tenant_id: tenantId } })
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

export function fetchSeoContentPublications({ tenantId, siteId, contentId, status }) {
  return client.get('/api/v1/seo/content-distribution/publications', { params: { tenant_id: tenantId, site_id: siteId || undefined, content_id: contentId || undefined, status: status || undefined } })
}

export function createSeoManualPublication(payload) {
  return client.post('/api/v1/seo/content-distribution/publications/manual', payload)
}

export function preflightSeoDistribution(payload) {
  return client.post('/api/v1/seo/content-distribution/preflight', payload)
}

export function adaptSeoDistributionContent(payload) {
  if (payload.use_ai) return requestSeoAi('/api/v1/seo/content-distribution/adapt', payload)
  return client.post('/api/v1/seo/content-distribution/adapt', payload, { timeout: 100000 })
}

export function fetchSeoDistributionVariants({ tenantId, siteId, contentId, connectionId, status, latestOnly = true }) {
  return client.get('/api/v1/seo/content-distribution/variants', { params: { tenant_id: tenantId, site_id: siteId || undefined, content_id: contentId || undefined, connection_id: connectionId || undefined, status: status || undefined, latest_only: latestOnly } })
}

export function saveSeoDistributionVariant(payload) {
  return client.post('/api/v1/seo/content-distribution/variants', payload)
}

export function generateSeoDistributionVariants(payload) {
  return client.post('/api/v1/seo/content-distribution/variants/generate', payload, { timeout: 360000 })
}

export function reviewSeoDistributionVariant({ variantId, payload }) {
  return client.post(`/api/v1/seo/content-distribution/variants/${variantId}/review`, payload)
}

export function fetchSeoDistributionVariantHistory({ variantId, tenantId, siteId }) {
  return client.get(`/api/v1/seo/content-distribution/variants/${variantId}/history`, { params: { tenant_id: tenantId, site_id: siteId || undefined } })
}

export function publishSeoDistribution(payload) {
  return client.post('/api/v1/seo/content-distribution/publish', payload, { timeout: 360000 })
}

export function completeSeoManualPublication({ publicationId, payload }) {
  return client.post(`/api/v1/seo/content-distribution/publications/${publicationId}/complete`, payload)
}

export function syncSeoContentPublication({ publicationId, tenantId, siteId }) {
  return client.post(`/api/v1/seo/content-distribution/publications/${publicationId}/sync`, null, { params: { tenant_id: tenantId, site_id: siteId || undefined }, timeout: 30000 })
}

export function retrySeoContentPublication({ publicationId, payload }) {
  return client.post(`/api/v1/seo/content-distribution/publications/${publicationId}/retry`, payload, { timeout: 360000 })
}

export function fetchSeoPublicationAttempts({ publicationId, tenantId, siteId }) {
  return client.get(`/api/v1/seo/content-distribution/publications/${publicationId}/attempts`, { params: { tenant_id: tenantId, site_id: siteId || undefined } })
}

export function assistSeoContent(payload) {
  return requestSeoAi('/api/v1/seo/content-ai/assist', payload)
}

export function fetchSeoImageEvidence({ tenantId, siteId, pageId, snapshotId }) {
  return client.get('/api/v1/seo/site-pages/image-evidence', { params: { tenant_id: tenantId, site_id: siteId, page_id: pageId, snapshot_id: snapshotId || undefined } })
}

export function fetchSeoImageRemediation({ tenantId, siteId, pageId, snapshotId }) {
  return client.get('/api/v1/seo/site-pages/image-remediation', { params: { tenant_id: tenantId, site_id: siteId, page_id: pageId, snapshot_id: snapshotId || undefined } })
}

export function fetchSeoImageRemediationWorkbench({ tenantId, siteId, q = '', reviewState = 'all', decision = 'all', page = 1, pageSize = 50 }) {
  return client.get('/api/v1/seo/site-pages/image-remediation-workbench', { params: { tenant_id: tenantId, site_id: siteId, q: q || undefined, review_state: reviewState, decision, page, page_size: pageSize } })
}

export function saveSeoImageRemediation(payload) {
  return client.put('/api/v1/seo/site-pages/image-remediation', payload)
}

export function generateSeoImageAltDrafts(payload) {
  return client.post('/api/v1/seo/site-pages/image-remediation/ai-drafts', payload, { timeout: 60000 })
}

export function fetchSeoImageRemediationHistory({ tenantId, siteId, pageId, beforeSnapshotId, limit = 20 }) {
  return client.get('/api/v1/seo/site-pages/image-remediation-history', { params: { tenant_id: tenantId, site_id: siteId, page_id: pageId, before_snapshot_id: beforeSnapshotId || undefined, limit } })
}

export function copySeoImageRemediation(payload) {
  return client.post('/api/v1/seo/site-pages/image-remediation/copy', payload)
}

export function fetchSeoImageRemediationReusePreview({ tenantId, siteId, pageId }) {
  return client.get('/api/v1/seo/site-pages/image-remediation-reuse-preview', { params: { tenant_id: tenantId, site_id: siteId, page_id: pageId } })
}

export function reuseSeoImageRemediation(payload) {
  return client.post('/api/v1/seo/site-pages/image-remediation/reuse', payload)
}

export function previewSeoRemediation(payload) {
  return client.post('/api/v1/seo/site-pages/ai-remediation', payload, { timeout: 95000 })
}

export function fetchSeoInternalLinks({ tenantId, siteId }) {
  return client.get('/api/v1/seo/internal-links', { params: { tenant_id: tenantId, site_id: siteId || undefined } })
}

export function crawlSeoInternalLinks({ tenantId, pageId }) {
  return client.post('/api/v1/seo/internal-links/crawl', null, { params: { tenant_id: tenantId, page_id: pageId }, timeout: 60000 })
}

export function fetchSeoBacklinks({ tenantId, siteId, status }) {
  return client.get('/api/v1/seo/backlinks', { params: { tenant_id: tenantId, site_id: siteId || undefined, status: status || undefined } })
}

export function createSeoBacklink(payload) {
  return client.post('/api/v1/seo/backlinks', payload)
}

export function fetchSeoCompetitors({ tenantId, siteId }) {
  return client.get('/api/v1/seo/competitors', { params: { tenant_id: tenantId, site_id: siteId } })
}

export function fetchSeoCompetitorRankings({ tenantId, siteId, device = 'desktop' }) {
  return client.get('/api/v1/seo/competitors/rankings', {
    params: { tenant_id: tenantId, site_id: siteId, device },
  })
}

export function createSeoCompetitor(payload) {
  return client.post('/api/v1/seo/competitors', payload)
}

export function createSeoCompetitorEvent(payload) {
  return client.post('/api/v1/seo/competitors/events', payload)
}

export function collectSeoCompetitor({ competitorId, tenantId, siteId, maxPages = 10 }) {
  return client.post(`/api/v1/seo/competitors/${competitorId}/collect`, {
    tenant_id: tenantId,
    site_id: siteId,
    max_pages: maxPages,
  }, { timeout: 180000 })
}

export function discoverSeoBacklinks(payload) {
  return client.post('/api/v1/seo/backlinks/discover', payload)
}
export function fetchSeoBacklinkSources({ tenantId, siteId }) {
  return client.get('/api/v1/seo/backlinks/discovery-sources', { params: { tenant_id: tenantId, site_id: siteId } })
}
export function verifySeoBacklink(id, payload) {
  return client.post(`/api/v1/seo/backlinks/${id}/verify`, payload)
}
export function monitorSeoBacklink(id, payload) {
  return client.patch(`/api/v1/seo/backlinks/${id}/monitoring`, payload)
}

export function importSeoBacklinkCsv({ tenantId, siteId, file, dryRun = true }) {
  const form = new FormData(); form.append('file',file)
  return client.post('/api/v1/seo/backlinks/import',form,{params:{tenant_id:tenantId,site_id:siteId,dry_run:dryRun}})
}
export function fetchSeoBacklinkAnalysis({tenantId,siteId}) {
  return client.get('/api/v1/seo/backlinks/analysis',{params:{tenant_id:tenantId,site_id:siteId}})
}
export function fetchSeoBacklinkIndexStatus({tenantId,siteId}) {
  return client.get('/api/v1/seo/backlinks/index-status',{params:{tenant_id:tenantId,site_id:siteId}})
}
export function querySeoBacklinkIndex(payload) {
  return client.post('/api/v1/seo/backlinks/query-index',payload,{timeout:30000})
}
export function fetchSeoBacklinkOpportunities({tenantId,siteId}) {
  return client.get('/api/v1/seo/backlinks/opportunities',{params:{tenant_id:tenantId,site_id:siteId}})
}
export function querySeoBacklinkOpportunities(payload) {
  return client.post('/api/v1/seo/backlinks/opportunities/query',payload,{timeout:120000})
}
export function downloadSeoPublicationMaterials(id,payload) {
  return client.post(`/api/v1/seo/content-distribution/publications/${id}/materials`,payload,{responseType:'blob',timeout:30000})
}


export const analyzeSeoQaSemantic = payload => requestSeoAi('/api/v1/seo/qa/planning/semantic', {
  ...payload, items: [...payload.items].sort((a,b) => a.id-b.id),
})
