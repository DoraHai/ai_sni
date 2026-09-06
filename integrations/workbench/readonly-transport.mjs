// Network boundary only. Module clients still validate identity, permission and data.
// The host supplies its ordinary login session; this module never logs in or stores it.
const paths = [
  /^\/api\/v1\/auth\/me$/,
  /^\/api\/v1\/auth\/modules$/,
  /^\/api\/v1\/auth\/tenants$/,
  /^\/api\/v1\/dashboard\/cockpit$/,
  /^\/api\/v1\/keywords\/cockpit$/,
  /^\/api\/v1\/keywords\/cockpit\/[1-9]\d*$/,
  /^\/api\/v1\/search-terms\/cockpit$/,
]

const seoRoutes = [
  [/^\/api\/v1\/seo\/content-assets$/, ['tenant_id', 'site_id', 'content_id', 'source_page_id', 'status', 'content_type', 'content_types', 'q', 'page', 'page_size']],
  [/^\/api\/v1\/seo\/content-assets\/[1-9]\d*\/review-history$/, ['tenant_id']],
  [/^\/api\/v1\/seo\/content-distribution\/publications$/, ['tenant_id', 'site_id', 'content_id']],
  [/^\/api\/v1\/seo\/content-distribution\/publications\/[1-9]\d*\/attempts$/, ['tenant_id', 'site_id']],
  [/^\/api\/v1\/seo\/site-pages$/, ['tenant_id', 'site_id', 'page_id', 'q', 'status', 'issue_code', 'page', 'page_size']],
  [/^\/api\/v1\/seo\/site-pages\/image-evidence$/, ['tenant_id', 'site_id', 'page_id', 'snapshot_id']],
]

function reject(code) { const error = new Error(code); error.code = code; throw error }

export function createReadonlyTransport({ origin, fetchImpl, getSession }) {
  const base = new URL(origin)
  if (base.origin !== origin || base.protocol !== 'https:') reject('INVALID_ORIGIN')
  if (typeof fetchImpl !== 'function' || typeof getSession !== 'function') reject('INVALID_HOST')
  let generation = 0
  const pending = new Set()

  function invalidate() {
    generation++
    for (const controller of pending) controller.abort()
    pending.clear()
  }

  async function transport(path, options = {}) {
    if (options.method !== 'GET' || options.body !== undefined || options.headers !== undefined) reject('READ_ONLY')
    if (typeof path !== 'string' || !path.startsWith('/api/v1/') || /[\\#\s]/.test(path)) reject('ROUTE_DENIED')
    const url = new URL(path, base)
    // Reject normalization tricks and credentials in query strings as well as unknown routes.
    const seoRoute = seoRoutes.find(([rule]) => rule.test(url.pathname))
    if (url.origin !== origin || path.split('?')[0] !== url.pathname || (!seoRoute && !paths.some(rule => rule.test(url.pathname)))) reject('ROUTE_DENIED')
    const authTenants = url.pathname === '/api/v1/auth/tenants'
    const authNoQuery = url.pathname === '/api/v1/auth/me' || url.pathname === '/api/v1/auth/modules'
    const allowed = new Set(seoRoute ? seoRoute[1] : authTenants ? ['module'] : authNoQuery ? []
      : ['tenant_id', 'start_date', 'end_date', 'baidu_account_id', 'q', 'campaign_id', 'adgroup_id', 'page', 'page_size'])
    for (const key of url.searchParams.keys()) {
      if (!allowed.has(key) || url.searchParams.getAll(key).length !== 1) reject('QUERY_DENIED')
    }
    if (authTenants && (url.searchParams.size !== 1 || url.searchParams.get('module') !== 'sem')) reject('QUERY_DENIED')
    if (seoRoute) {
      const required = seoRoute[1].includes('site_id') ? ['tenant_id', 'site_id'] : ['tenant_id']
      if (url.pathname.endsWith('/image-evidence')) required.push('page_id')
      if (url.pathname.endsWith('/publications')) required.push('content_id')
      for (const key of required) {
        const value = url.searchParams.get(key)
        if (!/^[1-9]\d*$/.test(value ?? '') || !Number.isSafeInteger(Number(value))) reject('QUERY_DENIED')
      }
    }
    const session = getSession()
    if (!session || typeof session.token !== 'string' || !session.token || /\s/.test(session.token) || !Number.isSafeInteger(session.revision)) reject('NO_SESSION')
    const revision = session.revision
    const token = session.token
    const started = generation
    const controller = new AbortController()
    const abort = () => controller.abort()
    if (options.signal?.aborted) controller.abort()
    options.signal?.addEventListener('abort', abort, { once: true })
    pending.add(controller)
    function assertCurrent() {
      const current = getSession()
      if (controller.signal.aborted || started !== generation || current?.revision !== revision || current?.token !== token) reject('STALE_SESSION')
    }
    try {
      assertCurrent()
      const response = await fetchImpl(url.href, {
        method: 'GET', cache: 'no-store', redirect: 'error', credentials: 'omit',
        headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' }, signal: controller.signal,
      })
      assertCurrent()
      // A late body is checked too: switching customers after headers must not expose old data.
      return {
        ok: response.ok, status: response.status,
        async json() { assertCurrent(); const body = await response.json(); assertCurrent(); return body },
      }
    } finally {
      pending.delete(controller)
      options.signal?.removeEventListener('abort', abort)
    }
  }
  return { transport, invalidate }
}
