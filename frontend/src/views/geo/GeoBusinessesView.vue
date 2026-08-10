<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  createGeoBusiness,
  createGeoUnit,
  downloadGeoDailyMetricsCsv,
  listGeoBusinesses,
  listGeoDailyMetrics,
  listGeoPrompts,
  listGeoUnits,
  patchGeoBusiness,
  patchGeoUnit,
  rebuildGeoDailyMetrics,
} from '../../api/geoContent'
import { useClientPager } from '../../composables/useClientPager'
import { useGeoTenant } from '../../composables/useGeoTenant'
import {
  DAILY_METRIC_COLUMNS,
  REPORT_GLOSSARY,
  engineDisplay,
  fmtPct,
} from '../../utils/geoReportLabels'

const router = useRouter()
const { tenantId } = useGeoTenant()
const M = DAILY_METRIC_COLUMNS

const loading = ref(false)
const rebuilding = ref(false)
const exporting = ref(false)
const error = ref('')
const businesses = ref([])
const units = ref([])
const prompts = ref([])
const promptsLoading = ref(false)
const selectedBusinessId = ref(null)
const selectedUnitId = ref(null)
const dailyItems = ref([])
const citationNote = ref('')
const metricsOpen = ref(false)
const engineFilter = ref('')
/** tenant | business | unit | all_units_in_biz */
const dailyScope = ref('tenant')

const bizPager = useClientPager(businesses, { pageSize: 12 })
const unitPager = useClientPager(units, { pageSize: 12 })
const promptPager = useClientPager(prompts, { pageSize: 12 })
const dailyPager = useClientPager(dailyItems, { pageSize: 20 })

const bizOpen = ref(false)
const unitOpen = ref(false)
const saving = ref(false)
const bizForm = ref({ name: '', description: '' })
const unitForm = ref({ name: '', keyword: '', description: '' })

const selectedBusiness = computed(() =>
  businesses.value.find((b) => b.id === selectedBusinessId.value) || null,
)

const selectedUnit = computed(() =>
  units.value.find((u) => u.id === selectedUnitId.value) || null,
)

const pathSegments = computed(() => [
  { key: 'biz', label: selectedBusiness.value?.name || '选择业务', active: !!selectedBusiness.value },
  { key: 'unit', label: selectedUnit.value?.name || '选择单元', active: !!selectedUnit.value },
  {
    key: 'prompt',
    label: selectedUnit.value
      ? `意图词 ${prompts.value.length}`
      : '意图词',
    active: !!selectedUnit.value,
  },
])

const dailyPanelTitle = computed(() => {
  if (dailyScope.value === 'tenant') return '按天汇总 · 租户全量'
  if (dailyScope.value === 'business') {
    const n = selectedBusiness.value?.name || `#${selectedBusinessId.value}`
    return `按天汇总 · 优化业务「${n}」`
  }
  if (dailyScope.value === 'unit') {
    const u = units.value.find((x) => x.id === selectedUnitId.value)
    return `按天汇总 · 优化单元「${u?.name || selectedUnitId.value}」`
  }
  if (dailyScope.value === 'all_units_in_biz') {
    const n = selectedBusiness.value?.name || `#${selectedBusinessId.value}`
    return `按天汇总 · 「${n}」下全部单元切片`
  }
  return '按天汇总'
})

async function loadBusinesses() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    businesses.value = []
    return
  }
  loading.value = true
  error.value = ''
  try {
    const data = await listGeoBusinesses(tenantId.value, { status: 'active' })
    businesses.value = data.items || []
    if (!selectedBusinessId.value && businesses.value.length) {
      selectedBusinessId.value = businesses.value[0].id
    }
    if (
      selectedBusinessId.value &&
      !businesses.value.some((b) => b.id === selectedBusinessId.value)
    ) {
      selectedBusinessId.value = businesses.value[0]?.id || null
    }
  } catch (e) {
    error.value = e.message || '加载失败'
    businesses.value = []
  } finally {
    loading.value = false
  }
}

