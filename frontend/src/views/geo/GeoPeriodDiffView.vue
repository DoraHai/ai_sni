<script setup>
/**
 * 期次对比：before / after 两窗可见性与认知率 Δ
 * 支持 period_id 锁窗（期前 14 天基线 vs 期次窗；closed 用固化指标）
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  fetchVisibilityPeriodDiff,
  listOptimizationPeriods,
} from '../../api/geoContent'
import SampleCredibilityAlert from '../../components/SampleCredibilityAlert.vue'
import { useGeoTenant } from '../../composables/useGeoTenant'
import {
  REPORT_GLOSSARY,
  downloadCsv,
  fmtDeltaPp,
  fmtInt,
  fmtPct,
} from '../../utils/geoReportLabels'

const router = useRouter()
const route = useRoute()
const { tenantId } = useGeoTenant()

const loading = ref(false)
const error = ref('')
const result = ref(null)
const periods = ref([])

const periodId = ref(null)
const beforeRange = ref([])
const afterRange = ref([])

const lockedByPeriod = computed(() => !!periodId.value)

function defaultRanges() {
  const end = new Date()
  const mid = new Date()
  mid.setDate(end.getDate() - 14)
  const start = new Date()
  start.setDate(end.getDate() - 28)
  const iso = (d) => d.toISOString().slice(0, 10)
  beforeRange.value = [iso(start), iso(mid)]
  afterRange.value = [iso(new Date(mid.getTime() + 86400000)), iso(end)]
}

const deltaType = (v) => {
  if (v == null) return 'info'
  if (v > 0.001) return 'success'
  if (v < -0.001) return 'danger'
  return 'info'
}

const rows = computed(() => {
  if (!result.value) return []
  const b = result.value.before || {}
  const a = result.value.after || {}
  const d = result.value.delta || {}
  return [
    {
      key: 'visibility_mention_rate',
      label: '品牌提及率',
      hint: '排除品牌探测题的可见性样本',
      before: b.visibility_mention_rate ?? b.brand_mention_rate,
      after: a.visibility_mention_rate ?? a.brand_mention_rate,
      delta: d.visibility_mention_rate,
    },
    {
      key: 'visibility_top1_rate',
      label: '首位推荐率',
      hint: '本品位置 = 首位推荐 的占比',
      before: b.visibility_top1_rate ?? b.top1_rate,
      after: a.visibility_top1_rate ?? a.top1_rate,
      delta: d.visibility_top1_rate ?? null,
    },
    {
      key: 'probe_recognition_rate',
      label: '品牌点名认知率',
      hint: '仅品牌探测题样本',
      before: b.probe_recognition_rate ?? b.brand_probe_recognition_rate,
      after: a.probe_recognition_rate ?? a.brand_probe_recognition_rate,
      delta: d.probe_recognition_rate,
    },
    {
      key: 'own_domain_cite_rate',
      label: '自有域引用率',
      hint: '含引用的快照中命中官网/文档域的占比',
      before: b.own_domain_cite_rate,
      after: a.own_domain_cite_rate,
      delta: d.own_domain_cite_rate,
    },
  ]
})

const periodMeta = computed(() => result.value?.period || null)
const sampleAfter = computed(() => result.value?.after?.sample_composition || {})
const sampleBefore = computed(() => result.value?.before?.sample_composition || {})
const sampleWarn = computed(
  () => !!(sampleAfter.value.has_simulated || sampleBefore.value.has_simulated),
)
const frozenHint = computed(() => {
  const b = result.value?.before?.frozen
  const a = result.value?.after?.frozen
  if (b && a) return '两端均使用关闭期次固化指标'
  if (b) return '对比前使用固化基线'
  if (a) return '对比后使用固化期末结果'
  return ''
})

async function loadPeriods() {
  if (!tenantId.value) {
    periods.value = []
    return
  }
  try {
    const p = await listOptimizationPeriods(tenantId.value)
    periods.value = p.items || []
  } catch {
    periods.value = []
  }
}

function syncPeriodFromRoute() {
  const q = route.query.period_id
  if (q != null && q !== '') {
    const n = Number(q)
    if (Number.isFinite(n) && n > 0) periodId.value = n
  }
}

function onPeriodChange(id) {
  periodId.value = id || null
  const q = { ...route.query }
  if (id) q.period_id = String(id)
  else delete q.period_id
  router.replace({ path: route.path, query: q })
  load()
}

function clearPeriodLock() {
  onPeriodChange(null)
}

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户'
    return
  }
  loading.value = true
  error.value = ''
  try {
    if (periodId.value) {
      result.value = await fetchVisibilityPeriodDiff(tenantId.value, {
        period_id: periodId.value,
      })
      // mirror locked windows into date pickers for display
      const b = result.value?.before
      const a = result.value?.after
      if (b?.from && b?.to) {
        beforeRange.value = [String(b.from).slice(0, 10), String(b.to).slice(0, 10)]
      }
      if (a?.from && a?.to) {
        afterRange.value = [String(a.from).slice(0, 10), String(a.to).slice(0, 10)]
      }
    } else {
      if (!beforeRange.value?.length || !afterRange.value?.length) {
        ElMessage.warning('请选择对比前 / 对比后日期范围')
        result.value = null
        return
      }
      result.value = await fetchVisibilityPeriodDiff(tenantId.value, {
        before_from: `${beforeRange.value[0]}T00:00:00`,
        before_to: `${beforeRange.value[1]}T23:59:59`,
        after_from: `${afterRange.value[0]}T00:00:00`,
        after_to: `${afterRange.value[1]}T23:59:59`,
      })
    }
  } catch (e) {
    error.value = e.message || '加载失败'
    result.value = null
  } finally {
    loading.value = false
  }
}

function exportCsv() {
  if (!rows.value.length) return
  downloadCsv(
    `geo-period-diff-${tenantId.value}.csv`,
    ['指标', '说明', '对比前', '对比后', '差值(pp)'],
    rows.value.map((r) => [
      r.label,
      r.hint,
      fmtPct(r.before),
      fmtPct(r.after),
      fmtDeltaPp(r.delta),
    ]),
  )
  ElMessage.success('已导出')
}

function goDeliverable() {
  if (periodId.value) {
    router.push({ path: '/geo/deliverables', query: { period_id: String(periodId.value) } })
  } else {
    router.push('/geo/deliverables')
  }
}

watch(tenantId, async () => {
  await loadPeriods()
  load()
})
watch(
  () => route.query.period_id,
  () => {
    syncPeriodFromRoute()
    load()
  },
)
onMounted(async () => {
  defaultRanges()
  syncPeriodFromRoute()
  await loadPeriods()
  load()
})
</script>

<template>
  <div v-loading="loading" class="geo-page">
    <div class="page-header">
      <div>
        <div class="page-title">期次对比</div>
        <div class="page-desc">
          对比两个观测窗口的关键可见性指标变化（百分点）。可选锁定优化期次（期前 14 天基线 vs 期内）；关闭期次优先用固化指标。
        </div>
      </div>
      <div class="header-actions">
        <el-button :disabled="!result" @click="exportCsv">导出 CSV</el-button>
        <el-button @click="router.push('/geo/periods')">优化期次</el-button>
        <el-button @click="router.push('/geo/visibility')">可见度</el-button>
        <el-button @click="goDeliverable">交付摘要</el-button>
        <el-button type="primary" :loading="loading" @click="load">重新计算</el-button>
      </div>
    </div>

    <details class="geo-glossary">
      <summary>统计口径（点击展开）</summary>
      <ul>
        <li v-for="(line, i) in REPORT_GLOSSARY.periodDiff" :key="i">{{ line }}</li>
        <li>传入 period_id 时：before = 期前 14 天基线窗，after = 期次起止；closed 使用 result/baseline 固化值。</li>
      </ul>
    </details>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <section class="geo-panel">
      <div class="panel-title">对比窗口</div>
      <div class="geo-filter-bar period-bar">
        <div>
          <div class="ctrl-label">锁定优化期次</div>
          <el-select
            :model-value="periodId"
            clearable
            filterable
            placeholder="不锁定 · 自由日期"
            style="width: 280px"
            @change="onPeriodChange"
          >
            <el-option
              v-for="p in periods"
              :key="p.id"
              :label="`#${p.id} ${p.name} (${p.status})`"
              :value="p.id"
            />
          </el-select>
        </div>
        <el-button v-if="periodId" size="small" plain @click="clearPeriodLock">
          改为自由日期
        </el-button>
      </div>
      <el-alert
        v-if="periodMeta"
        type="info"
        :closable="false"
        show-icon
        class="mb"
        :title="`期次 #${periodMeta.id} · ${periodMeta.name} · ${periodMeta.status}`"
        :description="frozenHint || '按期次窗实时计算（未关闭或无固化时）'"
      />
      <div class="geo-filter-bar">
        <div>
          <div class="ctrl-label">对比前（Before）{{ lockedByPeriod ? ' · 期前基线' : '' }}</div>
          <el-date-picker
            v-model="beforeRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="开始"
            end-placeholder="结束"
            :clearable="false"
            :disabled="lockedByPeriod"
          />
        </div>
        <div>
          <div class="ctrl-label">对比后（After）{{ lockedByPeriod ? ' · 期次窗' : '' }}</div>
          <el-date-picker
            v-model="afterRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="开始"
            end-placeholder="结束"
            :clearable="false"
            :disabled="lockedByPeriod"
          />
        </div>
      </div>
    </section>

    <SampleCredibilityAlert
      v-if="result"
      :composition="sampleAfter"
      window-label="对比后窗口"
    />
    <SampleCredibilityAlert
      v-if="result"
      :composition="sampleBefore"
      window-label="对比前窗口"
      compact
    />

    <section v-if="result" class="geo-panel">
      <div class="panel-title">指标变化</div>
      <p class="geo-metric-note">
        对比前快照 {{ fmtInt(result.before?.snapshots_total ?? result.before?.snapshots_visibility) }} ·
        对比后快照 {{ fmtInt(result.after?.snapshots_total ?? result.after?.snapshots_visibility) }} ·
        Δ 单位为百分点（pp）
        <template v-if="result.before?.frozen || result.after?.frozen">
          · <el-tag size="small" type="success">固化</el-tag>
        </template>
      </p>
      <el-table :data="rows" size="small" stripe>
        <el-table-column label="指标" min-width="180">
          <template #default="{ row }">
            <div class="metric-name">{{ row.label }}</div>
            <div class="geo-muted">{{ row.hint }}</div>
          </template>
        </el-table-column>
        <el-table-column label="对比前" width="120">
          <template #default="{ row }">{{ row.before == null ? '未测' : fmtPct(row.before) }}</template>
        </el-table-column>
        <el-table-column label="对比后" width="120">
          <template #default="{ row }">{{ row.after == null ? '未测' : fmtPct(row.after) }}</template>
        </el-table-column>
        <el-table-column label="变化 Δ" width="140">
          <template #default="{ row }">
            <el-tag size="small" :type="deltaType(row.delta)">{{ fmtDeltaPp(row.delta) }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <div v-else-if="!loading && !error" class="geo-empty">
      <div class="empty-title">选择期次或窗口后点击「重新计算」</div>
      <div>需要两端窗口都有可见度快照，差值才有意义。</div>
    </div>
  </div>
</template>

<style scoped>
.mb { margin-bottom: 12px; }
.ctrl-label { font-size: 12px; color: #6b7280; margin-bottom: 6px; font-weight: 600; }
.metric-name { font-weight: 600; color: #374151; margin-bottom: 2px; }
.period-bar { margin-bottom: 12px; align-items: flex-end; }
</style>
