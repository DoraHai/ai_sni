<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { fetchGeoCompetitorInsights } from '../../api/geoContent'
import { session } from '../../store/session'

const tenantId = computed(() =>
  session.tenantId || (import.meta.env.DEV && import.meta.env.VITE_API_KEY ? 1 : null),
)

const loading = ref(false)
const error = ref('')
const items = ref([])

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const data = await fetchGeoCompetitorInsights(tenantId.value)
    items.value = data.items || []
  } catch (e) {
    error.value = e.message || '加载失败'
    items.value = []
  } finally {
    loading.value = false
  }
}

watch(tenantId, load)
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="geo-comp">
    <div class="page-header">
      <div>
        <div class="page-title">竞品分析</div>
        <div class="page-desc">由可见度快照人工标注聚合（无自动巡检）。</div>
      </div>
      <div class="header-actions">
        <el-button :loading="loading" @click="load">刷新</el-button>
        <router-link class="el-button" to="/geo/visibility">去登记快照</router-link>
        <router-link class="el-button" to="/geo/evaluation">评价分析</router-link>
        <router-link class="el-button" to="/geo/overview">GEO 概览</router-link>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" class="mb" />

    <section class="panel">
      <div class="panel-title">竞品提及聚合</div>
      <el-table
        :data="items"
        size="small"
        empty-text="暂无竞品标注 · 在「AI 可见度」保存快照时填写竞品名"
      >
        <el-table-column prop="name" label="竞品" min-width="140" />
        <el-table-column prop="mention_count" label="出现次数" width="100" />
        <el-table-column prop="prompt_count" label="关联提问" width="100" />
        <el-table-column label="引擎" min-width="140">
          <template #default="{ row }">{{ (row.engines || []).join(', ') || '—' }}</template>
        </el-table-column>
        <el-table-column prop="latest_captured_at" label="最近观测" width="170" />
        <el-table-column prop="sample_prompt_question" label="样例提问" min-width="200" />
      </el-table>
    </section>
  </div>
</template>

<style scoped>
.geo-comp { padding: 4px 2px 24px; }
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
.panel {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 16px 18px;
}
.panel-title { font-size: 14px; font-weight: 600; color: #374151; margin-bottom: 12px; }
</style>
