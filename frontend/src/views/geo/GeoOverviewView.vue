<script setup>
import { geoSnapshotLink } from '../../utils/geoRoutes'
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  createTasksFromGaps,
  downloadGeoDailyMetricsCsv,
  downloadGeoDeliverablesMarkdown,
  fetchBrandMentionMetric,
  fetchGapWorkbench,
  fetchGeoContentStats,
  fetchGeoOpsAlerts,
  fetchGeoCitationInsights,
  fetchGeoCompetitorInsights,
  fetchGeoEvaluationInsights,
  fetchGeoWeeklyInsights,
  geoContentHealth,
  listGeoAnswerSnapshots,
  listGeoBusinesses,
  listGeoDailyMetrics,
  listGeoUnits,
  rebuildGeoDailyMetrics,
  fetchVisibilityPatrolOpsStatus,
} from '../../api/geoContent'
import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
import { diagnoseEmptyMonitoring } from '../../utils/geoEmptyReason'
import { useClientPager } from '../../composables/useClientPager'
import { useGeoTenant } from '../../composables/useGeoTenant'
import { useObservationPeriod } from '../../composables/useObservationPeriod'
import { session } from '../../store/session'
import {
  avgRecommendRank,
  pctDelta,
  shareOfVoiceRows,
  splitByMidpoint,
  visibilityScore,
  sentimentShare,
} from '../../utils/geoSnapshotSummary'
import {
  DAILY_METRIC_COLUMNS,
  REPORT_GLOSSARY,
  engineDisplay,
  engineKeyOf,
  engineLabelOf,
  fmtInt,
  fmtPct,
} from '../../utils/geoReportLabels'

const { tenantId } = useGeoTenant()
const tenantName = computed(() => {
  const hit = (session.tenants || []).find((t) => t.id === tenantId.value)
  return hit?.name || (tenantId.value ? `客户 #${tenantId.value}` : '未选择客户')
})
const {
  days: observationDays,
  start: obsStart,
  end: obsEnd,
  label: obsLabel,
  allowedDays: observationAllowedDays,
  setDays: setObservationDays,
} = useObservationPeriod()

/** 运维：账号管理权限 或 本地 DEV API Key */
const canForceRebuild = computed(
  () =>
    session.canManage ||
    (import.meta.env.DEV &&
      import.meta.env.VITE_API_KEY &&
      String(import.meta.env.VITE_API_KEY).trim() !== 'CHANGE_ME'),
)
const forceRebuildOpen = ref(false)
const forceRebuilding = ref(false)

const loading = ref(false)
const error = ref('')
const stats = ref(null)
const brandMetric = ref(null)
const healthOk = ref(null)

const businesses = ref([])
const units = ref([])
const filterBusinessId = ref(null)
const filterUnitId = ref(null)
/** 近 14 天切片序列（选中 scope） */
const dailySeries = ref([])
const dailyLatest = ref(null)
const citationNote = ref('')
const opsAlerts = ref([])
const opsSummary = ref(null)
const weekly = ref(null)
const patrolOps = ref(null)
const exporting = ref(false)
const snapshots = ref([])
const citations = ref(null)
const competitors = ref(null)
const evaluation = ref(null)
const engineDaily = ref([])
const qSearch = ref('')

const ENGINE_COLORS = {
  deepseek: '#4d6bfe',
  doubao: '#ff6a00',
  kimi: '#111827',
  qwen: '#615ced',
  tongyi: '#615ced',
  yuanbao: '#0ea5e9',
  chatgpt: '#10a37f',
  claude: '#d97706',
  gemini: '#4285f4',
  perplexity: '#1d4ed8',
  wenxin: '#2932e1',
}
function engineColor(key) {
  const k = String(key || '').toLowerCase()
  for (const [id, c] of Object.entries(ENGINE_COLORS)) {
    if (k.includes(id)) return c
  }
  return '#7c3aed'
}
const dailyPager = useClientPager(dailySeries, { pageSize: 14 })
const M = DAILY_METRIC_COLUMNS

const scopeHint = computed(() => {
  if (filterUnitId.value) {
    const u = units.value.find((x) => x.id === filterUnitId.value)
    return `单元切片 · ${u?.name || '#' + filterUnitId.value}`
  }
  if (filterBusinessId.value) {
    const b = businesses.value.find((x) => x.id === filterBusinessId.value)
    return `业务切片 · ${b?.name || '#' + filterBusinessId.value}`
  }
  return '租户全量'
})

const sampleComposition = computed(() => {
  const c =
    brandMetric.value?.sample_composition ||
    stats.value?.sample_composition ||
    null
  return c
})

/** W6: 未挂 unit 的意图词 → 日指标 unc 桶 */
const emptyReason = computed(() =>
  diagnoseEmptyMonitoring({
    engineCount: (patrolOps.value?.engines || []).length,
    enabledEngines: (patrolOps.value?.engines || []).filter((e) => e.enabled).length,
    patrolEnabled: !!patrolOps.value?.settings?.enabled,
    lastRunAt: patrolOps.value?.last_run?.created_at || patrolOps.value?.last_run?.id,
    snapshotCount: stats.value?.snapshots ?? 0,
    mentionCount:
      stats.value?.snapshots_mention_brand ??
      brandMetric.value?.brand_mentions ??
      null,
  }),
)

const promptsUnclassified = computed(
  () => Number(stats.value?.prompts_unclassified || 0),
)

