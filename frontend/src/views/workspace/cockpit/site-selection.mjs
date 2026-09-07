export function resolveSeoSiteSelection({ sites = [], currentSiteId = null } = {}) {
  const selectable = sites.filter(site => site?.status === 'active')
  const selectedId = Number(currentSiteId)
  if (Number.isSafeInteger(selectedId) && selectedId > 0) {
    const selected = sites.find(site => site.id === selectedId)
    if (selected?.status === 'active') return { siteId: selectedId, reason: 'selected' }
    return { siteId: null, reason: 'selection_unavailable' }
  }
  if (selectable.length === 1) return { siteId: selectable[0].id, reason: 'single_selectable_site' }
  if (selectable.length > 1) return { siteId: null, reason: 'selection_required' }
  return { siteId: null, reason: 'no_selectable_site' }
}
