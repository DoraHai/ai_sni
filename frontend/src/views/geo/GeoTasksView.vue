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
    sub="从零生产或导入已有内容，统一进行 GEO 检测、优化与发布"
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

      <section class="geo-intro mb">
        <div>
          <span class="kicker">Citation-ready Content</span>
          <h2>GEO 写作的核心不是“多写”，而是让事实更容易被 AI 找到、理解和引用</h2>
          <p>无论从目标问题生成新文章，还是导入已有内容，系统都会结合品牌资料、知识库与可信信源，完成 GEO 检测、内容补强和持续优化。</p>
          <div class="geo-principles">
            <span>独家信息</span><span>事实可核验</span><span>明确来源</span><span>定义 / 对比 / FAQ</span><span>不堆关键词</span>
          </div>
        </div>
        <div class="geo-flow" aria-label="GEO 内容工作流">
          <div class="geo-flow-step"><span class="geo-flow-no">1</span><b>选择文章起点</b><small>AI 新建或导入已有内容</small></div>
          <div class="geo-flow-step"><span class="geo-flow-no">2</span><b>关联目标问题</b><small>明确文章需要回答什么</small></div>
          <div class="geo-flow-step"><span class="geo-flow-no">3</span><b>GEO 检测与优化</b><small>补强结构、事实与可信信源</small></div>
          <div class="geo-flow-step"><span class="geo-flow-no">4</span><b>发布与回流</b><small>分发成稿并跟进引用表现</small></div>
        </div>
      </section>

      <div class="gd-card">
        <div class="gd-hd workbench-bar">
          <h3>内容任务</h3>
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
            <el-table-column label="目标提问" min-width="200">
              <template #default="{ row }">{{ row.prompt_question || `提问 #${row.prompt_id}` }}</template>
            </el-table-column>
            <el-table-column label="适配引擎" min-width="140">
              <template #default="{ row }">{{ enginesText(row) }}</template>
            </el-table-column>
            <el-table-column label="AI 友好度" width="110">
              <template #default="{ row }">{{ row.geo_score == null ? '—' : row.geo_score }}</template>
            </el-table-column>
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <el-tag size="small" :type="statusTagType(row.status)" effect="light">
                  {{ taskStatusLabel(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="发布信源" min-width="140">
              <template #default="{ row }">{{ pubsText(row) }}</template>
            </el-table-column>
            <el-table-column label="下一步与验收" min-width="300">
              <template #default="{ row }">
                <strong>{{ taskNextWork(row).action }}</strong>
                <p>{{ taskNextWork(row).acceptance }}</p>
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
.kicker { color: #5b5ce2; font-size: 12px; font-weight: 800; letter-spacing: .04em; }
.geo-intro {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(440px, .85fr);
  gap: 0;
  overflow: hidden;
  padding: 0;
  border: 1px solid #2d3d48;
  border-radius: 12px;
  background: #1f2b34;
}
.geo-intro > div:first-child { padding: 28px 34px; }
.kicker { color: #62d5cf; }
.geo-intro h2 { max-width: 900px; margin: 12px 0; color: #f8fafc; font-size: 22px; line-height: 1.45; }
.geo-intro p { max-width: 980px; margin: 0; color: #b7c3cc; font-size: 13px; line-height: 1.7; }
.geo-principles { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 18px; }
.geo-principles span { padding: 5px 9px; border: 1px solid #40515c; border-radius: 7px; background: #293843; color: #cbd6dd; font-size: 11px; font-weight: 650; }
.geo-flow { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); align-content: stretch; border-left: 1px solid #33434e; }
.geo-flow-step { display: grid; grid-template-columns: 30px minmax(0, 1fr); column-gap: 9px; align-content: center; padding: 20px 24px; border-bottom: 1px solid #33434e; }
.geo-flow-step:nth-child(odd) { border-right: 1px solid #33434e; }
.geo-flow-step:nth-last-child(-n + 2) { border-bottom: 0; }
.geo-flow-no { grid-row: span 2; display: grid; width: 30px; height: 30px; place-items: center; border-radius: 50%; background: #62d5cf; color: #17323a; font-size: 12px; font-weight: 850; }
.geo-flow b { display: block; color: #f8fafc; font-size: 13px; }
.geo-flow small { margin-top: 4px; color: #9cafba; font-size: 11px; line-height: 1.45; }
.workbench-bar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.workbench-bar h3 { margin-right: 8px; }
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
.task-actions { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
.geo-pager { display: flex; justify-content: flex-end; padding: 12px 14px; }
@media (max-width: 900px) {
  .geo-intro { grid-template-columns: 1fr; }
  .geo-flow { border-top: 1px solid #33434e; border-left: 0; }
  .gd-search { margin-left: 0; width: 100%; }
}
</style>
