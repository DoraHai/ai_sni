<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createGeoContentTask,
  deleteGeoContentTask,
  fetchGeoContentTaskImpact,
  listGeoContentTasks,
  listGeoPrompts,
} from '../../api/geoContent'
import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
import { useGeoTenant } from '../../composables/useGeoTenant'
import { pipelineLabel, taskStatusLabel } from '../../utils/geoReportLabels'

const router = useRouter()
const { tenantId } = useGeoTenant()

const loading = ref(false)
const error = ref('')
const items = ref([])
const statusFilter = ref('')
const chip = ref('all')
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
const recPrompts = ref([])
const citeRows = ref([])

const CHIP_STATUS = {
  all: null,
  draft: ['draft', 'facts_bound', 'editing', 'generating'],
  polish: ['needs_fix'],
  publish: ['ready', 'exported'],
  published: ['published'],
}

const chipCounts = computed(() => {
  const rows = items.value || []
  const count = (keys) => rows.filter((t) => keys.includes(t.status)).length
  return {
    all: rows.length,
    draft: count(CHIP_STATUS.draft),
    polish: count(CHIP_STATUS.polish),
    publish: count(CHIP_STATUS.publish),
    published: count(CHIP_STATUS.published),
  }
})

const tableRows = computed(() => {
  const keys = CHIP_STATUS[chip.value]
  let rows = items.value || []
  if (keys) rows = rows.filter((t) => keys.includes(t.status))
  const qq = q.value.trim()
  if (qq) {
    rows = rows.filter(
      (t) =>
        String(t.title || '').includes(qq) ||
        String(t.prompt_question || '').includes(qq),
    )
  }
  return rows
})

function friendliness(t) {
  let s = 38
  if (t.brief_ready) s += 16
  const rich = Number(t.strategy_richness || 0)
  if (rich) s += Math.min(20, rich)
  if (t.status === 'published') s += 24
  else if (t.status === 'ready' || t.status === 'exported') s += 16
  else if (t.status === 'needs_fix') s += 4
  return Math.min(99, s)
}

function channelLabel(ch) {
  return { website: '官网', wechat: '公众号', zhihu: '知乎', media: '媒体' }[ch] || ch
}

const recommended = computed(() =>
  recPrompts.value
    .filter((p) => Array.isArray(p.tags) && p.tags.includes('brand_missing'))
    .slice(0, 4),
)

function statusTagType(status) {
  if (status === 'published' || status === 'ready') return 'success'
  if (status === 'needs_fix' || status === 'failed') return 'danger'
  if (status === 'archived') return 'info'
  return ''
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
      limit: 200,
      offset: 0,
    }
    if (statusFilter.value) params.status = statusFilter.value
    if (q.value.trim()) params.q = q.value.trim()
    if (includeArchived.value && !statusFilter.value) params.include_archived = true
    const data = await listGeoContentTasks(tenantId.value, params)
    items.value = data.items || []
    total.value = Number(data.total ?? items.value.length) || 0
    try {
      const pr = await listGeoPrompts(tenantId.value, { status: 'active' })
      recPrompts.value = pr.items || []
    } catch {
      recPrompts.value = []
    }
    const published = (items.value || []).filter((t) => t.status === 'published').slice(0, 6)
    try {
      const impacts = await Promise.all(
        published.map((t) =>
          fetchGeoContentTaskImpact(tenantId.value, t.id, 14).then((imp) => ({
            title: t.title,
            cites: Number(imp.cite_hits?.total ?? imp.summary?.cite_hit_total ?? 0),
            question: recPrompts.value.find((p) => p.id === t.prompt_id)?.question || '—',
            id: t.id,
          })).catch(() => ({
            title: t.title,
            cites: t.citation_count ?? 0,
            question: '—',
            id: t.id,
          })),
        ),
      )
      citeRows.value = impacts
    } catch {
      citeRows.value = published.map((t) => ({
        title: t.title,
        cites: 0,
        question: '—',
        id: t.id,
      }))
    }
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

