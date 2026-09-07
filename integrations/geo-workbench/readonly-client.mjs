/**
 * GEO phase-one read-only consumer.
 *
 * The host injects an authenticated GET-only transport and verified identity
 * context. This module neither stores credentials nor starts GEO work.
 */

import {
  answerMetricDisplay,
  answerSourceDisplay,
  officialMetricDisplay,
  officialWeekDisplay,
} from '../../frontend/src/utils/geoWorkbenchDisplay.js'

const routes = Object.freeze({
  periodContext: '/api/v1/geo/integration/read/period-context',
  metrics: '/api/v1/geo/integration/metrics/snapshot',
  dictionary: '/api/v1/geo/integration/metrics/dictionary',
  answers: '/api/v1/geo/integration/read/answers',
  answerDetail: '/api/v1/geo/integration/read/answers/',
  questions: '/api/v1/geo/integration/read/questions',
})

const allowedFilters = Object.freeze({
  periodContext: new Set(), metrics: new Set(), dictionary: new Set(),
  answers: new Set(['promptId', 'engineKey', 'patrolRunId', 'sourceKind', 'capturedFrom', 'capturedTo', 'limit', 'cursor']),
  answerDetail: new Set(['snapshotId']),
  questions: new Set(['status', 'isBrandProbe', 'unitId', 'businessId', 'limit', 'beforeId']),
})
const coreMetricKeys = Object.freeze([
  'geo.visibility.ai_mention_count_7d',
  'geo.visibility.ai_mention_rate_7d',
  'geo.visibility.ai_visibility_score',
])

export class GeoReadonlyError extends Error {
  constructor(code, message) { super(message); this.name = 'GeoReadonlyError'; this.code = code }
}

function fail(code, message) { throw new GeoReadonlyError(code, message) }
function object(value) { return value !== null && typeof value === 'object' && !Array.isArray(value) }
function positive(value) { return Number.isSafeInteger(value) && value > 0 }
function finiteOrNull(value) { return value === null || (typeof value === 'number' && Number.isFinite(value)) }
function contract(condition) { if (!condition) fail('CONTRACT_MISMATCH', 'GEO 只读响应字段、范围或空值契约不匹配') }
function validWeekEnd(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const instant = new Date(`${value}T00:00:00Z`)
  return Number.isFinite(instant.valueOf()) && instant.toISOString().slice(0, 10) === value && instant.getUTCDay() === 1
}

