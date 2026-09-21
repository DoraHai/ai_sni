<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createGeoContentTask,
  deleteGeoContentTask,
  listGeoContentTasks,
  listGeoPrompts,
} from '../../api/geoContent'
import GeoCreateEvidenceTask from '../../components/GeoCreateEvidenceTask.vue'
import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
import GeoEvidenceWorkQueue from '../../components/GeoEvidenceWorkQueue.vue'
import { taskNextWork } from '../../utils/geoWorkQueue'
import { geoSnapshotLink } from '../../utils/geoRoutes'
import { useGeoTenant } from '../../composables/useGeoTenant'
import { engineDisplay, taskStatusLabel } from '../../utils/geoReportLabels'

const router = useRouter()
const { tenantId } = useGeoTenant()

const CHANNEL_CN = {
  website: '官网', wechat: '微信', zhihu: '知乎', baijiahao: '百家号',
  toutiao: '头条', docs: '文档', industry_media: '行业媒体',
}

const loading = ref(false)
let loadGeneration = 0
const error = ref('')
const items = ref([])
const workbenchTab = ref('')
const q = ref('')
const evidenceContent = ref(null)
const createOpen = ref(false)
const createMode = ref('prompt')
const creating = ref(false)
const prompts = ref([])
const form = ref({ prompt_id: null, title: '', target_channels: ['website', 'wechat', 'zhihu'] })
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const workbenchCounts = ref({ all: 0, draft: 0, polish: 0, ready: 0, published: 0 })

const tabs = computed(() => [
  { value: '', label: '全部', count: workbenchCounts.value.all },
  { value: 'draft', label: '草稿', count: workbenchCounts.value.draft },
  { value: 'polish', label: '待润色', count: workbenchCounts.value.polish },
  { value: 'ready', label: '待发布', count: workbenchCounts.value.ready },
  { value: 'published', label: '已发布', count: workbenchCounts.value.published },
])

const statusSummary = computed(() => [
  { label: '内容', value: workbenchCounts.value.all, tone: 'neutral' },
  { label: '草稿', value: workbenchCounts.value.draft, tone: 'muted' },
  { label: '待优化', value: workbenchCounts.value.polish, tone: 'violet' },
  { label: '待发布', value: workbenchCounts.value.ready, tone: 'amber' },
  { label: '已发布', value: workbenchCounts.value.published, tone: 'green' },
])

function statusTagType(status) {
  if (status === 'published' || status === 'ready') return 'success'
  if (status === 'needs_fix' || status === 'failed') return 'danger'
  return 'info'
}

function enginesText(row) {
  const keys = row.engine_keys || []
  if (!keys.length) return '—'
  return keys.map((key) => engineDisplay(key)).join(' / ')
}

function pubsText(row) {
  const channels = row.publication_channels || []
  if (!channels.length) return '—'
  return channels.map((key) => CHANNEL_CN[key] || key).join('、')
}

function geoState(row) {
  if (row.geo_score == null) return { label: '待检测', detail: '尚无检测结果', tone: 'muted' }
  const score = Number(row.geo_score)
  return { label: `GEO 完整度 ${score}%`, detail: score >= 80 ? '结构与事实已就绪' : '仍有优化空间', tone: score >= 80 ? 'green' : 'violet' }
}

