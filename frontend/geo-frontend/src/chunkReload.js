const RELOAD_KEY = 'geo:chunk-reload-at'
const RELOAD_WINDOW_MS = 30_000
const UPDATE_MESSAGE = '系统已更新，请按 Ctrl+F5 刷新'

function isChunkLoadError(error) {
  const message = typeof error === 'string' ? error : error?.message || ''
  return error?.name === 'ChunkLoadError'
    || /Failed to fetch dynamically imported module|error loading dynamically imported module|Importing a module script failed|Loading (?:CSS )?chunk .+ failed|Unable to preload CSS/i.test(message)
}

// Install before app.use(router), so initial navigation failures are covered too.
export function installGeoChunkReload(win, router, notify) {
  let pendingRoute
  let reloading = false
  let notified = false

  router.beforeEach((to) => { pendingRoute = to.fullPath })
  router.afterEach(() => { pendingRoute = undefined })

  function recover(error, route = pendingRoute) {
    if (!isChunkLoadError(error)) return false
    // Vite, the router and unhandledrejection can report the same failure.
    if (reloading) return true

    let canReload = false
    try {
      const now = Date.now()
      const lastReload = Number(win.sessionStorage.getItem(RELOAD_KEY))
      canReload = !lastReload || now - lastReload >= RELOAD_WINDOW_MS
      if (canReload) win.sessionStorage.setItem(RELOAD_KEY, String(now))
    } catch {
      // Without a persistent marker, a reload could loop across page loads.
      canReload = false
    }

    if (!canReload) {
      if (!notified) notify(UPDATE_MESSAGE)
      notified = true
      return true
    }

    reloading = true
    if (route) {
      try {
        // Hash navigation has not committed when a lazy route fails. Keep the
        // dashboard entry and outer query, and reload at the intended route.
        win.history.replaceState(win.history.state, '', router.resolve(route).href)
      } catch {
        // A browser that rejects replaceState can still reload the current URL.
      }
    }
    win.location.reload()
    return true
  }

  // Leave Vite's rejection intact so the router's existing error flow still runs.
  win.addEventListener('vite:preloadError', (event) => { recover(event.payload) })
  win.addEventListener('unhandledrejection', (event) => { recover(event.reason) })
  router.onError((error, to) => {
    if (!recover(error, to?.fullPath)) console.error(error)
  })
}