function knownUrl(value, pathname, expected) {
  contract(typeof value === 'string' && value.startsWith('/') && !value.startsWith('//') && !/[\\#\s]/.test(value))
  const parsed = new URL(value, 'https://geo-read.invalid')
  contract(parsed.origin === 'https://geo-read.invalid' && parsed.pathname === pathname && value.split('?')[0] === pathname)
  contract(parsed.searchParams.size === Object.keys(expected).length)
  for (const [key, expectedValue] of Object.entries(expected)) {
    contract(parsed.searchParams.getAll(key).length === 1 && parsed.searchParams.get(key) === String(expectedValue))
  }
  for (const key of parsed.searchParams.keys()) contract(Object.hasOwn(expected, key))
  const rebuilt = new URLSearchParams()
  for (const [key, expectedValue] of Object.entries(expected)) rebuilt.set(key, String(expectedValue))
  return `${pathname}?${rebuilt}`
}

function query(context, params = {}, includeWeek = true) {
  const result = new URLSearchParams({ tenant_id: String(context.tenantId) })
  if (includeWeek) result.set('week_end', context.weekEnd)
  const names = {
    promptId: 'prompt_id', engineKey: 'engine_key', patrolRunId: 'patrol_run_id', sourceKind: 'source_kind',
    capturedFrom: 'captured_from', capturedTo: 'captured_to', limit: 'limit', cursor: 'cursor',
    status: 'status', isBrandProbe: 'is_brand_probe', unitId: 'unit_id', businessId: 'business_id', beforeId: 'before_id',
  }
  for (const [key, value] of Object.entries(params)) {
    if (key !== 'snapshotId' && value !== undefined) result.set(names[key], String(value))
  }
  return result
}

function fingerprint(params) {
  return JSON.stringify(Object.entries(params).filter(([key, value]) => key !== 'cursor' && value !== undefined).sort())
}

function validateFilters(resource, params) {
  if (!object(params) || Object.keys(params).some(key => !allowedFilters[resource].has(key))) fail('UNSUPPORTED_FILTER', '存在未审核的 GEO 只读筛选')
  for (const key of ['promptId', 'patrolRunId', 'snapshotId', 'unitId', 'businessId', 'limit', 'beforeId']) {
    if (Object.hasOwn(params, key) && !positive(params[key])) fail('INVALID_FILTER', `${key} 必须是正整数`)
  }
  if (params.limit > 200) fail('INVALID_FILTER', 'limit 超出接口上限')
  if (params.sourceKind !== undefined && !['real', 'manual', 'simulated', 'unknown'].includes(params.sourceKind)) fail('INVALID_FILTER', 'sourceKind 无效')
  for (const key of ['engineKey', 'status']) if (Object.hasOwn(params, key) && (typeof params[key] !== 'string' || !params[key].trim())) fail('INVALID_FILTER', `${key} 必须是非空字符串`)
  for (const key of ['capturedFrom', 'capturedTo']) {
    if (Object.hasOwn(params, key) && (typeof params[key] !== 'string' || !/(Z|[+-]\d{2}:\d{2})$/.test(params[key]) || !Number.isFinite(Date.parse(params[key])))) fail('INVALID_FILTER', `${key} 必须包含有效的明确时区`)
  }
  if (params.capturedFrom !== undefined && params.capturedTo !== undefined && Date.parse(params.capturedFrom) >= Date.parse(params.capturedTo)) fail('INVALID_FILTER', '回答观察区间必须起点早于终点')
  if (params.cursor !== undefined && (typeof params.cursor !== 'string' || !params.cursor || params.cursor.length > 4096)) fail('INVALID_FILTER', 'cursor 无效')
  if (params.isBrandProbe !== undefined && typeof params.isBrandProbe !== 'boolean') fail('INVALID_FILTER', 'isBrandProbe 必须是布尔值')
}

function validateRef(ref, type, tenantId) {
  contract(object(ref) && ref.module === 'geo' && ref.type === type && positive(ref.id))
  if (Object.hasOwn(ref, 'tenant_id')) contract(ref.tenant_id === tenantId)
}

function validatePeriod(data, active) {
  contract(object(data) && data.tenant_id === active.tenantId && data.week_end === active.weekEnd && data.timezone === 'Asia/Shanghai')
  contract(object(data.current) && object(data.previous) && object(data.comparison) && Array.isArray(data.metric_status))
  contract(data.current.closed === true && data.previous.closed === true && typeof data.comparison.comparable === 'boolean')
  const statusKeys = data.metric_status.map(row => row?.metric_key)
  contract(new Set(statusKeys).size === statusKeys.length && coreMetricKeys.every(key => statusKeys.includes(key)))
  knownUrl(data.metrics_url, routes.metrics, { tenant_id: active.tenantId, week_end: active.weekEnd })
  knownUrl(data.dictionary_url, routes.dictionary, { tenant_id: active.tenantId, week_end: active.weekEnd })
}

function validateMetric(item, active) {
  contract(object(item) && typeof item.metric_key === 'string' && item.metric_key.startsWith('geo.'))
  contract(finiteOrNull(item.value) && ['count', 'percent', 'score'].includes(item.unit))
  contract(typeof item.as_of === 'string' && item.as_of.slice(0, 10) === active.weekEnd)
  contract(item.trend_7d === null || (object(item.trend_7d) && (item.trend_7d.direction === null || ['up', 'down', 'flat'].includes(item.trend_7d.direction))
    && finiteOrNull(item.trend_7d.change_pct) && finiteOrNull(item.trend_7d.change_abs)))
}

function validateAnswer(item, active, detail = false) {
  validateRef(item?.ref, 'answer_snapshot', active.tenantId)
  contract(object(item.question) && positive(item.question.id) && object(item.engine) && typeof item.engine.key === 'string')
  contract(object(item.source) && ['real', 'manual', 'simulated', 'unknown'].includes(item.source.kind))
  contract(Array.isArray(item.metric_adoption) && object(item.sample_eligibility) && object(item.week_membership))
  const adoptionKeys = item.metric_adoption.map(row => row?.metric_key)
  contract(new Set(adoptionKeys).size === adoptionKeys.length && coreMetricKeys.every(key => adoptionKeys.includes(key)))
  contract(item.metric_adoption.every(row => object(row) && ['included', 'excluded', 'unavailable'].includes(row.status) && Array.isArray(row.reasons)))
  contract(item.captured_at === null || typeof item.captured_at === 'string')
  contract(item.captured_at_local === null || typeof item.captured_at_local === 'string')
  contract(['stored_utc', 'unknown'].includes(item.time_basis))
  if (detail) contract(typeof item.raw_text === 'string')
  knownUrl(item.detail_url, `${routes.answerDetail}${item.ref.id}`, { tenant_id: active.tenantId, week_end: active.weekEnd })
}

function answerMatches(item, params) {
  if (params.promptId !== undefined) contract(item.question.id === params.promptId)
  if (params.engineKey !== undefined) contract(item.engine.key === params.engineKey)
  if (params.sourceKind !== undefined) contract(item.source.kind === params.sourceKind)
  if (params.patrolRunId !== undefined) {
    contract(Array.isArray(item.relations) && item.relations.some(row => row?.relation === 'captured_by'
      && row.target?.module === 'geo' && row.target?.type === 'patrol_run' && row.target?.id === params.patrolRunId))
  }
  if (params.capturedFrom !== undefined || params.capturedTo !== undefined) {
    contract(typeof item.captured_at === 'string' && Number.isFinite(Date.parse(item.captured_at)))
    const captured = Date.parse(item.captured_at)
    if (params.capturedFrom !== undefined) contract(captured >= Date.parse(params.capturedFrom))
    if (params.capturedTo !== undefined) contract(captured < Date.parse(params.capturedTo))
  }
}

function validateQuestion(item, active) {
  validateRef(item?.ref, 'question', active.tenantId)
  contract(typeof item.current_text === 'string' && typeof item.language === 'string' && typeof item.status === 'string')
  contract(item.timestamp_source_timezone === 'unknown')
  // Deliberately retain source strings. Historical naive timestamps have no
  // trustworthy offset and must not be converted using the browser timezone.
  contract(typeof item.created_at === 'string' && typeof item.updated_at === 'string')
}

function questionMatches(item, params) {
  if (params.status !== undefined) contract(item.status === params.status)
  if (params.isBrandProbe !== undefined) contract(item.is_brand_probe === params.isBrandProbe)
  if (params.unitId !== undefined) contract(item.unit_ref?.module === 'geo' && item.unit_ref?.type === 'optimization_unit' && item.unit_ref?.id === params.unitId)
  if (params.businessId !== undefined) contract(item.business_ref?.module === 'geo' && item.business_ref?.type === 'optimization_business' && item.business_ref?.id === params.businessId)
}

export function createGeoReadonlyClient({ transport, onClear }) {
  if (typeof transport !== 'function' || typeof onClear !== 'function') throw new TypeError('Authenticated transport and a clearing callback are required')
  let context = null
  let revision = 0
  const pending = new Map()
  let period = null
  let metrics = null
  let dictionary = null
  const answers = new Map()
  const answerCursors = new Map()
  const answerPages = new Map()
  let answerFingerprint = null
  const questions = new Map()
  const questionCursors = new Map()
  const questionPages = new Map()
  let questionFingerprint = null

  function clearData() {
    period = null; metrics = null; dictionary = null
    answers.clear(); answerCursors.clear(); answerPages.clear(); answerFingerprint = null
    questions.clear(); questionCursors.clear(); questionPages.clear(); questionFingerprint = null
  }
  function abort(prefix) {
    for (const [key, controller] of pending) if (key.startsWith(prefix)) { controller.abort(); pending.delete(key) }
  }
  function invalidate() {
    revision++; context = null
    for (const controller of pending.values()) controller.abort()
    pending.clear(); clearData(); onClear()
  }
  function setContext(next) {
    invalidate()
    if (next === null) return
    if (!object(next) || !positive(next.tenantId) || !positive(next.userId) || !validWeekEnd(next.weekEnd)
      || typeof next.authorizationRevision !== 'string' || !next.authorizationRevision.trim()
      || !Array.isArray(next.allowedReads) || next.allowedReads.some(key => !Object.hasOwn(routes, key))) {
      fail('INVALID_CONTEXT', '需要已核验的客户、用户、完整周、权限版本和只读范围')
    }
    context = Object.freeze({ ...next, allowedReads: Object.freeze([...next.allowedReads]) })
  }

  function prepare(resource, params) {
    if (resource === 'answerDetail' && !answers.has(params.snapshotId)) fail('UNVERIFIED_REFERENCE', '须先在当前回答查询中核验 snapshotId')
    if (resource === 'answers') {
      const mark = fingerprint(params)
      if (params.cursor !== undefined) {
        if (answerFingerprint !== mark || answerCursors.get(params.cursor) !== mark) fail('CURSOR_CONTEXT_CHANGED', '游标与当前租户、周或筛选条件不匹配')
      } else {
        abort('answerDetail:'); answers.clear(); answerCursors.clear(); answerPages.clear(); answerFingerprint = mark
      }
    }
    if (resource === 'questions') {
      const mark = fingerprint({ ...params, beforeId: undefined })
      if (params.beforeId === undefined) { questions.clear(); questionCursors.clear(); questionPages.clear(); questionFingerprint = mark }
      else if (questionFingerprint !== mark || questionCursors.get(params.beforeId) !== mark) fail('CURSOR_CONTEXT_CHANGED', '问题分页与当前筛选条件不匹配')
    }
  }

  function route(resource, params, active) {
    if (resource === 'answerDetail') return `${routes.answerDetail}${params.snapshotId}?${query(active, {}, true)}`
    const includeWeek = resource !== 'questions'
    return `${routes[resource]}?${query(active, params, includeWeek)}`
  }

  function accept(resource, data, params, active) {
    if (resource === 'periodContext') { validatePeriod(data, active); period = data }
    else if (resource === 'metrics') {
      contract(Array.isArray(data)); data.forEach(item => validateMetric(item, active))
      const keys = data.map(item => item.metric_key)
      contract(new Set(keys).size === keys.length && coreMetricKeys.every(key => keys.includes(key)))
      metrics = data
    } else if (resource === 'dictionary') {
      contract(object(data) && Object.entries(data).every(([key, value]) => key.startsWith('geo.') && typeof value === 'string' && value.trim()))
      dictionary = data
    } else if (resource === 'answers') {
      contract(object(data) && data.tenant_id === active.tenantId && data.official_week_end === active.weekEnd && data.timezone === 'Asia/Shanghai')
      contract(object(data.pagination) && positive(data.pagination.limit) && typeof data.pagination.has_more === 'boolean' && Array.isArray(data.items))
      contract(data.pagination.limit === (params.limit ?? 50) && data.items.length <= data.pagination.limit)
      knownUrl(data.period_context_url, routes.periodContext, { tenant_id: active.tenantId, week_end: active.weekEnd })
      const next = data.pagination.next_cursor
      contract(next === null || (typeof next === 'string' && next.length > 0 && next.length <= 4096))
      contract(data.pagination.has_more === (next !== null))
      const pageKey = params.cursor ?? null
      const ids = data.items.map(item => item?.ref?.id)
      contract(new Set(ids).size === ids.length)
      const priorPage = answerPages.get(pageKey)
      if (priorPage) contract(JSON.stringify(priorPage.ids) === JSON.stringify(ids) && priorPage.next === next)
      else {
        contract(params.cursor === undefined || ids.every(id => !answers.has(id)))
        if (next !== null) {
          contract(next !== params.cursor)
          let probe = next
          const visited = new Set()
          while (probe !== null && !visited.has(probe)) {
            contract(probe !== params.cursor)
            visited.add(probe)
            probe = answerPages.get(probe)?.next ?? null
          }
          contract(probe === null)
        }
      }
      for (const item of data.items) { validateAnswer(item, active); answerMatches(item, params); answers.set(item.ref.id, item) }
      answerPages.set(pageKey, { ids, next })
      if (next !== null) answerCursors.set(next, answerFingerprint)
    } else if (resource === 'answerDetail') {
      contract(object(data) && data.tenant_id === active.tenantId && data.official_week_end === active.weekEnd)
      knownUrl(data.period_context_url, routes.periodContext, { tenant_id: active.tenantId, week_end: active.weekEnd })
      validateAnswer(data.item, active, true); contract(data.item.ref.id === params.snapshotId && answers.has(params.snapshotId))
      answers.set(params.snapshotId, data.item)
    } else if (resource === 'questions') {
      contract(object(data) && data.tenant_id === active.tenantId && object(data.pagination) && Array.isArray(data.items))
      contract(data.pagination.limit === (params.limit ?? 50) && typeof data.pagination.has_more === 'boolean')
      contract(data.items.length <= data.pagination.limit)
      if (params.beforeId !== undefined) contract(data.items.every(item => item.ref.id < params.beforeId))
      const next = data.pagination.next_before_id
      contract(next === null || positive(next)); contract(data.pagination.has_more === (next !== null))
      if (next !== null) {
        contract(data.items.length > 0 && next === data.items.at(-1).ref.id)
        if (params.beforeId !== undefined) contract(next < params.beforeId)
      }
      const pageKey = params.beforeId ?? null
      const ids = data.items.map(item => item?.ref?.id)
      contract(new Set(ids).size === ids.length)
      const priorPage = questionPages.get(pageKey)
      if (priorPage) contract(JSON.stringify(priorPage.ids) === JSON.stringify(ids) && priorPage.next === next)
      else contract(params.beforeId === undefined || ids.every(id => !questions.has(id)))
      for (const item of data.items) { validateQuestion(item, active); questionMatches(item, params); questions.set(item.ref.id, item) }
      questionPages.set(pageKey, { ids, next })
      if (next !== null) questionCursors.set(next, questionFingerprint)
    }
    return data
  }

  async function read(resource, params = {}) {
    if (!Object.hasOwn(routes, resource)) fail('UNSUPPORTED_RESOURCE', '不支持的 GEO 只读资源')
    if (!context || !context.allowedReads.includes(resource)) fail('NOT_AUTHORIZED', '尚未确认该 GEO 读取权限')
    validateFilters(resource, params); prepare(resource, params)
    const active = context
    const atRevision = revision
    const key = resource === 'answerDetail' ? `answerDetail:${params.snapshotId}` : resource
    pending.get(key)?.abort()
    const controller = new AbortController(); pending.set(key, controller)
    const stale = () => revision !== atRevision || controller.signal.aborted || pending.get(key) !== controller
    try {
      const response = await transport(route(resource, params, active), { method: 'GET', cache: 'no-store', signal: controller.signal })
      if (stale()) fail('STALE_RESPONSE', '已丢弃旧客户、权限、周或筛选结果')
      if (response.status === 401 || response.status === 403) { invalidate(); fail('ACCESS_REVOKED', 'GEO 只读权限、租户或模块资格已失效') }
      if (response.status === 404) fail('NOT_FOUND', '当前 GEO 关联对象不存在')
      if (!response.ok) fail('READ_FAILED', `GEO 只读接口失败（${response.status}），未回退为模拟或零值`)
      let data
      try { data = await response.json() } catch { if (stale()) fail('STALE_RESPONSE', '已丢弃旧 GEO 响应'); invalidate(); fail('CONTRACT_MISMATCH', 'GEO 响应不是有效 JSON') }
      if (stale()) fail('STALE_RESPONSE', '已丢弃旧客户、权限、周或筛选结果')
      try { return accept(resource, data, params, active) } catch (error) {
        invalidate(); if (error instanceof GeoReadonlyError) throw error
        fail('CONTRACT_MISMATCH', 'GEO 响应字段、范围或空值契约不匹配')
      }
    } catch (error) {
      if (!(error instanceof GeoReadonlyError) && stale()) fail('STALE_RESPONSE', '已丢弃旧 GEO 请求错误')
      if (!(error instanceof GeoReadonlyError)) fail('READ_FAILED', 'GEO 只读网络不可用，未回退为模拟或零值')
      throw error
    } finally { if (pending.get(key) === controller) pending.delete(key) }
  }

  function officialSnapshot() {
    if (!period || !metrics || !dictionary) fail('DATA_NOT_LOADED', '须先读取同一完整周的周期、正式指标和字典')
    if (metrics.some(item => typeof dictionary[item.metric_key] !== 'string' || !dictionary[item.metric_key].trim())) {
      fail('CONTRACT_MISMATCH', '每个 GEO 正式指标都必须有一句话口径说明')
    }
    return Object.freeze({
      week: officialWeekDisplay(period),
      metrics: metrics.map(item => officialMetricDisplay(item, period, dictionary[item.metric_key] ?? null)),
      source: 'geo_metrics_snapshot',
    })
  }

  function answerView(snapshotId, metricKey) {
    const item = answers.get(snapshotId)
    if (!item) fail('UNVERIFIED_REFERENCE', '当前回答查询中没有已核验的 snapshotId')
    return { item, source: answerSourceDisplay(item), metric: answerMetricDisplay(item, metricKey) }
  }

  return Object.freeze({ setContext, invalidate, read, officialSnapshot, answerView })
}
