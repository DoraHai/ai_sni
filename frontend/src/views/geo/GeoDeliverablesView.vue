<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  downloadGeoDeliverablesMarkdown,
  fetchGeoDeliverablesPack,
  listGeoBusinesses,
  listGeoUnits,
} from '../../api/geoContent'
import { session } from '../../store/session'

const tenantId = computed(() =>
  session.tenantId || (import.meta.env.DEV && import.meta.env.VITE_API_KEY ? 1 : null),
)

const loading = ref(false)
const error = ref('')
const pack = ref(null)
const range = ref([])
const businesses = ref([])
const units = ref([])
const filterBusinessId = ref(null)
const filterUnitId = ref(null)

const fmtPct = (v) => {
  if (v == null) return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return `${(n * 100).toFixed(1)}%`
}

function defaultRange() {
  const end = new Date()
  const start = new Date()
  start.setDate(end.getDate() - 29)
  const iso = (d) => d.toISOString().slice(0, 10)
  return [iso(start), iso(end)]
}

const filteredUnits = computed(() => {
  if (!filterBusinessId.value) return units.value
  return units.value.filter((u) => u.business_id === filterBusinessId.value)
})

const scopeParams = computed(() => {
  const p = {}
  if (filterUnitId.value) p.unit_id = filterUnitId.value
  else if (filterBusinessId.value) p.business_id = filterBusinessId.value
  return p
})

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

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    return
  }
  if (!range.value?.length) range.value = defaultRange()
  loading.value = true
  error.value = ''
  try {
    pack.value = await fetchGeoDeliverablesPack(tenantId.value, {
      from: `${range.value[0]}T00:00:00`,
      to: `${range.value[1]}T23:59:59`,
      ...scopeParams.value,
    })
  } catch (e) {
    error.value = e.message || '加载失败'
    pack.value = null
  } finally {
    loading.value = false
  }
}

async function copyMarkdown() {
  try {
    const md = await downloadGeoDeliverablesMarkdown(tenantId.value, {
      from: `${range.value[0]}T00:00:00`,
      to: `${range.value[1]}T23:59:59`,
      ...scopeParams.value,
    })
    await navigator.clipboard.writeText(md)
    ElMessage.success('Markdown 已复制')
  } catch (e) {
    ElMessage.error(e.message || '复制失败')
  }
}

async function downloadMarkdown() {
  try {
    const md = await downloadGeoDeliverablesMarkdown(tenantId.value, {
      from: `${range.value[0]}T00:00:00`,
      to: `${range.value[1]}T23:59:59`,
      ...scopeParams.value,
    })
    const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' })
    const href = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = href
    a.download = `geo-deliverables-${tenantId.value}.md`
    a.click()
    URL.revokeObjectURL(href)
    ElMessage.success('已下载 Markdown')
  } catch (e) {
    ElMessage.error(e.message || '下载失败')
  }
}

function printReport() {
  window.print()
}

function onBusinessChange() {
  if (
    filterUnitId.value &&
    !filteredUnits.value.some((u) => u.id === filterUnitId.value)
  ) {
    filterUnitId.value = null
  }
  load()
}

watch(tenantId, async () => {
  await loadHierarchy()
  await load()
})
watch(range, load, { deep: true })
watch(filterUnitId, load)
onMounted(async () => {
  range.value = defaultRange()
  await loadHierarchy()
  await load()
})
</script>