async function createFromPrompt(prompt) {
  if (!prompt?.id) return
  try {
    const task = await createGeoContentTask({
      tenant_id: tenantId.value,
      prompt_id: prompt.id,
      title: prompt.question,
    })
    ElMessage.success(`已创建任务 #${task.id}`)
    router.push(`/geo/tasks/${task.id}`)
  } catch (e) {
    ElMessage.error(e.message || '创建失败')
  }
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
  <GeoWorkbenchPage
    title="GEO 文章工作台"
    sub="围绕用户提问生产可验证、可摘取、可被 AI 引用的内容"
    :loading="loading"
    class="geo-tasks"
  >
    <template #actions>
      <button class="gd-btn" @click="router.push('/geo/placements')">信源素材库</button>
      <button class="gd-btn" @click="load">刷新</button>
      <button class="gd-btn primary" @click="openCreate">AI 生成 GEO 文章</button>
    </template>
    <div class="geo-dash">

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />
    <div v-if="recommended.length" class="gd-card" style="margin-bottom:16px">
      <div class="gd-hd">
        <h3>优先从这些提问写</h3>
        <button class="gd-btn primary" style="margin-left:auto" @click="createFromPrompt(recommended[0])">立即生成</button>
      </div>
      <div class="gd-bd">
        <div v-for="p in recommended" :key="p.id" style="display:flex;justify-content:space-between;gap:12px;padding:8px 0;border-bottom:1px solid #e8eaf0">
          <span>「{{ p.question }}」</span>
          <el-button link type="primary" @click="createFromPrompt(p)">生成文章</el-button>
        </div>
      </div>
    </div>

    <div class="geo-chips">
      <button class="geo-chip" :class="{ active: chip === 'all' }" @click="chip = 'all'">全部 {{ chipCounts.all }}</button>
      <button class="geo-chip" :class="{ active: chip === 'draft' }" @click="chip = 'draft'">草稿 {{ chipCounts.draft }}</button>
      <button class="geo-chip" :class="{ active: chip === 'polish' }" @click="chip = 'polish'">待润色 {{ chipCounts.polish }}</button>
      <button class="geo-chip" :class="{ active: chip === 'publish' }" @click="chip = 'publish'">待发布 {{ chipCounts.publish }}</button>
      <button class="geo-chip" :class="{ active: chip === 'published' }" @click="chip = 'published'">已发布 {{ chipCounts.published }}</button>
      <input v-model="q" class="gd-search" placeholder="搜索文章或目标提问" @keyup.enter="load" />
    </div>

    <div class="gd-card">
      <div class="gd-bd" style="padding:0">
        <table>
          <thead>
            <tr>
              <th>文章</th>
              <th>目标提问</th>
              <th>发布信源</th>
              <th>AI 友好度</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in tableRows" :key="row.id">
              <td>
                <b>{{ row.title || '—' }}</b>
                <div class="gd-sub" style="margin:0">{{ pipelineLabel(row.pipeline_step) }}</div>
              </td>
              <td>{{ row.prompt_question || `提问 #${row.prompt_id}` }}</td>
              <td>
                <span v-for="ch in (row.target_channels || [])" :key="ch" class="gd-tag" style="margin-right:4px">{{ channelLabel(ch) }}</span>
              </td>
              <td>
                <span class="geo-ready"><i :style="{ '--ready': friendliness(row) + '%' }" />{{ friendliness(row) }}</span>
              </td>
              <td><span class="gd-badge" :class="row.status === 'published' ? 'green' : row.status === 'needs_fix' ? 'amber' : 'blue'">{{ taskStatusLabel(row.status) }}</span></td>
              <td>
                <el-button link type="primary" @click="openEditor(row)">在线编辑</el-button>
                <el-button v-if="row.status !== 'archived'" link @click="archiveTask(row)">归档</el-button>
              </td>
            </tr>
            <tr v-if="!tableRows.length"><td colspan="6" class="gd-sub">暂无优化文章</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <el-dialog v-model="createOpen" title="新建优化文章" width="500px" class="geo-form-dialog">
      <el-form label-width="100px" class="geo-dialog-form">
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
          <el-select v-model="form.target_channels" multiple style="width: 100%" collapse-tags>
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
  </GeoWorkbenchPage>
</template>

<style scoped>
.title-cell { font-weight: 650; color: #0f172a; }
.sub { font-size: 12px; color: #94a3b8; margin-top: 3px; line-height: 1.4; }
.blocked { color: #b45309; font-size: 12px; }
.muted { color: #9ca3af; }
.task-table { width: 100%; }
</style>
