<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  createGeoContentTask,
  listGeoContentTasks,
  listGeoPrompts,
} from '../../api/geoContent'
import { session } from '../../store/session'

const router = useRouter()
const tenantId = computed(() =>
  session.tenantId || (import.meta.env.DEV && import.meta.env.VITE_API_KEY ? 1 : null),
)

const loading = ref(false)
const error = ref('')
const items = ref([])
const statusFilter = ref('')
const q = ref('')
const createOpen = ref(false)
const creating = ref(false)
const prompts = ref([])
const form = ref({ prompt_id: null, title: '', target_channels: ['website', 'wechat', 'zhihu'] })

const statusOptions = [
  { value: '', label: '全部状态' },
  { value: 'draft', label: '草稿' },
  { value: 'facts_bound', label: '已绑事实' },
  { value: 'editing', label: '编辑中' },
  { value: 'needs_fix', label: '待修补' },
  { value: 'ready', label: '就绪' },
  { value: 'published', label: '已发布' },
]

const pipelineLabel = {
  opportunity: '机会',
  evidence: '证据',
  draft: '母稿',
  adapt: '渠道',
  publish: '发布',
}

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    items.value = []
    return
  }
  loading.value = true
  error.value = ''
  try {
    const params = {}
    if (statusFilter.value) params.status = statusFilter.value
    if (q.value.trim()) params.q = q.value.trim()
    const data = await listGeoContentTasks(tenantId.value, params)
    items.value = data.items || []
  } catch (e) {
    error.value = e.message || '加载失败'
    items.value = []
  } finally {
    loading.value = false
  }
}

async function openCreate() {
  if (!tenantId.value) return
  createOpen.value = true
  try {
    const data = await listGeoPrompts(tenantId.value, { status: 'active' })
    prompts.value = data.items || []
    if (!form.value.prompt_id && prompts.value.length) {
      form.value.prompt_id = prompts.value[0].id
    }
  } catch (e) {
    ElMessage.error(e.message || '加载机会词失败')
  }
}

async function submitCreate() {
  if (!form.value.prompt_id) {
    ElMessage.warning('请选择机会词')
    return
  }
  creating.value = true
  try {
    const task = await createGeoContentTask({
      tenant_id: tenantId.value,
      prompt_id: form.value.prompt_id,
      title: form.value.title || undefined,
      target_channels: form.value.target_channels,
    })
    ElMessage.success(`已创建任务 #${task.id}`)
    createOpen.value = false
    form.value = { prompt_id: null, title: '', target_channels: ['website', 'wechat', 'zhihu'] }
    await load()
    router.push(`/geo/tasks/${task.id}`)
  } catch (e) {
    ElMessage.error(e.message || '创建失败')
  } finally {
    creating.value = false
  }
}

function openEditor(row) {
  router.push(`/geo/tasks/${row.id}`)
}

function openStaticWorkbench() {
  const tid = tenantId.value || 1
  const key = import.meta.env.VITE_API_KEY || ''
  const qs = new URLSearchParams({ tenant_id: String(tid) })
  if (key) qs.set('api_key', key)
  window.open(`/deal-sniper/geo/dashboard.html?${qs}`, '_blank')
}

watch([tenantId, statusFilter], load)
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="geo-tasks">
    <div class="page-header">
      <div>
        <div class="page-title">内容任务</div>
        <div class="page-desc">
          Vue 任务列表（P1）。编辑母稿/渠道稿仍复用静态编辑器流水线，减少双端断点。
        </div>
      </div>
      <div class="header-actions">
        <el-button @click="openStaticWorkbench">全量静态工作台</el-button>
        <el-button type="primary" @click="openCreate">新建任务</el-button>
        <el-button @click="load">刷新</el-button>
      </div>
    </div>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <div class="filters">
      <el-select v-model="statusFilter" style="width: 160px" placeholder="状态">
        <el-option v-for="o in statusOptions" :key="o.value || 'all'" :label="o.label" :value="o.value" />
      </el-select>
      <el-input
        v-model="q"
        clearable
        placeholder="搜索标题 / 阻断原因"
        style="width: 260px"
        @keyup.enter="load"
      />
      <el-button @click="load">查询</el-button>
    </div>

    <el-table :data="items" stripe empty-text="暂无内容任务" class="task-table">
      <el-table-column prop="id" label="ID" width="72" />
      <el-table-column label="标题" min-width="220">
        <template #default="{ row }">
          <div class="title-cell">{{ row.title || '—' }}</div>
          <div class="sub">{{ row.prompt_question || `prompt #${row.prompt_id}` }}</div>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag size="small">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="流水线" width="90">
        <template #default="{ row }">
          {{ pipelineLabel[row.pipeline_step] || row.pipeline_step || '—' }}
        </template>
      </el-table-column>
      <el-table-column label="阻断" min-width="120">
        <template #default="{ row }">
          <span v-if="row.blocked_reason" class="blocked">{{ row.blocked_reason }}</span>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column label="更新" width="170">
        <template #default="{ row }">{{ row.updated_at || row.created_at || '—' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="120" fixed="right">
        <template #default="{ row }">
          <el-button type="primary" link @click="openEditor(row)">打开编辑器</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="createOpen" title="新建内容任务" width="480px">
      <el-form label-width="88px">
        <el-form-item label="机会词" required>
          <el-select v-model="form.prompt_id" filterable style="width: 100%" placeholder="选择机会词">
            <el-option
              v-for="p in prompts"
              :key="p.id"
              :label="`#${p.id} ${p.question}`"
              :value="p.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="标题">
          <el-input v-model="form.title" placeholder="默认用机会词问题" />
        </el-form-item>
        <el-form-item label="目标渠道">
          <el-select v-model="form.target_channels" multiple style="width: 100%">
            <el-option label="官网" value="website" />
            <el-option label="微信" value="wechat" />
            <el-option label="知乎" value="zhihu" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.geo-tasks { padding: 4px 2px 24px; }
.page-header {
  display: flex; justify-content: space-between; align-items: flex-start;
  gap: 16px; margin-bottom: 16px;
}
.page-title { font-size: 20px; font-weight: 700; color: #1e2330; }
.page-desc { margin-top: 4px; font-size: 13px; color: #6b7280; }
.header-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.filters { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; }
.mb { margin-bottom: 12px; }
.title-cell { font-weight: 600; color: #1e2330; }
.sub { font-size: 12px; color: #8b93a7; margin-top: 2px; }
.blocked { color: #b45309; font-size: 12px; }
.muted { color: #9ca3af; }
.task-table { width: 100%; background: #fff; border-radius: 12px; }
</style>
