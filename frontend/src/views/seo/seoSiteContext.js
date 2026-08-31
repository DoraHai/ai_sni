import { computed, reactive } from 'vue'
import { currentTenantId } from '../../store/session'

const SITE_KEY = 'seo_site_id'
const TENANT_KEY = 'seo_site_tenant_id'

const state = reactive({
  tenantId: Number(sessionStorage.getItem(TENANT_KEY)) || null,
  siteId: Number(sessionStorage.getItem(SITE_KEY)) || null,
})

function normalizeId(value) {
  const id = Number(value)
  return Number.isInteger(id) && id > 0 ? id : null
}

export const currentSeoSiteId = computed({
  get() {
    const tenantId = normalizeId(currentTenantId.value)
    return tenantId && tenantId === state.tenantId ? state.siteId : null
  },
  set(value) {
    const tenantId = normalizeId(currentTenantId.value)
    const siteId = normalizeId(value)
    state.tenantId = tenantId
    state.siteId = siteId
    if (tenantId && siteId) {
      sessionStorage.setItem(TENANT_KEY, String(tenantId))
      sessionStorage.setItem(SITE_KEY, String(siteId))
    } else {
      sessionStorage.removeItem(TENANT_KEY)
      sessionStorage.removeItem(SITE_KEY)
    }
  },
})

export function clearSeoSiteId() {
  state.tenantId = null
  state.siteId = null
  sessionStorage.removeItem(TENANT_KEY)
  sessionStorage.removeItem(SITE_KEY)
}
