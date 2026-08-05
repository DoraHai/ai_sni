<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { staticGeoWorkbenchUrl } from '../../api/geoContent'
import { useGeoTenant } from '../../composables/useGeoTenant'

const router = useRouter()
const { tenantId } = useGeoTenant()

const cards = [
  { title: '内容任务', desc: '任务列表 · Vue 母稿编辑器（第一刀）', path: '/geo/tasks', phase: 'Vue' },
  { title: '机会词', desc: 'prompts 列表 / 新建 / 归档', path: '/geo/prompts', phase: 'Vue' },
  { title: '事实库', desc: 'facts 列表 / 新建 / 核验', path: '/geo/facts', phase: 'Vue' },
  { title: '跟踪引擎', desc: '监测引擎开关 · sample_mode', path: '/geo/engines', phase: 'Vue' },
  { title: 'AI 能力配置', desc: '租户 LLM（百炼/DeepSeek）', path: '/geo/ai-settings', phase: 'Vue' },
  { title: '发布渠道', desc: '渠道目录 · Webhook 账号', path: '/geo/publishing', phase: 'Vue' },
  { title: 'GEO 概览', desc: 'KPI 与观测入口', path: '/geo/overview', phase: 'Vue' },
  { title: 'AI 可见度', desc: '快照登记与探测', path: '/geo/visibility', phase: 'Vue' },
]

function go(card) {
  router.push(card.path)
}

function openStaticEditor() {
  const tid = tenantId.value || 1
  window.open(staticGeoWorkbenchUrl('editor.html', tid), '_blank')
}

function openStaticFull() {
  const tid = tenantId.value || 1
  window.open(staticGeoWorkbenchUrl('dashboard.html', tid), '_blank')
}

const note = computed(() =>
  '方案 B：工作台已 Vue。母稿第一刀在「内容任务」打开；渠道/审校仍可进静态完整 editor。',
)
</script>

<template>
  <div class="geo-hub">
    <div class="page-header">
      <div>
        <div class="page-title">内容工作台</div>
        <div class="page-desc">{{ note }}</div>
      </div>
      <div class="header-actions">
        <el-button type="primary" @click="openStaticEditor">打开静态编辑器</el-button>
        <el-button @click="openStaticFull">兼容：全量静态台</el-button>
      </div>
    </div>

    <div class="card-grid">
      <button
        v-for="c in cards"
        :key="c.path"
        type="button"
        class="hub-card"
        @click="go(c)"
      >
        <div class="hub-title">{{ c.title }}</div>
        <div class="hub-desc">{{ c.desc }}</div>
        <el-tag size="small" type="success">{{ c.phase }}</el-tag>
      </button>
    </div>
  </div>
</template>

<style scoped>
.geo-hub { padding: 4px 2px 24px; }
.page-header {
  display: flex; justify-content: space-between; align-items: flex-start;
  gap: 16px; margin-bottom: 18px; flex-wrap: wrap;
}
.page-title { font-size: 20px; font-weight: 700; color: #1e2330; }
.page-desc { margin-top: 4px; font-size: 13px; color: #6b7280; max-width: 640px; }
.header-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}
.hub-card {
  text-align: left;
  border: 1px solid #e8e4f5;
  background: #fff;
  border-radius: 12px;
  padding: 16px;
  cursor: pointer;
  transition: box-shadow .15s, border-color .15s;
}
.hub-card:hover {
  border-color: #c4b5fd;
  box-shadow: 0 4px 14px rgba(124, 58, 237, 0.08);
}
.hub-title { font-weight: 700; color: #1e2330; margin-bottom: 6px; }
.hub-desc { font-size: 12px; color: #6b7280; margin-bottom: 10px; min-height: 32px; }
</style>
