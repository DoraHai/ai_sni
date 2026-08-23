export function parseGeoScopeId(value) {
  const candidate = Array.isArray(value) ? value[0] : value
  const parsed = Number(candidate)

  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

export function normalizeGeoScope(scope = {}, data = {}) {
  const businesses = Array.isArray(data.businesses) ? data.businesses : []
  const units = Array.isArray(data.units) ? data.units : []
  const prompts = Array.isArray(data.prompts) ? data.prompts : []

  let businessId = parseGeoScopeId(scope.businessId)
  let unitId = parseGeoScopeId(scope.unitId)
  let promptId = parseGeoScopeId(scope.promptId)

  if (businessId && !businesses.some((item) => item.id === businessId)) {
    businessId = null
    unitId = null
    promptId = null
  }

  const unit = unitId ? units.find((item) => item.id === unitId) : null
  if (unitId && !unit) {
    unitId = null
    promptId = null
  } else if (businessId && unit && unit.business_id !== businessId) {
    unitId = null
    promptId = null
  }

  const prompt = promptId ? prompts.find((item) => item.id === promptId) : null
  if (promptId && !prompt) {
    promptId = null
  } else if (unitId && prompt && prompt.unit_id !== unitId) {
    promptId = null
  } else if (businessId && !unitId && prompt) {
    const promptUnit = units.find((item) => item.id === prompt.unit_id)
    if (!promptUnit || promptUnit.business_id !== businessId) promptId = null
  }

  return { businessId, unitId, promptId }
}