const summaryCards = computed(() => {
  const s = stats.value
  if (!s) return []
  const d = dailyLatest.value
  const bm = brandMetric.value
  // 租户级主 KPI 走统一 metric service（观察期）；有业务/单元切片时日表最新一天作补充
  const scoped = !!(filterUnitId.value || filterBusinessId.value)
  const mention = scoped
    ? (d?.brand_mention_rate ?? bm?.brand_mention_rate ?? s.visibility_mention_rate)
    : (bm?.brand_mention_rate ?? s.visibility_mention_rate)
  const probe = scoped
    ? (d?.brand_probe_recognition_rate ?? bm?.brand_probe_recognition_rate ?? s.probe_recognition_rate)
    : (bm?.brand_probe_recognition_rate ?? s.probe_recognition_rate)
  const top1 = scoped
    ? (d?.top1_rate ?? bm?.top1_rate ?? s.visibility_top1_rate)
    : (bm?.top1_rate ?? s.visibility_top1_rate)
  const citeDomains = d?.distinct_cited_domains ?? s.distinct_cited_domains
  const citeCount = d?.citation_count
  const snapVis = scoped
    ? (d?.snapshots_visibility ?? bm?.snapshots_visibility ?? s.snapshots_visibility)
    : (bm?.snapshots_visibility ?? s.snapshots_visibility)
  const snapProbe = scoped
    ? (d?.snapshots_probe ?? bm?.snapshots_probe ?? s.snapshots_probe)
    : (bm?.snapshots_probe ?? s.snapshots_probe)

  return [
    {
      label: '优化意图词',
      value: fmtInt(s.prompts),
      hint: `探测题 ${fmtInt(s.prompts_probe)} · ${scopeHint.value}`,
      drill: '/geo/questions',
    },
    {
      label: '优化文章',
      value: fmtInt(s.tasks),
      hint: `待修 ${fmtInt(s.todo_blocked)} · 待发 ${fmtInt(s.todo_publish)}`,
      drill: '/geo/tasks',
    },
    {
      label: '已发布',
      value: fmtInt(s.published),
      hint: `就绪及以上 ${fmtInt(s.ready_or_beyond)}`,
      drill: '/geo/tasks',
    },
    {
      label: '品牌提及率',
      value: fmtPct(mention),
      hint: scoped
        ? `切片 · 排除探测 · 快照 ${fmtInt(snapVis)} · top1 ${fmtPct(top1)}`
        : `观察期 ${obsLabel.value} · 排除探测 · 快照 ${fmtInt(snapVis)} · top1 ${fmtPct(top1)}`,
      drill: '/geo/visibility',
    },
    {
      label: '品牌点名认知率',
      value: fmtPct(probe),
      hint: `仅探测题 · 样本 ${fmtInt(snapProbe)}`,
      drill: '/geo/visibility/snapshots',
    },
    {
      label: 'AI 引用次数',
      value: citeCount != null ? fmtInt(citeCount) : fmtInt(citeDomains),
      hint:
        citeCount != null
          ? `口径：URL 出现次数 · 独立域名 ${fmtInt(citeDomains)}`
          : `全时段独立被引域名 · 含引用快照 ${fmtInt(s.snapshots_with_citations)}（不受观察期限制）`,
      drill: '/geo/citations',
    },
    {
      label: '待复测意图词',
      value: fmtInt(s.prompts_need_recheck),
      hint: `品牌缺失标签 ${fmtInt(s.prompts_brand_missing)}`,
      drill: '/geo/recommend',
    },
    {
      label: '未分类意图词',
      value: fmtInt(s.prompts_unclassified),
      hint: '未挂优化单元 · 日指标记入 unc 桶',
      drill: '/geo/questions',
      warn: Number(s.prompts_unclassified || 0) > 0,
    },
  ]
})

function deltaText(v) {
  if (v == null) return ''
  const n = Number(v)
  if (Number.isNaN(n)) return ''
  return `${n > 0 ? '+' : ''}${n.toFixed(1)}%`
}

const mentionRate = computed(
  () =>
    weekly.value?.metrics?.brand_mention_rate ??
    brandMetric.value?.brand_mention_rate ??
    stats.value?.visibility_mention_rate,
)
const top1Rate = computed(
  () =>
    weekly.value?.metrics?.top1_rate ??
    brandMetric.value?.top1_rate ??
    stats.value?.visibility_top1_rate,
)
const citeCountVal = computed(
  () =>
    weekly.value?.metrics?.citation_count ??
    dailyLatest.value?.citation_count ??
    stats.value?.distinct_cited_domains,
)
const mentionDelta = computed(() =>
  deltaText(weekly.value?.metrics?.brand_mention_delta_pct),
)
const top1Delta = computed(() => {
  const cur = weekly.value?.metrics?.top1_rate
  const prev = weekly.value?.metrics?.top1_rate_prev
  if (cur == null || prev == null || !prev) return ''
  return deltaText(((cur - prev) / Math.abs(prev)) * 100)
})
const citeDelta = computed(() => {
  const cur = weekly.value?.metrics?.citation_count
  const prev = weekly.value?.metrics?.citation_count_prev
  if (cur == null || prev == null) return ''
  if (!prev) return cur ? '+100%' : ''
  return deltaText(((cur - prev) / Math.abs(prev)) * 100)
})

