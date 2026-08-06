<script setup>
/**
 * 期次对比：before / after 两窗可见性与认知率 Δ
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { fetchVisibilityPeriodDiff } from '../../api/geoContent'
import { useGeoTenant } from '../../composables/useGeoTenant'

const router = useRouter()
const { tenantId } = useGeoTenant()

const loading = ref(false)
const error = ref('')
const result = ref(null)

const beforeRange = ref([])
const afterRange = ref([])

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

const fmtPct = (v) => {
  if (v == null) return '未测'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return `${(n * 100).toFixed(1)}%`
}

const fmtDelta = (v) => {
  if (v == null) return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  const sign = n > 0 ? '+' : ''
  return `${sign}${(n * 100).toFixed(1)} pp`
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
      label: '可见性提及率',
      hint: '排除品牌探测题',
      before: b.visibility_mention_rate,
      after: a.visibility_mention_rate,
      delta: d.visibility_mention_rate,
    },
    {
      key: 'visibility_top1_rate',
      label: '首位推荐率',
      hint: 'brand_position=first',
      before: b.visibility_top1_rate,
      after: a.visibility_top1_rate,
      delta: d.visibility_top1_rate ?? null,
    },
    {
      key: 'probe_recognition_rate',
      label: '品牌认知率',
      hint: '仅探测题',
      before: b.probe_recognition_rate,
      after: a.probe_recognition_rate,
      delta: d.probe_recognition_rate,
    },
    {
      key: 'own_domain_cite_rate',
      label: '自有域引用率',
      hint: '有引用的快照中',
      before: b.own_domain_cite_rate,
      after: a.own_domain_cite_rate,
      delta: d.own_domain_cite_rate,
    },
  ]
})

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户'
    return
  }
  if (!beforeRange.value?.length || !afterRange.value?.length) {
    ElMessage.warning('请选择 before / after 日期范围')
    return
  }
  loading.value = true
  error.value = ''
  try {
    result.value = await fetchVisibilityPeriodDiff(tenantId.value, {
      before_from: `${beforeRange.value[0]}T00:00:00`,
      before_to: `${beforeRange.value[1]}T23:59:59`,
      after_from: `${afterRange.value[0]}T00:00:00`,
      after_to: `${afterRange.value[1]}T23:59:59`,
    })
  } catch (e) {
    error.value = e.message || '加载失败'
    result.value = null
  } finally {
    loading.value = false
  }
}

watch(tenantId, load)
onMounted(() => {
  defaultRanges()
  load()
})
</script>

<template>
  <div v-loading="loading" class="period-page">
    <div class="page-header">
      <div>
        <div class="crumbs">
          <router-link to="/geo/overview">GEO 概览</router-link>
          <span> / </span>
          <span>期次对比</span>
        </div>
        <div class="page-title">期次对比</div>
        <div class="page-desc">
          对比两个观测窗口的可见性提及率、首位率、品牌认知与自有域引用。
          未测记为「未测」，不用 0 冒充。
        </div>
      </div>
      <div class="header-actions">
        <el-button @click="router.push('/geo/visibility')">可见度</el-button>
        <el-button @click="router.push('/geo/deliverables')">交付摘要</el-button>
        <el-button type="primary" :loading="loading" @click="load">计算 Δ</el-button>
      </div>
    </div>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <section class="panel controls">
      <div class="ctrl">
        <div class="ctrl-label">Before 窗口</div>
        <el-date-picker
          v-model="beforeRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="开始"
          end-placeholder="结束"
          :clearable="false"
        />
      </div>
      <div class="ctrl">
        <div class="ctrl-label">After 窗口</div>
        <el-date-picker
          v-model="afterRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="开始"
          end-placeholder="结束"
          :clearable="false"
        />
      </div>
    </section>

    <section v-if="result" class="panel">
      <div class="meta">
        Before 快照 {{ result.before?.snapshots_total ?? 0 }} ·
        After 快照 {{ result.after?.snapshots_total ?? 0 }}
      </div>
      <el-table :data="rows" size="small" stripe>
        <el-table-column label="指标" min-width="160">
          <template #default="{ row }">
            <div class="metric-name">{{ row.label }}</div>
            <div class="metric-hint">{{ row.hint }}</div>
          </template>
        </el-table-column>
        <el-table-column label="Before" width="120">
          <template #default="{ row }">{{ fmtPct(row.before) }}</template>
        </el-table-column>
        <el-table-column label="After" width="120">
          <template #default="{ row }">{{ fmtPct(row.after) }}</template>
        </el-table-column>
        <el-table-column label="Δ" width="140">
          <template #default="{ row }">
            <el-tag size="small" :type="deltaType(row.delta)">{{ fmtDelta(row.delta) }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<style scoped>
.period-page { padding: 4px 2px 28px; }
.page-header {
  display: flex; justify-content: space-between; gap: 12px; margin-bottom: 14px; flex-wrap: wrap;
}
.crumbs { font-size: 12px; color: #9ca3af; margin-bottom: 4px; }
.crumbs a { color: #7c3aed; text-decoration: none; }
.page-title { font-size: 20px; font-weight: 700; color: #1e2330; }
.page-desc { font-size: 13px; color: #6b7280; margin-top: 4px; max-width: 560px; line-height: 1.5; }
.header-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.mb { margin-bottom: 12px; }
.panel {
  background: #fff; border: 1px solid #e8e4f5; border-radius: 12px; padding: 14px 16px; margin-bottom: 12px;
}
.controls { display: flex; flex-wrap: wrap; gap: 20px; }
.ctrl-label { font-size: 12px; color: #6b7280; margin-bottom: 6px; font-weight: 600; }
.meta { font-size: 13px; color: #6b7280; margin-bottom: 10px; }
.metric-name { font-weight: 600; color: #374151; }
.metric-hint { font-size: 11px; color: #9ca3af; }
</style>
