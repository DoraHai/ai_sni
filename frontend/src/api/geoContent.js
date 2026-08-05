import client from './client'

export function geoContentHealth() {
  return client.get('/api/v1/geo/content-health')
}

export function fetchGeoContentStats(tenantId) {
  return client.get('/api/v1/geo/content-stats', { params: { tenant_id: tenantId } })
}

export function listGeoPrompts(tenantId, statusOrParams, maybeParams) {
  const params =
    statusOrParams && typeof statusOrParams === 'object'
      ? { tenant_id: tenantId, ...statusOrParams }
      : { tenant_id: tenantId, status: statusOrParams, ...(maybeParams || {}) }
  return client.get('/api/v1/geo/prompts', { params })
}

export function createGeoPrompt(body) {
  return client.post('/api/v1/geo/prompts', body)
}

export function patchGeoPrompt(tenantId, promptId, body) {
  return client.patch(`/api/v1/geo/prompts/${promptId}`, body, {
    params: { tenant_id: tenantId },
  })
}

export function listGeoFacts(tenantId, params = {}) {
  return client.get('/api/v1/geo/facts', { params: { tenant_id: tenantId, ...params } })
}

export function createGeoFact(body) {
  return client.post('/api/v1/geo/facts', body)
}

export function patchGeoFact(tenantId, factId, body) {
  return client.patch(`/api/v1/geo/facts/${factId}`, body, {
    params: { tenant_id: tenantId },
  })
}

export function verifyGeoFact(tenantId, factId) {
  return client.post(`/api/v1/geo/facts/${factId}/verify`, null, {
    params: { tenant_id: tenantId },
  })
}

export function fetchGeoAiSettings(tenantId) {
  return client.get('/api/v1/geo/ai-settings', { params: { tenant_id: tenantId } })
}

export function putGeoAiSettings(body) {
  return client.put('/api/v1/geo/ai-settings', body)
}

export function testGeoAiSettings(tenantId) {
  return client.post('/api/v1/geo/ai-settings/test', {}, {
    params: { tenant_id: tenantId },
    timeout: 60000,
  })
}

export function putGeoTrackingEngines(tenantId, items) {
  return client.put('/api/v1/geo/tracking-engines', {
    tenant_id: tenantId,
    items,
  })
}

export function listGeoPublishingChannels(tenantId, enabledOnly = false) {
  return client.get('/api/v1/geo/publishing-channels', {
    params: { tenant_id: tenantId, enabled_only: enabledOnly },
  })
}

export function createGeoPublishingChannel(body) {
  return client.post('/api/v1/geo/publishing-channels', body)
}

export function patchGeoPublishingChannel(tenantId, channelId, body) {
  return client.patch(`/api/v1/geo/publishing-channels/${channelId}`, body, {
    params: { tenant_id: tenantId },
  })
}

export function listGeoChannelAccounts(tenantId, channelId) {
  return client.get('/api/v1/geo/channel-accounts', {
    params: { tenant_id: tenantId, ...(channelId ? { channel_id: channelId } : {}) },
  })
}

export function createGeoChannelAccount(body) {
  return client.post('/api/v1/geo/channel-accounts', body)
}

/** Deep-link to static editor (plan B: editor last). */
export function staticGeoEditorUrl(tenantId, taskId) {
  const qs = new URLSearchParams({ tenant_id: String(tenantId) })
  if (taskId) qs.set('task_id', String(taskId))
  const key = import.meta.env.VITE_API_KEY
  if (key) qs.set('api_key', key)
  if (import.meta.env.DEV) {
    qs.set('api_origin', 'http://127.0.0.1:8011')
    return `http://127.0.0.1:5176/geo/editor.html?${qs}`
  }
  return `/deal-sniper/geo/editor.html?${qs}`
}

export function staticGeoWorkbenchUrl(page = 'dashboard.html', tenantId = 1) {
  const qs = new URLSearchParams({ tenant_id: String(tenantId) })
  const key = import.meta.env.VITE_API_KEY
  if (key) qs.set('api_key', key)
  if (import.meta.env.DEV) {
    qs.set('api_origin', 'http://127.0.0.1:8011')
    return `http://127.0.0.1:5176/geo/${page}?${qs}`
  }
  return `/deal-sniper/geo/${page}?${qs}`
}

export function listGeoContentTasks(tenantId, params = {}) {
  return client.get('/api/v1/geo/content-tasks', { params: { tenant_id: tenantId, ...params } })
}

export function getGeoContentTask(tenantId, taskId) {
  return client.get(`/api/v1/geo/content-tasks/${taskId}`, { params: { tenant_id: tenantId } })
}

export function createGeoContentTask(body) {
  return client.post('/api/v1/geo/content-tasks', body)
}

export function bindGeoTaskFacts(tenantId, taskId, factIds) {
  return client.put(`/api/v1/geo/content-tasks/${taskId}/facts`, { fact_ids: factIds }, {
    params: { tenant_id: tenantId },
  })
}

export function generateGeoContentTask(tenantId, taskId) {
  return client.post(`/api/v1/geo/content-tasks/${taskId}/generate`, null, {
    params: { tenant_id: tenantId },
    timeout: 120000,
  })
}

export function saveGeoArticle(tenantId, taskId, body) {
  return client.put(`/api/v1/geo/content-tasks/${taskId}/article`, body, {
    params: { tenant_id: tenantId },
  })
}

