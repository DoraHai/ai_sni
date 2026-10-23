/**
 * GEO 全局观察期（Asia/Shanghai 日历日语义，由后端按时区切分）。
 * 各页顶栏共用状态；报告页使用本页日期范围。localStorage 记忆天数。
 */
import { computed, reactive, watch } from 'vue'
import { shanghaiDate, addDaysIso } from '../utils/geoDate'

const STORAGE_KEY = 'geo_observation_days'
const ALLOWED_DAYS = [7, 14, 30, 90]

function readStoredDays() {
  try {
    const n = Number(localStorage.getItem(STORAGE_KEY))
    if (ALLOWED_DAYS.includes(n)) return n
  } catch {
    /* ignore */
  }
  return 14
}

const state = reactive({
  days: readStoredDays(),
  /** 可选：自定义起止（YYYY-MM-DD）；为空则用 days 推算 */
  customFrom: '',
  customTo: '',
})

watch(
  () => state.days,
  (n) => {
    try {
      localStorage.setItem(STORAGE_KEY, String(n))
    } catch {
      /* ignore */
    }
  },
)

export function useObservationPeriod() {
  const end = computed(() => state.customTo || shanghaiDate())
  const start = computed(() => {
    if (state.customFrom) return state.customFrom
    return addDaysIso(end.value, -(Math.max(1, state.days) - 1))
  })
  const label = computed(() => {
    if (state.customFrom && state.customTo) {
      return `${state.customFrom} ~ ${state.customTo}`
    }
    return `近 ${state.days} 天 · ${start.value} ~ ${end.value}`
  })
  const queryParams = computed(() => ({
    date_from: start.value,
    date_to: end.value,
    days: state.days,
  }))

  function setDays(n) {
    const v = Number(n)
    if (!ALLOWED_DAYS.includes(v)) return
    state.days = v
    state.customFrom = ''
    state.customTo = ''
  }

  function setCustomRange(from, to) {
    state.customFrom = from || ''
    state.customTo = to || ''
  }

  function clearCustom() {
    state.customFrom = ''
    state.customTo = ''
  }

  return {
    state,
    days: computed(() => state.days),
    start,
    end,
    label,
    queryParams,
    allowedDays: ALLOWED_DAYS,
    setDays,
    setCustomRange,
    clearCustom,
  }
}
