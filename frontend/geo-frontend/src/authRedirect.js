import { currentAppPath } from '../../src/auth/loginRedirect.js'

const SENSITIVE_QUERY_KEYS = new Set([
  'api_key',
  'api_origin',
  'token',
  'access_token',
  'authorization',
])

function stripSensitiveQuery(url) {
  for (const key of [...url.searchParams.keys()]) {
    if (SENSITIVE_QUERY_KEYS.has(key.toLowerCase())) url.searchParams.delete(key)
  }
}

export function geoLoginRedirectPath(path = currentAppPath()) {
  const raw = String(path || '')
  if (!raw.startsWith('/') || raw.startsWith('//')) return '/'

  const parsed = new URL(raw, 'https://geo.invalid')
  stripSensitiveQuery(parsed)
  if (parsed.hash.startsWith('#/')) {
    const hashRoute = new URL(parsed.hash.slice(1), 'https://geo.invalid')
    stripSensitiveQuery(hashRoute)
    parsed.hash = `#${hashRoute.pathname}${hashRoute.search}${hashRoute.hash}`
  }
  return `${parsed.pathname}${parsed.search}${parsed.hash}`
}
