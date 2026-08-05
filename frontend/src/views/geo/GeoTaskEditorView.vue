<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getGeoContentTask } from '../../api/geoContent'
import { session } from '../../store/session'

const route = useRoute()
const router = useRouter()

const tenantId = computed(() =>
  session.tenantId || (import.meta.env.DEV && import.meta.env.VITE_API_KEY ? 1 : null),
)
const taskId = computed(() => Number(route.params.taskId))
const loading = ref(false)
const error = ref('')
const task = ref(null)

/** Prefer same-origin static editor so auth/cookie align with SPA. */
const editorSrc = computed(() => {
  if (!taskId.value || !tenantId.value) return ''
  const qs = new URLSearchParams({
    tenant_id: String(tenantId.value),
    task_id: String(taskId.value),
  })
  const key = import.meta.env.VITE_API_KEY
  if (key) qs.set('api_key', key)
  // Local static demo often on :5176; in SPA we serve public files via Vite root.
  if (import.meta.env.DEV && window.location.port === '5173') {
    // Prefer dedicated static server when present, else Vite public path.
    const localStatic = `http://127.0.0.1:5176/geo/editor.html?${qs}&api_origin=http://127.0.0.1:8011`
    return localStatic
  }
  return `/deal-sniper/geo/editor.html?${qs}`
})

async function loadMeta() {
  if (!tenantId.value || !taskId.value) {
    error.value = '缺少租户或任务 ID'
    return
  }
  loading.value = true
  error.value = ''
  try {
    task.value = await getGeoContentTask(tenantId.value, taskId.value)
  } catch (e) {
    error.value = e.message || '加载任务失败'
    task.value = null
  } finally {
    loading.value = false
  }
}

function openInNewTab() {
  if (editorSrc.value) window.open(editorSrc.value, '_blank')
}

watch([tenantId, taskId], loadMeta)
onMounted(loadMeta)
</script>

<template>
  <div class="geo-task-editor">
    <div class="toolbar">
      <div class="left">
        <el-button text type="primary" @click="router.push('/geo/tasks')">← 任务列表</el-button>
        <div class="meta">
          <span class="title">任务 #{{ taskId }}</span>
          <span v-if="task" class="sub">{{ task.title }} · {{ task.status }}</span>
        </div>
      </div>
      <div class="right">
        <el-button @click="openInNewTab">新窗口打开</el-button>
        <el-button @click="loadMeta">刷新元数据</el-button>
      </div>
    </div>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />
    <el-alert
      type="info"
      show-icon
      class="mb"
      title="P1 混合编辑器：SPA 壳 + 静态 editor 流水线。完整生成/门禁/渠道适配仍在 iframe 内完成。"
    />

    <div v-loading="loading" class="frame-wrap">
      <iframe v-if="editorSrc" class="frame" :src="editorSrc" title="GEO content editor" />
    </div>
  </div>
</template>

<style scoped>
.geo-task-editor {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 88px);
  min-height: 480px;
}
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.left, .right { display: flex; align-items: center; gap: 10px; }
.meta { display: flex; flex-direction: column; }
.title { font-weight: 700; color: #1e2330; }
.sub { font-size: 12px; color: #6b7280; }
.mb { margin-bottom: 10px; }
.frame-wrap {
  flex: 1;
  min-height: 0;
  border: 1px solid #e8e4f5;
  border-radius: 12px;
  overflow: hidden;
  background: #fff;
}
.frame {
  width: 100%;
  height: 100%;
  border: 0;
  display: block;
  min-height: 560px;
}
</style>
