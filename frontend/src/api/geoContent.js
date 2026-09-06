import client from './client'

export function geoContentHealth() {
  return client.get('/api/v1/geo/content-health')
}

export function fetchGeoContentStats(tenantId) {
  return client.get('/api/v1/geo/content-stats', { params: { tenant_id: tenantId } })
}

/** 统一品牌提及率（观察期 + 样本构成） */
export function fetchBrandMentionMetric(tenantId, params = {}) {
  return client.get('/api/v1/geo/metrics/brand-mention', {
    params: { tenant_id: tenantId, ...params },
  })
}

export function fetchGeoMetricDictionary() {
  return client.get('/api/v1/geo/metric-dictionary')
}

export function listCompetitorAliases(tenantId) {
  return client.get('/api/v1/geo/competitor-aliases', {
    params: { tenant_id: tenantId },
  })
}

export function putCompetitorAliases(tenantId, body) {
  return client.put('/api/v1/geo/competitor-aliases', body, {
    params: { tenant_id: tenantId },
  })
}

export function listDeliverableArchives(tenantId, limit = 30) {
  return client.get('/api/v1/geo/deliverables/archives', {
    params: { tenant_id: tenantId, limit },
  })
}

export function createDeliverableArchive(tenantId, body) {
  return client.post('/api/v1/geo/deliverables/archives', body, {
    params: { tenant_id: tenantId },
  })
}

export function getDeliverableArchive(tenantId, archiveId) {
  return client.get(`/api/v1/geo/deliverables/archives/${archiveId}`, {
    params: { tenant_id: tenantId },
  })
}

export function getDeliverableByShareToken(shareToken) {
  return client.get(`/api/v1/geo/deliverables/share/${shareToken}`)
}

