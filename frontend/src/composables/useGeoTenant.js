import { computed } from 'vue'
import { session } from '../store/session'

/** Shared tenant id for GEO SPA pages (login tenant or DEV API-key fallback). */
export function useGeoTenant() {
  const tenantId = computed(() => {
    if (session.tenantId) return session.tenantId
    const stored = Number(sessionStorage.getItem('sem_tenant_id') || 0)
    if (stored > 0) return stored
    const first = session.tenants?.[0]?.id
    if (first) return first
    if (import.meta.env.DEV && import.meta.env.VITE_API_KEY) return 1
    return null
  })
  return { tenantId, session }
}
