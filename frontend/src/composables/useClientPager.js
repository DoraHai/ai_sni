import { computed, reactive, ref, watch } from 'vue'

/**
 * Client-side table pager for GEO lists that return full arrays.
 * Returns a reactive object so nested refs unwrap in templates.
 * @param {import('vue').Ref|import('vue').ComputedRef} sourceRef - array ref/computed
 * @param {{ pageSize?: number }} [opts]
 */
export function useClientPager(sourceRef, opts = {}) {
  const page = ref(1)
  const pageSize = ref(opts.pageSize ?? 20)

  const total = computed(() => {
    const list = sourceRef.value
    return Array.isArray(list) ? list.length : 0
  })

  const pagedItems = computed(() => {
    const list = Array.isArray(sourceRef.value) ? sourceRef.value : []
    const start = (page.value - 1) * pageSize.value
    return list.slice(start, start + pageSize.value)
  })

  function onPageChange(p) {
    page.value = p
  }

  function onSizeChange(s) {
    pageSize.value = s
    page.value = 1
  }

  function resetPage() {
    page.value = 1
  }

  watch(total, (t) => {
    const maxPage = Math.max(1, Math.ceil(t / pageSize.value) || 1)
    if (page.value > maxPage) page.value = maxPage
  })

  return reactive({
    page,
    pageSize,
    total,
    pagedItems,
    onPageChange,
    onSizeChange,
    resetPage,
  })
}
