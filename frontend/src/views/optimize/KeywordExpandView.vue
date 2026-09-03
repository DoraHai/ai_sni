<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  batchAddNegative,
  batchSetCategory,
  batchSetPreset,
  batchSetStatus,
  candidatesExportUrl,
  evaluateCandidates,
  fetchCandidates,
  sampleCandidates,
  syncExpansion,
  syncUrlWords,
  updateCandidateStatus,
} from '../../api/expansion'
import { fetchAdgroupList } from '../../api/keywords'
import AddToPlanDialog from '../../components/AddToPlanDialog.vue'
import { session } from '../../store/session'
import { formatLocalDate, formatUtcTimestamp } from '../../utils/dateTime'

const TENANT_ID = computed(() => session.tenantId) // 当前客户，顶栏切换器驱动

const loading = ref(false)
const syncing = ref(false)
const exporting = ref(false)
const evaluating = ref(false)
const error = ref('')
const data = ref(null)

// 4 源卡（原型 03-optimize/01-keyword-expand），二期已全部启用（2026-06-12）
const SOURCES = [
  { code: 'planner', name: '百度关键词规划师', icon: '🔍', cls: 'src-c-planner', desc: '种子词拓展 + 账户主动推荐，含官方搜索量与竞争度', enabled: true },
  { code: 'query', name: '搜索词转拓词', icon: '📝', cls: 'src-c-query', desc: '搜索词报告中已触发但未添加的高价值搜索词', enabled: true },
  { code: 'url', name: 'URL 爬取', icon: '🌐', cls: 'src-c-url', desc: '输入官网或产品页 URL，自研提词 + 百度流量回查', enabled: true },
  { code: 'cold', name: '冷门词识别', icon: '❄', cls: 'src-c-cold', desc: '低搜索量高意图 / 低展现有点击，自动识别归入', enabled: true },
]
const MATCH_MODE_LABELS = { exact: '精确', phrase: '短语', smart: '智能匹配' }

const filters = reactive({
  source: '',
  status: 'pending',
  suggestedCategory: '',
  minScore: null,
  q: '',
  aiRelevance: '',
  page: 1,
  pageSize: 20,
})
const sortBy = ref('potential_score')
const sortOrder = ref('desc')
const selection = ref([])
const addToPlanDialogRef = ref(null)

const syncForm = reactive({ seeds: '', queryDays: 30, smallBatch: true, limit: 20 })
const evaluationLimit = computed(() => Math.min(syncForm.limit, 5))
const evaluationResult = ref('')
const evaluationRound = ref(null)
const operationBusy = computed(() => syncing.value || evaluating.value || crawling.value)

function validBatchLimit() {
  if (Number.isInteger(syncForm.limit) && syncForm.limit >= 1 && syncForm.limit <= 20) return true
  ElMessage.warning('每批上限必须为 1–20 的整数')
  return false
}
const urlForm = reactive({ urls: '' })
const crawling = ref(false)

let loadVersion = 0
async function load() {
  const version = ++loadVersion
  const tenantId = TENANT_ID.value
  loading.value = true
  error.value = ''
  try {
    const result = await fetchCandidates({
      tenantId,
      ...filters,
      sortBy: sortBy.value,
      order: sortOrder.value,
    })
    if (version !== loadVersion || tenantId !== TENANT_ID.value) return
    data.value = result
    selection.value = []
  } catch (e) {
    if (version === loadVersion && tenantId === TENANT_ID.value) error.value = e.message
  } finally {
    if (version === loadVersion && tenantId === TENANT_ID.value) loading.value = false
  }
}

watch(
  () => [filters.source, filters.status, filters.suggestedCategory, filters.minScore, filters.aiRelevance],
  () => { filters.page = 1; load() },
)
let qTimer = null
watch(() => filters.q, () => {
  clearTimeout(qTimer)
  qTimer = setTimeout(() => { filters.page = 1; load() }, 400)
})
watch(() => [filters.page, filters.pageSize], load)

function onSelectionChange(rows) {
  selection.value = rows
}

function onSortChange({ prop, order }) {
  sortBy.value = prop || 'potential_score'
  sortOrder.value = order === 'ascending' ? 'asc' : 'desc'
  filters.page = 1
  load()
}

function toggleSource(s) {
  if (!s.enabled) return
  filters.source = filters.source === s.code ? '' : s.code
}

