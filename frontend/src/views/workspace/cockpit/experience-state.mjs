const BOUNDARY_STATES = new Set(['partial', 'no_data', 'unavailable'])

export function readCompletionProgress({ availableCount, completedCount }) {
  if (!Number.isSafeInteger(availableCount) || availableCount <= 0) return 0
  const completed = Number.isSafeInteger(completedCount) ? completedCount : 0
  return Math.round(Math.min(availableCount, Math.max(0, completed)) / availableCount * 100)
}

export function evidenceBoundaryCount({ unresolvedModules, cards }) {
  const unresolved = Number.isSafeInteger(unresolvedModules) ? Math.max(0, unresolvedModules) : 0
  const cardBoundaries = Array.isArray(cards)
    ? cards.filter(card => BOUNDARY_STATES.has(card?.state)).length
    : 0
  return unresolved + cardBoundaries
}

export function normalizeModuleSelection(activeModule, availableCodes) {
  if (activeModule === 'all') return 'all'
  return Array.isArray(availableCodes) && availableCodes.includes(activeModule) ? activeModule : 'all'
}

export function isCurrentCommandContext(request, current) {
  return Number(request?.tenantId) === Number(current?.tenantId)
    && request?.loadGeneration === current?.loadGeneration
    && request?.contextRevision === current?.contextRevision
}