<template>
  <div v-loading="loading" class="geo-deliv">
    <div class="page-header">
      <div>
        <div class="page-title">GEO 交付摘要</div>
        <div class="page-desc">
          按周期与业务/单元切片汇总可见度、AI 引用与优化文章；可复制 / 下载 Markdown。
        </div>
      </div>
      <div class="header-actions">
        <el-button :loading="loading" @click="load">刷新</el-button>
        <el-button @click="copyMarkdown">复制 Markdown</el-button>
        <el-button type="primary" @click="downloadMarkdown">下载 Markdown</el-button>
        <el-button plain @click="printReport">打印</el-button>
      </div>
    </div>

    <div class="geo-toolbar">
      <el-date-picker
        v-model="range"
        type="daterange"
        value-format="YYYY-MM-DD"
        start-placeholder="开始"
        end-placeholder="结束"
        :clearable="false"
        style="width: 260px"
      />
      <el-select
        v-model="filterBusinessId"
        clearable
        filterable
        placeholder="全部业务"
        style="width: 180px"
        @change="onBusinessChange"
      >
        <el-option v-for="b in businesses" :key="b.id" :label="b.name" :value="b.id" />
      </el-select>
      <el-select
        v-model="filterUnitId"
        clearable
        filterable
        placeholder="全部单元"
        style="width: 200px"
      >
        <el-option
          v-for="u in filteredUnits"
          :key="u.id"
          :label="`${u.name}${u.keyword ? ' · ' + u.keyword : ''}`"
          :value="u.id"
        />
      </el-select>
      <span class="toolbar-hint">筛选后刷新报告数据</span>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" class="mb" />

    <template v-if="pack">
      <div id="geo-deliv-print" class="report">
      <div class="meta">
        <strong>{{ pack.tenant_name }}</strong>
        <span>· 周期 {{ pack.period?.from?.slice(0, 10) }} ~ {{ pack.period?.to?.slice(0, 10) }}</span>
        <span>· {{ pack.period?.days }} 天</span>
        <span class="scope-tag">· {{ pack.scope?.label || '租户全量' }}</span>
      </div>

      <div class="kpi-row">
        <div class="kpi">
          <div class="kpi-label">品牌提及率</div>
          <div class="kpi-value">{{ fmtPct(pack.summary?.visibility_mention_rate) }}</div>
          <div class="kpi-sub">排除探测题 · 未测记 —</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">首位推荐率</div>
          <div class="kpi-value">{{ fmtPct(pack.summary?.visibility_top1_rate) }}</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">品牌点名认知率</div>
          <div class="kpi-value">{{ fmtPct(pack.summary?.probe_recognition_rate) }}</div>
          <div class="kpi-sub">仅探测题 · 可选分列</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">周期快照</div>
          <div class="kpi-value">{{ pack.summary?.snapshots ?? '—' }}</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">优化文章 / 已发布</div>
          <div class="kpi-value">{{ pack.summary?.tasks ?? 0 }} / {{ pack.summary?.published ?? 0 }}</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">AI 引用次数</div>
          <div class="kpi-value">
            {{ pack.summary?.citation_count ?? pack.summary?.distinct_cited_domains ?? '—' }}
          </div>
          <div class="kpi-sub">
            URL 次数 · 独立域名 {{ pack.summary?.distinct_cited_domains ?? '—' }}
          </div>
        </div>
      </div>

      <section v-if="(pack.daily_series || []).length" class="panel">
        <div class="panel-title">按天汇总 · {{ pack.scope?.label || '租户' }}</div>
        <el-table :data="pack.daily_series || []" size="small" max-height="260">
          <el-table-column prop="metric_date" label="日期" width="110" />
          <el-table-column label="品牌提及率" width="110">
            <template #default="{ row }">{{ fmtPct(row.brand_mention_rate) }}</template>
          </el-table-column>
          <el-table-column label="点名认知率" width="110">
            <template #default="{ row }">{{ fmtPct(row.brand_probe_recognition_rate) }}</template>
          </el-table-column>
          <el-table-column prop="citation_count" label="AI 引用" width="90" />
          <el-table-column prop="distinct_cited_domains" label="独立域名" width="90" />
          <el-table-column prop="snapshots_visibility" label="可见快照" width="90" />
        </el-table>
      </section>

      <section v-if="(pack.business_slices || []).length" class="panel">
        <div class="panel-title">优化业务切片（周期内最近一日）</div>
        <el-table :data="pack.business_slices || []" size="small">
          <el-table-column label="业务" min-width="140">
            <template #default="{ row }">{{ row.business_name || `业务#${row.business_id}` }}</template>
          </el-table-column>
          <el-table-column prop="metric_date" label="日期" width="110" />
          <el-table-column label="品牌提及率" width="110">
            <template #default="{ row }">{{ fmtPct(row.brand_mention_rate) }}</template>
          </el-table-column>
          <el-table-column prop="citation_count" label="AI 引用" width="90" />
          <el-table-column prop="snapshots_visibility" label="可见快照" width="90" />
        </el-table>
      </section>

      <section v-if="(pack.unit_slices || []).length" class="panel">
        <div class="panel-title">优化单元切片（周期内最近一日）</div>
        <el-table :data="pack.unit_slices || []" size="small">
          <el-table-column label="单元" min-width="160">
            <template #default="{ row }">
              <span v-if="row.business_name">{{ row.business_name }} / </span>
              {{ row.unit_name || `单元#${row.unit_id}` }}
            </template>
          </el-table-column>
          <el-table-column prop="metric_date" label="日期" width="110" />
          <el-table-column label="品牌提及率" width="110">
            <template #default="{ row }">{{ fmtPct(row.brand_mention_rate) }}</template>
          </el-table-column>
          <el-table-column prop="citation_count" label="AI 引用" width="90" />
          <el-table-column prop="snapshots_visibility" label="可见快照" width="90" />
        </el-table>
      </section>

      <section class="panel">
        <div class="panel-title">AI 引用次数 · 域名 Top</div>
        <el-table :data="pack.citations_top || []" size="small" empty-text="本期无引用">
          <el-table-column prop="domain" label="域名" min-width="160" />
          <el-table-column prop="cite_count" label="次数" width="80" />
          <el-table-column label="自有" width="70">
            <template #default="{ row }">{{ row.is_own_domain ? '是' : '否' }}</template>
          </el-table-column>
          <el-table-column label="蓝图" min-width="120">
            <template #default="{ row }">
              {{ row.blueprint_channel_name || row.blueprint_channel_key || '—' }}
            </template>
          </el-table-column>
          <el-table-column label="引擎" min-width="140">
            <template #default="{ row }">{{ (row.engines || []).join(', ') || '—' }}</template>
          </el-table-column>
        </el-table>
      </section>

      <section class="panel">
        <div class="panel-title">优化文章</div>
        <el-table :data="pack.tasks || []" size="small" empty-text="本期无任务">
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="status" label="状态" width="110" />
          <el-table-column label="标题" min-width="200">
            <template #default="{ row }">{{ row.title || row.prompt_question || '—' }}</template>
          </el-table-column>
          <el-table-column prop="updated_at" label="更新" width="170" />
        </el-table>
      </section>

      <section class="panel">
        <div class="panel-title">可见度快照抽样</div>
        <el-table :data="pack.snapshots_sample || []" size="small" empty-text="本期无快照">
          <el-table-column prop="captured_at" label="观测时间" width="170" />
          <el-table-column prop="engine" label="引擎" width="100" />
          <el-table-column label="提及" width="70">
            <template #default="{ row }">{{ row.mentions_brand ? '是' : '否' }}</template>
          </el-table-column>
          <el-table-column label="问题" min-width="200">
            <template #default="{ row }">{{ row.prompt_question || `#${row.prompt_id}` }}</template>
          </el-table-column>
        </el-table>
      </section>
      </div>
    </template>
  </div>
