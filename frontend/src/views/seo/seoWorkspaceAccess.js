function positiveId(value) {
  const id = Number(value)
  return Number.isInteger(id) && id > 0 ? id : null
}

export function canRenderSeoRoute(accessState, routePath) {
  return accessState === 'ready'
    || (accessState === 'no-active-site' && routePath === '/seo/sites')
}

export function selectOwnedSeoSite(sites, requestedSiteId, selectableStatuses = ['active']) {
  const rows = Array.isArray(sites) ? sites : []
  const allowed = new Set(Array.isArray(selectableStatuses) ? selectableStatuses : [])
  const selectable = rows.filter((site) => allowed.has(site?.status))
  const requested = positiveId(requestedSiteId)
  if (requested && selectable.some((site) => positiveId(site?.id) === requested)) return requested
  return positiveId(selectable[0]?.id) || null
}

export function reconcileSeoRouteSite({
  sites,
  selectableStatuses,
  requestedSiteId,
  selectSite,
  replaceSiteQuery,
  noSite,
}) {
  const requested = positiveId(requestedSiteId)
  const selected = selectOwnedSeoSite(sites, requested, selectableStatuses)
  if (!selected) {
    noSite()
    return null
  }
  selectSite(selected)
  if (selected !== requested) replaceSiteQuery(selected)
  return selected
}

export function createSeoWorkspaceAccess({ fetchSites, fetchTenants, selectTenant, boundTenantId, reset, ready, noSite, unavailable }) {
  let generation = 0

  async function validate({ tenantId, requestedSiteId = null }) {
    const scopeTenantId = positiveId(tenantId)
    const ticket = ++generation
    reset({ tenantId: scopeTenantId })
    let eligibleTenants
    try {
      if (fetchTenants) {
        const response = await fetchTenants()
        if (ticket !== generation) return
        eligibleTenants = Array.isArray(response?.tenants) ? response.tenants : []
        const bound = positiveId(boundTenantId?.())
        const allowed = eligibleTenants.filter((tenant) => !bound || positiveId(tenant.id) === bound)
        const selected = allowed.find((tenant) => positiveId(tenant.id) === scopeTenantId) || allowed[0]
        const selectedId = positiveId(selected?.id)
        if (!selectedId) {
          unavailable({ tenantId: scopeTenantId, error: new Error('当前账号没有已开通 SEO 的客户'), tenants: eligibleTenants })
          return
        }
        if (selectedId !== scopeTenantId) {
          // The tenant watcher starts a fresh validation; never query sites for
          // a stale remembered tenant or carry its site selection into fallback.
          selectTenant(selectedId)
          return
        }
      }
      if (!scopeTenantId) {
        unavailable({ tenantId: null, error: null, tenants: [] })
        return
      }
      // This endpoint checks active/trial + unexpired SEO entitlement and returns
      // only sites owned by the requested tenant. It is the authoritative gate.
      const response = await fetchSites(scopeTenantId)
      if (ticket !== generation) return
      const sites = Array.isArray(response?.sites) ? response.sites : []
      const tenants = eligibleTenants ?? (Array.isArray(response?.tenants) ? response.tenants : [])
      const selectableStatuses = Array.isArray(response?.selection_policy?.selectable_statuses)
        ? response.selection_policy.selectable_statuses
        : ['active']
      const siteId = selectOwnedSeoSite(sites, requestedSiteId, selectableStatuses)
      const result = {
        tenantId: scopeTenantId,
        sites,
        tenants,
        selectableStatuses,
        siteId,
      }
      if (!siteId) noSite(result)
      else ready(result)
    } catch (error) {
      if (ticket !== generation) return
      unavailable({
        tenantId: scopeTenantId,
        error,
        tenants: eligibleTenants ?? (Array.isArray(error?.seoTenants) ? error.seoTenants : []),
      })
    }
  }

  function invalidate() {
    generation += 1
    reset({ tenantId: null })
  }

  function dispose() {
    generation += 1
  }

  return { validate, invalidate, dispose }
}