const sparkPoints = computed(() => {
  const rows = (dailySeries.value || []).slice(-8)
  if (rows.length < 2) return ''
  const vals = rows.map((r) => Number(r.brand_mention_rate) || 0)
  const max = Math.max(...vals, 0.01)
  return vals
    .map((v, i) => {
      const x = 20 + (i * 380) / (vals.length - 1)
      const y = 96 - (v / max) * 70
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
})

const engineRanks = computed(() =>
  (patrolOps.value?.engines || [])
    .filter((e) => e.enabled !== false && e.enabled !== 0)
    .slice(0, 4)
    .map((e, i) => ({
      rank: String(i + 1),
      name: engineLabelOf(e),
      value: (e.sample_mode || '') === 'openai_compat' && e.api_key_configured ? 80 : 45,
    })),
)

const briefActions = computed(() => {
  const s = stats.value || {}
  const actions = []
  if (s.prompts_brand_missing > 0) {
    actions.push({
      no: '01',
      title: '补齐未被推荐的提问',
      text: `${s.prompts_brand_missing} 条提问品牌缺失。优先生成直答内容和案例。`,
      impact: '预期提升核心提问推荐率',
      href: '/geo/questions?tag=brand_missing',
    })
  }
  if (s.todo_blocked > 0 || s.todo_publish > 0) {
    actions.push({
      no: String(actions.length + 1).padStart(2, '0'),
      title: '推进待发内容',
      text: `待修 ${fmtInt(s.todo_blocked)} 篇 · 待发 ${fmtInt(s.todo_publish)} 篇。`,
      impact: '让已有内容进入可被引用的页面',
      href: '/geo/tasks',
    })
  }
  const falling = weekly.value?.falling_topics || []
  if (falling.length) {
    actions.push({
      no: String(actions.length + 1).padStart(2, '0'),
      title: `防守「${falling[0].label}」`,
      text: '覆盖回落，建议补对比内容和事实澄清。',
      impact: '避免被竞品持续占位',
      href: '/geo/answers',
    })
  }
  if (actions.length < 3) {
    actions.push({
      no: String(actions.length + 1).padStart(2, '0'),
      title: '补齐第三方可信来源',
      text: '优先补行业媒体、客户案例、公开报告三类可被 AI 验证的材料。',
      impact: '降低推荐理由不稳定风险',
      href: '/geo/knowledge',
    })
  }
  return actions.slice(0, 3)
})

const briefJudgements = computed(() => {
  const bullets = weekly.value?.bullets || []
  if (bullets.length) {
    return bullets.slice(0, 3).map((b) => {
      const parts = String(b).split('：')
      return { title: parts[0] || '经营判断', text: parts.slice(1).join('：') || b }
    })
  }
  return [
    {
      title: '先把监测跑起来',
      text: '近 7 天还没有足够日指标。登记快照或跑巡检后再看增长是否均衡。',
    },
  ]
})

const briefRisks = computed(() => {
  const risks = []
  const falling = weekly.value?.falling_topics || []
  if (falling[0]) {
    risks.push({
      title: falling[0].label,
      happened: `覆盖回落${falling[0].delta_pct != null ? ` ${falling[0].delta_pct}%` : ''}`,
      detail: '建议本周补对比内容和事实',
    })
  }
  const top = weekly.value?.metrics?.top_competitor
  if (top) {
    risks.push({
      title: top,
      happened: `近端领先竞品覆盖约 ${fmtPct(weekly.value.metrics.top_competitor_rate)}`,
      detail: '盯防对比类提问',
    })
  }
  if (opsAlerts.value[0]) {
    risks.push({
      title: opsAlerts.value[0].title || '运营告警',
      happened: opsAlerts.value[0].detail || '',
      detail: '去处理以免监测中断',
    })
  }
  if (!risks.length) {
    risks.push({
      title: '官网可信度',
      happened: '引用可能仍偏少',
      detail: '检查知识库与发布 URL',
    })
  }
  return risks.slice(0, 3)
})

const overviewAnswer = computed(() => ({
  now: [
    '经营判断',
    weekly.value?.headline || '先看本周品牌是否被 AI 提及和推荐。',
    'CRM 或核心业务是否在拉动整体认知。',
  ],
  why: [
    '核心原因',
    'AI 更愿意引用结构清晰、事实可验证的内容。',
    '新增 GEO 文章和信源会反映在提及率上。',
  ],
  next: [
    '管理动作',
    briefActions.value[0]?.title || '查看本周建议',
    '把资源集中到少数可见的品牌经营动作。',
  ],
}))

const workbenchLinks = [
  { label: '优化文章', path: '/geo/tasks', desc: '主入口 · 列表 + 混合编辑器', vue: true, primary: true },
  { label: 'AI 可见度', path: '/geo/visibility', desc: '仪表盘 + 采集判断', vue: true, primary: true },
  { label: '期次对比', path: '/geo/period-diff', desc: 'before/after 品牌提及 Δ', vue: true, primary: true },
  { label: '交付摘要', path: '/geo/deliverables', desc: '周期报告 Markdown / 打印', vue: true, primary: true },
  { label: '竞品监测', path: '/geo/competitors', desc: '竞品出现、同题对比与日监测', vue: true },
  { label: 'AI 引用分析', path: '/geo/citations', desc: '被引域名与自有域占比', vue: true },
  { label: '优化业务', path: '/geo/businesses', desc: '业务 → 单元 → 意图词', vue: true, primary: true },
  { label: '优化意图词', path: '/geo/prompts', desc: '意图词 · 探测题标记', vue: true },
  { label: '事实库', path: '/geo/facts', desc: 'facts 管理', vue: true },
  { label: '发布渠道', path: '/geo/publishing', desc: '渠道与 Webhook', vue: true },
]

const router = useRouter()

function openWorkbench(link) {
  if (link?.path) router.push(link.path)
}

async function loadHierarchy() {
  if (!tenantId.value) {
    businesses.value = []
    units.value = []
    return
  }
  try {
    const [b, u] = await Promise.all([
      listGeoBusinesses(tenantId.value, { status: 'active' }),
      listGeoUnits(tenantId.value, { status: 'active' }),
    ])
    businesses.value = b.items || []
    units.value = u.items || []
  } catch {
    businesses.value = []
    units.value = []
  }
}

const filteredUnits = computed(() => {
  if (!filterBusinessId.value) return units.value
  return units.value.filter((u) => u.business_id === filterBusinessId.value)
})

function dailyQueryParams() {
  const params = {
    date_from: obsStart.value,
    date_to: obsEnd.value,
  }
  if (filterUnitId.value) {
    params.scope_level = 'unit'
    params.unit_id = filterUnitId.value
  } else if (filterBusinessId.value) {
    params.scope_level = 'business'
    params.business_id = filterBusinessId.value
  } else {
    params.scope_level = 'tenant'
  }
  return params
}

async function loadDailySlice() {
  if (!tenantId.value) {
    dailySeries.value = []
    dailyLatest.value = null
    return
  }
  try {
    let data = await listGeoDailyMetrics(tenantId.value, dailyQueryParams())
    let items = data.items || []
    // 窗口内无聚合行：静默补算（客户不看到「重算」按钮）
    if (!items.length) {
      try {
        await rebuildGeoDailyMetrics(tenantId.value, {
          dateFrom: obsStart.value,
          dateTo: obsEnd.value,
        })
        data = await listGeoDailyMetrics(tenantId.value, dailyQueryParams())
        items = data.items || []
      } catch {
        /* 补算失败仍展示空态 */
      }
    }
    dailySeries.value = items
    dailyLatest.value = items.length ? items[items.length - 1] : null
    citationNote.value = data.citation_stat_note || ''
  } catch {
    dailySeries.value = []
    dailyLatest.value = null
  }
}

async function loadBrandMetric() {
  if (!tenantId.value) {
    brandMetric.value = null
    return
  }
  try {
    brandMetric.value = await fetchBrandMentionMetric(tenantId.value, {
      days: observationDays.value,
    })
  } catch {
    brandMetric.value = null
  }
}

async function loadOps() {
  if (!tenantId.value) {
    opsAlerts.value = []
    opsSummary.value = null
    return
  }
  try {
    const data = await fetchGeoOpsAlerts(tenantId.value)
    opsAlerts.value = data.alerts || []
    opsSummary.value = data.summary || null
  } catch {
    opsAlerts.value = []
    opsSummary.value = null
  }
}

async function loadWeekly() {
  if (!tenantId.value) {
    weekly.value = null
    return
  }
  try {
    const params = {}
    if (filterUnitId.value) params.scope_key = `u${filterUnitId.value}`
    else if (filterBusinessId.value) params.scope_key = `b${filterBusinessId.value}`
    weekly.value = await fetchGeoWeeklyInsights(tenantId.value, params)
  } catch {
    weekly.value = null
  }
}

async function loadPatrolOps() {
  if (!tenantId.value) {
    patrolOps.value = null
    return
  }
  try {
    patrolOps.value = await fetchVisibilityPatrolOpsStatus(tenantId.value)
  } catch {
    patrolOps.value = null
  }
}

async function loadDashboardExtras() {
  if (!tenantId.value) {
    snapshots.value = []
    citations.value = null
    competitors.value = null
    evaluation.value = null
    engineDaily.value = []
    return
  }
  const params = { days: observationDays.value }
  const [sn, ci, co, ev, ed] = await Promise.all([
    listGeoAnswerSnapshots(tenantId.value, { limit: 80 }).catch(() => ({ items: [] })),
    fetchGeoCitationInsights(tenantId.value, params).catch(() => null),
    fetchGeoCompetitorInsights(tenantId.value).catch(() => null),
    fetchGeoEvaluationInsights(tenantId.value, params).catch(() => null),
    listGeoDailyMetrics(tenantId.value, {
      date_from: obsStart.value,
      date_to: obsEnd.value,
      include_engines: true,
    }).catch(() => ({ items: [] })),
  ])
  const items = sn.items || sn.snapshots || []
  const lo = Date.parse(`${obsStart.value}T00:00:00`)
  const hi = Date.parse(`${obsEnd.value}T23:59:59`)
  snapshots.value = items.filter((s) => {
    const t = Date.parse(s.captured_at || '')
    if (!Number.isFinite(t) || !Number.isFinite(lo) || !Number.isFinite(hi)) return true
    return t >= lo && t <= hi
  })
  citations.value = ci
  competitors.value = co
  evaluation.value = ev
  engineDaily.value = ed.items || []
}

function mapEngineChips(list) {
  return (list || [])
    .map((e) => {
      const key = engineKeyOf(e)
      if (!key) return null
      return { key, name: engineLabelOf(e), color: engineColor(key) }
    })
    .filter(Boolean)
}

const dashEngines = computed(() => {
  const fromPatrol = mapEngineChips(
    (patrolOps.value?.engines || []).filter((e) => e.enabled !== false && e.enabled !== 0),
  )
  if (fromPatrol.length) return fromPatrol
  const fromDaily = [
    ...new Set(
      engineDaily.value
        .filter((r) => String(r.scope_key || '').startsWith('t@'))
        .map((r) => engineKeyOf(r.engine || String(r.scope_key || '').split('@')[1] || ''))
        .filter(Boolean),
    ),
  ]
  if (fromDaily.length) return mapEngineChips(fromDaily)
  const fromSnaps = [...new Set(snapshots.value.map((s) => engineKeyOf(s.engine)).filter(Boolean))]
  return mapEngineChips(fromSnaps)
})

const lastPatrolLabel = computed(() => {
  const run = patrolOps.value?.last_run || patrolOps.value?.last_run
  const t = run?.created_at || run?.finished_at || run?.started_at
  if (!t) return '尚未巡检'
  return String(t).replace('T', ' ').slice(0, 16)
})

const windowSplit = computed(() =>
  splitByMidpoint(snapshots.value, obsStart.value, obsEnd.value),
)

/** 加权可见度得分；样本不足时回退到提及率，不把提及率标成「得分」而不说明 */
const visScore = computed(() => {
  const scored = visibilityScore(snapshots.value)
  if (scored != null) return scored
  return brandMetric.value?.brand_mention_rate ?? stats.value?.visibility_mention_rate
})
const visScoreFromSnaps = computed(() => visibilityScore(snapshots.value) != null)
const visDelta = computed(() => {
  const { prev, cur } = windowSplit.value
  if (prev.length && cur.length) {
    return pctDelta(visibilityScore(cur), visibilityScore(prev))
  }
  return weekly.value?.metrics?.brand_mention_delta_pct ?? null
})

const mentionCount = computed(() => {
  if (snapshots.value.length) return snapshots.value.filter((s) => s.mentions_brand).length
  return brandMetric.value?.brand_mentions ?? stats.value?.snapshots_mention_brand
})
const mentionCountDelta = computed(() => {
  const { prev, cur } = windowSplit.value
  if (!prev.length || !cur.length) return null
  const a = prev.filter((s) => s.mentions_brand).length
  const b = cur.filter((s) => s.mentions_brand).length
  return pctDelta(b, a)
})

const avgRank = computed(() => avgRecommendRank(snapshots.value))
const avgRankDelta = computed(() => {
  const { prev, cur } = windowSplit.value
  if (!prev.length || !cur.length) return null
  const a = avgRecommendRank(prev)
  const b = avgRecommendRank(cur)
  if (a == null || b == null) return null
  return a - b
})

const positiveShare = computed(() => {
  const fromSnaps = sentimentShare(snapshots.value)
  if (fromSnaps.n) return fromSnaps.positive
  const sc = evaluation.value?.sentiment_counts || {}
  const total =
    Number(sc.positive || 0) + Number(sc.neutral || 0) + Number(sc.negative || 0)
  if (!total) return null
  return Number(sc.positive || 0) / total
})
const positiveDelta = computed(() => {
  const { prev, cur } = windowSplit.value
  if (!prev.length || !cur.length) return null
  const a = sentimentShare(prev).positive
  const b = sentimentShare(cur).positive
  if (a == null || b == null) return null
  return (b - a) * 100
})

function deltaLabel(v, { pp = false, rank = false } = {}) {
  if (v == null || Number.isNaN(Number(v)) || Number(v) === 0) return ''
  const n = Number(v)
  const arrow = n < 0 ? '▼ ' : '▲ '
  if (rank) return `${n > 0 ? '▲ 上升' : '▼ 下降'} ${Math.abs(n).toFixed(1)}`
  if (pp) return `${arrow}${Math.abs(n).toFixed(1)} pp`
  return `${arrow}${Math.abs(n).toFixed(1)}%`
}
function deltaTone(v) {
  if (v == null || Number.isNaN(Number(v)) || Number(v) === 0) return 'hint'
  return Number(v) < 0 ? 'down' : 'up'
}

const sovRows = computed(() => shareOfVoiceRows(snapshots.value, '本品牌'))

function exposureScore(s) {
  if (s.brand_position === 'first') return 4
  if (s.brand_position === 'alternative') return 3
  if (s.mentions_brand || s.brand_position === 'mentioned') return 2
  if ((s.competitors || []).length) return 1
  return 0
}

const promptRows = computed(() => {
  const q = qSearch.value.trim()
  let rows = snapshots.value.map((s) => {
    let badge = '未提及'
    let tone = 'red'
    if (s.mentions_brand) {
      badge = '已提及'
      tone = 'green'
    } else if ((s.competitors || []).length) {
      badge = '竞品提及'
      tone = 'amber'
    }
    let rank = '—'
    if (s.brand_position === 'first') rank = '1'
    else if (s.brand_position === 'alternative') rank = '2'
    else if (s.brand_position === 'mentioned') rank = '3'
    return {
      promptId: s.prompt_id,
      question: s.prompt_question || `提问 #${s.prompt_id}`,
      engine: engineDisplay(s.engine),
      badge,
      tone,
      rank,
      score: exposureScore(s),
      at: s.captured_at || '',
    }
  })
  if (q) rows = rows.filter((r) => r.question.includes(q) || r.engine.includes(q))
  rows.sort((a, b) => b.score - a.score || String(b.at).localeCompare(String(a.at)))
  const seen = new Set()
  const unique = []
  for (const r of rows) {
    if (seen.has(r.question)) continue
    seen.add(r.question)
    unique.push(r)
    if (unique.length >= 5) break
  }
  return unique
})

const sourceRows = computed(() => {
  const q = qSearch.value.trim()
  let items = citations.value?.items || []
  if (q) {
    items = items.filter(
      (x) =>
        String(x.domain || '').includes(q) ||
        String(x.blueprint_channel_name || '').includes(q),
    )
  }
  return items.slice(0, 5).map((x) => ({
    tag: x.blueprint_channel_name || (x.is_own_domain ? '官网' : '外部'),
    text: x.domain,
    count: x.cite_count,
  }))
})

const engineTrendDates = computed(() => {
  const rows = engineDaily.value.filter((r) => String(r.scope_key || '').startsWith('t@'))
  return [...new Set(rows.map((r) => String(r.metric_date || '')))].filter(Boolean).sort()
})

const engineTrend = computed(() => {
  const rows = engineDaily.value.filter((r) => String(r.scope_key || '').startsWith('t@'))
  const dates = [...new Set(rows.map((r) => String(r.metric_date || '')))].filter(Boolean).sort()
  const byEng = new Map()
  for (const r of rows) {
    const key = r.engine || String(r.scope_key || '').split('@')[1] || 'other'
    if (!byEng.has(key)) byEng.set(key, new Map())
    byEng.get(key).set(String(r.metric_date), Number(r.brand_mention_rate) || 0)
  }
  const n = dates.length
  return [...byEng.entries()].slice(0, 5).map(([key, byDate]) => {
    const pts = dates
      .map((d, i) => {
        if (!byDate.has(d)) return null
        const v = Math.min(1, Math.max(0, byDate.get(d)))
        const x = n === 1 ? 378 : 36 + (i * (720 - 36)) / (n - 1)
        const y = 210 - v * 170
        return `${x.toFixed(1)},${y.toFixed(1)}`
      })
      .filter(Boolean)
    return {
      key,
      name: engineDisplay(key),
      color: engineColor(key),
      points: pts.join(' '),
    }
  }).filter((s) => s.points)
})

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const [s, h] = await Promise.all([
      fetchGeoContentStats(tenantId.value),
      geoContentHealth().catch(() => null),
      loadHierarchy(),
      loadDailySlice(),
      loadBrandMetric(),
      loadOps(),
      loadWeekly(),
      loadPatrolOps(),
      loadDashboardExtras(),
    ])
    stats.value = s
    healthOk.value = h ? h.status === 'ok' : null
  } catch (e) {
    error.value = e.message || '加载失败'
    stats.value = null
  } finally {
    loading.value = false
  }
}