</template>

<style scoped>
.mb { margin-bottom: 16px; }
.meta {
  font-size: 13px;
  color: #475569;
  margin-bottom: 16px;
  line-height: 1.6;
  padding: 12px 16px;
  background: #f8fafc;
  border-radius: 10px;
}
.scope-tag { color: #2563eb; font-weight: 600; }
.kpi-sub { font-size: 12px; color: #94a3b8; margin-top: 6px; line-height: 1.4; }
.kpi-row {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(168px, 1fr));
  gap: 14px;
  margin-bottom: 18px;
}
.kpi {
  background: #fff;
  border: 1px solid #e8edf5;
  border-radius: 12px;
  padding: 16px 18px;
  min-height: 96px;
}
.kpi-label { font-size: 12px; color: #64748b; font-weight: 500; }
.kpi-value {
  margin-top: 8px;
  font-size: 22px;
  font-weight: 700;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
}
.panel {
  background: #fff;
  border: 1px solid #e8edf5;
  border-radius: 12px;
  padding: 18px 20px;
  margin-bottom: 18px;
}
.panel-title { font-size: 15px; font-weight: 650; margin-bottom: 14px; color: #1e293b; }
@media print {
  .page-header .header-actions { display: none; }
  .geo-deliv { padding: 0; }
}
</style>
