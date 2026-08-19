import { computed } from 'vue'
import { session } from '../store/session'

/** Shared tenant id for GEO SPA pages (login tenant or DEV API-key fallback). */
export function useGeoTenant() {
  const tenantId = computed(() =>
    session.tenantId || (import.meta.env.DEV && import.meta.env.VITE_API_KEY ? 1 : null),
  )
  return { tenantId, session }
}
