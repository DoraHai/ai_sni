export function installAuthContextRouting(browser, eventName, revalidate) {
  if (!browser?.addEventListener || typeof revalidate !== 'function') {
    throw new TypeError('INVALID_AUTH_ROUTE_REVALIDATION')
  }
  const handler = () => { void revalidate() }
  browser.addEventListener(eventName, handler)
  return () => browser.removeEventListener(eventName, handler)
}
