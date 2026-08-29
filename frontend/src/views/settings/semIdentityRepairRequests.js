export function createRequestController() {
  let current = null

  return {
    start() {
      current?.abort()
      current = new AbortController()
      return current
    },
    cancel() {
      current?.abort()
      current = null
    },
    finish(controller) {
      if (current !== controller) return false
      current = null
      return true
    },
  }
}
