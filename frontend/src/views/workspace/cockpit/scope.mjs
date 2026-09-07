export function isSecureCockpitRuntime(locationLike) {
  return locationLike?.protocol === 'https:'
}

export function resolveTenantModuleCodes({ modules, tenantsByModule, tenantId, moduleMeta, canView }) {
  const selected = Number(tenantId)
  if (!selected) return new Set()
  return new Set((modules || [])
    .filter(item => item.available && moduleMeta[item.module_code]
      && moduleMeta[item.module_code].permission.some(key => canView(key)))
    .filter(item => (tenantsByModule[item.module_code] || [])
      .some(tenant => Number(tenant.id) === selected))
    .map(item => item.module_code))
}