async function load() {
  const generation = ++loadGeneration
  const owner = tenantId.value
  items.value = []
  total.value = 0
  workbenchCounts.value = { all: 0, draft: 0, polish: 0, ready: 0, published: 0 }
  if (!tenantId.value) {
    loading.value = false
    error.value = '请先选择客户或配置本地 API Key'
    items.value = []
    total.value = 0
    return
  }
  loading.value = true
  error.value = ''
  try {
    const params = {
      limit: pageSize.value,
      offset: (page.value - 1) * pageSize.value,
    }
    if (workbenchTab.value) params.workbench_tab = workbenchTab.value
    if (q.value.trim()) params.q = q.value.trim()
    const data = await listGeoContentTasks(owner, params)
    if (generation !== loadGeneration) return
    items.value = data.items || []
    total.value = Number(data.total ?? items.value.length) || 0
    workbenchCounts.value = {
      all: 0, draft: 0, polish: 0, ready: 0, published: 0,
      ...(data.workbench_counts || {}),
    }
  } catch (e) {
    if (generation !== loadGeneration) return
    error.value = e.message || '加载失败'
    items.value = []
    total.value = 0
  } finally {
    if (generation === loadGeneration) loading.value = false
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

function setTab(value) {
  workbenchTab.value = value
  page.value = 1
  load()
}

async function openCreate() {
  if (!tenantId.value) return
  createMode.value = 'prompt'
  createOpen.value = true
  try {
    const data = await listGeoPrompts(tenantId.value, {
      status: 'active',
      active_inventory_only: true,
    })
    prompts.value = data.items || []
    if (!form.value.prompt_id && prompts.value.length) {
      form.value.prompt_id = prompts.value[0].id
    }
  } catch (e) {
    ElMessage.error(e.message || '加载目标问题失败')
  }
}

async function submitCreate() {
  if (createMode.value === 'import') {
    createOpen.value = false
    router.push('/geo/import')
    return
  }
  if (!form.value.prompt_id) {
    ElMessage.warning('请选择目标提问')
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

function openDistribution(row) {
  router.push(`/geo/tasks/${row.id}/distribution`)
}

function openCitations(row) {
  router.push({ path: '/geo/citations', query: { task_id: String(row.id) } })
}

function handleRowAction(row, command) {
  if (command === 'evidence') { evidenceContent.value = row; return }
  if (command === 'distribution') return openDistribution(row)
  if (command === 'citations') return openCitations(row)
  if (command === 'archive') return archiveTask(row)
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

watch(tenantId, () => {
  evidenceContent.value = null
  page.value = 1
  load()
})
onMounted(load)
</script>

<template>
  <GeoWorkbenchPage
    title="GEO 文章工作台"
    sub="让内容从生产走向被 AI 理解、引用和验证"
    :loading="loading"
    class="geo-tasks"
  >
    <template #actions>
      <router-link class="gd-btn" to="/geo/placements">信源素材库</router-link>
      <button class="gd-btn primary" type="button" @click="openCreate">＋ 创建 GEO 文章</button>
    </template>

    <div class="geo-dash">
      <GeoEvidenceWorkQueue :tenant-id="tenantId" />
      <GeoCreateEvidenceTask :tenant-id="tenantId" :content="evidenceContent" @close="evidenceContent = null" />
      <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

      <section class="status-strip" aria-label="内容状态摘要">
        <div class="status-summary"><span v-for="item in statusSummary" :key="item.label" class="status-summary-item" :class="`is-${item.tone}`"><b>{{ item.value }}</b><span>{{ item.label }}</span></span></div>
        <span class="status-note">近 14 天 · 内容状态与 AI 引用效果持续回流</span>
      </section>

      <section class="principle-line" aria-label="GEO 内容原则">
        <span class="principle-label">GEO 内容原则</span>
        <span>独家信息</span><i>·</i><span>事实可核验</span><i>·</i><span>明确来源</span><i>·</i><span>定义 / 对比 / FAQ</span><i>·</i><span>避免关键词堆砌</span>
        <button type="button" class="text-action" @click="ElMessage.info('GEO 写作规范将在内容编辑器中逐步提示')">查看 GEO 写作规范 →</button>
      </section>

      <div class="gd-card">
        <div class="gd-hd workbench-bar">
          <div><span class="eyebrow">WORKSPACE</span><h3>内容工作台</h3></div>
          <button
            v-for="tab in tabs"
            :key="tab.value || 'all'"
            class="geo-filter"
            :class="{ active: workbenchTab === tab.value }"
            type="button"
            @click="setTab(tab.value)"
          >
            {{ tab.label }} {{ tab.count }}
          </button>
          <input
            v-model="q"
            class="gd-search"
            placeholder="搜索文章或目标提问"
            @keyup.enter="() => { page = 1; load() }"
          />
        </div>
        <div class="gd-bd" style="padding:0">
          <el-table :data="items" empty-text="暂无任务 · 可创建 GEO 文章或导入已有文章" class="task-table">
            <el-table-column label="文章" min-width="240">
              <template #default="{ row }">
                <div class="title-cell">{{ row.title || '—' }}</div>
                <div class="sub">#{{ row.id }}</div>
              </template>
            </el-table-column>
            <el-table-column label="关联 AI 提问" min-width="220">
              <template #default="{ row }"><span class="question-cell">{{ row.prompt_question || `提问 #${row.prompt_id}` }}</span></template>
            </el-table-column>
            <el-table-column label="GEO 状态" width="155">
              <template #default="{ row }"><span class="geo-state" :class="`is-${geoState(row).tone}`"><b>{{ geoState(row).label }}</b><small>{{ geoState(row).detail }}</small></span></template>
            </el-table-column>
            <el-table-column label="发布状态" width="105">
              <template #default="{ row }">
                <el-tag size="small" :type="statusTagType(row.status)" effect="light">
                  {{ taskStatusLabel(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="信源" min-width="120">
              <template #default="{ row }">{{ pubsText(row) }}</template>
            </el-table-column>
            <el-table-column label="下一步" min-width="180">
              <template #default="{ row }">
                <strong class="next-action">{{ taskNextWork(row).action }}</strong>
                <small v-if="taskNextWork(row).retest">发布后复测引用效果</small>
                <el-button v-if="taskNextWork(row).retest" link type="primary" @click="router.push(geoSnapshotLink({ prompt_id: row.prompt_id }))">去同题复测</el-button>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="140" fixed="right">
              <template #default="{ row }">
                <div class="task-actions">
                  <el-button type="primary" link @click="openEditor(row)">打开</el-button>
                  <el-dropdown placement="bottom-end" @command="(command) => handleRowAction(row, command)">
                    <el-button link>更多</el-button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item v-if="row.status !== 'archived'" command="evidence">建立指标验收任务</el-dropdown-item>
                        <el-dropdown-item command="distribution">分发记录</el-dropdown-item>
                        <el-dropdown-item command="citations">引用回流</el-dropdown-item>
                        <el-dropdown-item v-if="row.status !== 'archived'" command="archive" divided>归档</el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </div>
              </template>
            </el-table-column>
          </el-table>
          <div class="geo-pager">
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
        </div>
      </div>

      <el-dialog v-model="createOpen" title="创建 GEO 文章" width="520px" class="geo-form-dialog">
        <el-form label-width="108px" class="geo-dialog-form">
          <el-form-item label="创建方式">
            <el-radio-group v-model="createMode">
              <el-radio label="prompt">从目标提问创建</el-radio>
              <el-radio label="import">导入已有文章</el-radio>
            </el-radio-group>
          </el-form-item>
          <template v-if="createMode === 'prompt'">
            <el-form-item label="目标提问" required>
              <el-select v-model="form.prompt_id" filterable style="width: 100%" placeholder="选择目标提问">
                <el-option
                  v-for="p in prompts"
                  :key="p.id"
                  :label="`#${p.id} ${p.question}`"
                  :value="p.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="标题">
              <el-input v-model="form.title" placeholder="默认用提问原文" />
            </el-form-item>
          </template>
        </el-form>
        <template #footer>
          <el-button @click="createOpen = false">取消</el-button>
          <el-button type="primary" :loading="creating" @click="submitCreate">
            {{ createMode === 'import' ? '去导入' : '创建' }}
          </el-button>
        </template>
      </el-dialog>
    </div>
  </GeoWorkbenchPage>
</template>

<style scoped>
.title-cell { font-weight: 650; color: #0f172a; }
.sub { font-size: 12px; color: #94a3b8; margin-top: 3px; }
.mb { margin-bottom: 12px; }
.tasks-workspace { --ink: #202533; --muted: #7d8494; --line: #e8eaf0; --violet: #6d43df; }
.status-strip { display:flex; align-items:center; justify-content:space-between; gap:20px; padding:14px 2px 16px; border-bottom:1px solid var(--line); margin-bottom:18px; }
.status-summary { display:flex; align-items:baseline; gap:22px; }
.status-summary-item { display:inline-flex; align-items:baseline; gap:6px; color:var(--muted); font-size:12px; }
.status-summary-item b { color:var(--ink); font-size:19px; font-weight:700; letter-spacing:-.03em; }
.status-summary-item.is-violet b { color:var(--violet); }.status-summary-item.is-amber b { color:#b7791f; }.status-summary-item.is-green b { color:#26866b; }
.status-note { color:var(--muted); font-size:12px; }
.principle-line { display:flex; align-items:center; flex-wrap:wrap; gap:9px; padding:12px 14px; border:1px solid var(--line); border-radius:10px; background:#fbfbfd; color:#697181; font-size:12px; margin-bottom:22px; }
.principle-label { color:var(--ink); font-weight:700; margin-right:4px; }.principle-line i { color:#b8bdc8; font-style:normal; }.text-action { margin-left:auto; border:0; background:none; color:var(--violet); font-size:12px; font-weight:650; cursor:pointer; }
.eyebrow { display:block; color:#a1a7b3; font-size:10px; font-weight:800; letter-spacing:.14em; margin-bottom:3px; }.workbench-bar h3 { margin:0; color:var(--ink); font-size:18px; }
.workbench-bar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.workbench-bar > div:first-child { margin-right:8px; }
.geo-filter {
  border: 1px solid #e7e9ef;
  background: #fff;
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
}
.geo-filter.active { background: #eef0ff; border-color: #c9ccf5; color: #4338ca; font-weight: 700; }
.gd-search { margin-left: auto; min-width: 220px; }
.task-table { width: 100%; }
.question-cell { display:block; max-width:300px; color:#414858; line-height:1.45; }
.geo-state { display:flex; flex-direction:column; gap:3px; }.geo-state b { font-size:12px; font-weight:700; }.geo-state small { color:var(--muted); font-size:11px; }.geo-state.is-green b { color:#25866b; }.geo-state.is-violet b { color:var(--violet); }.geo-state.is-muted b { color:#89909d; }
.next-action { display:block; max-width:165px; color:#343a48; font-size:12px; line-height:1.4; }.task-table :deep(.el-table__cell) { padding:14px 0; }.task-table :deep(.cell) { padding-left:12px; padding-right:12px; }
.task-actions { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
.geo-pager { display: flex; justify-content: flex-end; padding: 12px 14px; }
@media (max-width: 900px) {
  .geo-intro { grid-template-columns: 1fr; }
  .geo-flow { border-top: 1px solid #33434e; border-left: 0; }
  .gd-search { margin-left: 0; width: 100%; }
}
</style>
