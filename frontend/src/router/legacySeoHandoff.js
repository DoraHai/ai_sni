// Only routes present in the independently deployed SEO workspace belong here.
const SEO_PAGES = new Set([
  '/seo', '/seo/dashboard', '/seo/alerts', '/seo/keywords', '/seo/rankings',
  '/seo/trends', '/seo/site', '/seo/content', '/seo/content/articles',
  '/seo/content/rewrites', '/seo/content/qa', '/seo/content/editor',
  '/seo/content/answer-editor', '/seo/distribution', '/seo/links', '/seo/competitors',
])
const HANDOFF_KEY = 'legacy_seo_handoff_target'

function id(value) {
  if (typeof value !== 'string' && typeof value !== 'number') return null
  if (!/^[1-9]\d*$/.test(String(value))) return null
  const number = Number(value)
  return Number.isSafeInteger(number) ? String(number) : null
}

export function legacySeoUrl(to, { tenantId, siteId } = {}) {
  const path = to.path.replace(/\/$/, '')
  if (!SEO_PAGES.has(path) && !/^\/seo\/keywords\/[^/]+$/.test(path)) return null
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(to.query || {})) {
    if (key === 'tenant_id' || key === 'site_id') continue
    for (const item of Array.isArray(value) ? value : [value]) {
      if (item != null) query.append(key, String(item))
    }
  }
  const explicitTenant = Object.hasOwn(to.query || {}, 'tenant_id')
  const tenant = explicitTenant ? id(to.query.tenant_id) : id(tenantId)
  const site = Object.hasOwn(to.query || {}, 'site_id') ? id(to.query.site_id)
    : tenant && tenant === id(tenantId) ? id(siteId) : null
  if (tenant) query.set('tenant_id', tenant)
  if (tenant && site) query.set('site_id', site)
  const destination = path === '/seo' ? '/seo/dashboard' : path === '/seo/content' ? '/seo/content/articles' : path
  const search = query.toString()
  return destination + (search ? '?' + search : '') + (to.hash || '')
}

// This module is used only by the generic SPA, never by the independent SEO router.
// A single reload also handles a stale generic bundle opened directly at /seo/.
export function handoffLegacySeo(to, context, browser) {
  const target = legacySeoUrl(to, context)
  if (!target) {
    try { browser.sessionStorage.removeItem(HANDOFF_KEY) } catch { /* storage may be disabled */ }
    return null
  }
  const current = browser.location.pathname + browser.location.search + browser.location.hash
  try {
    if (browser.sessionStorage.getItem(HANDOFF_KEY) === target && current === target) return 'blocked'
    browser.sessionStorage.setItem(HANDOFF_KEY, target)
  } catch {
    // Without persistent storage, never reload an already matching document.
    if (current === target) return 'blocked'
  }
  browser.location.assign(target)
  return 'redirected'
}