async function loadUnits() {
  if (!tenantId.value || !selectedBusinessId.value) {
    units.value = []
    selectedUnitId.value = null
    prompts.value = []
    return
  }
  try {
    const data = await listGeoUnits(tenantId.value, {
      business_id: selectedBusinessId.value,
      status: 'active',
    })
    units.value = data.items || []
    if (
      selectedUnitId.value &&
      !units.value.some((u) => u.id === selectedUnitId.value)
    ) {
      selectedUnitId.value = null
    }
    if (!selectedUnitId.value && units.value.length) {
      selectedUnitId.value = units.value[0].id
    }
  } catch (e) {
    ElMessage.error(e.message || '加载单元失败')
    units.value = []
  }
}

async function loadPrompts() {
  if (!tenantId.value || !selectedUnitId.value) {
    prompts.value = []
    return
  }
  promptsLoading.value = true
  try {
    const data = await listGeoPrompts(tenantId.value, {
      unit_id: selectedUnitId.value,
      status: 'active',
    })
    prompts.value = data.items || []
  } catch (e) {
    ElMessage.error(e.message || '加载意图词失败')
    prompts.value = []
  } finally {
    promptsLoading.value = false
  }
}

function selectBusiness(row) {
  if (!row) return
  selectedBusinessId.value = row.id
  dailyScope.value = 'business'
}

function selectUnit(row) {
  if (!row) return
  selectedUnitId.value = row.id
  dailyScope.value = 'unit'
}

async function loadDaily() {
  if (!tenantId.value) {
    dailyItems.value = []
    return
  }
  try {
    const params = {}
    if (dailyScope.value === 'tenant') {
      params.scope_level = 'tenant'
    } else if (dailyScope.value === 'business') {
      if (!selectedBusinessId.value) {
        dailyItems.value = []
        return
      }
      params.scope_level = 'business'
      params.business_id = selectedBusinessId.value
    } else if (dailyScope.value === 'unit') {
      if (!selectedUnitId.value) {
        dailyItems.value = []
        return
      }
      params.scope_level = 'unit'
      params.unit_id = selectedUnitId.value
    } else if (dailyScope.value === 'all_units_in_biz') {
      if (!selectedBusinessId.value) {
        dailyItems.value = []
        return
      }
      params.scope_level = 'unit'
      params.business_id = selectedBusinessId.value
    }
    if (engineFilter.value) {
      params.engine = engineFilter.value
    }
    const data = await listGeoDailyMetrics(tenantId.value, params)
    dailyItems.value = data.items || []
    citationNote.value = data.citation_stat_note || ''
  } catch {
    dailyItems.value = []
  }
}

async function submitBusiness() {
  if (!bizForm.value.name.trim()) {
    ElMessage.warning('请填写业务名称')
    return
  }
  saving.value = true
  try {
    const row = await createGeoBusiness({
      tenant_id: tenantId.value,
      name: bizForm.value.name.trim(),
      description: bizForm.value.description || null,
    })
    ElMessage.success('已创建优化业务')
    bizOpen.value = false
    bizForm.value = { name: '', description: '' }
    await loadBusinesses()
    selectedBusinessId.value = row.id
  } catch (e) {
    ElMessage.error(e.message || '创建失败')
  } finally {
    saving.value = false
  }
}

async function submitUnit() {
  if (!selectedBusinessId.value) {
    ElMessage.warning('请先选择优化业务')
    return
  }
  if (!unitForm.value.name.trim()) {
    ElMessage.warning('请填写单元名称')
    return
  }
  saving.value = true
  try {
    await createGeoUnit({
      tenant_id: tenantId.value,
      business_id: selectedBusinessId.value,
      name: unitForm.value.name.trim(),
      keyword: unitForm.value.keyword.trim() || unitForm.value.name.trim(),
      description: unitForm.value.description || null,
    })
    ElMessage.success('已创建优化单元')
    unitOpen.value = false
    unitForm.value = { name: '', keyword: '', description: '' }
    await loadBusinesses()
    await loadUnits()
    await loadPrompts()
  } catch (e) {
    ElMessage.error(e.message || '创建失败')
  } finally {
    saving.value = false
  }
}

async function archiveBusiness(row) {
  try {
    await patchGeoBusiness(tenantId.value, row.id, { status: 'archived' })
    ElMessage.success(`已归档业务 #${row.id}`)
    if (selectedBusinessId.value === row.id) selectedBusinessId.value = null
    await loadBusinesses()
    await loadUnits()
    await loadPrompts()
  } catch (e) {
    ElMessage.error(e.message || '归档失败')
  }
}

