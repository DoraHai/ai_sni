export function geoSessionRouteDecision({
  route,
  session,
  devBypass = false,
  redirectToLogin,
  leaveWorkspace,
}) {
  if (route?.meta?.public) return true
  if (!session.isLoggedIn && !devBypass) {
    redirectToLogin()
    return false
  }
  if (devBypass || !route?.meta?.perm || session.canView(route.meta.perm)) return true
  return leaveWorkspace()
}

const AUTH_STORAGE_KEYS = new Set(['sem_token', 'sem_user'])

export function installGeoAuthContextRouting(browser, { eventName, revalidate, reload }) {
  if (
    !browser?.addEventListener
    || typeof eventName !== 'string'
    || !eventName
    || typeof revalidate !== 'function'
    || typeof reload !== 'function'
  ) {
    throw new TypeError('INVALID_GEO_AUTH_ROUTE_REVALIDATION')
  }
  const authContextHandler = () => { void revalidate() }
  const storageHandler = (event) => {
    if (event.storageArea !== browser.localStorage || !AUTH_STORAGE_KEYS.has(event.key)) return
    reload()
  }
  browser.addEventListener(eventName, authContextHandler)
  browser.addEventListener('storage', storageHandler)
  return () => {
    browser.removeEventListener(eventName, authContextHandler)
    browser.removeEventListener('storage', storageHandler)
  }
}
