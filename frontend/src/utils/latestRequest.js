function snapshot(value) {
  return JSON.stringify(value)
}

export function createLatestRequestGuard(readContext) {
  if (typeof readContext !== 'function') throw new TypeError('readContext must be a function')
  let generation = 0

  return Object.freeze({
    begin() {
      const requestGeneration = ++generation
      const context = readContext()
      const contextSnapshot = snapshot(context)
      return Object.freeze({
        context,
        isCurrent: () => requestGeneration === generation && contextSnapshot === snapshot(readContext()),
      })
    },
    invalidate() {
      generation += 1
    },
  })
}