async function archiveUnit(row) {
  try {
    await patchGeoUnit(tenantId.value, row.id, { status: 'archived' })
    ElMessage.success(`已归档单元 #${row.id}`)
    if (selectedUnitId.value === row.id) selectedUnitId.value = null
    await loadBusinesses()
    await loadUnits()
    await loadPrompts()
  } catch (e) {
    ElMessage.error(e.message || '归档失败')
  }
}

function goPrompts(unitId) {
  router.push({ path: '/geo/prompts', query: unitId ? { unit_id: unitId } : {} })
}

async function rebuildToday() {
  if (!tenantId.value) return
  rebuilding.value = true
  try {
    const r = await rebuildGeoDailyMetrics(tenantId.value, { includeEmptySlices: false })
    const t = r.tenant || {}
    const sc = r.scope_counts || {}
    ElMessage.success(
      `已重算 ${r.metric_date || '今日'}：租户快照 ${r.snapshot_total ?? 0} · ` +
        `业务切片 ${sc.business ?? 0} · 单元切片 ${sc.unit ?? 0} · ` +
        `AI 引用 ${t.citation_count ?? 0}`,
    )
    await loadDaily()
  } catch (e) {
    ElMessage.error(e.message || '重算失败')
  } finally {
    rebuilding.value = false
  }
}

async function rebuildLast14() {
  if (!tenantId.value) return
  rebuilding.value = true
  try {
    const end = new Date()
    const start = new Date()
    start.setDate(end.getDate() - 13)
    const fmt = (d) => d.toISOString().slice(0, 10)
    const r = await rebuildGeoDailyMetrics(tenantId.value, {
      dateFrom: fmt(start),
      dateTo: fmt(end),
    })
    ElMessage.success(`已重算区间 ${r.period?.from} ~ ${r.period?.to}，共 ${r.day_count || 0} 天`)
    await loadDaily()
  } catch (e) {
    ElMessage.error(e.message || '区间重算失败')
  } finally {
    rebuilding.value = false
  }
}

function dailyParams() {
  const params = {}
  if (dailyScope.value === 'tenant') params.scope_level = 'tenant'
  else if (dailyScope.value === 'business' && selectedBusinessId.value) {
    params.scope_level = 'business'
    params.business_id = selectedBusinessId.value
  } else if (dailyScope.value === 'unit' && selectedUnitId.value) {
    params.scope_level = 'unit'
    params.unit_id = selectedUnitId.value
  } else if (dailyScope.value === 'all_units_in_biz' && selectedBusinessId.value) {
    params.scope_level = 'unit'
    params.business_id = selectedBusinessId.value
  } else params.scope_level = 'tenant'
  if (engineFilter.value) params.engine = engineFilter.value
  return params
}

async function exportCsv() {
  if (!tenantId.value) return
  exporting.value = true
  try {
    const csv = await downloadGeoDailyMetricsCsv(tenantId.value, dailyParams())
    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' })
    const href = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = href
    a.download = `geo-daily-slice-${tenantId.value}.csv`
    a.click()
    URL.revokeObjectURL(href)
    ElMessage.success('已导出 CSV')
  } catch (e) {
    ElMessage.error(e.message || '导出失败')
  } finally {
    exporting.value = false
  }
}

watch(selectedBusinessId, async () => {
  selectedUnitId.value = null
  unitPager.resetPage()
  promptPager.resetPage()
  await loadUnits()
  await loadPrompts()
  if (dailyScope.value !== 'tenant') await loadDaily()
})
watch(selectedUnitId, async () => {
  promptPager.resetPage()
  await loadPrompts()
  if (dailyScope.value === 'unit') await loadDaily()
})
watch(dailyScope, () => {
  dailyPager.resetPage()
  loadDaily()
})
watch(tenantId, async () => {
  bizPager.resetPage()
  unitPager.resetPage()
  promptPager.resetPage()
  dailyPager.resetPage()
  await loadBusinesses()
  await loadUnits()
  await loadPrompts()
  await loadDaily()
})
onMounted(async () => {
  await loadBusinesses()
  await loadUnits()
  await loadPrompts()
  await loadDaily()
})
</script>