async function exportCsv() {
  if (!tenantId.value) return
  exporting.value = true
  try {
    let body = ''
    let name = `geo-brief-${tenantId.value}.md`
    try {
      body = await downloadGeoDeliverablesMarkdown(tenantId.value, {
        days: observationDays.value,
      })
    } catch {
      body = await downloadGeoDailyMetricsCsv(tenantId.value, dailyQueryParams())
      name = `geo-daily-${tenantId.value}.csv`
    }
    const blob = new Blob(['\ufeff' + body], { type: 'text/plain;charset=utf-8' })
    const href = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = href
    a.download = name
    a.click()
    URL.revokeObjectURL(href)
    ElMessage.success(name.endsWith('.md') ? '已导出经营简报' : '已导出 CSV')
  } catch (e) {
    ElMessage.error(e.message || '导出失败')
  } finally {
    exporting.value = false
  }
}

const approving = ref(false)
async function approvePlan() {
  if (!tenantId.value) return
  approving.value = true
  try {
    const gaps = await fetchGapWorkbench(tenantId.value)
    const ids = (gaps.items || [])
      .filter((i) => i.needs_task)
      .slice(0, 3)
      .map((i) => i.prompt_id)
    if (!ids.length) {
      ElMessage.info('当前没有待建内容的缺口')
      router.push('/geo/tasks')
      return
    }
    const r = await createTasksFromGaps(tenantId.value, ids)
    ElMessage.success(`已从缺口创建 ${r.created ?? ids.length} 篇 GEO 文章`)
    router.push('/geo/tasks')
  } catch (e) {
    ElMessage.error(e.message || '创建失败')
  } finally {
    approving.value = false
  }
}