async function runSync() {
  if (operationBusy.value) return
  if (syncForm.smallBatch && !validBatchLimit()) return
  const tenantId = TENANT_ID.value
  const seed = syncForm.seeds.trim()
  if (syncForm.smallBatch && (!seed || /[,，\n\r]/.test(seed))) {
    ElMessage.warning('小批量拉取请填写一个种子词')
    return
  }
  if (!syncForm.smallBatch) {
    try {
      await ElMessageBox.confirm('多源拉取不受小批量上限控制，并自动评估未评候选；确认继续？', '确认多源拉取', { type: 'warning' })
    } catch { return }
    if (tenantId !== TENANT_ID.value || operationBusy.value) return
  }
  syncing.value = true
  try {
    if (syncForm.smallBatch) {
      const resp = await sampleCandidates({ tenantId, seed, limit: syncForm.limit })
      if (tenantId !== TENANT_ID.value) return
      ElMessage.success(`小批量拉取完成：${resp.candidates_written} 条候选已更新；未调用 AI、未加入计划`)
      evaluationResult.value = ''
      await load()
      return
    }
    const resp = await syncExpansion({
      tenantId,
      seeds: syncForm.seeds.split(/[,，\n]/).map((s) => s.trim()).filter(Boolean).join(','),
      queryDays: syncForm.queryDays,
    })
    if (tenantId !== TENANT_ID.value) return
    if (resp.status === 'error') throw new Error(resp.message)
    ElMessage.success(`拉取完成：规划师 ${resp.planner_candidates} 条 / 搜索词 ${resp.query_candidates} 条（种子词 ${resp.seeds.length} 个）`)
    load()
  } catch (e) {
    if (tenantId === TENANT_ID.value) ElMessage.error('拉取失败：' + e.message)
  } finally {
    syncing.value = false
  }
}

async function runUrlCrawl() {
  if (operationBusy.value) return
  const urls = urlForm.urls.split(/[\n,，\s]+/).map((s) => s.trim()).filter(Boolean)
  if (!urls.length) {
    ElMessage.warning('请先输入至少 1 个 URL')
    return
  }
  if (urls.length > 5) {
    ElMessage.warning('最多 5 个 URL')
    return
  }
  crawling.value = true
  try {
    const resp = await syncUrlWords({ tenantId: TENANT_ID.value, urls })
    if (resp.status === 'error') throw new Error(resp.message)
    const failed = resp.urls.filter((u) => u.error)
    let msg = `爬取完成：入库 ${resp.candidates_written} 个候选`
    if (failed.length) msg += `；${failed.length} 个 URL 失败`
    failed.length ? ElMessage.warning(msg) : ElMessage.success(msg)
    failed.forEach((u) => ElMessage.error(`${u.url}：${u.error}`))
    load()
  } catch (e) {
    ElMessage.error('爬取失败：' + e.message)
  } finally {
    crawling.value = false
  }
}

async function runEvaluate(force = false, action = 'start') {
  if (operationBusy.value) return
  if (!validBatchLimit()) return
  const tenantId = TENANT_ID.value
  const round = evaluationRound.value
  const limit = evaluationLimit.value
  if (action !== 'start' && !round) return
  if (action === 'next' && round.nextAfterId == null) return
  if (action === 'retry' && !round.failedIds.length) return
  if (action !== 'start') force = round.force
  if (action === 'start' && (force || round?.nextAfterId != null || round?.failedIds.length)) {
    try {
      await ElMessageBox.confirm(`从头开始${force ? '重评（含旧结果）' : '评估'}，每批最多 ${limit} 词；当前批次进度将重置，旧评估结果保留。不会自动继续或采纳。继续？`, '开始新一轮评估')
    } catch { return }
    if (tenantId !== TENANT_ID.value || operationBusy.value) return
  }
  const retryIds = action === 'retry' ? round.failedIds.slice(0, limit) : undefined
  const afterId = action === 'next' ? round.nextAfterId : 0
  evaluating.value = true
  evaluationResult.value = ''
  try {
    const resp = await evaluateCandidates({ tenantId, force, limit, afterId, retryIds })
    if (tenantId !== TENANT_ID.value) return
    if (resp.enabled === false) {
      ElMessage.warning('未配置 DeepSeek，AI 评估不可用')
    } else {
      const previousFailures = action === 'start' ? [] : round.failedIds.filter(id => !retryIds?.includes(id))
      evaluationRound.value = {
        force,
        failedIds: [...new Set([...previousFailures, ...(resp.failed_candidate_ids || [])])],
        nextAfterId: action === 'retry' ? round.nextAfterId : resp.next_after_id ?? null,
        deferred: action === 'retry' ? round.deferred : resp.deferred ?? 0,
      }
      const progress = evaluationRound.value
      evaluationResult.value = `本次成功 ${resp.successful_words ?? 0} 个去重词 / ${resp.evaluated} 行；失败或缺失 ${resp.failed_words ?? 0} 词。本轮未尝试剩余 ${progress.deferred} 词，待重试 ${progress.failedIds.length} 词。${progress.nextAfterId == null ? '已到本轮末尾。' : '可继续下一批。'}不会自动继续；刷新或切换客户会重置进度。`
      if (resp.failed_batches || resp.failed_words) ElMessage.warning('部分词未评估成功，旧结果保留，可稍后重试')
      else ElMessage.success(resp.evaluated ? '小批量 AI 评估完成，建议未采纳' : '没有需要评估的候选')
    }
    load()
  } catch (e) {
    if (tenantId === TENANT_ID.value) ElMessage.error('AI 评估失败：' + e.message)
  } finally {
    evaluating.value = false
  }
}

