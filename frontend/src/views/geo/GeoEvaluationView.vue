<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { fetchGeoEvaluationInsights } from '../../api/geoContent'
import { useClientPager } from '../../composables/useClientPager'
import { session } from '../../store/session'

const router = useRouter()

const tenantId = computed(() =>
  session.tenantId || (import.meta.env.DEV && import.meta.env.VITE_API_KEY ? 1 : null),
)

const loading = ref(false)
const error = ref('')
const data = ref(null)
const recentItems = computed(() => data.value?.recent || [])
const recentPager = useClientPager(recentItems, { pageSize: 20 })

const sentLabel = {
  positive: '正面',
  neutral: '中性',
  negative: '负面',
  unknown: '未知',
}
const posLabel = {
  first: '首位',
  mentioned: '有提及',
  absent: '未出现',
  unknown: '未知',
}

const distRows = computed(() => {
  if (!data.value) return []
  const rows = []
  for (const [k, v] of Object.entries(data.value.sentiment_counts || {})) {
    rows.push({ dim: '情感', value: sentLabel[k] || k, count: v })
  }
  for (const [k, v] of Object.entries(data.value.position_counts || {})) {
    rows.push({ dim: '位置', value: posLabel[k] || k, count: v })
  }
  return rows
})

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    return
  }
  loading.value = true
  error.value = ''
  try {
    data.value = await fetchGeoEvaluationInsights(tenantId.value)
  } catch (e) {
    error.value = e.message || '加载失败'
    data.value = null
  } finally {
    loading.value = false
  }
}

function openVisibility(promptId) {
  router.push({ path: '/geo/visibility', query: promptId ? { prompt_id: String(promptId) } : {} })
}

watch(tenantId, load)
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="geo-eval">
    <div class="page-header">
      <div>
        <div class="page-title">评价分析</div>
        <div class="page-desc">快照情感与我方位置分布（人工标注）。</div>
      </div>
      <div class="header-actions">
        <el-button :loading="loading" @click="load">刷新</el-button>
        <router-link class="el-button" to="/geo/visibility">去登记快照</router-link>
        <router-link class="el-button" to="/geo/competitors">竞品分析</router-link>
        <router-link class="el-button" to="/geo/overview">GEO 概览</router-link>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" class="mb" />

    <div class="layout">
      <section class="panel">
        <div class="panel-title">分布</div>
        <p class="hint">快照总数：{{ data?.total ?? '—' }}</p>
        <el-table :data="distRows" size="small" empty-text="暂无数据">
          <el-table-column prop="dim" label="维度" width="80" />
          <el-table-column prop="value" label="值" min-width="100" />
          <el-table-column prop="count" label="次数" width="80" />
        </el-table>
      </section>

      <section class="panel">
        <div class="panel-title">最近快照</div>
        <el-table
          :data="recentPager.pagedItems"
          size="small"
          empty-text="暂无快照 · 先在「AI 可见度」登记"
        >
          <el-table-column label="问题" min-width="180">
            <template #default="{ row }">
              <button type="button" class="linkish" @click="openVisibility(row.prompt_id)">
                {{ row.prompt_question || `#${row.prompt_id}` }}
              </button>
            </template>
          </el-table-column>
          <el-table-column prop="engine" label="引擎" width="100" />
          <el-table-column label="位置" width="90">
            <template #default="{ row }">{{ posLabel[row.brand_position] || row.brand_position }}</template>
          </el-table-column>
          <el-table-column label="情感" width="80">
            <template #default="{ row }">{{ sentLabel[row.sentiment] || row.sentiment }}</template>
          </el-table-column>
          <el-table-column prop="captured_at" label="时间" width="170" />
        </el-table>
        <div class="geo-pager">
          <el-pagination
            background
            small
            layout="total, prev, pager, next"
            :total="recentPager.total"
            :page-size="recentPager.pageSize"
            :current-page="recentPager.page"
            @current-change="recentPager.onPageChange"
          />
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.geo-eval { padding: 4px 2px 24px; }
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
.layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr);
  gap: 14px;
}
.panel {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 16px 18px;
}
.panel-title { font-size: 14px; font-weight: 600; color: #374151; margin-bottom: 12px; }
.hint { margin: 0 0 10px; font-size: 12px; color: #9ca3af; }
.linkish {
  border: 0;
  background: none;
  color: #2563eb;
  cursor: pointer;
  padding: 0;
  text-align: left;
  font: inherit;
}
.linkish:hover { text-decoration: underline; }
@media (max-width: 960px) {
  .layout { grid-template-columns: 1fr; }
}
</style>