function alertType(level) {
  if (level === 'error') return 'error'
  if (level === 'warning') return 'warning'
  return 'info'
}

function goAlert(a) {
  if (a?.href) router.push(a.href)
}

function refresh() {
  load().then(() => {
    if (!error.value) ElMessage.success('已刷新')
  })
}

async function forceRebuildRange() {
  if (!tenantId.value || !canForceRebuild.value) return
  forceRebuilding.value = true
  try {
    const r = await rebuildGeoDailyMetrics(tenantId.value, {
      dateFrom: obsStart.value,
      dateTo: obsEnd.value,
    })
    ElMessage.success(
      `运维重算完成 ${r.period?.from || obsStart.value} ~ ${r.period?.to || obsEnd.value}` +
        (r.day_count != null ? ` · ${r.day_count} 天` : ''),
    )
    forceRebuildOpen.value = false
    await loadDailySlice()
    await loadBrandMetric()
  } catch (e) {
    ElMessage.error(e.message || '强制重算失败')
  } finally {
    forceRebuilding.value = false
  }
}

function onBusinessChange() {
  // 业务变更时清单元（若不在新业务下）
  if (
    filterUnitId.value &&
    !filteredUnits.value.some((u) => u.id === filterUnitId.value)
  ) {
    filterUnitId.value = null
  }
  loadDailySlice()
  loadWeekly()
}

