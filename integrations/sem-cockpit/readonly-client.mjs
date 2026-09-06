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
function validDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
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
      const data = await response.json()
      if (stale()) fail('STALE_RESPONSE', '已丢弃旧客户或旧筛选结果')
      if (data.tenant_id !== active.tenantId || data.module !== 'sem' || data.read_only !== true ||
          data.is_demo !== false || data.contract_version !== 'sem-cockpit-v1' || data.source !== route.source ||
          data.account_scope?.baidu_account_id !== (params.baidu_account_id ?? null) ||
          data.account_scope?.mode !== (params.baidu_account_id === undefined ? 'all' : 'single') ||
          (params.start_date !== undefined && (data.window?.start !== params.start_date || data.window?.end !== params.end_date)) ||
          (resource === 'keywordDetail' && data.keyword_id !== params.keyword_id)) {
        invalidate()
        fail('CONTRACT_MISMATCH', '响应身份或契约不匹配')
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
