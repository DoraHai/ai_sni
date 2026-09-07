import { canViewCockpit } from '../views/workspace/cockpit/scope.mjs'

export function resolvePostLoginPath(redirect, canView) {
  const safeRedirect = String(redirect || '')
  if (safeRedirect.startsWith('/') && !safeRedirect.startsWith('//')) return safeRedirect
  return canViewCockpit(canView) ? '/workspace/cockpit' : '/workspace'
}