watch(tenantId, load)
watch(filterUnitId, () => {
  loadDailySlice()
  loadWeekly()
})
watch([observationDays, obsStart, obsEnd], () => {
  loadDailySlice()
  loadBrandMetric()
  loadDashboardExtras()
})
onMounted(load)
</script>

<template>
  <GeoWorkbenchPage
    title="概览"
    :sub="`品牌：${tenantName} · 覆盖 ${dashEngines.length} 个模型 · ${obsLabel}`"
    :loading="loading"
  >
    <template #actions>
      <select
        class="gd-search gd-days"
        :value="observationDays"
        @change="setObservationDays(Number($event.target.value))"
      >
        <option v-for="d in observationAllowedDays" :key="d" :value="d">近 {{ d }} 天</option>
      </select>
      <input v-model="qSearch" class="gd-search" placeholder="搜索提问 / 来源…" />
      <button class="gd-btn" :disabled="exporting" @click="exportCsv">导出报告</button>
      <button class="gd-btn primary" @click="router.push('/geo/questions')">+ 添加监控词</button>
    </template>
  <div class="geo-dash">

    <el-alert v-if="error" :title="error" type="error" :closable="false" class="mb" />

    <div class="gd-card gd-engines">
      <span class="gd-engines-label">监测引擎</span>
      <div class="gd-engines-list">
        <span v-for="e in dashEngines" :key="e.key" class="gd-engine-chip">
          <i class="gd-dot" :style="{ background: e.color }" />{{ e.name }}
        </span>
        <span v-if="!dashEngines.length" class="gd-sub" style="margin:0">尚未开启引擎</span>
      </div>
      <span class="gd-engines-meta">最后巡检：{{ lastPatrolLabel }}</span>
    </div>

    <div class="gd-kpis">
      <div class="gd-card gd-stat">
        <div class="label">AI 可见度得分</div>
        <div class="value">{{ fmtPct(visScore) }}</div>
        <div class="delta" :class="deltaTone(visDelta)">
          {{ deltaLabel(visDelta) || (visScoreFromSnaps ? '加权提及+顺位' : '样本不足，暂用提及率') }}
        </div>
      </div>
      <div class="gd-card gd-stat">
        <div class="label">品牌提及次数</div>
        <div class="value">{{ fmtInt(mentionCount) }}</div>
        <div class="delta" :class="deltaTone(mentionCountDelta)">
          {{ deltaLabel(mentionCountDelta) || '观察期内快照' }}
        </div>
      </div>
      <div class="gd-card gd-stat">
        <div class="label">平均推荐顺位</div>
        <div class="value">{{ avgRank != null ? Number(avgRank).toFixed(1) : '—' }}</div>
        <div class="delta" :class="avgRankDelta == null ? 'hint' : (avgRankDelta >= 0 ? 'up' : 'down')">
          {{ deltaLabel(avgRankDelta, { rank: true }) || '首位=1 · 备选=2 · 提及=3' }}
        </div>
      </div>
      <div class="gd-card gd-stat">
        <div class="label">正向评价信号</div>
        <div class="value">{{ fmtPct(positiveShare) }}</div>
        <div class="delta" :class="deltaTone(positiveDelta)">
          {{ deltaLabel(positiveDelta, { pp: true }) || '已标注情感占比' }}
        </div>
      </div>
    </div>

    <div class="gd-mid">
      <div class="gd-card">
        <div class="gd-hd">
          <h3>各 AI 引擎可见度趋势</h3>
          <span class="more">{{ obsLabel }}</span>
        </div>
        <div class="gd-bd">
          <svg v-if="engineTrend.length" viewBox="0 0 720 230" width="100%" height="230">
            <g stroke="#eef0f5">
              <line x1="36" y1="40" x2="720" y2="40" />
              <line x1="36" y1="125" x2="720" y2="125" />
              <line x1="36" y1="210" x2="720" y2="210" />
            </g>
            <text x="0" y="44" font-size="10" fill="#9aa1ad">100%</text>
            <text x="0" y="129" font-size="10" fill="#9aa1ad">50%</text>
            <text x="0" y="214" font-size="10" fill="#9aa1ad">0%</text>
            <polyline
              v-for="s in engineTrend"
              :key="s.key"
              :points="s.points"
              fill="none"
              :stroke="s.color"
              stroke-width="2.5"
            />
            <text
              v-if="engineTrendDates[0]"
              x="36"
              y="228"
              font-size="10"
              fill="#9aa1ad"
            >{{ String(engineTrendDates[0]).slice(5) }}</text>
            <text
              v-if="engineTrendDates.length > 2"
              x="360"
              y="228"
              font-size="10"
              fill="#9aa1ad"
              text-anchor="middle"
            >{{ String(engineTrendDates[Math.floor(engineTrendDates.length / 2)]).slice(5) }}</text>
            <text
              v-if="engineTrendDates.length > 1"
              x="720"
              y="228"
              font-size="10"
              fill="#9aa1ad"
              text-anchor="end"
            >{{ String(engineTrendDates[engineTrendDates.length - 1]).slice(5) }}</text>
          </svg>
          <div v-else class="gd-sub">观察期内暂无按引擎日指标。开启巡检后会出现趋势。</div>
          <div class="gd-legend">
            <span v-for="s in engineTrend" :key="'lg-'+s.key"><i :style="{ background: s.color }" />{{ s.name }}</span>
          </div>
        </div>
      </div>
      <div class="gd-card">
        <div class="gd-hd"><h3>AI 声量占比 (SOV)</h3></div>
        <div class="gd-bd">
          <div class="gd-sov">
            <div v-for="r in sovRows" :key="r.name">
              <div class="row" :class="{ own: r.bar === 'own' }"><span>{{ r.name }}</span><b>{{ r.value.toFixed(1) }}%</b></div>
              <div class="gd-bar" :class="r.bar"><span :style="{ width: Math.min(100, r.width) + '%' }" /></div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="gd-bottom">
      <div class="gd-card">
        <div class="gd-hd">
          <h3>高曝光提问 (Prompt)</h3>
          <a class="more" @click="router.push('/geo/questions')">查看全部</a>
        </div>
        <div class="gd-bd" style="padding:0">
          <table>
            <thead><tr><th>用户提问</th><th>引擎</th><th>是否提及</th><th>顺位</th></tr></thead>
            <tbody>
              <tr
                v-for="(r, i) in promptRows"
                :key="i"
                class="geo-click"
                @click="r.promptId && router.push(geoSnapshotLink({ prompt_id: r.promptId }))"
              >
                <td>「{{ r.question }}」</td>
                <td>{{ r.engine }}</td>
                <td><span class="gd-badge" :class="r.tone">{{ r.badge }}</span></td>
                <td>{{ r.rank }}</td>
              </tr>
              <tr v-if="!promptRows.length"><td colspan="4" class="gd-sub">暂无回答快照</td></tr>
            </tbody>
          </table>
        </div>
      </div>
      <div class="gd-card">
        <div class="gd-hd">
          <h3>AI 引用的内容来源</h3>
          <span class="gd-badge blue" style="cursor:pointer" @click="router.push('/geo/citations')">提升引用率</span>
        </div>
        <div class="gd-bd">
          <ul class="gd-sources">
            <li v-for="s in sourceRows" :key="s.text">
              <span class="gd-tag">{{ s.tag }}</span>
              {{ s.text }} 被引用 {{ s.count }} 次
            </li>
            <li v-if="!sourceRows.length" class="gd-sub">暂无引用来源</li>
          </ul>
        </div>
      </div>
    </div>
  </div>
  </GeoWorkbenchPage>
