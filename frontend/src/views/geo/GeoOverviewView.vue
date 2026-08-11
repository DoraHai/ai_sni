<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  downloadGeoDailyMetricsCsv,
  fetchBrandMentionMetric,
  fetchGeoContentStats,
  fetchGeoOpsAlerts,
  fetchGeoWeeklyInsights,
  geoContentHealth,
  listGeoBusinesses,
  listGeoDailyMetrics,
  listGeoUnits,
  rebuildGeoDailyMetrics,
  staticGeoEditorUrl,
} from '../../api/geoContent'
import { useClientPager } from '../../composables/useClientPager'
import { useGeoTenant } from '../../composables/useGeoTenant'
import { useObservationPeriod } from '../../composables/useObservationPeriod'
import { session } from '../../store/session'
import {
  DAILY_METRIC_COLUMNS,
  REPORT_GLOSSARY,
  fmtInt,
  fmtPct,
} from '../../utils/geoReportLabels'

const { tenantId } = useGeoTenant()
const {
  days: observationDays,
  start: obsStart,
  end: obsEnd,
  label: obsLabel,
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
const exporting = ref(false)
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
      drill: '/geo/prompts',
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
      drill: '/geo/visibility/patrol',
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
      drill: '/geo/gaps',
    },
  ]
})

const workbenchLinks = [
  { label: '优化文章', path: '/geo/tasks', desc: '主入口 · 列表 + 混合编辑器', vue: true, primary: true },
  { label: 'AI 可见度', path: '/geo/visibility', desc: '登记 / 多引擎探测', vue: true, primary: true },
  { label: '全自动巡检', path: '/geo/visibility/patrol', desc: '多词×多引擎自动探测落库', vue: true, primary: true },
  { label: '期次对比', path: '/geo/period-diff', desc: 'before/after 品牌提及 Δ', vue: true, primary: true },
  { label: '交付摘要', path: '/geo/deliverables', desc: '周期报告 Markdown / 打印', vue: true, primary: true },
  { label: '竞品监测', path: '/geo/competitors', desc: '竞品出现、同题对比与日监测', vue: true },
  { label: '评价与位置', path: '/geo/evaluation', desc: '情感、位置与引用质量', vue: true },
  { label: 'AI 引用分析', path: '/geo/citations', desc: '被引域名与自有域占比', vue: true },
  { label: '内容工作台', path: '/geo/workbench', desc: 'Vue 页枢纽', vue: true },
  { label: '优化业务', path: '/geo/businesses', desc: '业务 → 单元 → 意图词', vue: true },
  { label: '优化意图词', path: '/geo/prompts', desc: '意图词 · 探测题标记', vue: true },
  { label: '事实库', path: '/geo/facts', desc: 'facts 管理', vue: true },
  { label: '发布渠道', path: '/geo/publishing', desc: '渠道与 Webhook', vue: true },
  {
    label: '静态编辑器（兼容）',
    path: 'static-editor',
    desc: '完整流水线后备 · :5176/geo/editor.html',
    static: true,
  },
  { label: '网站体检', path: '/diagnostic-center/', desc: '诊断 → 内容桥接', external: true },
]

const router = useRouter()

