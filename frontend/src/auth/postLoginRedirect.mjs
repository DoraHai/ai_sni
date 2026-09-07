import { canViewCockpit } from '../views/workspace/cockpit/scope.mjs'

const UNSAFE_REDIRECT_CHARACTERS = /[\\\u0000-\u001f\u007f]/

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

export function resolvePostLoginPath({ redirect, currentOrigin, canView }) {
  const safeRedirect = parseSameOriginRedirect(redirect, currentOrigin)
  if (safeRedirect) return safeRedirect
  return canViewCockpit(canView) ? '/workspace/cockpit' : '/workspace'
}
