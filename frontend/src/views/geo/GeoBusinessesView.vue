<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  createGeoBusiness,
  createGeoUnit,
  downloadGeoDailyMetricsCsv,
  listGeoBusinesses,
  listGeoContentTasks,
  listGeoDailyMetrics,
  listGeoPrompts,
  listGeoUnits,
  patchGeoBusiness,
  patchGeoUnit,
  rebuildGeoDailyMetrics,
} from '../../api/geoContent'
import GeoBusinessProfileForm from '../../components/GeoBusinessProfileForm.vue'
import GeoV2Page from '../../components/GeoV2Page.vue'
import NeedHintAlert from '../../components/NeedHintAlert.vue'
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
const allPrompts = ref([])
const allTasks = ref([])
const promptsLoading = ref(false)
const selectedBusinessId = ref(null)
const selectedUnitId = ref(null)
const showArchived = ref(false)
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
const profileOpen = ref(false)
const unitOpen = ref(false)
const saving = ref(false)
const emptyProfile = () => ({
  product_name: '',
  website: '',
  summary: '',
  honors: '',
  qualifications: '',
  capabilities: '',
  audience: '',
  scenarios: '',
  geo_scope: '',
  industry: '',
  competitors: '',
  recommend_reasons: '',
  banned_claims: '',
  cta: '',
})
const bizForm = ref({ name: '', description: '', profile: emptyProfile() })
const profileForm = ref(emptyProfile())
const profileBiz = ref(null)
const unitForm = ref({ name: '', keyword: '', description: '' })

function profileFromRow(row) {
  const p = row?.profile || {}
  const join = (v) => (Array.isArray(v) ? v.join('，') : v || '')
  return {
    ...p,
    product_name: p.product_name || '',
    website: p.website || p.website_url || p.official_url || '',
    summary: p.summary || '',
    honors: join(p.honors),
    qualifications: join(p.qualifications),
    capabilities: join(p.capabilities),
    audience: p.audience || '',
    scenarios: join(p.scenarios),
    geo_scope: p.geo_scope || '',
    industry: p.industry || '',
    competitors: join(p.competitors),
    recommend_reasons: join(p.recommend_reasons),
    banned_claims: join(p.banned_claims),
    cta: p.cta || '',
  }
}

function profileFilled(row) {
  const p = row?.profile || {}
  return !!(p.product_name || p.summary || p.audience || p.industry)
}

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

async function pickBusinessWithPrompts() {
  const fallback = businesses.value[0]?.id || null
  try {
    const data = await listGeoUnits(tenantId.value, { status: 'active' })
    const countByBiz = new Map()
    for (const u of data.items || []) {
      countByBiz.set(u.business_id, (countByBiz.get(u.business_id) || 0) + Number(u.prompt_count || 0))
    }
    const hit = businesses.value.find((b) => (countByBiz.get(b.id) || 0) > 0)
    return hit?.id || fallback
  } catch {
    return fallback
  }
}

