/** SEM-only consumer. Supply the workspace's authenticated transport after
 * identity/module integration is verified. This module has no default network
 * transport, token storage, demo fallback, persistent cache or write endpoint.
 * Client gates are usability guards; the SEM server remains the authority.
 */
const routes = Object.freeze({
  report: { path: '/api/v1/dashboard/cockpit', source: 'kw_report_snapshots', dates: 'required', fields: [] },
  keywords: { path: '/api/v1/keywords/cockpit', source: 'keywords+kw_report_snapshots', dates: 'optional', fields: ['q', 'campaign_id', 'page', 'page_size'] },
  keywordDetail: { path: '/api/v1/keywords/cockpit/', source: 'kw_report_snapshots', dates: 'required', fields: ['keyword_id'] },
  searchTerms: { path: '/api/v1/search-terms/cockpit', source: 'search_term_reports', dates: 'none', fields: ['q', 'campaign_id', 'adgroup_id', 'page', 'page_size'] },
})

export class SemReadError extends Error {
  constructor(code, message) { super(message); this.name = 'SemReadError'; this.code = code }
}

function fail(code, message) { throw new SemReadError(code, message) }
function positive(value) { return Number.isSafeInteger(value) && value > 0 }
function nonnegativeInteger(value) { return Number.isSafeInteger(value) && value >= 0 }
function object(value) { return value !== null && typeof value === 'object' && !Array.isArray(value) }
function contract(condition) { if (!condition) fail('CONTRACT_MISMATCH', '响应字段、空值或范围契约不匹配') }
function validDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}
function validStamp(value) {
  return value === null || (typeof value === 'string' && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value)))
}
function nullableNumber(value) { return value === null || (typeof value === 'number' && Number.isFinite(value) && value >= 0) }
function nullableCount(value) { return value === null || nonnegativeInteger(value) }
function allNull(metrics) { return ['cost', 'click', 'impression', 'ctr', 'cpc'].every(key => metrics[key] === null) }
function validateMetrics(metrics) {
  contract(object(metrics) && ['cost', 'click', 'impression', 'ctr', 'cpc'].every(key => Object.hasOwn(metrics, key)))
  contract(nullableNumber(metrics.cost) && nullableCount(metrics.click) && nullableCount(metrics.impression))
  contract(metrics.ctr === null || (typeof metrics.ctr === 'number' && Number.isFinite(metrics.ctr) && metrics.ctr >= 0 && metrics.ctr <= 1))
  contract(nullableNumber(metrics.cpc))
  if (metrics.ctr !== null) contract(metrics.click !== null && metrics.impression > 0)
  if (metrics.cpc !== null) contract(metrics.cost !== null && metrics.click > 0)
}
function validateWindow(window, start, end, mode) {
  contract(object(window) && window.timezone === 'Asia/Shanghai' && window.inclusive === true)
  contract((window.start === null || validDate(window.start)) && (window.end === null || validDate(window.end)))
  if (window.start !== null && window.end !== null) contract(window.start <= window.end)
  if (start !== undefined) contract(window.start === start && window.end === end)
  if (mode !== undefined) contract(window.mode === mode)
}
function dateRange(start, end) {
  const dates = []
  for (let time = Date.parse(`${start}T00:00:00Z`), last = Date.parse(`${end}T00:00:00Z`); time <= last; time += 86400000) {
    dates.push(new Date(time).toISOString().slice(0, 10))
  }
  return dates
}
function validateCoverage(coverage, window, metrics) {
  contract(object(coverage) && ['observed', 'no_data'].includes(coverage.status) && coverage.completeness === 'unknown')
  contract(nonnegativeInteger(coverage.observed_days) && Array.isArray(coverage.missing_dates))
  contract(coverage.latest_report_date === null || validDate(coverage.latest_report_date))
  contract(validStamp(coverage.updated_at))
  const expected = window.start === null || window.end === null ? null : new Set(dateRange(window.start, window.end))
  contract(new Set(coverage.missing_dates).size === coverage.missing_dates.length)
  contract(coverage.missing_dates.every(date => validDate(date) && (!expected || expected.has(date))))
  if (expected) contract(coverage.observed_days + coverage.missing_dates.length === expected.size)
  if (coverage.status === 'no_data') {
    contract(coverage.observed_days === 0 && coverage.latest_report_date === null && coverage.updated_at === null)
    if (metrics) contract(allNull(metrics))
  } else contract(coverage.observed_days > 0 && coverage.latest_report_date !== null)
}
function validateUnits(units) {
  contract(object(units) && units.cost === 'CNY' && units.click === 'count' && units.impression === 'count' &&
    units.ctr === 'ratio' && units.cpc === 'CNY/click')
}
function validateAccountScope(scope, accountId) {
  contract(object(scope) && scope.mode === (accountId === undefined ? 'all' : 'single'))
  contract(scope.baidu_account_id === (accountId ?? null))
  for (const field of ['configured_account_ids', 'observed_account_ids']) if (Object.hasOwn(scope, field)) {
    contract(Array.isArray(scope[field]) && new Set(scope[field]).size === scope[field].length)
    contract(scope[field].every(id => field === 'observed_account_ids' ? id === null || positive(id) : positive(id)))
    if (accountId !== undefined) contract(scope[field].every(id => id === accountId))
    if (field === 'configured_account_ids' && accountId !== undefined) contract(scope[field].length === 1)
  }
  if (Object.hasOwn(scope, 'includes_unassigned')) contract(typeof scope.includes_unassigned === 'boolean')
}
function validatePhone(phone) {
  contract(object(phone) && phone.unit === 'count' && phone.source_field === 'ocpcConversionsDetail2' && phone.completeness === 'unknown')
  contract(['no_data', 'observed', 'partial', 'unavailable'].includes(phone.status))
  contract(nonnegativeInteger(phone.stored_rows) && nonnegativeInteger(phone.known_rows) && nonnegativeInteger(phone.unknown_rows))
  contract(phone.known_rows + phone.unknown_rows === phone.stored_rows)
  contract(phone.value === null || nonnegativeInteger(phone.value))
  contract(phone.known_subtotal === null || nonnegativeInteger(phone.known_subtotal))
  if (phone.status === 'no_data') contract(phone.stored_rows === 0 && phone.value === null && phone.known_subtotal === null)
  if (phone.status === 'observed') contract(phone.stored_rows > 0 && phone.known_rows === phone.stored_rows && phone.value === phone.known_subtotal)
  if (phone.status === 'partial') contract(phone.known_rows > 0 && phone.unknown_rows > 0 && phone.value === null && phone.known_subtotal !== null)
  if (phone.status === 'unavailable') contract(phone.stored_rows > 0 && phone.known_rows === 0 && phone.value === null && phone.known_subtotal === null)
}
function validateReport(data, params, detail = false) {
  validateWindow(data.window, params.start_date, params.end_date)
  validateMetrics(data.metrics)
  validateCoverage(data.coverage, data.window, data.metrics)
  contract(data.source_scope === 'keyword_report_only' && Array.isArray(data.accounts) && Array.isArray(data.trend) && Array.isArray(data.devices))
  const accountIds = new Set()
  for (const account of data.accounts) {
    contract(object(account) && (account.baidu_account_id === null || positive(account.baidu_account_id)) && !accountIds.has(account.baidu_account_id))
    accountIds.add(account.baidu_account_id)
    validateMetrics(account.metrics)
    validateCoverage(account.coverage, data.window, account.metrics)
  }
  if (params.baidu_account_id !== undefined) contract(accountIds.size === 1 && accountIds.has(params.baidu_account_id))
  if (Object.hasOwn(data.account_scope, 'includes_unassigned')) contract(data.account_scope.includes_unassigned === accountIds.has(null))
  const dates = dateRange(data.window.start, data.window.end)
  contract(data.trend.length === dates.length)
  const missing = []
  data.trend.forEach((row, index) => {
    contract(object(row) && row.date === dates[index] && ['observed', 'no_data'].includes(row.status))
    validateMetrics(row)
    if (row.status === 'no_data') { contract(allNull(row)); missing.push(row.date) } else contract(!allNull(row))
  })
  contract(JSON.stringify(missing) === JSON.stringify(data.coverage.missing_dates))
  const devices = new Set()
  for (const row of data.devices) {
    contract(object(row) && (row.device === null || Number.isSafeInteger(row.device)) && !devices.has(row.device) && typeof row.label === 'string')
    devices.add(row.device); validateMetrics(row)
  }
  if (!detail) contract(object(data.unavailable) && typeof data.unavailable.phone_button_clicks === 'string')
}
function validateKeywords(data, params) {
  const explicit = params.start_date !== undefined
  validateWindow(data.window, explicit ? params.start_date : undefined, explicit ? params.end_date : undefined,
    explicit ? 'explicit' : 'latest_report_7d')
  if (!explicit) {
    contract((data.window.start === null) === (data.window.end === null))
    if (data.window.start !== null) contract(dateRange(data.window.start, data.window.end).length === 7)
  }
  contract(object(data.filters) && data.filters.q === (params.q ?? null) && data.filters.campaign_id === (params.campaign_id ?? null))
  contract(data.page === (params.page ?? 1) && data.page_size === (params.page_size ?? 20) && nonnegativeInteger(data.total) && Array.isArray(data.items))
  contract(data.items.length <= data.page_size && (data.total !== 0 || data.items.length === 0))
  for (const item of data.items) {
    contract(object(item) && positive(item.keyword_id) && (item.baidu_account_id === null || positive(item.baidu_account_id)))
    if (params.baidu_account_id !== undefined) contract(item.baidu_account_id === params.baidu_account_id)
    contract(item.keyword === null || typeof item.keyword === 'string')
    contract(item.campaign_id === null || positive(item.campaign_id)); contract(item.adgroup_id === null || positive(item.adgroup_id))
    contract(nullableNumber(item.price) && (item.pause === null || typeof item.pause === 'boolean') && validStamp(item.asset_updated_at))
    validateMetrics(item.metrics); validateCoverage(item.coverage, data.window, item.metrics); validatePhone(item.phone_button_clicks)
  }
}
function validateDimensionAccounts(payload, expectedIds) {
  contract(Array.isArray(payload.accounts))
  const ids = new Set()
  for (const account of payload.accounts) {
    contract(object(account) && (account.baidu_account_id === null || positive(account.baidu_account_id)) && !ids.has(account.baidu_account_id))
    ids.add(account.baidu_account_id); validateCoverage(account.coverage, payload.window)
  }
  contract(ids.size === expectedIds.size && [...ids].every(id => expectedIds.has(id)))
}
function validateDimensions(dimensions, window, expectedAccountIds) {
  contract(object(dimensions) && object(dimensions.region) && object(dimensions.schedule))
  const region = dimensions.region
  contract(region.source === 'keyword_region_reports' && Array.isArray(region.rows) && Array.isArray(region.totals_by_level))
  validateWindow(region.window, window.start, window.end, 'explicit'); validateCoverage(region.coverage, region.window); validateDimensionAccounts(region, expectedAccountIds)
  region.rows.forEach(row => { contract(object(row) && typeof row.region_level === 'string' && typeof row.region_name === 'string'); validateMetrics(row.metrics) })
  region.totals_by_level.forEach(row => { contract(object(row) && typeof row.region_level === 'string'); validateMetrics(row.metrics) })
  const schedule = dimensions.schedule
  contract(schedule.source === 'keyword_hourly_reports' && schedule.dimension === 'weekday_hour' && Array.isArray(schedule.cells) && schedule.cells.length === 168)
  validateWindow(schedule.window, window.start, window.end, 'explicit'); validateCoverage(schedule.coverage, schedule.window); validateDimensionAccounts(schedule, expectedAccountIds); validateMetrics(schedule.metrics)
  const keys = new Set()
  for (const cell of schedule.cells) {
    const key = `${cell.weekday}:${cell.hour}`
    contract(positive(cell.weekday) && cell.weekday <= 7 && nonnegativeInteger(cell.hour) && cell.hour <= 23 && !keys.has(key))
    keys.add(key); contract(['observed', 'no_data'].includes(cell.status)); validateMetrics(cell.metrics)
    if (cell.status === 'no_data') contract(allNull(cell.metrics))
  }
}
function validateSearchTerms(data, params) {
  contract(object(data.filters) && data.filters.q === (params.q ?? null) && data.filters.campaign_id === (params.campaign_id ?? null) &&
    data.filters.adgroup_id === (params.adgroup_id ?? null))
  contract(data.page === (params.page ?? 1) && data.page_size === (params.page_size ?? 50) && nonnegativeInteger(data.total) && Array.isArray(data.items))
  contract(['observed', 'no_data'].includes(data.status) && data.completeness === 'unknown' && Array.isArray(data.windows))
  const pairs = new Set()
  const windows = new Set()
  for (const entry of data.windows) {
    contract(object(entry) && (entry.baidu_account_id === null || positive(entry.baidu_account_id)))
    if (params.baidu_account_id !== undefined) contract(entry.baidu_account_id === params.baidu_account_id)
    validateWindow(entry, undefined, undefined, 'sync_snapshot')
    contract(nonnegativeInteger(entry.stored_rows) && nonnegativeInteger(entry.unknown_timestamp_rows) && entry.unknown_timestamp_rows <= entry.stored_rows)
    contract(validStamp(entry.updated_at) && validStamp(entry.oldest_updated_at) && entry.completeness === 'unknown')
    pairs.add(`${entry.start ?? ''}:${entry.end ?? ''}`); windows.add(`${entry.baidu_account_id ?? 'null'}:${entry.start ?? ''}:${entry.end ?? ''}`)
  }
  contract(data.mixed_windows === (pairs.size > 1))
  for (const item of data.items) {
    contract(object(item) && positive(item.id) && (item.baidu_account_id === null || positive(item.baidu_account_id)) && typeof item.query_word === 'string')
    if (params.baidu_account_id !== undefined) contract(item.baidu_account_id === params.baidu_account_id)
    contract(item.trigger_keyword === null || typeof item.trigger_keyword === 'string')
    contract(item.campaign_id === null || positive(item.campaign_id)); contract(item.adgroup_id === null || positive(item.adgroup_id))
    validateMetrics(item.metrics); validateWindow(item.window, undefined, undefined, 'sync_snapshot'); contract(validStamp(item.updated_at))
    contract(windows.has(`${item.baidu_account_id ?? 'null'}:${item.window.start ?? ''}:${item.window.end ?? ''}`))
  }
  contract(data.status === (data.total ? 'observed' : 'no_data'))
}
function validatePayload(resource, data, params) {
  validateUnits(data.units); validateAccountScope(data.account_scope, params.baidu_account_id)
  contract(typeof data.retrieved_at === 'string' && validStamp(data.retrieved_at))
  if (resource === 'report') validateReport(data, params)
  if (resource === 'keywords') validateKeywords(data, params)
  if (resource === 'keywordDetail') {
    validateReport(data, params, true); validatePhone(data.phone_button_clicks)
    contract(Array.isArray(data.keyword_assets))
    for (const asset of data.keyword_assets) {
      contract(object(asset) && (asset.baidu_account_id === null || positive(asset.baidu_account_id)) && (asset.keyword === null || typeof asset.keyword === 'string') && validStamp(asset.asset_updated_at))
      if (params.baidu_account_id !== undefined) contract(asset.baidu_account_id === params.baidu_account_id)
    }
    validateDimensions(data.dimensions, data.window, new Set(data.accounts.map(account => account.baidu_account_id)))
  }
  if (resource === 'searchTerms') validateSearchTerms(data, params)
}

