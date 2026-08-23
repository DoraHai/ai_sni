import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { listGeoBusinesses, listGeoPrompts, listGeoUnits } from '../api/geoContent'
import { useGeoTenant } from './useGeoTenant'
import { normalizeGeoScope, parseGeoScopeId } from '../utils/geoPrototypeScope'

/** Shared 业务 → 关键词 → AI提问 scope for GEO v2 visibility pages. */
export function useGeoObjectScope() {
  const route = useRoute()
  const router = useRouter()
  const { tenantId } = useGeoTenant()

  const businesses = ref([])
  const units = ref([])
  const prompts = ref([])
  const loading = ref(false)

  const businessId = computed({
    get: () => parseGeoScopeId(route.query.business_id),
    set: (v) => patchQuery({ business_id: v, unit_id: undefined, prompt_id: undefined }),
  })
  const unitId = computed({
    get: () => parseGeoScopeId(route.query.unit_id),
    set: (v) => patchQuery({ unit_id: v, prompt_id: undefined }),
  })
  const promptId = computed({
    get: () => parseGeoScopeId(route.query.prompt_id),
    set: (v) => patchQuery({ prompt_id: v }),
  })

  const filteredUnits = computed(() => {
    if (!businessId.value) return units.value
    return units.value.filter((u) => u.business_id === businessId.value)
  })
  const filteredPrompts = computed(() => {
    let rows = prompts.value
    if (unitId.value) rows = rows.filter((p) => p.unit_id === unitId.value)
    else if (businessId.value) {
      const ids = new Set(filteredUnits.value.map((u) => u.id))
      rows = rows.filter((p) => ids.has(p.unit_id))
    }
    return rows
  })

  const currentBusiness = computed(
    () => businesses.value.find((b) => b.id === businessId.value) || null,
  )
  const currentUnit = computed(
    () => units.value.find((u) => u.id === unitId.value) || null,
  )
  const currentPrompt = computed(
    () => prompts.value.find((p) => p.id === promptId.value) || null,
  )

  function patchQuery(patch) {
    const next = { ...route.query }
    for (const [k, v] of Object.entries(patch)) {
      if (v == null || v === '') delete next[k]
      else next[k] = String(v)
    }
    router.replace({ query: next })
  }

  function normalizeRouteScope() {
    const next = normalizeGeoScope(
      {
        businessId: businessId.value,
        unitId: unitId.value,
        promptId: promptId.value,
      },
      {
        businesses: businesses.value,
        units: units.value,
        prompts: prompts.value,
      },
    )

    if (
      next.businessId === businessId.value &&
      next.unitId === unitId.value &&
      next.promptId === promptId.value
    ) return

    patchQuery({
      business_id: next.businessId,
      unit_id: next.unitId,
      prompt_id: next.promptId,
    })
  }

  async function load() {
    if (!tenantId.value) {
      businesses.value = []
      units.value = []
      prompts.value = []
      return
    }
    loading.value = true
    try {
      const [b, u, p] = await Promise.all([
        listGeoBusinesses(tenantId.value, { status: 'active' }),
        listGeoUnits(tenantId.value, { status: 'active' }),
        listGeoPrompts(tenantId.value, { status: 'active' }),
      ])
      businesses.value = b.items || []
      units.value = u.items || []
      prompts.value = p.items || []
      normalizeRouteScope()
    } catch {
      businesses.value = []
      units.value = []
      prompts.value = []
    } finally {
      loading.value = false
    }
  }

  watch(tenantId, load, { immediate: true })
  watch([businessId, unitId, promptId], () => {
    if (!loading.value) normalizeRouteScope()
  })

  return {
    tenantId,
    loading,
    businesses,
    units,
    prompts,
    filteredUnits,
    filteredPrompts,
    businessId,
    unitId,
    promptId,
    currentBusiness,
    currentUnit,
    currentPrompt,
    load,
  }
}