async function loadBusinesses() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    businesses.value = []
    return
  }
  loading.value = true
  error.value = ''
  try {
    const active = await listGeoBusinesses(tenantId.value, { status: 'active' })
    if (showArchived.value) {
      const archived = await listGeoBusinesses(tenantId.value, { status: 'archived' })
      businesses.value = [...(active.items || []), ...(archived.items || [])]
    } else {
      businesses.value = active.items || []
    }
    if (
      selectedBusinessId.value &&
      !businesses.value.some((b) => b.id === selectedBusinessId.value)
    ) {
      selectedBusinessId.value = null
    }
    if (!selectedBusinessId.value && businesses.value.length) {
      selectedBusinessId.value = await pickBusinessWithPrompts()
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
    const unitParams = {
      business_id: selectedBusinessId.value,
      status: 'active',
    }
    const active = await listGeoUnits(tenantId.value, unitParams)
    if (showArchived.value) {
      const archived = await listGeoUnits(tenantId.value, {
        ...unitParams,
        status: 'archived',
      })
      units.value = [...(active.items || []), ...(archived.items || [])]
    } else {
      units.value = active.items || []
    }
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
    let data = await listGeoDailyMetrics(tenantId.value, params)
    let items = data.items || []
    if (!items.length && tenantId.value) {
      try {
        const end = new Date()
        const start = new Date()
        start.setDate(end.getDate() - 13)
        const fmt = (d) => d.toISOString().slice(0, 10)
        await rebuildGeoDailyMetrics(tenantId.value, {
          dateFrom: fmt(start),
          dateTo: fmt(end),
        })
        data = await listGeoDailyMetrics(tenantId.value, params)
        items = data.items || []
      } catch {
        /* keep empty */
      }
    }
    dailyItems.value = items
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
      profile: bizForm.value.profile,
    })
    ElMessage.success('已创建优化业务')
    bizOpen.value = false
    bizForm.value = { name: '', description: '', profile: emptyProfile() }
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
    ElMessage.success(`已归档「${row.name}」。打开「显示已归档」可恢复。`)
    if (selectedBusinessId.value === row.id) selectedBusinessId.value = null
    await loadBusinesses()
    await loadUnits()
    await loadPrompts()
  } catch (e) {
    ElMessage.error(e.message || '归档失败')
  }
}

function openProfile(row) {
  profileBiz.value = row
  profileForm.value = profileFromRow(row)
  profileOpen.value = true
}

async function saveProfile() {
  if (!profileBiz.value) return
  saving.value = true
  try {
    await patchGeoBusiness(tenantId.value, profileBiz.value.id, {
      profile: profileForm.value,
    })
    ElMessage.success('业务画像已保存，Brief / 母稿 / 报告将读取这套上下文')
    profileOpen.value = false
    await loadBusinesses()
  } catch (e) {
    ElMessage.error(e.message || '保存画像失败')
  } finally {
    saving.value = false
  }
}

async function restoreBusiness(row) {
  try {
    await patchGeoBusiness(tenantId.value, row.id, { status: 'active' })
    ElMessage.success(`已恢复业务「${row.name}」`)
    await loadBusinesses()
    await loadUnits()
    await loadPrompts()
  } catch (e) {
    ElMessage.error(e.message || '恢复失败')
  }
}

async function archiveUnit(row) {
  try {
    await patchGeoUnit(tenantId.value, row.id, { status: 'archived' })
    ElMessage.success(`已归档单元「${row.name}」。打开「显示已归档」可恢复。`)
    if (selectedUnitId.value === row.id) selectedUnitId.value = null
    await loadBusinesses()
    await loadUnits()
    await loadPrompts()
  } catch (e) {
    ElMessage.error(e.message || '归档失败')
  }
}