export function createSemReadonlyClient({ transport, onClear }) {
  if (typeof transport !== 'function' || typeof onClear !== 'function') {
    throw new TypeError('Authenticated transport and a view/context clearing callback are required')
  }
  let context = null
  let revision = 0
  const pending = new Map()
  function invalidate() {
    revision++
    context = null
    for (const controller of pending.values()) controller.abort()
    pending.clear()
    onClear()
  }
  function setContext(next) {
    invalidate()
    if (next === null) return
    if (!next || !positive(next.tenantId) || !positive(next.userId) ||
        typeof next.authorizationRevision !== 'string' || !next.authorizationRevision.trim() ||
        !Array.isArray(next.allowedReads) || next.allowedReads.some(key => !Object.hasOwn(routes, key))) {
      fail('INVALID_CONTEXT', '需要已确认的客户、用户、权限版本与可读取范围')
    }
    context = Object.freeze({ ...next, allowedReads: Object.freeze([...next.allowedReads]) })
  }
  async function read(resource, params = {}) {
    const route = Object.hasOwn(routes, resource) ? routes[resource] : null
    if (!route) fail('UNSUPPORTED_RESOURCE', '不支持的只读资源')
    if (!context || !context.allowedReads.includes(resource)) fail('NOT_AUTHORIZED', '尚未确认读取权限')
    const allowed = new Set(['baidu_account_id', ...route.fields,
      ...(route.dates === 'none' ? [] : ['start_date', 'end_date'])])
    if (!params || typeof params !== 'object' || Array.isArray(params) || Object.keys(params).some(key => !allowed.has(key))) {
      fail('UNSUPPORTED_FILTER', '存在不支持的筛选；搜索词不支持日期联动')
    }
    for (const key of ['baidu_account_id', 'campaign_id', 'adgroup_id', 'page', 'page_size', 'keyword_id']) {
      if (Object.hasOwn(params, key) && !positive(params[key])) fail('INVALID_FILTER', `${key} 必须是正整数`)
    }
    if (params.page_size > 200 || (params.q !== undefined && (typeof params.q !== 'string' || params.q.length > 200))) {
      fail('INVALID_FILTER', '筛选超出接口限制')
    }
    if (route.dates === 'required' || params.start_date !== undefined || params.end_date !== undefined) {
      if (!validDate(params.start_date) || !validDate(params.end_date)) fail('INVALID_WINDOW', '须提供有效的起止日期')
      const days = (new Date(params.end_date) - new Date(params.start_date)) / 86400000 + 1
      if (days < 1 || days > 366) fail('INVALID_WINDOW', '日期范围须为1至366天')
    }
    if (resource === 'keywordDetail' && !positive(params.keyword_id)) fail('INVALID_FILTER', '缺少关键词ID')
    const active = context
    const atRevision = revision
    const query = new URLSearchParams({ tenant_id: String(active.tenantId) })
    for (const [key, value] of Object.entries(params)) if (key !== 'keyword_id') query.set(key, String(value))
    const path = route.path + (resource === 'keywordDetail' ? params.keyword_id : '')
    pending.get(resource)?.abort()
    const controller = new AbortController()
    pending.set(resource, controller)
    const stale = () => revision !== atRevision || controller.signal.aborted || pending.get(resource) !== controller
    try {
      // Transport must preserve the current authenticated identity, never an admin API key.
      const response = await transport(`${path}?${query}`, { method: 'GET', cache: 'no-store', signal: controller.signal })
      if (stale()) fail('STALE_RESPONSE', '已丢弃旧客户或旧筛选结果')
      if (response.status === 401 || response.status === 403) {
        invalidate()
        fail('ACCESS_REVOKED', '权限已失效，请重新确认身份和模块资格')
      }
      if (!response.ok) fail('READ_FAILED', `读取失败（${response.status}），未回退为演示或零值`)
      let data
      try { data = await response.json() } catch (error) {
        if (stale()) fail('STALE_RESPONSE', '已丢弃旧请求错误')
        invalidate()
        fail('CONTRACT_MISMATCH', '响应不是有效的只读JSON契约')
      }
      if (stale()) fail('STALE_RESPONSE', '已丢弃旧客户或旧筛选结果')
      if (!object(data) || data.tenant_id !== active.tenantId || data.module !== 'sem' || data.read_only !== true ||
          data.is_demo !== false || data.contract_version !== 'sem-cockpit-v1' || data.source !== route.source ||
          data.account_scope?.baidu_account_id !== (params.baidu_account_id ?? null) ||
          data.account_scope?.mode !== (params.baidu_account_id === undefined ? 'all' : 'single') ||
          (params.start_date !== undefined && (data.window?.start !== params.start_date || data.window?.end !== params.end_date)) ||
          (resource === 'keywordDetail' && data.keyword_id !== params.keyword_id)) {
        invalidate()
        fail('CONTRACT_MISMATCH', '响应身份或契约不匹配')
      }
      try { validatePayload(resource, data, params) } catch (error) {
        invalidate()
        if (error instanceof SemReadError) throw error
        fail('CONTRACT_MISMATCH', '响应字段、空值或范围契约不匹配')
      }
      return data
    } catch (error) {
      if (!(error instanceof SemReadError) && stale()) fail('STALE_RESPONSE', '已丢弃旧请求错误')
      throw error
    } finally {
      if (pending.get(resource) === controller) pending.delete(resource)
    }
  }
  return Object.freeze({ setContext, invalidate, read })
}
