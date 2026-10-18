function positiveId(value) {
  if (typeof value !== 'number' && (typeof value !== 'string' || !/^\d+$/.test(value))) return null
  const id = Number(value)
  return Number.isSafeInteger(id) && id > 0 ? id : null
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

export function createSeoWorkspaceAccess({ fetchSites, fetchTenants, selectTenant, boundTenantId, checkScope, recoverScope, reset, ready, noSite, unavailable }) {
  let generation = 0

  async function validate({ tenantId, requestedSiteId = null, urlTenantId = undefined, strictSite = false }) {
    const scopeTenantId = positiveId(tenantId)
    const ticket = ++generation
    reset({ tenantId: scopeTenantId })
    let eligibleTenants
    try {
      // Identity tokens must first obtain a server-authorized business scope.
      // The normal account path has no extra request.
      if (checkScope) {
        await checkScope()
        if (ticket !== generation) return
      }
      if (fetchTenants) {
        const response = await fetchTenants()
        if (ticket !== generation) return
        eligibleTenants = Array.isArray(response) ? response : Array.isArray(response?.tenants) ? response.tenants : []
        const bound = positiveId(boundTenantId?.())
        const allowed = eligibleTenants.filter((tenant) => !bound || positiveId(tenant.id) === bound)
        const hasUrlTenant = urlTenantId !== undefined
        const requestedTenant = hasUrlTenant ? positiveId(urlTenantId) : scopeTenantId
        const selected = allowed.find((tenant) => positiveId(tenant.id) === requestedTenant)
          || (!hasUrlTenant ? allowed[0] : null)
        const selectedId = positiveId(selected?.id)
        if (!selectedId) {
          unavailable({ tenantId: scopeTenantId, error: new Error(hasUrlTenant
            ? '地址里的客户无权访问或未开通 SEO，请在右上角手动选择客户'
            : '当前账号没有已开通 SEO 的客户'), tenants: allowed })
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
      if (strictSite && (!positiveId(requestedSiteId) || siteId !== positiveId(requestedSiteId))) {
        unavailable({ tenantId: scopeTenantId, error: new Error('地址里的网站不属于该客户或不可用，请在右上角手动选择客户后重新选择网站'), tenants })
        return
      }
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
      if (recoverScope) {
        try {
          const recovered = await recoverScope(error)
          if (ticket !== generation) return
          if (recovered) {
            await validate({ tenantId: recovered.tenantId, requestedSiteId, urlTenantId, strictSite })
            return
          }
        } catch (recoveryError) {
          error = recoveryError
        }
        if (ticket !== generation) return
      }
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
