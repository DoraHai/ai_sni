<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  createGeoBusiness,
  createGeoUnit,
  listGeoBusinesses,
  listGeoDailyMetrics,
  listGeoUnits,
  patchGeoBusiness,
  patchGeoUnit,
  rebuildGeoDailyMetrics,
} from '../../api/geoContent'
import { useGeoTenant } from '../../composables/useGeoTenant'

const router = useRouter()
const { tenantId } = useGeoTenant()

const loading = ref(false)
const rebuilding = ref(false)
const error = ref('')
const businesses = ref([])
const units = ref([])
const selectedBusinessId = ref(null)
const selectedUnitId = ref(null)
const dailyItems = ref([])
const citationNote = ref('')
/** tenant | business | unit | all_units_in_biz */
const dailyScope = ref('tenant')

const bizOpen = ref(false)
const unitOpen = ref(false)
const saving = ref(false)
const bizForm = ref({ name: '', description: '' })
const unitForm = ref({ name: '', keyword: '', description: '' })

const selectedBusiness = computed(() =>
  businesses.value.find((b) => b.id === selectedBusinessId.value) || null,
)

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
    return
  }
  try {
    const data = await listGeoUnits(tenantId.value, {
      business_id: selectedBusinessId.value,
      status: 'active',
    })
    units.value = data.items || []
  } catch (e) {
    ElMessage.error(e.message || '加载单元失败')
    units.value = []
  }
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
  } catch (e) {
    ElMessage.error(e.message || '归档失败')
  }
}