</template>
<style scoped>
.health {
  margin-left: 8px;
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 999px;
}
.week-headline {
  margin: 0 0 8px;
  font-size: 15px;
  font-weight: 600;
  color: #111827;
}
.week-bullets {
  margin: 0;
  padding-left: 1.2rem;
  color: #374151;
  font-size: 13px;
  line-height: 1.6;
}
.week-period { margin: 10px 0 0; font-size: 12px; }
.health.ok {
  background: #ecfdf5;
  color: #047857;
}
.health.bad {
  background: #fef2f2;
  color: #b91c1c;
}
.mb {
  margin-bottom: 16px;
}
.empty-daily {
  font-size: 13px;
  color: #64748b;
  padding: 12px 0 4px;
  line-height: 1.5;
}
.next-list {
  margin: 0;
  padding-left: 1.25rem;
  font-size: 13px;
  color: #334155;
  line-height: 1.85;
}
.ops-title {
  cursor: pointer;
  font-weight: 600;
}
.ops-detail {
  font-size: 13px;
  color: #475569;
  line-height: 1.5;
  margin-top: 2px;
}
.ops-summary {
  padding: 0 4px 4px;
}
.panel-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.panel-title-row .panel-title {
  margin-bottom: 0;
}
.sample-compose {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 12px;
  margin-bottom: 14px;
  padding: 10px 14px;
  border-radius: 12px;
  background: #f0f9ff;
  border: 1px solid #bae6fd;
  font-size: 13px;
  color: #0f172a;
}
.sample-compose.warn {
  background: #fffbeb;
  border-color: #fde68a;
}
.sample-compose-title {
  font-weight: 700;
  color: #0369a1;
  flex-shrink: 0;
}
.sample-compose.warn .sample-compose-title {
  color: #b45309;
}
.sample-compose-body {
  font-weight: 600;
  color: #1e293b;
}
.sample-compose-meta {
  margin-left: auto;
  font-size: 11px;
  color: #94a3b8;
}
.geo-kpi.clickable {
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.geo-kpi.clickable:hover {
  border-color: #93c5fd;
  box-shadow: 0 4px 14px rgba(24, 95, 165, 0.1);
}
.geo-kpi.kpi-warn {
  border-color: #fcd34d;
  background: #fffbeb;
}
.action-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  align-items: center;
  margin: 0 0 14px;
  padding: 10px 14px;
  border-radius: 12px;
  background: #f8fafc;
  border: 1px solid #e8edf5;
  font-size: 13px;
  color: #334155;
}
.strip-link {
  margin-left: 6px;
  color: #185fa5;
  font-weight: 650;
  text-decoration: none;
}
.strip-link:hover { text-decoration: underline; }
.force-hint {
  font-size: 13px;
  line-height: 1.55;
  color: #475569;
  margin: 0;
}
.force-hint code {
  font-size: 12px;
  background: #f1f5f9;
  padding: 1px 6px;
  border-radius: 4px;
}
</style>
