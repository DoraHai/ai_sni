// Network boundary only. Module clients still validate identity, permission and data.
// The host supplies its ordinary login session; this module never logs in or stores it.
const paths = [
  /^\/api\/v1\/dashboard\/cockpit$/,
  /^\/api\/v1\/keywords\/cockpit$/,
  /^\/api\/v1\/keywords\/cockpit\/[1-9]\d*$/,
  /^\/api\/v1\/search-terms\/cockpit$/,
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
    if (url.origin !== origin || path.split('?')[0] !== url.pathname || !paths.some(rule => rule.test(url.pathname))) reject('ROUTE_DENIED')
    const allowed = new Set(['start_date', 'end_date', 'baidu_account_id', 'q', 'campaign_id', 'adgroup_id', 'page', 'page_size'])
    for (const key of url.searchParams.keys()) if (!allowed.has(key)) reject('QUERY_DENIED')
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
