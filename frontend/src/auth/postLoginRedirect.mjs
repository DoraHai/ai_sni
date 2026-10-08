const UNSAFE_REDIRECT_CHARACTERS = /[\\\u0000-\u001f\u007f]/
const ACQUISITION_MODULE_CODES = new Set(['sem', 'seo', 'geo'])

function containsUnsafeCharacters(value) {
  let decoded = value
  for (let depth = 0; depth < 8; depth += 1) {
    if (UNSAFE_REDIRECT_CHARACTERS.test(decoded)) return true
    let next
    try {
      next = decodeURIComponent(decoded)
    } catch {
      return true
    }
    if (next === decoded) return false
    decoded = next
  }
  return true
}

export function parseSameOriginRedirect(redirect, currentOrigin) {
  const raw = typeof redirect === 'string' ? redirect : ''
  if (!raw || raw !== raw.trim() || containsUnsafeCharacters(raw)) return null

  try {
    const base = new URL(currentOrigin)
    const target = new URL(raw, base)
    if (!['http:', 'https:'].includes(base.protocol)
        || target.origin !== base.origin
        || target.username
        || target.password) return null
    return `${target.pathname}${target.search}${target.hash}`
  } catch {
    return null
  }
}

export function hasAvailableAcquisitionModule(modules) {
  return Array.isArray(modules) && modules.some(module => (
    ACQUISITION_MODULE_CODES.has(module?.module_code) && module?.available === true
  ))
}

export function resolvePostLoginPath({ redirect, currentOrigin, modules }) {
  // Only the independent SEO workbench may return to a scoped deep link.
  // This selects navigation, not access: the destination rechecks user/site scope.
  const safePath = parseSameOriginRedirect(redirect, currentOrigin)
  if (safePath && Array.isArray(modules)
      && modules.some(module => module?.module_code === 'seo' && module?.available === true)) {
    const target = new URL(safePath, currentOrigin)
    const keys = [...target.searchParams.keys()]
    const validId = key => {
      const value = target.searchParams.get(key) || ''
      return /^[1-9]\d*$/.test(value) && Number.isSafeInteger(Number(value))
    }
    if (['/customer-workbench', '/customer-workbench/'].includes(target.pathname)
        && !target.hash && keys.length === 2
        && target.searchParams.getAll('tenant_id').length === 1
        && target.searchParams.getAll('site_id').length === 1
        && validId('tenant_id') && validId('site_id')) {
      return `/customer-workbench/?${target.searchParams.toString()}`
    }
  }
  // All other entry points keep the established cockpit landing behavior.
  return '/workspace/cockpit'
}
