<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  downloadGeoDeliverablesMarkdown,
  fetchGeoDeliverablesPack,
} from '../../api/geoContent'
import { session } from '../../store/session'

const tenantId = computed(() =>
  session.tenantId || (import.meta.env.DEV && import.meta.env.VITE_API_KEY ? 1 : null),
)

const loading = ref(false)
const error = ref('')
const pack = ref(null)
const range = ref([])

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

watch(tenantId, load)
watch(range, load, { deep: true })
onMounted(() => {
  range.value = defaultRange()
  load()
})
</script>

<template>
  <div v-loading="loading" class="geo-deliv">
    <div class="page-header">
      <div>
        <div class="page-title">GEO 交付摘要</div>
        <div class="page-desc">
          按周期汇总可见度、引用与内容任务，供客户沟通；可复制 / 下载 Markdown。
        </div>
      </div>
      <div class="header-actions">
        <el-date-picker
          v-model="range"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="开始"
          end-placeholder="结束"
          :clearable="false"
          style="width: 260px"
        />
        <el-button :loading="loading" @click="load">刷新</el-button>
        <el-button @click="copyMarkdown">复制 Markdown</el-button>
        <el-button type="primary" @click="downloadMarkdown">下载 Markdown</el-button>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" class="mb" />

    <template v-if="pack">
      <div class="meta">
        <strong>{{ pack.tenant_name }}</strong>
        <span>· 周期 {{ pack.period?.from?.slice(0, 10) }} ~ {{ pack.period?.to?.slice(0, 10) }}</span>
        <span>· {{ pack.period?.days }} 天</span>
      </div>

      <div class="kpi-row">
        <div class="kpi">
          <div class="kpi-label">可见性提及率</div>
          <div class="kpi-value">{{ fmtPct(pack.summary?.visibility_mention_rate) }}</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">周期快照</div>
          <div class="kpi-value">{{ pack.summary?.snapshots ?? '—' }}</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">内容任务 / 已发布</div>
          <div class="kpi-value">{{ pack.summary?.tasks ?? 0 }} / {{ pack.summary?.published ?? 0 }}</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">引用域名</div>
          <div class="kpi-value">{{ pack.summary?.distinct_cited_domains ?? '—' }}</div>
        </div>
      </div>

      <section class="panel">
        <div class="panel-title">引用域名 Top</div>
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
        <div class="panel-title">内容任务</div>
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
    </template>
  </div>
</template>

<style scoped>
.geo-deliv { padding: 4px 2px 24px; }
.page-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.page-title { font-size: 20px; font-weight: 650; color: #1f2937; }
.page-desc { margin-top: 4px; font-size: 13px; color: #6b7280; }
.header-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.mb { margin-bottom: 14px; }
.meta { font-size: 13px; color: #4b5563; margin-bottom: 12px; }
.kpi-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}
.kpi {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 14px 16px;
}
.kpi-label { font-size: 12px; color: #6b7280; }
.kpi-value {
  margin-top: 6px;
  font-size: 22px;
  font-weight: 650;
  color: #111827;
  font-variant-numeric: tabular-nums;
}
.panel {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 16px 18px;
  margin-bottom: 14px;
}
.panel-title { font-size: 14px; font-weight: 600; color: #374151; margin-bottom: 12px; }
@media (max-width: 960px) {
  .kpi-row { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
