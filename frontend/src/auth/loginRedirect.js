export function currentAppPath() {
  return `${window.location.pathname}${window.location.search}${window.location.hash}`
}

export function loginUrl(redirect = currentAppPath()) {
  const safeRedirect = String(redirect || '/')
  const params = new URLSearchParams()
  const configuredOrigin = String(import.meta.env.VITE_AUTH_ORIGIN || '').replace(/\/$/, '')
  const authOrigin = configuredOrigin || (import.meta.env.DEV ? 'http://127.0.0.1:5174' : '')

  if (safeRedirect.startsWith('/') && !safeRedirect.startsWith('//') && safeRedirect !== '/login') {
    params.set('redirect', safeRedirect)
  }

  const query = params.toString()
  return query ? `${authOrigin}/login?${query}` : `${authOrigin}/login`
}

export function redirectToLogin(redirect) {
  window.location.assign(loginUrl(redirect))
}
