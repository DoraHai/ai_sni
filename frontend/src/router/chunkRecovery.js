const RECOVERY_KEY = 'sem:chunk-recovery'

export function isChunkLoadError(error) {
  const message = String(error?.message || error || '')
  return /Failed to fetch dynamically imported module|Importing a module script failed|ChunkLoadError|Loading chunk/i.test(message)
}

export function recoverFromChunkLoadError(error) {
  if (!isChunkLoadError(error)) return false

  const attemptedPath = `${window.location.pathname}${window.location.search}`
  if (window.sessionStorage.getItem(RECOVERY_KEY) === attemptedPath) return false

  window.sessionStorage.setItem(RECOVERY_KEY, attemptedPath)
  window.location.reload()
  return true
}

export function clearChunkRecoveryMarker() {
  window.sessionStorage.removeItem(RECOVERY_KEY)
}