async function setStatus(row, status, label) {
  try {
    await updateCandidateStatus({ tenantId: TENANT_ID.value, candidateId: row.id, status })
    ElMessage.success(`「${row.word}」${label}`)
    load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

const selectedIds = computed(() => selection.value.map((row) => row.id))

const presetDialogVisible = ref(false)
const presetForm = ref({ price: null, matchMode: null })

function openPresetDialog() {
  if (!selection.value.length) return
  presetForm.value = { price: null, matchMode: null }
  presetDialogVisible.value = true
}

function editSinglePreset(row) {
  presetForm.value = { price: row.preset_price, matchMode: row.preset_match_mode }
  selection.value = [row]
  presetDialogVisible.value = true
}

async function submitPreset() {
  if (!selectedIds.value.length) return
  try {
    await batchSetPreset({
      tenantId: TENANT_ID.value,
      candidateIds: selectedIds.value,
      presetPrice: presetForm.value.price,
      presetMatchMode: presetForm.value.matchMode,
    })
    ElMessage.success('预设值已更新')
    presetDialogVisible.value = false
    load()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  }
}

async function batchMarkCore() {
  if (!selectedIds.value.length) return
  try {
    await ElMessageBox.confirm(`确认把 ${selectedIds.value.length} 个候选词标记为核心关键词（重点词）？`, '确认', { type: 'warning' })
    await batchSetCategory({ tenantId: TENANT_ID.value, candidateIds: selectedIds.value, category: 'focus' })
    ElMessage.success('已标记为重点词')
    load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e.response?.data?.detail || e.message)
  }
}

async function batchMarkProcessed() {
  if (!selectedIds.value.length) return
  try {
    await ElMessageBox.confirm(`确认将 ${selectedIds.value.length} 个候选词标记为已处理？`, '确认', { type: 'warning' })
    await batchSetStatus({ tenantId: TENANT_ID.value, candidateIds: selectedIds.value, status: 'ignored' })
    ElMessage.success('已标记已处理')
    load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e.response?.data?.detail || e.message)
  }
}

const negativeDialogVisible = ref(false)
const negativeForm = ref({ adgroupId: null, matchMode: 'phrase' })
const adgroupOptions = ref([])

async function openNegativeDialog() {
  if (!selection.value.length) return
  negativeForm.value = { adgroupId: null, matchMode: 'phrase' }
  negativeDialogVisible.value = true
  if (!adgroupOptions.value.length) {
    try {
      adgroupOptions.value = (await fetchAdgroupList({ tenantId: TENANT_ID.value })).adgroups || []
    } catch (e) {
      ElMessage.error('加载单元失败：' + (e.message || ''))
    }
  }
}

async function submitNegative() {
  if (!negativeForm.value.adgroupId) {
    ElMessage.warning('请选择目标单元')
    return
  }
  try {
    const res = await batchAddNegative({
      tenantId: TENANT_ID.value,
      candidateIds: selectedIds.value,
      adgroupId: negativeForm.value.adgroupId,
      matchMode: negativeForm.value.matchMode,
    })
    const failCount = (res.results || []).filter((r) => r.status === 'failed').length
    const dryRunCount = (res.results || []).filter((r) => r.status === 'dry_run').length
    if (failCount) {
      ElMessage.warning(`已处理，其中 ${failCount} 个失败${dryRunCount ? `，${dryRunCount} 个仅记入演练台账` : ''}`)
    } else if (dryRunCount) {
      ElMessage.warning(`演练模式：${dryRunCount} 个候选已记入台账，未修改百度账户`)
    } else {
      ElMessage.success('批量加否词成功')
    }
    negativeDialogVisible.value = false
    load()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  }
}

async function openAddToPlan(row) {
  addToPlanDialogRef.value?.open(row)
}

async function exportCsv() {
  exporting.value = true
  try {
    const resp = await fetch(candidatesExportUrl({ tenantId: TENANT_ID.value, ...filters }), {
      headers: session.token
        ? { Authorization: `Bearer ${session.token}` }
        : { 'X-API-Key': import.meta.env.VITE_API_KEY || '' },
    })
    if (!resp.ok) throw new Error('导出失败 HTTP ' + resp.status)
    const blob = await resp.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `expansion_${formatLocalDate()}.csv`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    exporting.value = false
  }
}

const fmtInt = (v) => (v == null ? '—' : Number(v).toLocaleString('zh-CN'))
const fmtMoney = (v) => (v == null ? '—' : '¥ ' + Number(v).toFixed(2))
const fmtTime = (v) => formatUtcTimestamp(v, { short: true })

const pendingCount = (code) => data.value?.source_pending_counts?.[code] ?? 0
const catClass = computed(() => ({
  brand: 'cat-brand', focus: 'cat-focus', normal: 'cat-normal',
  longtail: 'cat-longtail', observe: 'cat-observe', negative: 'cat-negative',
}))