async function restoreUnit(row) {
  try {
    await patchGeoUnit(tenantId.value, row.id, { status: 'active' })
    ElMessage.success(`已恢复单元「${row.name}」`)
    await loadBusinesses()
    await loadUnits()
    await loadPrompts()
  } catch (e) {
    ElMessage.error(e.message || '恢复失败')
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
watch(showArchived, async () => {
  await loadBusinesses()
  await loadUnits()
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
const bizCards = computed(() =>
  (businesses.value || [])
    .filter((b) => b.status !== 'archived')
    .map((b) => {
      const kw = (units.value || []).filter((u) => u.business_id === b.id && u.status !== 'archived')
      const uids = new Set(kw.map((u) => u.id))
      const ps = (allPrompts.value || []).filter((p) => uids.has(p.unit_id))
      const gaps = ps.filter((p) => Array.isArray(p.tags) && p.tags.includes('brand_missing'))
      const arts = (allTasks.value || []).filter(
        (t) => t.business_id === b.id || uids.has(t.unit_id) || ps.some((p) => p.id === t.prompt_id),
      )
      const score = ps.length ? Math.round(((ps.length - gaps.length) / ps.length) * 100) : 0
      return {
        id: b.id,
        name: b.name,
        score,
        keywords: kw.map((u) => u.keyword || u.name).filter(Boolean).join('、') || '未绑定关键词',
        promptCount: ps.length,
        articleCount: arts.length,
        reason: gaps.length
          ? `${gaps.length} 条提问品牌未被推荐；关键词 ${kw.length}、提问 ${ps.length}。`
          : kw.length
            ? `关键词 ${kw.length}、提问 ${ps.length}，覆盖较完整。`
            : '还没有关键词，AI 不知道该推荐哪条业务。',
        action: gaps.length ? '补内容' : kw.length ? '查看进度' : '绑定关键词',
      }
    }),
)

const bizAnswer = computed(() => {
  const weak = [...bizCards.value].sort((a, b) => a.score - b.score)[0]
  return {
    now: [
      '我现在怎么样？',
      weak
        ? `${weak.name} 覆盖 ${weak.score} 分，${weak.reason}`
        : '还没有业务线。先新增一条业务。',
    ],
    why: ['为什么？', 'AI 回答更容易引用有清晰对象、适用场景和客户证据的业务资料。'],
    next: [
      '下一步怎么办？',
      weak?.action === '绑定关键词'
        ? '先给业务绑定关键词，再生成 AI 提问。'
        : '先补缺口提问对应的案例和 GEO 文章。',
    ],
  }
})

onMounted(async () => {
  await loadBusinesses()
  await loadUnits()
  await loadPrompts()
  await loadDaily()
  if (tenantId.value) {
    try {
      const [p, t] = await Promise.all([
        listGeoPrompts(tenantId.value, { status: 'active' }),
        listGeoContentTasks(tenantId.value, { limit: 200 }),
      ])
      allPrompts.value = p.items || []
      allTasks.value = t.items || []
    } catch {
      allPrompts.value = []
      allTasks.value = []
    }
  }
})
</script>

<template>
  <div v-loading="loading">
    <GeoV2Page
      tag="定义优化对象"
      title="先把业务边界说清楚，AI 才知道应该在哪些场景里推荐你。"
      desc="按品牌下的业务线管理产品、解决方案、目标客户和核心卖点，确保后续关键词、AI 提问和内容都围绕明确业务展开。"
      :steps="['新增业务', '补充卖点', '绑定关键词', '查看优化进度']"
      :answer="bizAnswer"
    >
      <template #actions>
        <el-button type="primary" @click="bizOpen = true">新增业务</el-button>
        <el-button :disabled="!selectedBusinessId" @click="unitOpen = true">绑定关键词</el-button>
        <el-button
          :disabled="!selectedBusinessId"
          @click="router.push(`/geo/businesses/${selectedBusinessId}`)"
        >
          查看优化进度
        </el-button>
      </template>

      <section class="gv2-panel">
        <div class="gv2-panel-head">
          <div>
            <span class="gv2-kicker">业务线健康度</span>
            <h2>当前业务</h2>
            <p class="sub">分数来自该业务下「已被推荐的提问 / 全部提问」。点卡片选中后可补卖点或绑关键词。</p>
          </div>
        </div>
        <div class="metric-list">
          <div
            v-for="c in bizCards"
            :key="c.id"
            class="gv2-card gv2-metric"
            role="button"
            @click="selectBusiness(businesses.find((b) => b.id === c.id))"
          >
            <div>
              <b>{{ c.name }}</b>
              <p>{{ c.reason }}</p>
            </div>
            <div>
              <strong>{{ c.score }}</strong>
              <em>{{ c.action }}</em>
            </div>
          </div>
        </div>
      </section>
      <section class="gv2-panel">
        <div class="gv2-panel-head">
          <div>
            <span class="gv2-kicker">业务与关键词关系</span>
            <h2>绑定情况</h2>
          </div>
        </div>
        <el-table :data="bizCards" stripe empty-text="还没有业务">
          <el-table-column prop="name" label="业务" min-width="140" />
          <el-table-column prop="keywords" label="关键词" min-width="200" />
          <el-table-column label="AI提问" width="110">
            <template #default="{ row }">{{ row.promptCount }} 条</template>
          </el-table-column>
          <el-table-column label="内容" width="110">
            <template #default="{ row }">{{ row.articleCount }} 篇</template>
          </el-table-column>
          <el-table-column label="操作" width="120">
            <template #default="{ row }">
              <el-button link type="primary" @click="router.push(`/geo/businesses/${row.id}`)">查看进度</el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>

    <details class="geo-glossary">
      <summary>统计口径（点击展开）</summary>
      <ul>
        <li v-for="(line, i) in REPORT_GLOSSARY.businesses" :key="i">{{ line }}</li>
        <li v-for="(line, i) in REPORT_GLOSSARY.dailyMetrics" :key="`d-${i}`">{{ line }}</li>
      </ul>
    </details>

    <div class="geo-toolbar">
      <el-button :loading="exporting" @click="exportCsv">导出 CSV</el-button>
      <el-checkbox v-model="showArchived">显示已归档</el-checkbox>
      <span class="toolbar-hint">归档不是删除。勾选「显示已归档」后可点恢复。</span>
    </div>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />
    <NeedHintAlert />
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
          <el-table-column prop="name" label="名称" min-width="120">
            <template #default="{ row }">
              {{ row.name }}
              <el-tag v-if="row.status === 'archived'" size="small" type="info" class="ml-tag">已归档</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="unit_count" label="单元" width="64" />
          <el-table-column label="画像" width="64">
            <template #default="{ row }">
              <el-tag v-if="profileFilled(row)" size="small" type="success">已填</el-tag>
              <el-tag v-else size="small" type="warning">缺</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="" width="108" fixed="right">
            <template #default="{ row }">
              <el-button type="primary" link size="small" @click.stop="openProfile(row)">画像</el-button>
              <el-button
                v-if="row.status === 'archived'"
                type="primary"
                link
                size="small"
                @click.stop="restoreBusiness(row)"
              >恢复</el-button>
              <el-button
                v-else
                type="danger"
                link
                size="small"
                @click.stop="archiveBusiness(row)"
              >归档</el-button>
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
          <el-table-column prop="name" label="单元名" min-width="100">
            <template #default="{ row }">
              {{ row.name }}
              <el-tag v-if="row.status === 'archived'" size="small" type="info" class="ml-tag">已归档</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="keyword" label="关键词" min-width="90" />
          <el-table-column prop="prompt_count" label="意图" width="56" />
          <el-table-column label="" width="72" fixed="right">
            <template #default="{ row }">
              <el-button
                v-if="row.status === 'archived'"
                type="primary"
                link
                size="small"
                @click.stop="restoreUnit(row)"
              >恢复</el-button>
              <el-button
                v-else
                type="danger"
                link
                size="small"
                @click.stop="archiveUnit(row)"
              >归档</el-button>
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
          empty-text="当前单元没有意图词。点左侧其他业务看看，或到「优化意图词」挂载"
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
          悬停表头可看口径。无数据时：意图词挂到单元 → 登记快照/巡检 → 刷新本页。
        </p>
        <el-table
          :data="dailyPager.pagedItems"
          size="small"
          empty-text="暂无按天数据：先挂意图词到单元并登记快照/巡检，再刷新"
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

    <el-dialog v-model="bizOpen" title="新建优化业务" width="640px">
      <el-form label-width="88px">
        <el-form-item label="名称" required>
          <el-input v-model="bizForm.name" placeholder="如：智能客服产品线" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="bizForm.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <p class="toolbar-hint">业务画像会作为 Brief、母稿和报告的唯一品牌上下文，不要只填租户总品牌。</p>
      <GeoBusinessProfileForm v-model="bizForm.profile" />
      <template #footer>
        <el-button @click="bizOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitBusiness">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="profileOpen" :title="`业务画像 · ${profileBiz?.name || ''}`" width="640px">
      <p class="toolbar-hint">每条业务线独立：产品名、禁止表述、竞品和 CTA 都会进入内容生成。</p>
      <GeoBusinessProfileForm v-model="profileForm" />
      <template #footer>
        <el-button @click="profileOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveProfile">保存画像</el-button>
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
    </GeoV2Page>
  </div>
</template>

<style scoped>
.ml-tag { margin-left: 6px; }
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
