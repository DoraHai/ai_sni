<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createGeoContentTask,
  deleteGeoContentTask,
  listGeoContentTasks,
  listGeoPrompts,
  staticGeoWorkbenchUrl,
} from '../../api/geoContent'
import { useGeoTenant } from '../../composables/useGeoTenant'

const router = useRouter()
const { tenantId } = useGeoTenant()

const loading = ref(false)
const error = ref('')
const items = ref([])
const statusFilter = ref('')
const q = ref('')
const createOpen = ref(false)
const creating = ref(false)
const prompts = ref([])
const form = ref({ prompt_id: null, title: '', target_channels: ['website', 'wechat', 'zhihu'] })
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)

const statusOptions = [
  { value: '', label: '全部（不含归档）' },
  { value: 'draft', label: '草稿' },
  { value: 'facts_bound', label: '已绑事实' },
  { value: 'editing', label: '编辑中' },
  { value: 'needs_fix', label: '待修补' },
  { value: 'ready', label: '就绪' },
  { value: 'published', label: '已发布' },
  { value: 'archived', label: '已归档' },
]
const includeArchived = ref(false)

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
    const params = {
      limit: pageSize.value,
      offset: (page.value - 1) * pageSize.value,
    }
    if (statusFilter.value) params.status = statusFilter.value
    if (q.value.trim()) params.q = q.value.trim()
    if (includeArchived.value && !statusFilter.value) params.include_archived = true
    const data = await listGeoContentTasks(tenantId.value, params)
    items.value = data.items || []
    total.value = Number(data.total ?? items.value.length) || 0
  } catch (e) {
    error.value = e.message || '加载失败'
    items.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function onPageChange(p) {
  page.value = p
  load()
}

function onSizeChange(s) {
  pageSize.value = s
  page.value = 1
  load()
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
    ElMessage.error(e.message || '加载优化意图词失败')
  }
}

async function submitCreate() {
  if (!form.value.prompt_id) {
    ElMessage.warning('请选择优化意图词')
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
  window.open(staticGeoWorkbenchUrl('dashboard.html', tenantId.value || 1), '_blank')
}

async function archiveTask(row) {
  try {
    await ElMessageBox.confirm(`归档任务 #${row.id}？列表默认不再显示。`, '归档', {
      type: 'warning',
      confirmButtonText: '归档',
    })
    await deleteGeoContentTask(tenantId.value, row.id, false)
    ElMessage.success('已归档')
    await load()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error(e.message || '归档失败')
  }
}

async function hardDeleteTask(row) {
  try {
    await ElMessageBox.confirm(
      `物理删除任务 #${row.id}（级联删除母稿/渠道稿，不可恢复）？`,
      '删除',
      { type: 'error', confirmButtonText: '删除' },
    )
    await deleteGeoContentTask(tenantId.value, row.id, true)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error(e.message || '删除失败')
  }
}

watch([tenantId, statusFilter, includeArchived], () => {
  page.value = 1
  load()
})
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="geo-tasks">
    <div class="page-header">
      <div>
        <div class="page-title">优化文章</div>
        <div class="page-desc">
          内容任务列表 · 母稿完整流水线可走本页编辑器或静态 editor 兼容壳。
        </div>
      </div>
      <div class="header-actions">
        <router-link class="el-button" to="/geo/workbench">工作台枢纽</router-link>
        <router-link class="el-button" to="/geo/prompts">优化意图词</router-link>
        <router-link class="el-button" to="/geo/facts">事实库</router-link>
        <el-button @click="openStaticWorkbench">兼容静态台</el-button>
        <el-button type="primary" @click="openCreate">新建优化文章</el-button>
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
      <el-checkbox v-model="includeArchived" :disabled="!!statusFilter">含归档</el-checkbox>
    </div>

    <el-table :data="items" stripe empty-text="暂无优化文章" class="task-table">
      <el-table-column prop="id" label="ID" width="72" />
      <el-table-column label="标题" min-width="220">
        <template #default="{ row }">
          <div class="title-cell">{{ row.title || '—' }}</div>
          <div class="sub">{{ row.prompt_question || `prompt #${row.prompt_id}` }}</div>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag size="small" :type="row.status === 'archived' ? 'info' : ''">{{ row.status }}</el-tag>
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
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button type="primary" link @click="openEditor(row)">打开</el-button>
          <el-button
            v-if="row.status !== 'archived'"
            type="warning"
            link
            @click="archiveTask(row)"
          >归档</el-button>
          <el-button type="danger" link @click="hardDeleteTask(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination
        background
        layout="total, sizes, prev, pager, next"
        :total="total"
        :page-size="pageSize"
        :current-page="page"
        :page-sizes="[10, 20, 50, 100]"
        @current-change="onPageChange"
        @size-change="onSizeChange"
      />
    </div>

    <el-dialog v-model="createOpen" title="新建优化文章" width="480px">
      <el-form label-width="100px">
        <el-form-item label="优化意图词" required>
          <el-select v-model="form.prompt_id" filterable style="width: 100%" placeholder="选择优化意图词">
            <el-option
              v-for="p in prompts"
              :key="p.id"
              :label="`#${p.id} ${p.question}`"
              :value="p.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="标题">
          <el-input v-model="form.title" placeholder="默认用意图词问题" />
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
.filters { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; align-items: center; }
.pager { display: flex; justify-content: flex-end; margin-top: 14px; }
.mb { margin-bottom: 12px; }
.title-cell { font-weight: 600; color: #1e2330; }
.sub { font-size: 12px; color: #8b93a7; margin-top: 2px; }
.blocked { color: #b45309; font-size: 12px; }
.muted { color: #9ca3af; }
.task-table { width: 100%; background: #fff; border-radius: 12px; }
</style>
