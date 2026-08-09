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

/** 优化业务 */
export function listGeoBusinesses(tenantId, params = {}) {
  return client.get('/api/v1/geo/optimization-businesses', {
    params: { tenant_id: tenantId, ...params },
  })
}

export function createGeoBusiness(body) {
  return client.post('/api/v1/geo/optimization-businesses', body)
}

export function patchGeoBusiness(tenantId, businessId, body) {
  return client.patch(`/api/v1/geo/optimization-businesses/${businessId}`, body, {
    params: { tenant_id: tenantId },
  })
}

/** 优化单元（关键词） */
export function listGeoUnits(tenantId, params = {}) {
  return client.get('/api/v1/geo/optimization-units', {
    params: { tenant_id: tenantId, ...params },
  })
}

export function createGeoUnit(body) {
  return client.post('/api/v1/geo/optimization-units', body)
}

export function patchGeoUnit(tenantId, unitId, body) {
  return client.patch(`/api/v1/geo/optimization-units/${unitId}`, body, {
    params: { tenant_id: tenantId },
  })
}

/** 运营告警（巡检 / token / 推送配置） */
export function fetchGeoOpsAlerts(tenantId) {
  return client.get('/api/v1/geo/ops-alerts', {
    params: { tenant_id: tenantId },
  })
}

/** 按天汇总（租户 / 业务 / 单元切片） */
export function listGeoDailyMetrics(tenantId, params = {}) {
  return client.get('/api/v1/geo/daily-metrics', {
    params: { tenant_id: tenantId, ...params },
  })
}

/** 下载日汇总 CSV（blob） */
export async function downloadGeoDailyMetricsCsv(tenantId, params = {}) {
  const data = await client.get('/api/v1/geo/daily-metrics', {
    params: { tenant_id: tenantId, format: 'csv', ...params },
    responseType: 'text',
    transformResponse: [(v) => v],
  })
  return typeof data === 'string' ? data : String(data ?? '')
}

/**
 * @param {number} tenantId
 * @param {{ metricDate?: string, dateFrom?: string, dateTo?: string, includeEmptySlices?: boolean }} [opts]
 */