// AI 相关性徽章配色
const aiRelClass = { relevant: 'ai-relevant', generic: 'ai-generic', irrelevant: 'ai-irrelevant' }
const aiEnabled = computed(() => data.value?.ai_enabled === true)
const aiUnevaluated = computed(() => data.value?.ai_unevaluated ?? 0)
const aiRelCount = (code) => data.value?.ai_relevance_counts?.[code] ?? 0

// 顶栏切换客户后重新拉数
watch(TENANT_ID, () => {
  data.value = null
  selection.value = []
  filters.page = 1
  syncForm.seeds = ''
  syncForm.smallBatch = true
  syncForm.limit = 20
  evaluationResult.value = ''
  evaluationRound.value = null
  load()
})

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <div class="page-header">
      <div>
        <div class="page-title">拓词</div>
        <div class="page-desc">
          4 源聚合候选关键词 ·「加入计划」写回受客户、推广账户和动作门禁保护并记台账
          <template v-if="data?.last_synced_at"> · 同步于 {{ fmtTime(data.last_synced_at) }}</template>
          <template v-if="aiEnabled && data?.last_ai_eval_at"> · AI 评估于 {{ fmtTime(data.last_ai_eval_at) }}</template>
        </div>
      </div>
      <div class="page-actions">
        <label v-if="session.canEdit('optimize.expand')">每批上限
          <el-input-number v-model="syncForm.limit" :min="1" :max="20" :precision="0" :disabled="operationBusy" aria-label="每批去重词上限" />
        </label>
        <el-button :loading="exporting" @click="exportCsv">导出 CSV</el-button>
        <el-dropdown
          v-if="session.canEdit('optimize.expand') && aiEnabled"
          split-button
          type="primary"
          :loading="evaluating"
          :disabled="operationBusy"
          @click="runEvaluate(false)"
        >
          {{ evaluating ? 'AI 研判中…' : `小批量 AI 评估（最多 ${evaluationLimit} 词）` }}
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item :disabled="operationBusy" @click="runEvaluate(true)">新一轮小批量重评（含旧结果）</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-button v-if="session.canEdit('optimize.expand') && aiEnabled && evaluationRound?.nextAfterId != null" :disabled="operationBusy" @click="runEvaluate(false, 'next')">继续下一批</el-button>
        <el-button v-if="session.canEdit('optimize.expand') && aiEnabled && evaluationRound?.failedIds.length" :disabled="operationBusy" @click="runEvaluate(false, 'retry')">重试失败词（{{ evaluationRound.failedIds.length }}）</el-button>
        <el-tooltip content="批量加入计划需统一指定目标单元，暂未支持，请逐条「加入计划」" placement="top">
          <span><el-button type="primary" disabled>批量加入计划</el-button></span>
        </el-tooltip>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" style="margin-bottom: 14px" />
    <el-alert v-if="evaluationResult" :title="evaluationResult" type="info" :closable="false" style="margin-bottom: 14px" />
    <div v-if="aiEnabled" class="sync-hint">当前客户待评 {{ aiUnevaluated }} 行；AI 每次最多 5 词、一次模型请求，超时不自动重试；候选拉取仍按每批上限。评估按词去重，上限不受列表筛选或勾选影响，不自动采纳。</div>
    <el-alert
      v-if="aiEnabled && ((data?.ai_freshness_counts?.stale || 0) + (data?.ai_freshness_counts?.unverified || 0) > 0)"
      type="warning" :closable="false" show-icon
      title="部分 AI 结论需要重新核验"
      :description="`画像或评估规则已变更 ${data?.ai_freshness_counts?.stale || 0} 条；历史结果未核验 ${data?.ai_freshness_counts?.unverified || 0} 条。旧结论仍保留并参与当前筛选，但不作为默认 AI 出价依据。普通评估会跳过旧结果；请通过下拉菜单手动开启新一轮小批量重评（含旧结果），每次最多 5 词，不自动继续或采纳。`"
    />

    <!-- 4 源卡 -->
    <div class="source-tabs">
      <div
        v-for="s in SOURCES"
        :key="s.code"
        class="src-card"
        :class="{ active: filters.source === s.code, disabled: !s.enabled }"
        @click="toggleSource(s)"
      >
        <div class="src-icon" :class="s.cls">{{ s.icon }}</div>
        <div class="src-name">{{ s.name }}</div>
        <div class="src-desc">{{ s.desc }}</div>
        <span v-if="s.enabled" class="src-count">{{ fmtInt(pendingCount(s.code)) }} 待处理</span>
        <span v-else class="src-count dim-badge">二期</span>
      </div>
    </div>

    <!-- URL 爬取面板（选中 URL 爬取源时显示） -->
    <div v-if="session.canEdit('optimize.expand') && filters.source === 'url'" class="sync-panel url-panel">
      <span class="sync-label">URL 列表</span>
      <el-input
        v-model="urlForm.urls"
        type="textarea"
        :rows="3"
        placeholder="每行一个 URL，最多 5 个，示例：&#10;https://www.sulzer.com/zh-cn/products/pumps"
        style="flex: 1; max-width: 620px"
      />
      <el-button type="primary" :loading="crawling" :disabled="operationBusy" @click="runUrlCrawl">
        {{ crawling ? '爬取中（约 20-60 秒）' : '开始爬取' }}
      </el-button>
      <span class="sync-hint">仅爬页面文本 · 单 URL 最多 30 个候选 · 自动回查百度搜索量</span>
    </div>

    <!-- 拉取面板 -->
    <div v-else-if="session.canEdit('optimize.expand')" class="sync-panel">
      <el-switch v-model="syncForm.smallBatch" active-text="小批量（仅规划师）" :disabled="operationBusy" />
      <span class="sync-label">种子词</span>
      <el-input
        v-model="syncForm.seeds"
        :placeholder="syncForm.smallBatch ? '填写一个种子词，例如：粉末涂料' : '逗号分隔，最多 20 个；留空自动选种子词'"
        :disabled="operationBusy"
        clearable
        style="flex: 1; max-width: 520px"
      />
      <span v-if="!syncForm.smallBatch" class="sync-label">搜索词回看</span>
      <el-select v-if="!syncForm.smallBatch" v-model="syncForm.queryDays" style="width: 110px" :disabled="operationBusy">
        <el-option label="近 30 天" :value="30" />
        <el-option label="近 60 天" :value="60" />
        <el-option label="近 91 天" :value="91" />
      </el-select>
      <el-button type="primary" :loading="syncing" :disabled="operationBusy" @click="runSync">
        {{ syncing ? '拉取中（约 10-30 秒）' : (syncForm.smallBatch ? '小批量拉取候选' : '多源拉取（非小批量）') }}
      </el-button>
      <span v-if="syncForm.smallBatch" class="sync-hint">最多更新 {{ syncForm.limit }} 个候选，不自动评估；已有候选不保证新增，未返回数量未知。</span>
    </div>

    <!-- 筛选行 -->
    <div class="filter-row">
      <el-select v-model="filters.status" style="width: 130px">
        <el-option label="待处理" value="pending" />
        <el-option label="已采纳" value="adopted" />
        <el-option label="已忽略" value="ignored" />
        <el-option label="全部状态" value="" />
      </el-select>
      <el-select v-model="filters.suggestedCategory" placeholder="建议分类 · 全部" clearable style="width: 150px">
        <el-option
          v-for="o in data?.category_options || []"
          :key="o.code"
          :label="o.label"
          :value="o.code"
        />
      </el-select>
      <el-select v-model="filters.minScore" placeholder="潜力分 · 全部" clearable style="width: 130px">
        <el-option label="高（≥ 8）" :value="8" />
        <el-option label="中（≥ 5）" :value="5" />
        <el-option label="≥ 3" :value="3" />
      </el-select>
      <el-select
        v-if="aiEnabled"
        v-model="filters.aiRelevance"
        placeholder="AI 相关性 · 全部"
        clearable
        style="width: 170px"
      >
        <el-option
          v-for="o in data?.ai_relevance_options || []"
          :key="o.code"
          :value="o.code"
        >
          {{ o.label }}（{{ fmtInt(aiRelCount(o.code)) }}）
        </el-option>
      </el-select>
      <el-button
        v-if="aiEnabled"
        :type="filters.aiRelevance === 'relevant' ? 'primary' : 'default'"
        text
        @click="filters.aiRelevance = filters.aiRelevance === 'relevant' ? '' : 'relevant'"
      >
        {{ filters.aiRelevance === 'relevant' ? '✓ 已隐藏通用噪音' : '隐藏通用噪音' }}
      </el-button>
      <el-input v-model="filters.q" placeholder="搜索候选词" clearable style="width: 200px" />
    </div>

    <!-- 候选表 -->
    <div class="table-panel">
      <div class="bulk-toolbar" :class="{ active: selection.length }">
        <span class="bt-count">
          已选 <b>{{ selection.length }}</b> 个
          <span v-if="!selection.length" class="bt-hint">· 勾选候选词以启用批量操作</span>
        </span>
        <div class="bt-actions">
          <button class="bt-btn" :disabled="!selection.length" @click="openPresetDialog">
            设置预设出价/匹配 ▾
          </button>
          <button class="bt-btn bt-primary" :disabled="!selection.length" @click="batchMarkCore">
            圈选为核心关键词
          </button>
          <button class="bt-btn" :disabled="!selection.length" @click="batchMarkProcessed">
            标记已处理
          </button>
          <button class="bt-btn" :disabled="!selection.length" @click="openNegativeDialog">
            批量加否词
          </button>
        </div>
      </div>
      <el-table
        :data="data?.candidates || []"
        class="kw-table"
        row-key="id"
        :fit="true"
        @selection-change="onSelectionChange"
        @sort-change="onSortChange"
      >
        <el-table-column type="selection" width="44" />
        <el-table-column label="候选关键词" width="176">
          <template #default="{ row }">
            <div class="kw-cell-name">{{ row.word }}</div>
            <div class="kw-cell-sub">
              <template v-if="row.matched_keyword">触发词：{{ row.matched_keyword }}</template>
              <template v-else-if="row.seed_word && row.seed_word.startsWith('http')">来源页面：{{ row.seed_word }}</template>
              <template v-else-if="row.seed_word">种子词：{{ row.seed_word }}</template>
              <template v-else-if="row.source === 'planner'">账户主动推荐</template>
              <span v-if="row.show_reasons.length" class="candidate-reason" :title="row.show_reasons.join(' / ')"> · {{ row.show_reasons[0] }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="74">
          <template #default="{ row }">
            <span class="source-tag" :class="'tag-' + row.source">{{ row.source_label }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="monthly_pv" label="月搜索量" width="82" align="right" sortable="custom">
          <template #default="{ row }">
            <span class="num">{{ fmtInt(row.monthly_pv) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="recommend_price_pc" label="指导价 PC/移动" width="105" align="right" sortable="custom">
          <template #default="{ row }">
            <span class="num">{{ fmtMoney(row.recommend_price_pc) }}<template v-if="row.recommend_price_mobile != null"> / {{ Number(row.recommend_price_mobile).toFixed(2) }}</template></span>
          </template>
        </el-table-column>
        <el-table-column prop="impression" label="窗口展现/点击" width="100" align="right" sortable="custom">
          <template #default="{ row }">
            <span class="num" v-if="row.impression != null">{{ fmtInt(row.impression) }} / {{ fmtInt(row.click) }}</span>
            <span v-else class="dim">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="potential_score" label="潜力分" width="78" sortable="custom">
          <template #default="{ row }">
            <span class="heat-bar"><span class="heat-fill" :style="{ width: (row.potential_score ?? 0) * 10 + '%' }" /></span>
            <span class="num">{{ row.potential_score ?? '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="建议分类" width="80">
          <template #default="{ row }">
            <span v-if="row.suggested_category" class="cat-pill" :class="catClass[row.suggested_category]">
              {{ row.suggested_category_label }}
            </span>
            <span v-else class="dim">—</span>
          </template>
        </el-table-column>
        <el-table-column label="预设" width="104">
          <template #default="{ row }">
            <div class="preset-cell">
              <span v-if="row.preset_price || row.preset_match_mode" class="preset-tag">
                ¥{{ row.preset_price ?? '-' }} / {{ MATCH_MODE_LABELS[row.preset_match_mode] || row.preset_match_mode || '-' }}
              </span>
              <span v-else class="dim">—</span>
              <el-button
                v-if="session.canEdit('optimize.expand')"
                size="small"
                text
                @click="editSinglePreset(row)"
              >
                {{ row.preset_price || row.preset_match_mode ? '编辑' : '设置' }}
              </el-button>
            </div>
          </template>
        </el-table-column>
        <el-table-column v-if="aiEnabled" label="AI 研判" width="150">
          <template #default="{ row }">
            <template v-if="row.ai_relevance">
              <span v-if="row.ai_freshness && row.ai_freshness !== 'current'" class="dim">{{ row.ai_freshness_label }} · 旧结论</span>
              <el-tooltip :content="row.ai_reason || '—'" placement="top" :disabled="!row.ai_reason">
                <span class="ai-pill" :class="aiRelClass[row.ai_relevance]">
                  {{ row.ai_relevance_label }}
                </span>
              </el-tooltip>
              <span v-if="row.ai_recommend" class="ai-rec" :class="'rec-' + row.ai_recommend">
                {{ row.ai_recommend_label }}
              </span>
            </template>
            <span v-else class="dim">未评估</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="150" class-name="action-column">
          <template #default="{ row }">
            <div class="row-actions">
              <template v-if="session.canEdit('optimize.expand') && row.status === 'pending'">
                <el-tooltip content="选目标单元 + 匹配 + 出价，加成正式关键词写回百度（dry-run 保护）" placement="top">
                  <el-button class="row-action-primary" size="small" type="primary" @click="openAddToPlan(row)">加入计划</el-button>
                </el-tooltip>
                <el-button class="row-action-secondary" size="small" @click="setStatus(row, 'ignored', '已忽略')">忽略</el-button>
              </template>
              <template v-else>
                <span class="status-mark" :class="row.status">{{ row.status_label }}</span>
                <el-button v-if="session.canEdit('optimize.expand')" size="small" text @click="setStatus(row, 'pending', '已恢复待处理')">恢复</el-button>
              </template>
            </div>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-line">暂无候选词。点上方「拉取最新候选」从百度规划师 + 搜索词报告聚合。</div>
        </template>
      </el-table>
      <div class="table-footer">
        <span>共 {{ fmtInt(data?.total || 0) }} 条</span>
        <el-pagination
          v-model:current-page="filters.page"
          v-model:page-size="filters.pageSize"
          :total="data?.total || 0"
          :page-sizes="[10, 20, 50, 100]"
          layout="sizes, prev, pager, next, jumper"
          background
          small
        />
      </div>
    </div>

    <div class="note">
      <b>说明</b>：潜力分由搜索量/真实触发流量、竞争度、特色标签综合估算（启发式 v1）；建议分类仅供参考，
      加入计划后请在关键词工作台完成最终 5 类分级。月搜索量与指导价来自百度规划师；窗口展现/点击来自搜索词报告（已触发未添加）。
      <template v-if="aiEnabled"><br><b>AI 研判</b>：DeepSeek 对候选词做语义相关性判断（业务相关/通用噪音/不相关），
      帮你快速筛掉"设备""中心"、地名等通用词噪音；仅作参考，不影响潜力分排序。小批量拉取不自动评估；AI 评估每次最多 20 个去重词，不自动继续。多源拉取保留原有自动评估行为，不属于小批量验收。</template>
    </div>

    <AddToPlanDialog ref="addToPlanDialogRef" :tenant-id="TENANT_ID" @success="load" />

    <el-dialog v-model="presetDialogVisible" title="设置预设出价/匹配方式" width="400px">
      <div class="preset-form">
        <label>预设出价（元）</label>
        <el-input-number
          v-model="presetForm.price"
          :min="0"
          :precision="2"
          placeholder="不填则不更新"
          style="width: 100%"
        />
        <label>预设匹配方式</label>
        <el-select v-model="presetForm.matchMode" placeholder="不选则不更新" clearable style="width: 100%">
          <el-option label="精确" value="exact" />
          <el-option label="短语" value="phrase" />
          <el-option label="智能匹配" value="smart" />
        </el-select>
      </div>
      <template #footer>
        <el-button @click="presetDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitPreset">确认</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="negativeDialogVisible" title="批量加否词" width="420px">
      <div class="negative-form">
        <p>将把选中的 {{ selection.length }} 个候选词，添加为以下单元的否词：</p>
        <label>目标单元</label>
        <el-select v-model="negativeForm.adgroupId" filterable placeholder="选择单元" style="width: 100%">
          <el-option
            v-for="adg in adgroupOptions"
            :key="adg.adgroup_id"
            :label="adg.adgroup_name"
            :value="adg.adgroup_id"
          />
        </el-select>
        <label>否词匹配方式</label>
        <el-select v-model="negativeForm.matchMode" style="width: 100%">
          <el-option label="精确否" value="exact" />
          <el-option label="短语否" value="phrase" />
        </el-select>
      </div>
      <template #footer>
        <el-button @click="negativeDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitNegative">确认添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-header { margin-bottom: 14px; display: flex; justify-content: space-between; align-items: flex-end; }
.page-title { font-size: 20px; font-weight: 600; color: var(--sem-text); }
.page-desc { font-size: 12px; color: var(--sem-text-sub); margin-top: 4px; }
.page-actions { display: flex; gap: 8px; }

.source-tabs { display: flex; gap: 12px; margin-bottom: 14px; }
.src-card { flex: 1; background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; padding: 14px 16px; cursor: pointer; transition: all 0.15s; position: relative; }
.src-card:hover { border-color: var(--sem-primary); box-shadow: 0 2px 8px rgba(24, 95, 165, 0.06); }
.src-card.active { border-color: var(--sem-primary); background: linear-gradient(135deg, #f4f8fd 0%, #fafbfc 100%); box-shadow: 0 4px 12px rgba(24, 95, 165, 0.1); }
.src-card.disabled { opacity: 0.55; cursor: not-allowed; }
.src-card.disabled:hover { border-color: var(--sem-border); box-shadow: none; }
.src-icon { width: 34px; height: 34px; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 17px; color: #fff; margin-bottom: 8px; }
.src-c-url { background: linear-gradient(135deg, #185fa5 0%, #2c7cc8 100%); }
.src-c-planner { background: linear-gradient(135deg, #ba7517 0%, #dc9a47 100%); }
.src-c-query { background: linear-gradient(135deg, #1d9e75 0%, #4dbe99 100%); }
.src-c-cold { background: linear-gradient(135deg, #6b47b5 0%, #9474d4 100%); }
.src-name { font-size: 13px; font-weight: 600; color: var(--sem-text); margin-bottom: 3px; }
.src-desc { font-size: 11px; color: var(--sem-text-sub); line-height: 1.5; }
.src-count { position: absolute; top: 12px; right: 12px; background: #eff4fb; color: var(--sem-primary); padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
.dim-badge { background: #f3f4f6; color: #9ca3af; }

.sync-panel { background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; padding: 12px 16px; margin-bottom: 12px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.sync-label { font-size: 12px; color: var(--sem-text-sub); flex-shrink: 0; }
.url-panel { align-items: flex-start; }
.url-panel .sync-label { padding-top: 6px; }
.sync-hint { font-size: 11px; color: #9ca3af; padding-top: 8px; }

.filter-row { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }

.table-panel { background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; overflow: hidden; }
.bulk-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--sem-border);
  background: #fafbfc;
}
.bulk-toolbar.active { background: #f4f8fd; }
.bt-count { font-size: 12px; color: var(--sem-text-sub); }
.bt-count b { color: var(--sem-primary); }
.bt-hint { color: #9ca3af; }
.bt-actions { margin-left: auto; display: flex; gap: 8px; flex-wrap: wrap; }
.bt-btn {
  padding: 5px 12px;
  border: 1px solid #dcdfe6;
  background: #fff;
  border-radius: 4px;
  color: #606266;
  cursor: pointer;
  font-size: 12px;
}
.bt-btn:hover:not(:disabled) { border-color: var(--sem-primary); color: var(--sem-primary); }
.bt-btn:disabled { opacity: .45; cursor: not-allowed; }
.bt-btn.bt-primary { background: var(--sem-primary); border-color: var(--sem-primary); color: #fff; }
.kw-cell-name { font-weight: 500; color: var(--sem-text); }
.kw-cell-sub { font-size: 11px; color: var(--sem-text-sub); margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.candidate-reason { color: #ba7517; }
.num { font-variant-numeric: tabular-nums; }
.dim { color: #c0c4cc; }

.source-tag { font-size: 11px; padding: 1px 7px; border-radius: 3px; }
.tag-planner { background: #fef1e1; color: #ba7517; }
.tag-query { background: #e5f4ed; color: #1d9e75; }
.tag-url { background: #eff4fb; color: #185fa5; }
.tag-cold { background: #f2ebfb; color: #6b47b5; }

.heat-bar { width: 40px; height: 4px; background: #f3f4f6; border-radius: 2px; overflow: hidden; display: inline-block; vertical-align: middle; margin-right: 6px; }
.heat-fill { height: 100%; display: block; background: linear-gradient(90deg, #1d9e75 0%, #185fa5 100%); }

.cat-pill { font-size: 11px; padding: 2px 8px; border-radius: 10px; }
.cat-brand { background: #eff4fb; color: #185fa5; }
.cat-focus { background: #fef1e1; color: #ba7517; }
.cat-normal { background: #f3f4f6; color: #4b5563; }
.cat-longtail { background: #e5f4ed; color: #1d9e75; }
.cat-observe { background: #f2ebfb; color: #6b47b5; }
.cat-negative { background: #fef6f6; color: #e24b4a; }

.preset-cell { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.preset-tag { font-size: 11px; padding: 2px 7px; border-radius: 4px; background: #eff4fb; color: var(--sem-primary); }

.ai-pill { font-size: 11px; padding: 2px 8px; border-radius: 10px; }
.ai-relevant { background: #e5f4ed; color: #1d9e75; }
.ai-generic { background: #fdf6e3; color: #b8860b; }
.ai-irrelevant { background: #fef6f6; color: #e24b4a; }
.ai-rec { display: block; margin-top: 3px; font-size: 10px; color: #9ca3af; }
.ai-rec.rec-adopt { color: #1d9e75; }
.ai-rec.rec-drop { color: #e24b4a; }

.reasons { font-size: 11px; color: #ba7517; }
.row-actions { display: flex; gap: 8px; align-items: center; justify-content: flex-start; white-space: nowrap; }
.row-actions :deep(.el-button) {
  min-width: 58px;
  height: 26px;
  padding: 0 10px;
  margin-left: 0;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1;
}
.row-actions :deep(.row-action-primary.el-button--primary) {
  background: #e86f1c;
  border-color: #e86f1c;
  color: #fff;
}
.row-actions :deep(.row-action-primary.el-button--primary:hover) {
  background: #d96014;
  border-color: #d96014;
  color: #fff;
}
.row-actions :deep(.row-action-secondary) {
  background: #fff;
  border-color: #dfe3e8;
  color: #344050;
}
.row-actions :deep(.row-action-secondary:hover) {
  border-color: #e86f1c;
  color: #c45f18;
}
.status-mark { font-size: 11px; padding: 2px 8px; border-radius: 10px; }
.status-mark.adopted { background: #e5f4ed; color: #1d9e75; }
.status-mark.ignored { background: #f3f4f6; color: #9ca3af; }

.table-footer { display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; font-size: 12px; color: var(--sem-text-sub); border-top: 1px solid var(--sem-border); }
.empty-line { font-size: 12px; color: var(--sem-text-sub); padding: 18px 0; }
.note { margin-top: 12px; padding: 10px 12px; background: #f4f8fd; border-radius: 6px; font-size: 11px; color: #4b5563; line-height: 1.7; }
.note b { color: var(--sem-primary); }
.preset-form, .negative-form { display: grid; gap: 10px; font-size: 13px; }
.preset-form label, .negative-form label { color: var(--sem-text-sub); font-size: 12px; }
.negative-form p { margin: 0 0 2px; color: var(--sem-text); line-height: 1.6; }
</style>