export function fetchGeoBriefCatalog() {
  return client.get('/api/v1/geo/content-brief-catalog')
}

export function lintGeoContentTask(tenantId, taskId) {
  return client.post(`/api/v1/geo/content-tasks/${taskId}/lint`, null, {
    params: { tenant_id: tenantId },
  })
}

export function suggestGeoTaskBrief(tenantId, taskId, body = {}) {
  return client.post(`/api/v1/geo/content-tasks/${taskId}/suggest-brief`, body, {
    params: { tenant_id: tenantId },
    timeout: 90000,
  })
}

export function retrieveGeoTaskFacts(tenantId, taskId, body = {}) {
  return client.post(`/api/v1/geo/content-tasks/${taskId}/retrieve-facts`, body, {
    params: { tenant_id: tenantId },
  })
}

export function applyGeoRetrievedFacts(tenantId, taskId, factIds) {
  return client.post(
    `/api/v1/geo/content-tasks/${taskId}/retrieve-facts/apply`,
    { fact_ids: factIds },
    { params: { tenant_id: tenantId } },
  )
}

export function patchGeoContentTask(tenantId, taskId, body) {
  return client.patch(`/api/v1/geo/content-tasks/${taskId}`, body, {
    params: { tenant_id: tenantId },
  })
}

export function checkGeoContentTask(tenantId, taskId, requireChannels = false) {
  return client.post(`/api/v1/geo/content-tasks/${taskId}/check`, null, {
    params: { tenant_id: tenantId, require_channels: requireChannels },
  })
}

export function aiReviewGeoContentTask(tenantId, taskId, body = { persist: true }) {
  return client.post(`/api/v1/geo/content-tasks/${taskId}/ai-review`, body, {
    params: { tenant_id: tenantId },
    timeout: 120000,
  })
}

export function createGeoVariants(tenantId, taskId, channels = ['website', 'wechat', 'zhihu']) {
  return client.post(`/api/v1/geo/content-tasks/${taskId}/variants`, { channels }, {
    params: { tenant_id: tenantId },
  })
}

export function exportGeoVariant(tenantId, taskId, channel = 'website') {
  return client.get(`/api/v1/geo/content-tasks/${taskId}/export`, {
    params: { tenant_id: tenantId, channel },
  })
}

export function publishGeoVariant(taskId, body) {
  return client.post(`/api/v1/geo/content-tasks/${taskId}/publications`, body)
}

export function applyGeoContentPatch(tenantId, taskId, code, authorName) {
  return client.post(`/api/v1/geo/content-tasks/${taskId}/apply-patch`, {
    code,
    author_name: authorName || null,
  }, { params: { tenant_id: tenantId } })
}

export function createGeoTaskFromDiagnosis(body) {
  return client.post('/api/v1/geo/content-tasks/from-diagnosis', body)
}

export function listGeoAnswerSnapshots(tenantId, params = {}) {
  return client.get('/api/v1/geo/answer-snapshots', {
    params: { tenant_id: tenantId, ...params },
  })
}

export function createGeoAnswerSnapshot(body) {
  return client.post('/api/v1/geo/answer-snapshots', body)
}

export function patchGeoAnswerSnapshot(tenantId, snapshotId, body) {
  return client.patch(`/api/v1/geo/answer-snapshots/${snapshotId}`, body, {
    params: { tenant_id: tenantId },
  })
}

export function probeGeoAnswerSnapshot(body) {
  return client.post('/api/v1/geo/answer-snapshots/probe', body, { timeout: 90000 })
}

export function probeGeoAnswerSnapshotBatch(body) {
  return client.post('/api/v1/geo/answer-snapshots/probe-batch', body, { timeout: 300000 })
}

export function extractGeoAnswerSnapshotUrls(body) {
  return client.post('/api/v1/geo/answer-snapshots/extract-urls', body)
}

export function suggestGeoAnswerSnapshotFields(body) {
  return client.post('/api/v1/geo/answer-snapshots/suggest-fields', body, { timeout: 90000 })
}

export function listGeoTrackingEngines(tenantId, enabledOnly = false) {
  return client.get('/api/v1/geo/tracking-engines', {
    params: { tenant_id: tenantId, enabled_only: enabledOnly },
  })
}

export function fetchGeoCitationInsights(tenantId) {
  return client.get('/api/v1/geo/citation-insights', {
    params: { tenant_id: tenantId },
  })
}

export function fetchGeoCompetitorInsights(tenantId) {
  return client.get('/api/v1/geo/competitor-insights', {
    params: { tenant_id: tenantId },
  })
}

export function fetchGeoEvaluationInsights(tenantId) {
  return client.get('/api/v1/geo/evaluation-insights', {
    params: { tenant_id: tenantId },
  })
}

export function fetchGeoDeliverablesPack(tenantId, params = {}) {
  return client.get('/api/v1/geo/deliverables/pack', {
    params: { tenant_id: tenantId, ...params },
  })
}

/** Absolute URL for Markdown download (uses same auth headers via browser navigation only if cookie; prefer blob fetch). */
export async function downloadGeoDeliverablesMarkdown(tenantId, params = {}) {
  const data = await client.get('/api/v1/geo/deliverables/pack', {
    params: { tenant_id: tenantId, format: 'md', ...params },
    responseType: 'text',
    transformResponse: [(v) => v],
  })
  return typeof data === 'string' ? data : String(data ?? '')
}