export function rebuildGeoDailyMetrics(tenantId, opts = {}) {
  // 兼容旧调用：rebuildGeoDailyMetrics(tid, '2026-08-07')
  if (typeof opts === 'string') {
    opts = { metricDate: opts }
  }
  return client.post('/api/v1/geo/daily-metrics/rebuild', null, {
    params: {
      tenant_id: tenantId,
      metric_date: opts.metricDate || undefined,
      date_from: opts.dateFrom || undefined,
      date_to: opts.dateTo || undefined,
      include_empty_slices: opts.includeEmptySlices || undefined,
    },
    timeout: 120000,
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

export function fetchChannelPolishPrompts(tenantId) {
  return client.get('/api/v1/geo/channel-polish-prompts', {
    params: { tenant_id: tenantId },
  })
}

export function putChannelPolishPrompts(body) {
  return client.put('/api/v1/geo/channel-polish-prompts', body)
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

/** soft disable by default; hard=true deletes channel (+ cascade accounts) */
export function deleteGeoPublishingChannel(tenantId, channelId, hard = false) {
  return client.delete(`/api/v1/geo/publishing-channels/${channelId}`, {
    params: { tenant_id: tenantId, hard: !!hard },
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

export function startSocialOAuth(tenantId, accountId) {
  return client.post('/api/v1/geo/oauth/social/start', null, {
    params: { tenant_id: tenantId, account_id: accountId },
  })
}

export function refreshSocialOAuth(tenantId, accountId) {
  return client.post('/api/v1/geo/oauth/social/refresh', null, {
    params: { tenant_id: tenantId, account_id: accountId },
  })
}

export function verifySocialAccount(tenantId, accountId) {
  return client.post(`/api/v1/geo/channel-accounts/${accountId}/verify-social`, null, {
    params: { tenant_id: tenantId },
  })
}

export function patchGeoChannelAccount(tenantId, accountId, body) {
  return client.patch(`/api/v1/geo/channel-accounts/${accountId}`, body, {
    params: { tenant_id: tenantId },
  })
}

/** soft disable by default; pass hard=true to delete row */
export function deleteGeoChannelAccount(tenantId, accountId, hard = false) {
  return client.delete(`/api/v1/geo/channel-accounts/${accountId}`, {
    params: { tenant_id: tenantId, hard: !!hard },
  })
}

/** Normalize static page name → always under /geo/*.html */
export function normalizeStaticGeoPage(page = 'dashboard.html') {
  let p = String(page || 'dashboard.html').trim().replace(/^\/+/, '')
  // accept "dashboard", "geo/dashboard", "dashboard.html", "geo/dashboard.html"
  p = p.replace(/^geo\//, '')
  if (!p.endsWith('.html')) p = `${p}.html`
  // common aliases without geo/ prefix
  const aliases = {
    'editor.html': 'editor.html',
    'dashboard.html': 'dashboard.html',
    'articles.html': 'articles.html',
    'prompts.html': 'prompts.html',
    'sources.html': 'sources.html',
  }
  if (!aliases[p] && !p.includes('/')) {
    // keep as-is under geo/
  }
  return p
}

function staticGeoQuery(tenantId, extra = {}) {
  const qs = new URLSearchParams({ tenant_id: String(tenantId || 1), ...extra })
  const key = import.meta.env.VITE_API_KEY
  if (key && key !== 'CHANGE_ME') qs.set('api_key', key)
  if (import.meta.env.DEV) qs.set('api_origin', 'http://127.0.0.1:8011')
  return qs
}

/** Deep-link to static editor (local :5176/geo/… or prod /deal-sniper/geo/…). */
export function staticGeoEditorUrl(tenantId, taskId) {
  const qs = staticGeoQuery(tenantId)
  if (taskId) qs.set('task_id', String(taskId))
  if (import.meta.env.DEV) {
    return `http://127.0.0.1:5176/geo/editor.html?${qs}`
  }
  return `/deal-sniper/geo/editor.html?${qs}`
}

/**
 * Static workbench URL.
 * Local static server root is deal-sniper-prototype → paths are /geo/*.html
 * NOT /dashboard.html (that 404s).
 */
export function staticGeoWorkbenchUrl(page = 'dashboard.html', tenantId = 1) {
  const file = normalizeStaticGeoPage(page)
  const qs = staticGeoQuery(tenantId)
  if (import.meta.env.DEV) {
    return `http://127.0.0.1:5176/geo/${file}?${qs}`
  }
  return `/deal-sniper/geo/${file}?${qs}`
}

/** Human-readable error from API / axios Error for toasts. */
export function formatGeoError(err, fallback = '操作失败') {
  if (!err) return fallback
  const msg = err.message || err.detail || err
  if (typeof msg === 'string' && msg.trim() && msg !== '[object Object]') {
    return msg.trim()
  }
  if (Array.isArray(msg)) {
    return msg.map((d) => d?.msg || JSON.stringify(d)).join('; ') || fallback
  }
  if (typeof msg === 'object') {
    return msg.msg || msg.detail || JSON.stringify(msg) || fallback
  }
  return fallback
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

/** hard=false archive; hard=true physical delete (cascade article/variants) */
export function deleteGeoContentTask(tenantId, taskId, hard = false) {
  return client.delete(`/api/v1/geo/content-tasks/${taskId}`, {
    params: { tenant_id: tenantId, hard: !!hard },
  })
}

export function bindGeoTaskFacts(tenantId, taskId, factIds) {
  const ids = (factIds || [])
    .map((x) => Number(x))
    .filter((n) => Number.isFinite(n) && n > 0)
  return client.put(
    `/api/v1/geo/content-tasks/${taskId}/facts`,
    { fact_ids: ids },
    { params: { tenant_id: tenantId } },
  )
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
  const ids = (factIds || [])
    .map((x) => Number(x))
    .filter((n) => Number.isFinite(n) && n > 0)
  return client.post(
    `/api/v1/geo/content-tasks/${taskId}/retrieve-facts/apply`,
    { fact_ids: ids },
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

export function createGeoVariants(
  tenantId,
  taskId,
  channels = ['website', 'wechat', 'zhihu'],
  { useLlm = true } = {},
) {
  return client.post(
    `/api/v1/geo/content-tasks/${taskId}/variants`,
    { channels, use_llm: useLlm },
    {
      params: { tenant_id: tenantId },
      // LLM polish per channel can take a while
      timeout: 180000,
    },
  )
}

export function patchGeoVariant(tenantId, taskId, channel, body) {
  return client.patch(`/api/v1/geo/content-tasks/${taskId}/variants/${channel}`, body, {
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

export function pushGeoVariantWebhook(taskId, body) {
  return client.post(`/api/v1/geo/content-tasks/${taskId}/push`, body, {
    timeout: 60000,
  })
}

export function fetchTaskPushTargets(tenantId, taskId) {
  return client.get(`/api/v1/geo/content-tasks/${taskId}/push-targets`, {
    params: { tenant_id: tenantId },
  })
}

export function pushGeoVariantBatch(taskId, body) {
  return client.post(`/api/v1/geo/content-tasks/${taskId}/push-batch`, body, {
    timeout: 300000,
  })
}

export function fetchAutoPushStatus(tenantId) {
  return client.get('/api/v1/geo/publishing-channels/auto-push-status', {
    params: { tenant_id: tenantId },
  })
}

export function enableMultiMediaAutoPack(tenantId) {
  return client.post('/api/v1/geo/publishing-channels/enable-multi-media-auto', null, {
    params: { tenant_id: tenantId },
  })
}

export function submitGeoTaskReview(tenantId, taskId, note = null) {
  return client.post(
    `/api/v1/geo/content-tasks/${taskId}/submit-review`,
    { note },
    { params: { tenant_id: tenantId } },
  )
}

export function decideGeoTaskReview(tenantId, taskId, decision, note = null) {
  return client.post(
    `/api/v1/geo/content-tasks/${taskId}/review`,
    { decision, note },
    { params: { tenant_id: tenantId } },
  )
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

/** 可见度全自动巡检 */
export function fetchVisibilityPatrolSettings(tenantId) {
  return client.get('/api/v1/geo/visibility-patrol/settings', {
    params: { tenant_id: tenantId },
  })
}

export function putVisibilityPatrolSettings(body) {
  return client.put('/api/v1/geo/visibility-patrol/settings', body)
}

export function listVisibilityPatrolRuns(tenantId, limit = 20) {
  return client.get('/api/v1/geo/visibility-patrol/runs', {
    params: { tenant_id: tenantId, limit },
  })
}

export function getVisibilityPatrolRun(tenantId, runId) {
  return client.get(`/api/v1/geo/visibility-patrol/runs/${runId}`, {
    params: { tenant_id: tenantId },
  })
}

export function startVisibilityPatrolRun(body) {
  return client.post('/api/v1/geo/visibility-patrol/runs', body, {
    timeout: 120000,
  })
}

export function deleteVisibilityPatrolRun(tenantId, runId, force = false) {
  return client.delete(`/api/v1/geo/visibility-patrol/runs/${runId}`, {
    params: { tenant_id: tenantId, force: !!force },
  })
}

export function cleanupVisibilityPatrolRuns(tenantId, keepLatest = 20) {
  return client.post('/api/v1/geo/visibility-patrol/runs/cleanup', null, {
    params: { tenant_id: tenantId, keep_latest: keepLatest, only_terminal: true },
  })
}

export function fetchVisibilityPatrolOpsStatus(tenantId) {
  return client.get('/api/v1/geo/visibility-patrol/ops-status', {
    params: { tenant_id: tenantId },
  })
}

export function fetchVisibilityPeriodDiff(tenantId, windows) {
  return client.get('/api/v1/geo/visibility-period-diff', {
    params: { tenant_id: tenantId, ...windows },
  })
}

export function fetchChannelBlueprint(tenantId, group = null) {
  return client.get('/api/v1/geo/channel-blueprint', {
    params: { tenant_id: tenantId, group: group || undefined },
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

export function deleteGeoAnswerSnapshot(tenantId, snapshotId) {
  return client.delete(`/api/v1/geo/answer-snapshots/${snapshotId}`, {
    params: { tenant_id: tenantId },
  })
}

export function listGeoMediaPlacements(tenantId) {
  return client.get('/api/v1/geo/media-placements', {
    params: { tenant_id: tenantId },
  })
}

export function createGeoMediaPlacement(body) {
  return client.post('/api/v1/geo/media-placements', body)
}

export function patchGeoMediaPlacement(tenantId, placementId, body) {
  return client.patch(`/api/v1/geo/media-placements/${placementId}`, body, {
    params: { tenant_id: tenantId },
  })
}

export function deleteGeoMediaPlacement(tenantId, placementId) {
  return client.delete(`/api/v1/geo/media-placements/${placementId}`, {
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
