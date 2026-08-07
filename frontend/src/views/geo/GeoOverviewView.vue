<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  fetchGeoContentStats,
  geoContentHealth,
  listGeoBusinesses,
  listGeoDailyMetrics,
  listGeoUnits,
  rebuildGeoDailyMetrics,
  staticGeoEditorUrl,
} from '../../api/geoContent'
import { session } from '../../store/session'

const tenantId = computed(() =>
  session.tenantId || (import.meta.env.DEV && import.meta.env.VITE_API_KEY ? 1 : null),
)

const loading = ref(false)
const rebuilding = ref(false)
const error = ref('')
const stats = ref(null)
const healthOk = ref(null)

const businesses = ref([])
const units = ref([])
const filterBusinessId = ref(null)
const filterUnitId = ref(null)
/** 近 14 天切片序列（选中 scope） */
const dailySeries = ref([])
const dailyLatest = ref(null)
const citationNote = ref('')

const fmtInt = (v) => (v == null ? '—' : Number(v).toLocaleString('zh-CN'))
const fmtPct = (v) => {
  if (v == null) return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return `${(n * 100).toFixed(1)}%`
}

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

const summaryCards = computed(() => {
  const s = stats.value
  if (!s) return []
  const d = dailyLatest.value
  // 有切片筛选时优先用 daily-metrics；租户级优先 daily 覆盖率/引用，任务数仍走 content-stats
  const mention = d?.brand_mention_rate ?? s.visibility_mention_rate
  const probe = d?.brand_probe_recognition_rate ?? s.probe_recognition_rate
  const top1 = d?.top1_rate ?? s.visibility_top1_rate
  const citeDomains = d?.distinct_cited_domains ?? s.distinct_cited_domains
  const citeCount = d?.citation_count
  const snapVis = d?.snapshots_visibility ?? s.snapshots_visibility
  const snapProbe = d?.snapshots_probe ?? s.snapshots_probe

  return [
    { label: '优化意图词', value: fmtInt(s.prompts), hint: `探测题 ${fmtInt(s.prompts_probe)} · ${scopeHint.value}` },
    { label: '优化文章', value: fmtInt(s.tasks), hint: `待修 ${fmtInt(s.todo_blocked)} · 待发 ${fmtInt(s.todo_publish)}` },
    { label: '已发布', value: fmtInt(s.published), hint: `就绪及以上 ${fmtInt(s.ready_or_beyond)}` },
    {
      label: '品牌提及率',
      value: fmtPct(mention),
      hint: d
        ? `切片 ${d.metric_date || ''} · 排除探测 · 快照 ${fmtInt(snapVis)} · top1 ${fmtPct(top1)}`
        : `排除探测 · 快照 ${fmtInt(snapVis)} · top1 ${fmtPct(top1)}`,
    },
    {
      label: '品牌点名认知率',
      value: fmtPct(probe),
      hint: `仅探测题 · 样本 ${fmtInt(snapProbe)}`,
    },
    {
      label: 'AI 引用次数',
      value: citeCount != null ? fmtInt(citeCount) : fmtInt(citeDomains),
      hint:
        citeCount != null
          ? `口径：URL 出现次数 · 独立域名 ${fmtInt(citeDomains)}`
          : `口径：独立被引域名 · 含引用快照 ${fmtInt(s.snapshots_with_citations)}`,
    },
    {
      label: '待复测意图词',
      value: fmtInt(s.prompts_need_recheck),
      hint: `品牌缺失标签 ${fmtInt(s.prompts_brand_missing)}`,
    },
  ]
})