<template>
  <div v-loading="loading" class="geo-page">
    <div class="page-header">
      <div>
        <div class="page-title">优化业务</div>
        <div class="page-desc">
          维护「业务 → 单元 → 意图词」结构，并查看按天汇总切片（提及率 / 引用 / 竞品）。
        </div>
      </div>
      <div class="header-actions">
        <el-button type="primary" @click="bizOpen = true">新建优化业务</el-button>
        <el-button :disabled="!selectedBusinessId" @click="unitOpen = true">新建优化单元</el-button>
        <router-link class="el-button is-plain" to="/geo/prompts">优化意图词</router-link>
        <router-link class="el-button is-plain" to="/geo/visibility">AI 可见度</router-link>
        <router-link class="el-button is-plain" to="/geo/tasks">优化文章</router-link>
      </div>
    </div>

    <details class="geo-glossary">
      <summary>统计口径（点击展开）</summary>
      <ul>
        <li v-for="(line, i) in REPORT_GLOSSARY.businesses" :key="i">{{ line }}</li>
        <li v-for="(line, i) in REPORT_GLOSSARY.dailyMetrics" :key="`d-${i}`">{{ line }}</li>
      </ul>
    </details>

    <div class="geo-toolbar">
      <el-button :loading="rebuilding" type="success" @click="rebuildToday">重算今日</el-button>
      <el-button :loading="rebuilding" @click="rebuildLast14">重算近 14 天</el-button>
      <el-button :loading="exporting" @click="exportCsv">导出 CSV</el-button>
      <span class="toolbar-hint">重算写入租户/业务/单元切片；导出当前按天表格范围</span>
    </div>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />
    <el-alert
      v-if="citationNote && metricsOpen"
      type="info"
      :title="citationNote"
      :closable="true"
      show-icon
      class="mb"
    />

    <div class="geo-path">
      <span
        v-for="(seg, idx) in pathSegments"
        :key="seg.key"
        class="path-item"
      >
        <span v-if="idx" class="path-sep">/</span>
        <span class="path-seg" :class="{ 'is-active': seg.active }">{{ seg.label }}</span>
      </span>
    </div>

    <div class="geo-split-3">
      <section class="geo-panel">
        <div class="panel-title-row">
          <div class="panel-title">业务</div>
          <el-button type="primary" link size="small" @click="bizOpen = true">新建</el-button>
        </div>
        <el-table
          :data="bizPager.pagedItems"
          size="small"
          highlight-current-row
          :row-class-name="({ row }) => (row.id === selectedBusinessId ? 'is-selected-row' : '')"
          empty-text="暂无优化业务"
          @row-click="selectBusiness"
        >
          <el-table-column prop="name" label="名称" min-width="120" />
          <el-table-column prop="unit_count" label="单元" width="64" />
          <el-table-column label="" width="56" fixed="right">
            <template #default="{ row }">
              <el-button type="danger" link size="small" @click.stop="archiveBusiness(row)">归档</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div v-if="bizPager.total > 12" class="geo-pager">
          <el-pagination
            background
            layout="prev, pager, next"
            :total="bizPager.total"
            :page-size="bizPager.pageSize"
            :current-page="bizPager.page"
            @current-change="bizPager.onPageChange"
          />
        </div>
      </section>

      <section class="geo-panel">
        <div class="panel-title-row">
          <div class="panel-title">
            单元
            <span v-if="selectedBusiness" class="sub"> · {{ selectedBusiness.name }}</span>
          </div>
          <el-button
            type="primary"
            link
            size="small"
            :disabled="!selectedBusinessId"
            @click="unitOpen = true"
          >新建</el-button>
        </div>
        <el-table
          :data="unitPager.pagedItems"
          size="small"
          highlight-current-row
          :row-class-name="({ row }) => (row.id === selectedUnitId ? 'is-selected-row' : '')"
          empty-text="请选择业务或新建单元"
          @row-click="selectUnit"
        >
          <el-table-column prop="name" label="单元名" min-width="100" />
          <el-table-column prop="keyword" label="关键词" min-width="90" />
          <el-table-column prop="prompt_count" label="意图" width="56" />
          <el-table-column label="" width="56" fixed="right">
            <template #default="{ row }">
              <el-button type="danger" link size="small" @click.stop="archiveUnit(row)">归档</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div v-if="unitPager.total > 12" class="geo-pager">
          <el-pagination
            background
            layout="prev, pager, next"
            :total="unitPager.total"
            :page-size="unitPager.pageSize"
            :current-page="unitPager.page"
            @current-change="unitPager.onPageChange"
          />
        </div>
      </section>

      <section v-loading="promptsLoading" class="geo-panel">
        <div class="panel-title-row">
          <div class="panel-title">
            意图词
            <span v-if="selectedUnit" class="sub"> · {{ selectedUnit.name }}</span>
          </div>
          <el-button
            type="primary"
            link
            size="small"
            :disabled="!selectedUnitId"
            @click="goPrompts(selectedUnitId)"
          >管理</el-button>
        </div>
        <el-table
          :data="promptPager.pagedItems"
          size="small"
          empty-text="请选择单元，或到「优化意图词」挂载"
        >
          <el-table-column prop="question" label="问题" min-width="160">
            <template #default="{ row }">
              <div class="q-line" :title="row.question">{{ row.question || '—' }}</div>
            </template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="72" />
          <el-table-column label="" width="72" fixed="right">
            <template #default="{ row }">
              <el-button type="primary" link size="small" @click="goPrompts(selectedUnitId)">打开</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div v-if="promptPager.total > 12" class="geo-pager">
          <el-pagination
            background
            layout="prev, pager, next"
            :total="promptPager.total"
            :page-size="promptPager.pageSize"
            :current-page="promptPager.page"
            @current-change="promptPager.onPageChange"
          />
        </div>
      </section>
    </div>

    <section class="geo-panel metrics-panel">
      <div class="panel-title-row">
        <div class="panel-title">
          按天汇总
          <span class="sub"> · {{ dailyPanelTitle.replace(/^按天汇总 · /, '') }}</span>
        </div>
        <div class="scope-tabs">
          <el-button size="small" @click="metricsOpen = !metricsOpen">
            {{ metricsOpen ? '收起' : '展开' }}
          </el-button>
          <template v-if="metricsOpen">
            <el-radio-group v-model="dailyScope" size="small">
              <el-radio-button label="tenant">租户</el-radio-button>
              <el-radio-button label="business" :disabled="!selectedBusinessId">当前业务</el-radio-button>
              <el-radio-button label="all_units_in_biz" :disabled="!selectedBusinessId">业务下单元</el-radio-button>
              <el-radio-button label="unit" :disabled="!selectedUnitId">选中单元</el-radio-button>
            </el-radio-group>
            <el-select
              v-model="engineFilter"
              clearable
              placeholder="全部引擎"
              size="small"
              style="width: 140px"
              @change="loadDaily"
            >
              <el-option
                v-for="ek in ['deepseek', 'doubao', 'kimi', 'chatgpt', 'perplexity']"
                :key="ek"
                :label="engineDisplay(ek)"
                :value="ek"
              />
            </el-select>
            <el-button size="small" @click="loadDaily">刷新</el-button>
            <el-button size="small" :loading="exporting" @click="exportCsv">导出 CSV</el-button>
          </template>
        </div>
      </div>
      <template v-if="metricsOpen">
        <p class="geo-panel-desc">
          悬停表头可看口径。无数据时：意图词挂到单元 → 有可见度快照 →「重算今日」。
        </p>
        <el-table
          :data="dailyPager.pagedItems"
          size="small"
          empty-text="暂无按天数据：先挂意图词到单元并登记快照，再「重算今日」"
        >
          <el-table-column prop="metric_date" label="日期" width="110" />
          <el-table-column label="切片" min-width="150">
            <template #default="{ row }">
              {{ row.scope_label || row.scope_key }}
              <span class="muted"> · {{ row.scope_key }}</span>
              <span v-if="row.engine" class="muted"> · {{ engineDisplay(row.engine) }}</span>
            </template>
          </el-table-column>
          <el-table-column width="112">
            <template #header>
              <el-tooltip :content="M.brand_mention_rate.hint" placement="top">
                <span>{{ M.brand_mention_rate.label }}</span>
              </el-tooltip>
            </template>
            <template #default="{ row }">{{ fmtPct(row.brand_mention_rate) }}</template>
          </el-table-column>
          <el-table-column width="112">
            <template #header>
              <el-tooltip :content="M.brand_probe_recognition_rate.hint" placement="top">
                <span>{{ M.brand_probe_recognition_rate.label }}</span>
              </el-tooltip>
            </template>
            <template #default="{ row }">{{ fmtPct(row.brand_probe_recognition_rate) }}</template>
          </el-table-column>
          <el-table-column width="112">
            <template #header>
              <el-tooltip :content="M.top1_rate.hint" placement="top">
                <span>{{ M.top1_rate.label }}</span>
              </el-tooltip>
            </template>
            <template #default="{ row }">{{ fmtPct(row.top1_rate) }}</template>
          </el-table-column>
          <el-table-column width="110">
            <template #header>
              <el-tooltip :content="M.citation_count.hint" placement="top">
                <span>{{ M.citation_count.label }}</span>
              </el-tooltip>
            </template>
            <template #default="{ row }">{{ row.citation_count ?? '—' }}</template>
          </el-table-column>
          <el-table-column width="96">
            <template #header>
              <el-tooltip :content="M.distinct_cited_domains.hint" placement="top">
                <span>{{ M.distinct_cited_domains.label }}</span>
              </el-tooltip>
            </template>
            <template #default="{ row }">{{ row.distinct_cited_domains ?? '—' }}</template>
          </el-table-column>
          <el-table-column min-width="100">
            <template #header>
              <el-tooltip :content="M.top_competitor.hint" placement="top">
                <span>{{ M.top_competitor.label }}</span>
              </el-tooltip>
            </template>
            <template #default="{ row }">{{ row.top_competitor || '—' }}</template>
          </el-table-column>
          <el-table-column width="110">
            <template #header>
              <el-tooltip :content="M.top_competitor_rate.hint" placement="top">
                <span>{{ M.top_competitor_rate.label }}</span>
              </el-tooltip>
            </template>
            <template #default="{ row }">{{ fmtPct(row.top_competitor_rate) }}</template>
          </el-table-column>
          <el-table-column width="96">
            <template #header>
              <el-tooltip :content="M.snapshots_visibility.hint" placement="top">
                <span>{{ M.snapshots_visibility.label }}</span>
              </el-tooltip>
            </template>
            <template #default="{ row }">{{ row.snapshots_visibility ?? '—' }}</template>
          </el-table-column>
          <el-table-column width="96">
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
            :page-sizes="[10, 20, 50, 100]"
            @current-change="dailyPager.onPageChange"
            @size-change="dailyPager.onSizeChange"
          />
        </div>
      </template>
      <div v-else class="metrics-collapsed">点击「展开」查看租户 / 业务 / 单元按天指标</div>
    </section>

    <el-dialog v-model="bizOpen" title="新建优化业务" width="480px">
      <el-form label-width="88px">
        <el-form-item label="名称" required>
          <el-input v-model="bizForm.name" placeholder="如：智能客服产品线" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="bizForm.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="bizOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitBusiness">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="unitOpen" title="新建优化单元（关键词）" width="480px">
      <el-form label-width="88px">
        <el-form-item label="单元名" required>
          <el-input v-model="unitForm.name" placeholder="如：价格对比" />
        </el-form-item>
        <el-form-item label="关键词">
          <el-input v-model="unitForm.keyword" placeholder="默认与单元名相同" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="unitForm.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="unitOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitUnit">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.mb { margin-bottom: 16px; }
.scope-tabs { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.sub { font-weight: 400; color: #94a3b8; font-size: 13px; }
.muted { font-size: 12px; color: #94a3b8; }
.q-line {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.4;
  font-size: 12px;
  color: #334155;
}
.metrics-collapsed {
  font-size: 12px;
  color: #94a3b8;
  padding: 4px 0 2px;
}
:deep(.is-selected-row) > td {
  background: #eff6ff !important;
}
:deep(.el-table__body tr) {
  cursor: pointer;
}
</style>
