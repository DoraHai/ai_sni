export const MODULE_PERMISSION_KEYS = Object.freeze({
  sem: Object.freeze([
    'sem.assets', 'assistant', 'onboarding',
    'monitor.dashboard', 'monitor.alerts', 'monitor.profile',
    'optimize.expand', 'optimize.keywords', 'optimize.searchterms',
    'optimize.negatives', 'verify.adjustments', 'verify.pending',
    'verify.leads', 'manage.account', 'manage.campaigns',
    'manage.adgroups', 'manage.ocpc', 'delivery.report',
    'settings.customers',
  ]),
  seo: Object.freeze([
    'seo.assets', 'seo.dashboard', 'seo.alerts', 'seo.keywords',
    'seo.content', 'seo.site', 'seo.links', 'seo.competitors',
  ]),
  geo: Object.freeze(['geo.assets', 'geo.content', 'geo.diagnosis']),
})

export const COCKPIT_PERMISSION_KEYS = Object.freeze(Object.values(MODULE_PERMISSION_KEYS).flat())

export function canViewCockpit(canView) {
  return typeof canView === 'function' && COCKPIT_PERMISSION_KEYS.some(key => canView(key))
}

export function hasDataReadPermission(moduleCode, canView, moduleMeta) {
  const keys = moduleMeta?.[moduleCode]?.permission || []
  return typeof canView === 'function' && keys.some(key => canView(key))
}

export function isSecureCockpitRuntime(locationLike) {
  return locationLike?.protocol === 'https:'
}

export function resolveTenantModuleCodes({ modules, tenantsByModule, tenantId, moduleMeta }) {
  const selected = Number(tenantId)
  if (!selected) return new Set()
  return new Set((modules || [])
    .filter(item => item.available && moduleMeta[item.module_code])
    .filter(item => (tenantsByModule[item.module_code] || [])
      .some(tenant => Number(tenant.id) === selected))
    .map(item => item.module_code))
}

export function selectCockpitTenants({ tenants, tenantsByModule, moduleCodes }) {
  const allowedIds = new Set((moduleCodes || []).flatMap(code => (
    tenantsByModule?.[code] || []
  )).map(tenant => Number(tenant.id)).filter(Number.isSafeInteger))
  return (tenants || []).filter(tenant => allowedIds.has(Number(tenant.id)))
}

export function selectAvailableModules(modules, tenantModuleCodes, moduleMeta) {
  return (modules || []).filter(item => item.available
    && tenantModuleCodes.has(item.module_code) && moduleMeta[item.module_code])
}

export function countUnresolvedModules(modules, moduleState) {
  return modules.filter(item => moduleState[item.module_code] !== 'ready').length
}

export function isCurrentCockpitScope(ticket, current) {
  return ticket.generation === current.generation
    && ticket.tenantId === current.tenantId
    && ticket.authRevision === current.authRevision
}
