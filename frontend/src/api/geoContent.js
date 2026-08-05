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

export function listGeoFacts(tenantId, params = {}) {
  return client.get('/api/v1/geo/facts', { params: { tenant_id: tenantId, ...params } })
}

export function createGeoFact(body) {
  return client.post('/api/v1/geo/facts', body)
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
    timeout: 90000,
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