async function archiveUnit(row) {
  try {
    await patchGeoUnit(tenantId.value, row.id, { status: 'archived' })
    ElMessage.success(`已归档单元 #${row.id}`)
    await loadBusinesses()
    await loadUnits()
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

function selectUnitForMetrics(row) {
  selectedUnitId.value = row.id
  dailyScope.value = 'unit'
}

const fmtPct = (v) => {
  if (v == null) return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return `${(n * 100).toFixed(1)}%`
}

watch(selectedBusinessId, async () => {
  selectedUnitId.value = null
  await loadUnits()
  if (dailyScope.value !== 'tenant') await loadDaily()
})
watch([dailyScope, selectedUnitId], loadDaily)
watch(tenantId, async () => {
  await loadBusinesses()
  await loadUnits()
  await loadDaily()
})
onMounted(async () => {
  await loadBusinesses()
  await loadUnits()
  await loadDaily()
})
</script>

<template>
  <div v-loading="loading" class="geo-page">
    <div class="page-header">
      <div>
        <div class="page-title">优化业务</div>
        <div class="page-desc">
          三级结构：优化业务 → 优化单元（关键词）→ 优化意图词 → 优化文章
        </div>
      </div>
      <div class="header-actions">
        <el-button type="primary" @click="bizOpen = true">新建优化业务</el-button>
        <el-button :disabled="!selectedBusinessId" @click="unitOpen = true">新建优化单元</el-button>
        <el-button :loading="rebuilding" type="success" @click="rebuildToday">重算今日（含业务/单元）</el-button>
        <el-button :loading="rebuilding" @click="rebuildLast14">重算近 14 天</el-button>
        <router-link class="el-button" to="/geo/prompts">优化意图词</router-link>
        <router-link class="el-button" to="/geo/tasks">优化文章</router-link>
      </div>
    </div>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />
    <el-alert
      v-if="citationNote"
      type="info"
      :title="citationNote"
      :closable="false"
      show-icon
      class="mb"
    />

    <div class="layout">
      <section class="panel">
        <div class="panel-title">优化业务</div>
        <el-table
          :data="businesses"
          stripe
          highlight-current-row
          empty-text="暂无优化业务"
          @current-change="(row) => { if (row) selectedBusinessId = row.id }"
        >
          <el-table-column prop="id" label="ID" width="64" />
          <el-table-column prop="name" label="名称" min-width="140" />
          <el-table-column prop="unit_count" label="单元数" width="80" />
          <el-table-column label="操作" width="160" fixed="right">
            <template #default="{ row }">
              <el-button type="primary" link @click="selectedBusinessId = row.id">查看单元</el-button>
              <el-button type="danger" link @click="archiveBusiness(row)">归档</el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <section class="panel">
        <div class="panel-title">
          优化单元（关键词）
          <span v-if="selectedBusiness" class="sub"> · {{ selectedBusiness.name }}</span>
        </div>
        <el-table :data="units" stripe empty-text="请选择业务或新建单元">
          <el-table-column prop="id" label="ID" width="64" />
          <el-table-column prop="name" label="单元名" min-width="120" />
          <el-table-column prop="keyword" label="关键词" min-width="120" />
          <el-table-column prop="prompt_count" label="意图词" width="80" />
          <el-table-column label="操作" width="220" fixed="right">
            <template #default="{ row }">
              <el-button type="primary" link @click="goPrompts(row.id)">意图词</el-button>
              <el-button type="success" link @click="selectUnitForMetrics(row)">看汇总</el-button>
              <el-button type="danger" link @click="archiveUnit(row)">归档</el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>
    </div>

    <section class="panel">
      <div class="panel-title-row">
        <div class="panel-title">{{ dailyPanelTitle }}</div>
        <div class="scope-tabs">
          <el-radio-group v-model="dailyScope" size="small">
            <el-radio-button label="tenant">租户</el-radio-button>
            <el-radio-button label="business" :disabled="!selectedBusinessId">当前业务</el-radio-button>
            <el-radio-button label="all_units_in_biz" :disabled="!selectedBusinessId">业务下单元</el-radio-button>
            <el-radio-button label="unit" :disabled="!selectedUnitId">选中单元</el-radio-button>
          </el-radio-group>
          <el-button size="small" @click="loadDaily">刷新</el-button>
        </div>
      </div>
      <el-table :data="dailyItems" size="small" empty-text="暂无按天数据：先挂意图词到单元，再「重算今日」">
        <el-table-column prop="metric_date" label="日期" width="110" />
        <el-table-column label="切片" min-width="140">
          <template #default="{ row }">
            {{ row.scope_label || row.scope_key }}
            <span class="muted"> · {{ row.scope_key }}</span>
          </template>
        </el-table-column>
        <el-table-column label="品牌提及率" width="110">
          <template #default="{ row }">{{ fmtPct(row.brand_mention_rate) }}</template>
        </el-table-column>
        <el-table-column label="品牌点名认知率" width="130">
          <template #default="{ row }">{{ fmtPct(row.brand_probe_recognition_rate) }}</template>
        </el-table-column>
        <el-table-column prop="citation_count" label="AI 引用次数" width="110" />
        <el-table-column prop="distinct_cited_domains" label="独立域名" width="90" />
        <el-table-column prop="snapshots_visibility" label="可见快照" width="90" />
        <el-table-column prop="snapshots_probe" label="探测快照" width="90" />
      </el-table>
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
.geo-page { padding: 4px 2px 24px; }
.page-header {
  display: flex; justify-content: space-between; gap: 12px; margin-bottom: 14px; flex-wrap: wrap;
}
.page-title { font-size: 20px; font-weight: 700; }
.page-desc { font-size: 13px; color: #6b7280; margin-top: 4px; }
.header-actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.mb { margin-bottom: 12px; }
.layout {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-bottom: 14px;
}
@media (max-width: 960px) {
  .layout { grid-template-columns: 1fr; }
}
.panel {
  background: #fff;
  border: 1px solid #e8ebf2;
  border-radius: 10px;
  padding: 12px 14px 16px;
  margin-bottom: 14px;
}
.panel-title { font-weight: 700; margin-bottom: 10px; color: #1e2330; }
.panel-title-row {
  display: flex; justify-content: space-between; align-items: center;
  gap: 12px; flex-wrap: wrap; margin-bottom: 10px;
}
.panel-title-row .panel-title { margin-bottom: 0; }
.scope-tabs { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.sub { font-weight: 400; color: #8b93a7; font-size: 13px; }
.muted { font-size: 12px; color: #8b93a7; }
</style>