export function fetchGeoWeeklyInsights(tenantId, params = {}) {
  return client.get('/api/v1/geo/weekly-insights', {
    params: { tenant_id: tenantId, ...params },
  })
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

/** Import prompt rows in one server-validated CSV batch. */
export function importGeoPromptsCsv(tenantId, file) {
  const form = new FormData()
  form.append('file', file)
  return client.post('/api/v1/geo/prompts/import-csv', form, {
    params: { tenant_id: tenantId },
    timeout: 120000,
  })
}

export function patchGeoPrompt(tenantId, promptId, body) {
  return client.patch(`/api/v1/geo/prompts/${promptId}`, body, {
    params: { tenant_id: tenantId },
  })
}

/** 智能意图词推荐（百度/Google 下拉拓词，不自动入库） */
export function expandGeoPromptCandidates(body) {
  return client.post('/api/v1/geo/prompts/expand-candidates', body, { timeout: 120000 })
}

/** 将拓词候选确认为意图词入库 */
export function promoteGeoPromptCandidates(body) {
  return client.post('/api/v1/geo/prompts/promote-candidates', body)
}

/** 话题热度：意图词/问题组在快照中的提问频次趋势 */
export function fetchGeoTopicHeat(tenantId, params = {}) {
  return client.get('/api/v1/geo/topic-heat', {
    params: { tenant_id: tenantId, ...params },
  })
}

/** AI 动态与策略影响建议 */
export function fetchGeoAiTrends(tenantId, params = {}) {
  return client.get('/api/v1/geo/ai-trends', {
    params: { tenant_id: tenantId, ...params },
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

/** Import fact rows in one server-validated CSV batch. */
export function importGeoFactsCsv(tenantId, file) {
  const form = new FormData()
  form.append('file', file)
  return client.post('/api/v1/geo/facts/import', form, {
    params: { tenant_id: tenantId },
    timeout: 120000,
  })
}

export function patchGeoFact(tenantId, factId, body) {
  return client.patch(`/api/v1/geo/facts/${factId}`, body, {
    params: { tenant_id: tenantId },
  })
}

export function verifyGeoFact(tenantId, factId, body = {}) {
  return client.post(`/api/v1/geo/facts/${factId}/verify`, body, {
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
  // 产品页禁止把 API Key 放进 URL（历史/Referer/代理日志）。静态壳仅保留 tenant 定位。
  const tid = Number(tenantId)
  const qs = new URLSearchParams({
    tenant_id: String(Number.isFinite(tid) && tid > 0 ? tid : ''),
    ...extra,
  })
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

export function optimizeGeoArticle(taskId, body) {
  return client.post(`/api/v1/geo/content-tasks/${taskId}/optimize`, body)
}

/** 发布后效果：引用命中 + 意图词发布前后提及率 */
export function fetchGeoContentTaskImpact(tenantId, taskId, windowDays = 14) {
  return client.get(`/api/v1/geo/content-tasks/${taskId}/impact`, {
    params: { tenant_id: tenantId, window_days: windowDays },
  })
}

export function fetchGapWorkbench(tenantId, params = {}) {
  return client.get('/api/v1/geo/gap-workbench', {
    params: { tenant_id: tenantId, ...params },
  })
}

/** 历史快照 publication 归因回填 */
export function backfillAttribution(tenantId, { limit = 500, onlyEmpty = true } = {}) {
  return client.post('/api/v1/geo/attribution/backfill', null, {
    params: {
      tenant_id: tenantId,
      limit,
      only_empty: !!onlyEmpty,
    },
    timeout: 120000,
  })
}

export function createTasksFromGaps(tenantId, promptIds) {
  return client.post('/api/v1/geo/gap-workbench/create-tasks', {
    tenant_id: tenantId,
    prompt_ids: promptIds,
  })
}

export function listOptimizationPeriods(tenantId, params = {}) {
  return client.get('/api/v1/geo/optimization-periods', {
    params: { tenant_id: tenantId, ...params },
  })
}

export function createOptimizationPeriod(body) {
  return client.post('/api/v1/geo/optimization-periods', body)
}

export function getOptimizationPeriod(tenantId, periodId) {
  return client.get(`/api/v1/geo/optimization-periods/${periodId}`, {
    params: { tenant_id: tenantId },
  })
}

export function closeOptimizationPeriod(tenantId, periodId) {
  return client.post(`/api/v1/geo/optimization-periods/${periodId}/close`, null, {
    params: { tenant_id: tenantId },
  })
}

export function createGeoSourceOpportunityTask(body) {
  return client.post('/api/v1/geo/content-tasks/from-source-opportunity', body)
}

export function createGeoContentTask(body) {
  return client.post('/api/v1/geo/content-tasks', body)
}

/** Preview an uploaded article before associating it with a GEO question. */
export function previewGeoArticleImportFile(tenantId, file) {
  const form = new FormData()
  form.append('file', file)
  return client.post('/api/v1/geo/content-imports/preview-file', form, {
    params: { tenant_id: tenantId },
    timeout: 120000,
  })
}

/** Fetch and normalize an existing article URL before importing it. */
export function previewGeoArticleImportUrl(tenantId, url) {
  return client.post(
    '/api/v1/geo/content-imports/preview-url',
    { tenant_id: tenantId, url },
    { timeout: 120000 },
  )
}

/** Create a content task from an already-authored article. */
export function createGeoArticleImportTask(payload) {
  return client.post('/api/v1/geo/content-imports/create-task', payload)
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

export function generateGeoContentTask(tenantId, taskId, { runAsync = true } = {}) {
  return client.post(`/api/v1/geo/content-tasks/${taskId}/generate`, null, {
    params: { tenant_id: tenantId, run_async: !!runAsync },
    timeout: runAsync ? 30000 : 180000,
  })
}

export function getGeoAsyncJob(tenantId, jobId) {
  return client.get(`/api/v1/geo/async-jobs/${jobId}`, {
    params: { tenant_id: tenantId },
  })
}

export function cancelGeoAsyncJob(tenantId, jobId) {
  return client.post(`/api/v1/geo/async-jobs/${jobId}/cancel`, null, {
    params: { tenant_id: tenantId },
  })
}

export function listGeoAsyncJobs(tenantId, params = {}) {
  return client.get('/api/v1/geo/async-jobs', {
    params: { tenant_id: tenantId, ...params },
  })
}

/** Poll async job until terminal status */
export async function waitGeoAsyncJob(
  tenantId,
  jobId,
  { intervalMs = 2500, maxMs = 45 * 60 * 1000, onTick, isCurrent = () => true } = {},
) {
  // Align with backend stale running window (~45min); do not fail UI while job still runs
  const start = Date.now()
  while (Date.now() - start < maxMs) {
    if (!isCurrent()) return null
    const job = await getGeoAsyncJob(tenantId, jobId)
    if (!isCurrent()) return null
    if (typeof onTick === 'function') onTick(job)
    if (['succeeded', 'failed', 'cancelled'].includes(job.status)) return job
    await new Promise((r) => setTimeout(r, intervalMs))
  }
  // Soft timeout: return last known job so UI can say「转后台继续」
  if (!isCurrent()) return null
  try {
    return await getGeoAsyncJob(tenantId, jobId)
  } catch {
    throw new Error('异步任务仍在后台运行，请稍后刷新查看结果')
  }
}

export function previewGeoOnboarding(body) {
  return client.post('/api/v1/geo/onboarding/preview', body, { timeout: 120000 })
}

export function applyGeoOnboarding(body) {
  return client.post('/api/v1/geo/onboarding/apply', body, { timeout: 60000 })
}

export function fetchOnboardingReadiness(tenantId) {
  return client.get('/api/v1/geo/onboarding/readiness', {
    params: { tenant_id: tenantId },
  })
}

export function fetchBusinessDashboard(tenantId, businessId, days = 14) {
  return client.get(`/api/v1/geo/optimization-businesses/${businessId}/dashboard`, {
    params: { tenant_id: tenantId, days },
  })
}

export function fetchMonitoringStance(tenantId) {
  return client.get('/api/v1/geo/monitoring-stance', {
    params: { tenant_id: tenantId },
  })
}

export function putMonitoringStance(tenantId, stance) {
  return client.put('/api/v1/geo/monitoring-stance', {
    tenant_id: tenantId,
    monitoring_stance: stance,
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
  { useLlm = true, runAsync = true } = {},
) {
  return client.post(
    `/api/v1/geo/content-tasks/${taskId}/variants`,
    { channels, use_llm: useLlm },
    {
      params: { tenant_id: tenantId, run_async: !!runAsync },
      timeout: runAsync ? 30000 : 180000,
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

export function pushGeoVariantBatch(taskId, body, { runAsync = true } = {}) {
  return client.post(`/api/v1/geo/content-tasks/${taskId}/push-batch`, body, {
    params: { run_async: !!runAsync },
    timeout: runAsync ? 30000 : 300000,
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

export function decideGeoTaskReview(tenantId, taskId, decision, note = null, expected = {}) {
  return client.post(
    `/api/v1/geo/content-tasks/${taskId}/review`,
    { decision, note, ...expected },
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

export function checkGeoAnswerSnapshotCitations(body) {
  return client.post('/api/v1/geo/answer-snapshots/check-citations', body, { timeout: 60000 })
}

export function listGeoTrackingEngines(tenantId, enabledOnly = false) {
  return client.get('/api/v1/geo/tracking-engines', {
    params: { tenant_id: tenantId, enabled_only: enabledOnly },
  })
}

export function fetchGeoCitationInsights(tenantId, params = {}) {
  return client.get('/api/v1/geo/citation-insights', {
    params: { tenant_id: tenantId, ...params },
  })
}

export function fetchGeoCompetitorInsights(tenantId) {
  return client.get('/api/v1/geo/competitor-insights', {
    params: { tenant_id: tenantId },
  })
}

export function fetchGeoCompetitorCompare(tenantId) {
  return client.get('/api/v1/geo/competitor-insights/compare', {
    params: { tenant_id: tenantId },
  })
}

export function fetchGeoCompetitorDaily(tenantId, params = {}) {
  return client.get('/api/v1/geo/competitor-insights/daily', {
    params: { tenant_id: tenantId, ...params },
  })
}

export function fetchGeoCompetitorTrace(tenantId, name) {
  return client.get('/api/v1/geo/competitor-insights/trace', {
    params: { tenant_id: tenantId, name },
  })
}

export function searchGeoCompetitorWeb(tenantId, name) {
  return client.post('/api/v1/geo/competitor-insights/web-search', null, {
    params: { tenant_id: tenantId, name },
    timeout: 60000,
  })
}

export function createGeoCompetitorReport(body) {
  return client.post('/api/v1/geo/competitor-insights/report', body)
}

export function listGeoCompetitorReports(tenantId, params = {}) {
  return client.get('/api/v1/geo/competitor-reports', {
    params: { tenant_id: tenantId, ...params },
  })
}

export function getGeoCompetitorReport(tenantId, reportId) {
  return client.get(`/api/v1/geo/competitor-reports/${reportId}`, {
    params: { tenant_id: tenantId },
  })
}

export function saveGeoCompetitorReport(body) {
  return client.post('/api/v1/geo/competitor-reports', body)
}

export function patchGeoCompetitorReport(tenantId, reportId, body) {
  return client.patch(`/api/v1/geo/competitor-reports/${reportId}`, body, {
    params: { tenant_id: tenantId },
  })
}

export function confirmGeoCompetitorReport(tenantId, reportId) {
  return client.post(`/api/v1/geo/competitor-reports/${reportId}/confirm`, null, {
    params: { tenant_id: tenantId },
  })
}

export function archiveGeoCompetitorReport(tenantId, reportId) {
  return client.post(`/api/v1/geo/competitor-reports/${reportId}/archive`, null, {
    params: { tenant_id: tenantId },
  })
}

export function createTaskFromCompetitorReport(tenantId, reportId) {
  return client.post(`/api/v1/geo/competitor-reports/${reportId}/create-task`, null, {
    params: { tenant_id: tenantId },
  })
}

export function restoreGeoCompetitorReport(tenantId, reportId, versionNo) {
  return client.post(`/api/v1/geo/competitor-reports/${reportId}/restore`, null, {
    params: { tenant_id: tenantId, version_no: versionNo },
  })
}

export async function exportGeoCompetitorReport(tenantId, reportId, format = 'md') {
  const data = await client.get(`/api/v1/geo/competitor-reports/${reportId}/export`, {
    params: { tenant_id: tenantId, format },
    responseType: 'text',
    transformResponse: [(v) => v],
  })
  return typeof data === 'string' ? data : String(data ?? '')
}

export function auditGeoSitemap(tenantId, websiteUrl) {
  return client.post('/api/v1/geo/onboarding/sitemap-audit', null, {
    params: { tenant_id: tenantId, website_url: websiteUrl },
    timeout: 180000,
  })
}

export function createTasksFromSitemapAudit(tenantId, items) {
  return client.post(
    '/api/v1/geo/onboarding/sitemap-audit/create-tasks',
    { items },
    { params: { tenant_id: tenantId } },
  )
}

export function createGeoCompetitorRecTasks(body) {
  return client.post('/api/v1/geo/competitor-insights/create-tasks', body)
}

export function fetchGeoEvaluationInsights(tenantId, params = {}) {
  return client.get('/api/v1/geo/evaluation-insights', {
    params: { tenant_id: tenantId, ...params },
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

export function listGeoDeliveries(taskId, tenantId) {
  return client.get(`/api/v1/geo/content-tasks/${taskId}/deliveries`, { params: { tenant_id: tenantId } })
}

export function resolveGeoDelivery(taskId, variantId, key, payload) {
  return client.post(`/api/v1/geo/content-tasks/${taskId}/deliveries/${variantId}/${key}/resolve`, payload)
}

export function listGeoPublicationMonitor(taskId, tenantId) {
  return client.get(`/api/v1/geo/content-tasks/${taskId}/publication-monitor`, { params: { tenant_id: tenantId } })
}
export function checkGeoPublicationMonitor(taskId, tenantId, publicationId) {
  return client.post(`/api/v1/geo/content-tasks/${taskId}/publication-monitor/${publicationId}/check`, null, { params: { tenant_id: tenantId } })
}