const workbenchLinks = [
  { label: '优化文章', path: '/geo/tasks', desc: '主入口 · 列表 + 混合编辑器', vue: true, primary: true },
  { label: 'AI 可见度', path: '/geo/visibility', desc: '登记 / 多引擎探测', vue: true, primary: true },
  { label: '全自动巡检', path: '/geo/visibility/patrol', desc: '多词×多引擎自动探测落库', vue: true, primary: true },
  { label: '期次对比', path: '/geo/period-diff', desc: 'before/after 品牌提及 Δ', vue: true, primary: true },
  { label: '交付摘要', path: '/geo/deliverables', desc: '周期报告 Markdown / 打印', vue: true, primary: true },
  { label: 'AI 引用次数', path: '/geo/citations', desc: '引用聚合 · 需看统计口径', vue: true },
  { label: '竞品分析', path: '/geo/competitors', desc: '竞品出现与份额', vue: true },
  { label: '评价分析', path: '/geo/evaluation', desc: '情感与位置分布', vue: true },
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

async function loadDailySlice() {
  if (!tenantId.value) {
    dailySeries.value = []
    dailyLatest.value = null
    return
  }
  try {
    const params = {}
    if (filterUnitId.value) {
      params.scope_level = 'unit'
      params.unit_id = filterUnitId.value
    } else if (filterBusinessId.value) {
      params.scope_level = 'business'
      params.business_id = filterBusinessId.value
    } else {
      params.scope_level = 'tenant'
    }
    const data = await listGeoDailyMetrics(tenantId.value, params)
    const items = data.items || []
    dailySeries.value = items
    dailyLatest.value = items.length ? items[items.length - 1] : null
    citationNote.value = data.citation_stat_note || ''
  } catch {
    dailySeries.value = []
    dailyLatest.value = null
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

function refresh() {
  load().then(() => {
    if (!error.value) ElMessage.success('已刷新')
  })
}

async function rebuildToday() {
  if (!tenantId.value) return
  rebuilding.value = true
  try {
    const r = await rebuildGeoDailyMetrics(tenantId.value)
    const t = r.tenant || {}
    ElMessage.success(
      `已重算 ${r.metric_date || '今日'} · 快照 ${r.snapshot_total ?? 0} · AI 引用 ${t.citation_count ?? 0}`,
    )
    await loadDailySlice()
  } catch (e) {
    ElMessage.error(e.message || '重算失败')
  } finally {
    rebuilding.value = false
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
}

watch(tenantId, load)
watch(filterUnitId, loadDailySlice)
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="geo-overview">
    <div class="page-header">
      <div>
        <div class="page-title">GEO 概览</div>
        <div class="page-desc">
          内容与可见度状态一览；可按优化业务 / 单元看品牌提及与 AI 引用切片。
          <span v-if="healthOk === true" class="health ok">API 正常</span>
          <span v-else-if="healthOk === false" class="health bad">API 异常</span>
        </div>
      </div>
      <div class="header-actions">
        <el-button :loading="loading" @click="refresh">刷新</el-button>
        <el-button :loading="rebuilding" @click="rebuildToday">重算今日指标</el-button>
        <el-button type="primary" @click="openWorkbench(workbenchLinks[0])">打开工作台</el-button>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" class="mb" />

    <div class="filters mb">
      <el-select
        v-model="filterBusinessId"
        clearable
        filterable
        placeholder="全部优化业务"
        style="width: 200px"
        @change="onBusinessChange"
      >
        <el-option
          v-for="b in businesses"
          :key="b.id"
          :label="b.name"
          :value="b.id"
        />
      </el-select>
      <el-select
        v-model="filterUnitId"
        clearable
        filterable
        placeholder="全部优化单元"
        style="width: 220px"
        :disabled="!filteredUnits.length && !filterBusinessId"
      >
        <el-option
          v-for="u in filteredUnits"
          :key="u.id"
          :label="`${u.name}${u.keyword ? ' · ' + u.keyword : ''}`"
          :value="u.id"
        />
      </el-select>
      <span class="filter-hint">{{ scopeHint }}</span>
      <router-link class="el-button el-button--small" to="/geo/businesses">管理业务/单元</router-link>
    </div>

    <el-alert
      v-if="citationNote"
      type="info"
      :title="citationNote"
      :closable="true"
      show-icon
      class="mb"
    />

    <div v-if="stats" class="kpi-grid">
      <div v-for="card in summaryCards" :key="card.label" class="kpi">
        <div class="kpi-label">{{ card.label }}</div>
        <div class="kpi-value">{{ card.value }}</div>
        <div class="kpi-hint">{{ card.hint }}</div>
      </div>
    </div>

    <section v-if="dailySeries.length" class="panel">
      <div class="panel-title">近 14 天 · {{ scopeHint }}</div>
      <el-table :data="dailySeries" size="small" max-height="280">
        <el-table-column prop="metric_date" label="日期" width="110" />
        <el-table-column label="品牌提及率" width="110">
          <template #default="{ row }">{{ fmtPct(row.brand_mention_rate) }}</template>
        </el-table-column>
        <el-table-column label="点名认知率" width="110">
          <template #default="{ row }">{{ fmtPct(row.brand_probe_recognition_rate) }}</template>
        </el-table-column>
        <el-table-column prop="citation_count" label="AI 引用次数" width="110" />
        <el-table-column prop="distinct_cited_domains" label="独立域名" width="90" />
        <el-table-column prop="snapshots_visibility" label="可见快照" width="90" />
        <el-table-column prop="snapshots_probe" label="探测快照" width="90" />
      </el-table>
    </section>
    <section v-else-if="stats" class="panel">
      <div class="panel-title">近 14 天 · {{ scopeHint }}</div>
      <div class="empty-daily">
        暂无按天汇总。登记快照 / 巡检落库后会自动重算；也可点「重算今日指标」。
      </div>
    </section>

    <section v-if="stats" class="panel">
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

    <section class="panel">
      <div class="panel-title">工作台入口</div>
      <div class="link-grid">
        <button
          v-for="link in workbenchLinks"
          :key="link.path"
          type="button"
          class="link-item"
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
.geo-overview {
  padding: 4px 2px 24px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
}
.page-title {
  font-size: 20px;
  font-weight: 650;
  color: #1f2937;
}
.page-desc {
  margin-top: 4px;
  font-size: 13px;
  color: #6b7280;
}
.header-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
  flex-wrap: wrap;
}
.health {
  margin-left: 8px;
  font-size: 12px;
  padding: 1px 8px;
  border-radius: 4px;
}
.health.ok {
  background: #ecfdf5;
  color: #047857;
}
.health.bad {
  background: #fef2f2;
  color: #b91c1c;
}
.mb {
  margin-bottom: 14px;
}
.filters {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}
.filter-hint {
  font-size: 13px;
  color: #6b7280;
}
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}
@media (max-width: 960px) {
  .kpi-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
.kpi {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 14px 16px;
}
.kpi-label {
  font-size: 12px;
  color: #6b7280;
}
.kpi-value {
  margin-top: 6px;
  font-size: 24px;
  font-weight: 650;
  color: #111827;
  font-variant-numeric: tabular-nums;
}
.kpi-hint {
  margin-top: 4px;
  font-size: 12px;
  color: #9ca3af;
}
.panel {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 16px 18px;
  margin-bottom: 14px;
}
.panel-title {
  font-size: 14px;
  font-weight: 650;
  color: #1f2937;
  margin-bottom: 10px;
}
.empty-daily {
  font-size: 13px;
  color: #6b7280;
  padding: 8px 0;
}
.next-list {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  color: #374151;
  line-height: 1.7;
}
.link-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}
@media (max-width: 960px) {
  .link-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
.link-item {
  text-align: left;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fafafa;
  padding: 12px 14px;
  cursor: pointer;
}
.link-item:hover {
  border-color: #93c5fd;
  background: #f0f9ff;
}
.link-label {
  display: block;
  font-weight: 600;
  color: #111827;
  font-size: 13px;
}
.link-desc {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  color: #6b7280;
}
</style>