function openWorkbench(link) {
  if (link.vue) {
    router.push(link.path)
    return
  }
  if (link.external) {
    window.location.assign(link.path)
    return
  }
  if (link.static) {
    const tid = tenantId.value || 1
    window.open(staticGeoEditorUrl(tid), '_blank')
    return
  }
  window.open(link.path, '_blank')
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
    const csv = await downloadGeoDailyMetricsCsv(tenantId.value, dailyQueryParams())
    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' })
    const href = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = href
    a.download = `geo-daily-${tenantId.value}.csv`
    a.click()
    URL.revokeObjectURL(href)
    ElMessage.success('已导出 CSV')
  } catch (e) {
    ElMessage.error(e.message || '导出失败')
  } finally {
    exporting.value = false
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
})
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="geo-overview geo-page">
    <div class="page-header">
      <div>
        <div class="page-title">GEO 概览</div>
        <div class="page-desc">
          运营告警与本周洞察优先；KPI 与趋势跟随顶栏<strong>观察期</strong>（{{ obsLabel }}），可按业务/单元切片。
          <span v-if="healthOk === true" class="health ok">API 正常</span>
          <span v-else-if="healthOk === false" class="health bad">API 异常</span>
        </div>
      </div>
      <div class="header-actions">
        <el-button :loading="loading" @click="refresh">刷新</el-button>
        <el-button :loading="exporting" @click="exportCsv">导出 CSV</el-button>
        <el-button
          v-if="canForceRebuild"
          type="warning"
          plain
          @click="forceRebuildOpen = true"
        >
          运维·强制重算
        </el-button>
        <el-button type="primary" @click="openWorkbench(workbenchLinks[0])">打开工作台</el-button>
      </div>
    </div>

    <el-dialog
      v-model="forceRebuildOpen"
      title="运维：强制重算日指标"
      width="440px"
      class="geo-form-dialog"
    >
      <p class="force-hint">
        仅管理员 / 本地开发可见。将按<strong>当前观察期</strong>
        （{{ obsStart }} ~ {{ obsEnd }}）重写
        <code>geo_daily_metrics</code>，客户界面已隐藏常规「重算」。
      </p>
      <template #footer>
        <el-button @click="forceRebuildOpen = false">取消</el-button>
        <el-button type="warning" :loading="forceRebuilding" @click="forceRebuildRange">
          确认重算观察期
        </el-button>
      </template>
    </el-dialog>

    <details class="geo-glossary">
      <summary>统计口径（点击展开）</summary>
      <ul>
        <li>观察期：顶栏全局选择，默认近 14 个上海日历日；品牌提及率/点名认知率/日趋势均跟此窗。</li>
        <li>品牌提及率：排除探测题；无可见性样本为「—」而非 0%。</li>
        <li>样本构成：真采样 / 模拟 / 人工；含模拟时不得当真实引擎效果汇报。</li>
        <li v-for="(line, i) in REPORT_GLOSSARY.overview" :key="i">{{ line }}</li>
        <li v-for="(line, i) in REPORT_GLOSSARY.dailyMetrics" :key="`d-${i}`">{{ line }}</li>
      </ul>
    </details>

    <el-alert v-if="error" :title="error" type="error" :closable="false" class="mb" />

    <div
      v-if="sampleComposition && sampleComposition.total > 0"
      class="sample-compose"
      :class="{ warn: sampleComposition.has_simulated }"
    >
      <span class="sample-compose-title">样本构成</span>
      <span class="sample-compose-body">{{ sampleComposition.label || '—' }}</span>
      <el-tag
        v-if="sampleComposition.has_simulated"
        size="small"
        type="warning"
        effect="light"
      >
        含模拟样本 · 交付须标注
      </el-tag>
      <span class="sample-compose-meta">全库快照（不受观察期限制）</span>
    </div>

    <div v-if="opsAlerts.length" class="geo-ops-stack">
      <el-alert
        v-for="(a, idx) in opsAlerts.slice(0, 6)"
        :key="idx"
        :type="alertType(a.level)"
        :closable="false"
        show-icon
      >
        <template #title>
          <span class="ops-title" @click="goAlert(a)">{{ a.title }}</span>
        </template>
        <div class="ops-detail">
          {{ a.detail }}
          <el-button v-if="a.href" link type="primary" size="small" @click="goAlert(a)">去处理</el-button>
        </div>
      </el-alert>
      <div v-if="opsSummary" class="ops-summary geo-muted">
        运营告警 {{ opsSummary.total }} 条
        · 错误 {{ opsSummary.error }} · 警告 {{ opsSummary.warning }}
        · 巡检配额 {{ opsSummary.patrol_quota_used }}/{{ opsSummary.patrol_quota_max }}
      </div>
    </div>

    <div class="geo-toolbar">
      <el-select
        v-model="filterBusinessId"
        clearable
        filterable
        placeholder="全部优化业务"
        style="width: 200px"
        @change="onBusinessChange"
      >
        <el-option v-for="b in businesses" :key="b.id" :label="b.name" :value="b.id" />
      </el-select>
      <el-select
        v-model="filterUnitId"
        clearable
        filterable
        placeholder="全部优化单元"
        style="width: 220px"
      >
        <el-option
          v-for="u in filteredUnits"
          :key="u.id"
          :label="`${u.name}${u.keyword ? ' · ' + u.keyword : ''}`"
          :value="u.id"
        />
      </el-select>
      <span class="toolbar-hint">{{ scopeHint }}</span>
      <router-link class="el-button el-button--small is-plain" to="/geo/businesses">管理业务/单元</router-link>
    </div>

    <div v-if="stats" class="geo-kpi-grid">
      <div
        v-for="card in summaryCards"
        :key="card.label"
        class="geo-kpi"
        :class="{ clickable: card.drill }"
        @click="card.drill && router.push(card.drill)"
      >
        <div class="kpi-label">{{ card.label }}</div>
        <div class="kpi-value">{{ card.value }}</div>
        <div class="kpi-hint">{{ card.hint }}</div>
      </div>
    </div>

    <div
      v-if="stats && (stats.prompts_brand_missing > 0 || stats.todo_blocked > 0)"
      class="action-strip"
    >
      <span v-if="stats.prompts_brand_missing > 0">
        <b>{{ stats.prompts_brand_missing }}</b> 个意图词品牌缺失
        <router-link class="strip-link" to="/geo/gaps">缺口工作台</router-link>
        <router-link class="strip-link" to="/geo/prompts?tag=brand_missing">去看意图词</router-link>
        <router-link class="strip-link" to="/geo/tasks">去生成内容</router-link>
      </span>
      <span v-if="stats.todo_blocked > 0">
        · <b>{{ stats.todo_blocked }}</b> 篇待修补
        <router-link class="strip-link" to="/geo/tasks">打开文章列表</router-link>
      </span>
      <router-link class="strip-link" to="/geo/visibility/patrol">跑巡检</router-link>
    </div>

    <section v-if="weekly" class="geo-panel mb">
      <div class="panel-title-row">
        <div class="panel-title">本周洞察 · {{ scopeHint }}</div>
        <router-link class="el-button el-button--small is-plain" to="/geo/topic-heat">话题热度</router-link>
      </div>
      <p class="week-headline">{{ weekly.headline }}</p>
      <ul class="week-bullets">
        <li v-for="(b, i) in (weekly.bullets || [])" :key="i">{{ b }}</li>
      </ul>
      <p v-if="weekly.period" class="geo-muted week-period">
        本周 {{ weekly.period.current?.from }} ~ {{ weekly.period.current?.to }}
        · 对照 {{ weekly.period.previous?.from }} ~ {{ weekly.period.previous?.to }}
      </p>
    </section>

    <section v-if="dailySeries.length" class="geo-panel">
      <div class="panel-title-row">
        <div class="panel-title">按天趋势 · {{ scopeHint }} · {{ obsLabel }}</div>
        <el-button size="small" :loading="exporting" @click="exportCsv">导出本切片 CSV</el-button>
      </div>
      <el-table :data="dailyPager.pagedItems" size="small" stripe>
        <el-table-column prop="metric_date" label="日期" width="120" />
        <el-table-column min-width="110">
          <template #header>
            <el-tooltip :content="M.brand_mention_rate.hint" placement="top">
              <span>{{ M.brand_mention_rate.label }}</span>
            </el-tooltip>
          </template>
          <template #default="{ row }">{{ fmtPct(row.brand_mention_rate) }}</template>
        </el-table-column>
        <el-table-column min-width="110">
          <template #header>
            <el-tooltip :content="M.brand_probe_recognition_rate.hint" placement="top">
              <span>{{ M.brand_probe_recognition_rate.label }}</span>
            </el-tooltip>
          </template>
          <template #default="{ row }">{{ fmtPct(row.brand_probe_recognition_rate) }}</template>
        </el-table-column>
        <el-table-column min-width="110">
          <template #header>
            <el-tooltip :content="M.top1_rate.hint" placement="top">
              <span>{{ M.top1_rate.label }}</span>
            </el-tooltip>
          </template>
          <template #default="{ row }">{{ fmtPct(row.top1_rate) }}</template>
        </el-table-column>
        <el-table-column min-width="110">
          <template #header>
            <el-tooltip :content="M.citation_count.hint" placement="top">
              <span>{{ M.citation_count.label }}</span>
            </el-tooltip>
          </template>
          <template #default="{ row }">{{ row.citation_count ?? '—' }}</template>
        </el-table-column>
        <el-table-column min-width="100">
          <template #header>
            <el-tooltip :content="M.distinct_cited_domains.hint" placement="top">
              <span>{{ M.distinct_cited_domains.label }}</span>
            </el-tooltip>
          </template>
          <template #default="{ row }">{{ row.distinct_cited_domains ?? '—' }}</template>
        </el-table-column>
        <el-table-column min-width="100">
          <template #header>
            <el-tooltip :content="M.snapshots_visibility.hint" placement="top">
              <span>{{ M.snapshots_visibility.label }}</span>
            </el-tooltip>
          </template>
          <template #default="{ row }">{{ row.snapshots_visibility ?? '—' }}</template>
        </el-table-column>
        <el-table-column min-width="100">
          <template #header>
            <el-tooltip :content="M.snapshots_probe.hint" placement="top">
              <span>{{ M.snapshots_probe.label }}</span>
            </el-tooltip>
          </template>
          <template #default="{ row }">{{ row.snapshots_probe ?? '—' }}</template>
        </el-table-column>
      </el-table>
      <div class="geo-pager">
        <el-pagination
          background
          layout="total, sizes, prev, pager, next"
          :total="dailyPager.total"
          :page-size="dailyPager.pageSize"
          :current-page="dailyPager.page"
          :page-sizes="[7, 14, 30, 60]"
          @current-change="dailyPager.onPageChange"
          @size-change="dailyPager.onSizeChange"
        />
      </div>
    </section>
    <section v-else-if="stats" class="geo-panel">
      <div class="panel-title">按天趋势 · {{ scopeHint }} · {{ obsLabel }}</div>
      <div class="geo-empty">
        <div class="empty-title">观察期内暂无按天汇总</div>
        <div>登记快照或跑巡检后会自动写入日指标；打开本页时若缺行会静默补算。</div>
        <div class="empty-actions">
          <router-link class="el-button el-button--small el-button--primary" to="/geo/visibility">
            去登记快照
          </router-link>
          <router-link class="el-button el-button--small is-plain" to="/geo/visibility/patrol">
            全自动巡检
          </router-link>
        </div>
      </div>
    </section>

    <section v-if="stats" class="geo-panel">
      <div class="panel-title">下一步</div>
      <ul class="next-list">
        <li v-if="stats.todo_blocked > 0">
          有 <b>{{ stats.todo_blocked }}</b> 个任务需规则补丁 / 审校后再发布。
        </li>
        <li v-if="stats.todo_publish > 0">
          有 <b>{{ stats.todo_publish }}</b> 个已导出任务可回填发布（含 Webhook）。
        </li>
        <li v-if="stats.prompts_need_recheck > 0">
          有 <b>{{ stats.prompts_need_recheck }}</b> 个意图词建议复测可见度。
        </li>
        <li v-if="!stats.todo_blocked && !stats.todo_publish && !stats.prompts_need_recheck">
          当前无阻塞待办；可继续登记快照或从诊断创建优化文章。
        </li>
      </ul>
    </section>

    <section class="geo-panel">
      <div class="panel-title">工作台入口</div>
      <div class="geo-link-grid">
        <button
          v-for="link in workbenchLinks"
          :key="link.path"
          type="button"
          class="geo-link-card"
          @click="openWorkbench(link)"
        >
          <span class="link-label">{{ link.label }}</span>
          <span class="link-desc">{{ link.desc }}</span>
        </button>
      </div>
    </section>
  </div>
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
