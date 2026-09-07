export const COCKPIT_PERMISSION_KEYS = Object.freeze([
  'monitor.dashboard',
  'optimize.keywords',
  'optimize.searchterms',
  'seo.content',
  'seo.site',
  'geo.content',
])

export function canViewCockpit(permissions = {}) {
  return COCKPIT_PERMISSION_KEYS.some((key) => {
    const level = permissions?.[key]
    return level === 'view' || level === 'edit'
  })
}
