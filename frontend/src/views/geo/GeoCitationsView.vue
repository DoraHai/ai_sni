<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { fetchGeoCitationInsights } from '../../api/geoContent'
import { session } from '../../store/session'

const tenantId = computed(() =>
  session.tenantId || (import.meta.env.DEV && import.meta.env.VITE_API_KEY ? 1 : null),
)

const loading = ref(false)
const error = ref('')
const data = ref(null)

const fmtPct = (v) => {
  if (v == null) return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return `${(n * 100).toFixed(1)}%`
}

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    return
  }
  loading.value = true
  error.value = ''
  try {
    data.value = await fetchGeoCitationInsights(tenantId.value)
  } catch (e) {
    error.value = e.message || '加载失败'
    data.value = null
  } finally {
    loading.value = false
  }
}

watch(tenantId, load)
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="geo-cite">
    <div class="page-header">
      <div>
        <div class="page-title">引用域名</div>
        <div class="page-desc">从回答快照聚合被引用域名，并对照国内蓝图主机。</div>
      </div>
      <div class="header-actions">
        <el-button :loading="loading" @click="load">刷新</el-button>
        <router-link class="el-button" to="/geo/visibility">可见度</router-link>
        <router-link class="el-button" to="/geo/overview">GEO 概览</router-link>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" class="mb" />

    <div v-if="data" class="kpi-row">
      <div class="kpi">
        <div class="kpi-label">含引用快照</div>
        <div class="kpi-value">{{ data.snapshots_with_citations ?? '—' }}</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">独立域名</div>
        <div class="kpi-value">{{ data.distinct_cited_domains ?? '—' }}</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">自我域名引用率</div>
        <div class="kpi-value">{{ fmtPct(data.own_domain_cite_rate) }}</div>
      </div>
    </div>

    <section v-if="data" class="panel">
      <div class="panel-title">域名明细</div>
      <el-table :data="data.items || []" size="small" empty-text="暂无引用数据，请先在可见度登记含 URL 的快照">
        <el-table-column prop="domain" label="域名" min-width="160" />
        <el-table-column prop="cite_count" label="次数" width="80" />
        <el-table-column label="引擎" min-width="140">
          <template #default="{ row }">{{ (row.engines || []).join(', ') || '—' }}</template>
        </el-table-column>
        <el-table-column label="蓝图" min-width="160">
          <template #default="{ row }">
            {{ row.blueprint_channel_name || row.blueprint_channel_key || '—' }}
          </template>
        </el-table-column>
        <el-table-column label="自有域" width="80">
          <template #default="{ row }">{{ row.is_own_domain ? '是' : '否' }}</template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<style scoped>
.geo-cite { padding: 4px 2px 24px; }
.page-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}
.page-title { font-size: 20px; font-weight: 650; color: #1f2937; }
.page-desc { margin-top: 4px; font-size: 13px; color: #6b7280; }
.header-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.mb { margin-bottom: 14px; }
.kpi-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
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
  font-size: 24px;
  font-weight: 650;
  color: #111827;
  font-variant-numeric: tabular-nums;
}
.panel {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 16px 18px;
}
.panel-title { font-size: 14px; font-weight: 600; color: #374151; margin-bottom: 12px; }
@media (max-width: 720px) {
  .kpi-row { grid-template-columns: 1fr; }
}
</style>
