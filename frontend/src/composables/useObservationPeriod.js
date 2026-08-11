/**
 * GEO 全局观察期（Asia/Shanghai 日历日语义，由后端按时区切分）。
 * 顶栏与报表页共用同一份状态；localStorage 记忆天数。
 */
import { computed, reactive, watch } from 'vue'

const STORAGE_KEY = 'geo_observation_days'
const ALLOWED_DAYS = [7, 14, 30, 90]

function todayIso() {
  // 前端用本地日；后端再按 Shanghai 对齐。中国用户本地≈上海。
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function addDaysIso(iso, delta) {
  const d = new Date(`${iso}T12:00:00`)
  d.setDate(d.getDate() + delta)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

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
  const end = computed(() => state.customTo || todayIso())
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
