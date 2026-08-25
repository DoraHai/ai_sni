<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createGeoAnswerSnapshot,
  extractGeoAnswerSnapshotUrls,
  listGeoAnswerSnapshots,
  listGeoPrompts,
  listGeoTrackingEngines,
  deleteGeoAnswerSnapshot,
  patchGeoAnswerSnapshot,
  probeGeoAnswerSnapshot,
  probeGeoAnswerSnapshotBatch,
  suggestGeoAnswerSnapshotFields,
  checkGeoAnswerSnapshotCitations,
  fetchGeoEvaluationInsights,
  fetchVisibilityPatrolOpsStatus,
  fetchVisibilityPatrolSettings,
  getVisibilityPatrolRun,
  listVisibilityPatrolRuns,
  putVisibilityPatrolSettings,
  startVisibilityPatrolRun,
} from '../../api/geoContent'
import GeoVisibilityNav from '../../components/GeoVisibilityNav.vue'
import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
import SampleCredibilityAlert from '../../components/SampleCredibilityAlert.vue'
import { useObservationPeriod } from '../../composables/useObservationPeriod'
import { diagnoseEmptyMonitoring } from '../../utils/geoEmptyReason'
import { useClientPager } from '../../composables/useClientPager'
import { session } from '../../store/session'
import {
  CITATION_ACCURACY_LABEL,
  CITATION_FORMAT_LABEL,
  PATROL_STATUS_LABEL,
  POSITION_LABEL,
  SENTIMENT_LABEL,
  downloadCsv,
  engineDisplay,
  fmtCaptured as fmtCapturedShared,
  fmtInt,
  labelOf,
} from '../../utils/geoReportLabels'

const route = useRoute()
const router = useRouter()
const {
  days: observationDays,
  start: obsStart,
  end: obsEnd,
  label: obsLabel,
} = useObservationPeriod()

const tenantId = computed(() =>
  session.tenantId || (import.meta.env.DEV && import.meta.env.VITE_API_KEY ? 1 : null),
)

const POSITION_OPTIONS = Object.entries(POSITION_LABEL).map(([value, label]) => ({ value, label }))
const SENTIMENT_OPTIONS = Object.entries(SENTIMENT_LABEL).map(([value, label]) => ({ value, label }))
const FORMAT_OPTIONS = Object.entries(CITATION_FORMAT_LABEL).map(([value, label]) => ({ value, label }))
const ACCURACY_OPTIONS = Object.entries(CITATION_ACCURACY_LABEL).map(([value, label]) => ({
  value,
  label,
}))

const loading = ref(false)
const probing = ref(false)
const batchProbing = ref(false)
const saving = ref(false)
const error = ref('')
const engines = ref([])
const prompts = ref([])
const snapshots = ref([])
const batchDrafts = ref([])
const snapPager = useClientPager(snapshots, { pageSize: 20 })

const filterPromptId = ref(route.query.prompt_id ? Number(route.query.prompt_id) : null)
const filterEngine = ref(route.query.engine ? String(route.query.engine) : '')
const filterDomain = ref(route.query.domain ? String(route.query.domain) : '')
const filterPatrolRunId = ref(
  route.query.patrol_run_id ? Number(route.query.patrol_run_id) : null,
)
const filterSimulated = ref(
  route.query.simulated === '1' ? true : route.query.simulated === '0' ? false : null,
)
const sampleComposition = ref(null)
const patrolOps = ref(null)
const patrolRuns = ref([])
const evalData = ref(null)
const collecting = ref(false)
const savingSchedule = ref(false)
const collectForm = ref({
  prefer_real: true,
  auto_persist: true,
  prompt_limit: 20,
  engine_keys: [],
  enabled: false,
  window_start_hour: 7,
  window_end_hour: 22,
  interval_hours: 24,
})
const intervalOptions = [
  { value: 1, label: '每 1 小时' },
  { value: 2, label: '每 2 小时' },
  { value: 3, label: '每 3 小时' },
  { value: 4, label: '每 4 小时' },
  { value: 6, label: '每 6 小时' },
  { value: 8, label: '每 8 小时' },
  { value: 12, label: '每 12 小时' },
  { value: 24, label: '每 24 小时（每天）' },
]
const queueMode = computed(() => route.query.queue === 'recheck')
const emptyReason = computed(() =>
  diagnoseEmptyMonitoring({
    engineCount: engines.value.length,
    enabledEngines: engines.value.filter((e) => e.enabled).length,
    patrolEnabled: !!patrolOps.value?.settings?.enabled,
    lastRunAt: patrolOps.value?.last_run?.created_at || patrolOps.value?.last_run?.id,
    snapshotCount: snapshots.value.length,
    mentionCount: snapshots.value.filter((s) => s.mentions_brand).length,
  }),
)

const lastRun = computed(() => patrolOps.value?.last_run || patrolRuns.value[0] || null)

const evalKpis = computed(() => {
  const total = Number(evalData.value?.total || snapshots.value.length || 0)
  const pos = evalData.value?.position_counts || {}
  const sent = evalData.value?.sentiment_counts || {}
  const mentioned = snapshots.value.filter((s) => s.mentions_brand).length
  const first = Number(pos.first || 0)
  return [
    { label: '快照样本', value: fmtInt(total), hint: obsLabel.value },
    {
      label: '首位推荐',
      value: fmtInt(first),
      hint: total ? `约占 ${Math.round((first / total) * 100)}%` : '采集后自动判断',
    },
    { label: '正面评价', value: fmtInt(sent.positive), hint: '对本品情感为正' },
    {
      label: '品牌提及',
      value: fmtInt(mentioned),
      hint: snapshots.value.length
        ? `${Math.round((mentioned / snapshots.value.length) * 100)}% 本页样本`
        : '采集后自动判断',
    },
  ]
})

function runStatusLabel(status) {
  return labelOf(PATROL_STATUS_LABEL, status, status || '—')
}

const form = ref({
  prompt_id: null,
  engine: 'deepseek',
  raw_text: '',
  captured_at: '',
  mentions_brand: false,
  brand_position: 'unknown',
  sentiment: 'unknown',
  citation_format: 'unknown',
  citation_accuracy: 'unknown',
  competitors: '',
  cited_urls: '',
  note: '',
})

const enabledEngines = computed(() => {
  const enabled = engines.value.filter((e) => e.enabled)
  return enabled.length ? enabled : engines.value
})

function snippet(text, max = 100) {
  const s = String(text || '').replace(/\s+/g, ' ').trim()
  return s.length > max ? `${s.slice(0, max)}…` : s
}

function fmtCaptured(iso) {
  const full = fmtCapturedShared(iso)
  if (full === '—' || full.length < 16) return full
  // 列表紧凑：MM-DD HH:mm
  const m = full.match(/^\d{4}-(\d{2})-(\d{2}) (\d{2}:\d{2})/)
  return m ? `${m[1]}-${m[2]} ${m[3]}` : full
}

function exportSnapshots() {
  const rows = snapshots.value.map((r) => [
    r.id,
    r.prompt_id,
    r.prompt_question || '',
    engineDisplay(r.engine),
    r.mentions_brand ? '是' : '否',
    labelOf(POSITION_LABEL, r.brand_position),
    labelOf(SENTIMENT_LABEL, r.sentiment),
    labelOf(CITATION_FORMAT_LABEL, r.citation_format),
    labelOf(CITATION_ACCURACY_LABEL, r.citation_accuracy),
    Array.isArray(r.competitors) ? r.competitors.join(' / ') : '',
    Array.isArray(r.cited_urls) ? r.cited_urls.join(' ') : '',
    fmtCapturedShared(r.captured_at),
    r.note || '',
  ])
  downloadCsv(
    `geo-visibility-snapshots-${tenantId.value}.csv`,
    [
      'ID',
      '意图词ID',
      '问题',
      '引擎',
      '提及本品',
      '位置',
      '情感',
      '引用格式',
      '引用准确性',
      '竞品',
      '引用URL',
      '观测时间',
      '备注',
    ],
    rows,
  )
  ElMessage.success(`已导出 ${rows.length} 条快照`)
}

function applySuggest(draft) {
  if (!draft) return
  if (typeof draft.suggested_mentions_brand === 'boolean') {
    form.value.mentions_brand = draft.suggested_mentions_brand
  }
  if (draft.suggested_brand_position) form.value.brand_position = draft.suggested_brand_position
  if (draft.suggested_sentiment) form.value.sentiment = draft.suggested_sentiment
  if (draft.suggested_citation_format) form.value.citation_format = draft.suggested_citation_format
  if (draft.suggested_citation_accuracy) {
    form.value.citation_accuracy = draft.suggested_citation_accuracy
  }
  const comps = draft.suggested_competitors || draft.competitors
  if (comps) form.value.competitors = (comps || []).join(', ')
  if (draft.suggested_cited_urls) form.value.cited_urls = (draft.suggested_cited_urls || []).join('\n')
}

function loadDraftIntoForm(draft) {
  if (!draft?.ok && draft?.error) {
    ElMessage.error(`${draft.engine}: ${draft.error}`)
    return
  }
  form.value.raw_text = draft.raw_text || ''
  if (draft.engine) form.value.engine = draft.engine
  form.value.note = draft.simulated
    ? `${draft.engine} 模拟探测草稿（待确认）`
    : `${draft.engine || 'deepseek'} 探测草稿（待确认）`
  applySuggest(draft)
}

async function loadEngines() {
  const data = await listGeoTrackingEngines(tenantId.value)
  engines.value = data.items || []
  if (!enabledEngines.value.some((e) => e.engine_key === form.value.engine)) {
    form.value.engine = enabledEngines.value[0]?.engine_key || 'deepseek'
  }
}

async function loadPrompts() {
  const data = queueMode.value
    ? await listGeoPrompts(tenantId.value, { need_recheck: true })
    : await listGeoPrompts(tenantId.value, { status: 'active' })
  prompts.value = data.items || []
  if (!queueMode.value && !prompts.value.length) {
    const all = await listGeoPrompts(tenantId.value)
    prompts.value = all.items || []
  }
  if (filterPromptId.value && prompts.value.some((p) => p.id === filterPromptId.value)) {
    form.value.prompt_id = filterPromptId.value
  } else if (!form.value.prompt_id && prompts.value.length) {
    form.value.prompt_id = prompts.value[0].id
  }
}

async function loadSnapshots() {
  const params = {}
  if (filterPromptId.value) params.prompt_id = filterPromptId.value
  if (filterEngine.value) params.engine = filterEngine.value
  if (filterPatrolRunId.value) params.patrol_run_id = filterPatrolRunId.value
  if (filterSimulated.value === true || filterSimulated.value === false) {
    params.simulated = filterSimulated.value
  }
  const data = await listGeoAnswerSnapshots(tenantId.value, params)
  let rows = data.items || []
  if (filterDomain.value) {
    const d = filterDomain.value.toLowerCase()
    rows = rows.filter((s) =>
      (s.cited_urls || []).some((u) => String(u || '').toLowerCase().includes(d)),
    )
  }
  snapshots.value = rows
  sampleComposition.value = data.sample_composition || null
  snapPager.resetPage()
  // deep-link 单条快照：滚动到表头提示
  if (route.query.snapshot_id) {
    const sid = Number(route.query.snapshot_id)
    const hit = snapshots.value.find((s) => s.id === sid)
    if (hit) {
      ElMessage.info(`已定位巡检相关快照 #${sid}`)
    }
  }
}

function clearPatrolFilter() {
  filterPatrolRunId.value = null
  const q = { ...route.query }
  delete q.patrol_run_id
  delete q.snapshot_id
  router.replace({ query: q })
  loadSnapshots().catch((e) => {
    error.value = e.message
  })
}

async function loadCollectMeta() {
  try {
    const [ops, settings, runs, insights] = await Promise.all([
      fetchVisibilityPatrolOpsStatus(tenantId.value).catch(() => null),
      fetchVisibilityPatrolSettings(tenantId.value).catch(() => null),
      listVisibilityPatrolRuns(tenantId.value, 8).catch(() => ({ items: [] })),
      fetchGeoEvaluationInsights(tenantId.value, {
        date_from: obsStart.value,
        date_to: obsEnd.value,
        days: observationDays.value,
      }).catch(() => null),
    ])
    patrolOps.value = ops
    patrolRuns.value = runs.items || runs.runs || []
    evalData.value = insights
    if (settings) {
      collectForm.value.prefer_real = settings.prefer_real !== false
      collectForm.value.auto_persist = settings.auto_persist !== false
      collectForm.value.prompt_limit = settings.prompt_limit || 20
      collectForm.value.engine_keys = settings.engine_keys || []
      collectForm.value.enabled = !!settings.enabled
      collectForm.value.window_start_hour = settings.window_start_hour ?? 7
      collectForm.value.window_end_hour = settings.window_end_hour ?? 22
      collectForm.value.interval_hours = settings.interval_hours ?? 24
    }
    if (!collectForm.value.engine_keys?.length) {
      collectForm.value.engine_keys = enabledEngines.value.map((e) => e.engine_key)
    }
  } catch {
    patrolOps.value = null
  }
}

async function startCollect() {
  if (!tenantId.value) return
  collecting.value = true
  try {
    const res = await startVisibilityPatrolRun({
      tenant_id: tenantId.value,
      auto_persist: collectForm.value.auto_persist !== false,
      prefer_real: collectForm.value.prefer_real !== false,
      prompt_limit: collectForm.value.prompt_limit || 20,
      engine_keys: collectForm.value.engine_keys?.length ? collectForm.value.engine_keys : null,
      run_async: true,
    })
    const id = res.run?.id
    ElMessage.success(id ? `采集 #${id} 进行中，完成后会按提及/位置/情感判断可见度` : '采集已启动')
    if (id) {
      for (let i = 0; i < 24; i += 1) {
        await new Promise((r) => setTimeout(r, 2500))
        const run = await getVisibilityPatrolRun(tenantId.value, id).catch(() => null)
        const st = String(run?.status || run?.run?.status || '').toLowerCase()
        if (['succeeded', 'success', 'done', 'completed', 'failed', 'error', 'cancelled'].includes(st)) {
          if (st === 'failed' || st === 'error') {
            ElMessage.error(`采集 #${id} 失败：${run?.error || '未知'}`)
          } else {
            const sum = run?.summary || {}
            ElMessage.success(
              `采集完成：成功 ${sum.ok_cells || sum.cells_ok || 0} · 落库 ${sum.snapshots_created || 0}`,
            )
          }
          break
        }
      }
    }
    await loadSnapshots()
    await loadCollectMeta()
  } catch (e) {
    ElMessage.error(e.message || '启动失败')
  } finally {
    collecting.value = false
  }
}

async function saveSchedule() {
  savingSchedule.value = true
  try {
    await putVisibilityPatrolSettings({
      tenant_id: tenantId.value,
      enabled: collectForm.value.enabled,
      window_start_hour: collectForm.value.window_start_hour,
      window_end_hour: collectForm.value.window_end_hour,
      interval_hours: collectForm.value.interval_hours,
      auto_persist: collectForm.value.auto_persist,
      prefer_real: collectForm.value.prefer_real,
      prompt_limit: collectForm.value.prompt_limit,
      engine_keys: collectForm.value.engine_keys?.length ? collectForm.value.engine_keys : null,
    })
    ElMessage.success('定时采集已保存')
    await loadCollectMeta()
  } catch (e) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    savingSchedule.value = false
  }
}

async function reloadAll() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    return
  }
  loading.value = true
  error.value = ''
  try {
    await loadEngines()
    await loadPrompts()
    await loadSnapshots()
    await loadCollectMeta()
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

function setPromptFilter(id) {
  filterPromptId.value = id
  form.value.prompt_id = id
  const q = { ...route.query, prompt_id: String(id) }
  router.replace({ query: q })
  loadSnapshots().catch((e) => { error.value = e.message })
}

function clearPromptFilter() {
  filterPromptId.value = null
  const q = { ...route.query }
  delete q.prompt_id
  router.replace({ query: q })
  loadSnapshots().catch((e) => { error.value = e.message })
}

function clearDomainFilter() {
  filterDomain.value = ''
  const q = { ...route.query }
  delete q.domain
  router.replace({ query: q })
  loadSnapshots().catch((e) => { error.value = e.message })
}

async function onProbe() {
  if (!form.value.prompt_id) {
    ElMessage.warning('请选择优化意图词')
    return
  }
  probing.value = true
  error.value = ''
  try {
    const draft = await probeGeoAnswerSnapshot({
      tenant_id: tenantId.value,
      prompt_id: form.value.prompt_id,
      engine: form.value.engine,
    })
    loadDraftIntoForm({ ...draft, ok: true })
    ElMessage.success('已填入探测草稿，请确认后保存')
  } catch (e) {
    error.value = e.message
  } finally {
    probing.value = false
  }
}

async function onProbeBatch() {
  if (!form.value.prompt_id) {
    ElMessage.warning('请选择优化意图词')
    return
  }
  batchProbing.value = true
  error.value = ''
  batchDrafts.value = []
  try {
    const result = await probeGeoAnswerSnapshotBatch({
      tenant_id: tenantId.value,
      prompt_id: form.value.prompt_id,
    })
    batchDrafts.value = result.items || []
    const firstOk = batchDrafts.value.find((i) => i.ok)
    if (firstOk) loadDraftIntoForm(firstOk)
    ElMessage.success(
      `多引擎探测完成：成功 ${result.ok_count || 0}，失败 ${result.error_count || 0}`,
    )
  } catch (e) {
    error.value = e.message
  } finally {
    batchProbing.value = false
  }
}

async function onSuggest() {
  if (!form.value.raw_text.trim()) {
    ElMessage.warning('请先粘贴或探测回答正文')
    return
  }
  try {
    const draft = await suggestGeoAnswerSnapshotFields({
      tenant_id: tenantId.value,
      raw_text: form.value.raw_text,
      prompt_id: form.value.prompt_id || null,
      use_llm: true,
    })
    applySuggest(draft)
    ElMessage.success('已填入标注建议')
  } catch (e) {
    error.value = e.message
  }
}

async function onExtractUrls() {
  if (!form.value.raw_text.trim()) {
    ElMessage.warning('请先粘贴或探测回答正文')
    return
  }
  try {
    const data = await extractGeoAnswerSnapshotUrls({
      tenant_id: tenantId.value,
      raw_text: form.value.raw_text,
    })
    form.value.cited_urls = (data.suggested_cited_urls || []).join('\n')
    ElMessage.success(
      data.suggested_cited_urls?.length
        ? `已抽取 ${data.suggested_cited_urls.length} 条 URL`
        : '正文中未识别到链接',
    )
  } catch (e) {
    error.value = e.message
  }
}

async function onCheckCitations() {
  const urls = form.value.cited_urls.split(/\n+/).map((s) => s.trim()).filter(Boolean)
  if (!urls.length) {
    ElMessage.warning('请先填写或抽取引用 URL')
    return
  }
  try {
    const data = await checkGeoAnswerSnapshotCitations({
      tenant_id: tenantId.value,
      cited_urls: urls,
    })
    if (data.suggested_citation_accuracy) {
      form.value.citation_accuracy = data.suggested_citation_accuracy
    }
    ElMessage.success(
      `校验完成：可达 ${data.reachable ?? 0}/${data.checked ?? 0} · 建议准确性 ${data.suggested_citation_accuracy}`,
    )
  } catch (e) {
    error.value = e.message
    ElMessage.error(e.message || '校验失败')
  }
}

async function onSave() {
  if (!form.value.prompt_id) {
    ElMessage.warning('请选择优化意图词')
    return
  }
  saving.value = true
  error.value = ''
  try {
    await createGeoAnswerSnapshot({
      tenant_id: tenantId.value,
      prompt_id: form.value.prompt_id,
      engine: form.value.engine,
      raw_text: form.value.raw_text,
      captured_at: form.value.captured_at || null,
      mentions_brand: form.value.mentions_brand,
      brand_position: form.value.brand_position,
      sentiment: form.value.sentiment,
      citation_format: form.value.citation_format,
      citation_accuracy: form.value.citation_accuracy,
      competitors: form.value.competitors.split(/[,，]/).map((s) => s.trim()).filter(Boolean),
      cited_urls: form.value.cited_urls.split(/\n+/).map((s) => s.trim()).filter(Boolean),
      note: form.value.note || null,
    })
    form.value.raw_text = ''
    form.value.cited_urls = ''
    form.value.competitors = ''
    form.value.note = ''
    form.value.mentions_brand = false
    form.value.brand_position = 'unknown'
    form.value.sentiment = 'unknown'
    form.value.citation_format = 'unknown'
    form.value.citation_accuracy = 'unknown'
    ElMessage.success('快照已保存')
    await loadSnapshots()
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}

async function toggleMention(row) {
  try {
    await patchGeoAnswerSnapshot(tenantId.value, row.id, {
      mentions_brand: !row.mentions_brand,
    })
    await loadSnapshots()
  } catch (e) {
    error.value = e.message
  }
}

async function patchSnapField(row, patch) {
  try {
    await patchGeoAnswerSnapshot(tenantId.value, row.id, patch)
    Object.assign(row, patch)
    ElMessage.success('已更新')
  } catch (e) {
    error.value = e.message
    ElMessage.error(e.message || '更新失败')
    await loadSnapshots()
  }
}

function compsText(row) {
  return Array.isArray(row.competitors) ? row.competitors.join(', ') : ''
}

async function saveCompetitors(row, text) {
  const competitors = String(text || '')
    .split(/[,，]/)
    .map((s) => s.trim())
    .filter(Boolean)
  await patchSnapField(row, { competitors })
}

async function removeSnapshot(row) {
  try {
    await ElMessageBox.confirm(`删除快照 #${row.id}？不可恢复。`, '删除快照', {
      type: 'warning',
      confirmButtonText: '删除',
    })
    await deleteGeoAnswerSnapshot(tenantId.value, row.id)
    ElMessage.success('已删除')
    await loadSnapshots()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') {
      error.value = e.message || '删除失败'
      ElMessage.error(error.value)
    }
  }
}

async function saveBatchItem(draft) {
  if (!draft.ok || !form.value.prompt_id) return
  saving.value = true
  try {
    await createGeoAnswerSnapshot({
      tenant_id: tenantId.value,
      prompt_id: form.value.prompt_id,
      engine: draft.engine,
      raw_text: draft.raw_text,
      mentions_brand: !!draft.suggested_mentions_brand,
      brand_position: draft.suggested_brand_position || 'unknown',
      sentiment: draft.suggested_sentiment || 'unknown',
      citation_format: draft.suggested_citation_format || 'unknown',
      citation_accuracy: draft.suggested_citation_accuracy || 'unknown',
      competitors: draft.suggested_competitors || [],
      cited_urls: draft.suggested_cited_urls || [],
      note: draft.simulated
        ? `${draft.engine} 模拟探测（批量确认）`
        : `${draft.engine} 探测（批量确认）`,
    })
    ElMessage.success(`已保存 ${draft.engine}`)
    draft._saved = true
    await loadSnapshots()
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}

watch(filterEngine, () => loadSnapshots())
watch(
  () => route.query.patrol_run_id,
  (v) => {
    filterPatrolRunId.value = v ? Number(v) : null
    loadSnapshots().catch((e) => {
      error.value = e.message
    })
  },
)
watch(tenantId, reloadAll)
watch([observationDays, obsStart, obsEnd], () => {
  if (!tenantId.value) return
  loadCollectMeta().catch(() => {})
})
onMounted(reloadAll)
</script>

<template>
  <GeoWorkbenchPage
    title="AI 可见度"
    :sub="`自动采集 AI 引擎回答，按提及 / 位置 / 情感判断可见度 · ${obsLabel}`"
    :loading="loading"
  >
    <template #actions>
      <button type="button" class="gd-btn" @click="reloadAll">刷新</button>
      <button type="button" class="gd-btn" :disabled="!snapshots.length" @click="exportSnapshots">导出 CSV</button>
      <button type="button" class="gd-btn primary" :disabled="collecting" @click="startCollect">
        {{ collecting ? '采集中…' : '立即采集并落库' }}
      </button>
    </template>

    <div class="geo-dash geo-vis">
      <GeoVisibilityNav />

      <el-alert v-if="error" :title="error" type="error" :closable="false" class="mb" />
      <el-alert
        v-if="queueMode"
        type="info"
        :closable="false"
        class="mb"
        :title="`待复核队列 · ${prompts.length} 条（已发布但无快照，或快照早于最近发布）`"
      />

      <section id="collect" class="gd-card collect-bar">
        <div class="collect-copy">
          <strong>自动采集 AI 引擎回答</strong>
          <p>
            按已启用引擎提问并落库，系统根据提及、推荐位置和情感判断可见度。
            最近一次：
            <template v-if="lastRun">
              #{{ lastRun.id }} {{ runStatusLabel(lastRun.status) }}
              · {{ fmtCaptured(lastRun.finished_at || lastRun.created_at) }}
            </template>
            <template v-else>尚未跑过</template>
          </p>
        </div>
        <div class="collect-controls">
          <el-checkbox v-model="collectForm.prefer_real">优先真采样</el-checkbox>
          <el-checkbox v-model="collectForm.auto_persist">自动落库</el-checkbox>
          <el-input-number v-model="collectForm.prompt_limit" :min="1" :max="50" size="small" />
          <el-select
            v-model="collectForm.engine_keys"
            multiple
            collapse-tags
            collapse-tags-tooltip
            placeholder="引擎"
            style="min-width: 180px"
            size="small"
          >
            <el-option
              v-for="e in enabledEngines"
              :key="e.engine_key"
              :label="e.display_name || engineDisplay(e.engine_key)"
              :value="e.engine_key"
            />
          </el-select>
          <button type="button" class="gd-btn primary" :disabled="collecting" @click="startCollect">
            {{ collecting ? '采集中…' : '立即采集并落库' }}
          </button>
        </div>
        <details class="collect-schedule">
          <summary>定时采集（可选）</summary>
          <div class="schedule-row">
            <el-switch v-model="collectForm.enabled" active-text="开启定时" />
            <span>允许 {{ collectForm.window_start_hour }}:00 – {{ collectForm.window_end_hour }}:00</span>
            <el-input-number v-model="collectForm.window_start_hour" :min="0" :max="23" size="small" />
            <el-input-number v-model="collectForm.window_end_hour" :min="0" :max="23" size="small" />
            <el-select v-model="collectForm.interval_hours" size="small" style="width: 160px">
              <el-option
                v-for="o in intervalOptions"
                :key="o.value"
                :label="o.label"
                :value="o.value"
              />
            </el-select>
            <el-button size="small" :loading="savingSchedule" @click="saveSchedule">保存定时</el-button>
          </div>
          <ul v-if="patrolRuns.length" class="run-list">
            <li v-for="r in patrolRuns.slice(0, 5)" :key="r.id">
              #{{ r.id }} {{ runStatusLabel(r.status) }}
              · {{ r.trigger === 'schedule' ? '定时' : '手动' }}
              · 成功 {{ r.summary?.ok_cells || r.summary?.cells_ok || 0 }}
              · 落库 {{ r.summary?.snapshots_created || 0 }}
            </li>
          </ul>
        </details>
      </section>

      <div class="gd-engine-kpis eval-kpis">
        <div v-for="c in evalKpis" :key="c.label" class="gd-card gd-stat">
          <div class="label">{{ c.label }}</div>
          <div class="value">{{ c.value }}</div>
          <div class="delta hint">{{ c.hint }}</div>
        </div>
      </div>

    <div class="layout">
      <section class="panel gd-card">
        <div class="panel-title">登记回答快照</div>
        <p class="hint">
          探测只填草稿不写库；确认标注后再点「保存快照」。列表内可直接改字段。
        </p>
        <el-form label-position="top" @submit.prevent>
          <el-form-item label="优化意图词">
            <el-select v-model="form.prompt_id" filterable style="width: 100%">
              <el-option
                v-for="p in prompts"
                :key="p.id"
                :label="`#${p.id} · ${p.question}`"
                :value="p.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="引擎">
            <el-select v-model="form.engine" style="width: 100%">
              <el-option
                v-for="e in enabledEngines"
                :key="e.engine_key"
                :label="e.display_name || engineDisplay(e.engine_key)"
                :value="e.engine_key"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="回答原文">
            <el-input v-model="form.raw_text" type="textarea" :rows="7" placeholder="粘贴模型回答…" />
          </el-form-item>
          <el-form-item label="观测时间（可选 ISO）">
            <el-input v-model="form.captured_at" placeholder="留空则用当前时间" />
          </el-form-item>
          <el-form-item>
            <el-checkbox v-model="form.mentions_brand">提及我方品牌</el-checkbox>
          </el-form-item>
          <div class="row2">
            <el-form-item label="本品位置">
              <el-select v-model="form.brand_position" style="width: 100%">
                <el-option
                  v-for="o in POSITION_OPTIONS"
                  :key="o.value"
                  :label="o.label"
                  :value="o.value"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="情感倾向">
              <el-select v-model="form.sentiment" style="width: 100%">
                <el-option
                  v-for="o in SENTIMENT_OPTIONS"
                  :key="o.value"
                  :label="o.label"
                  :value="o.value"
                />
              </el-select>
            </el-form-item>
          </div>
          <div class="row2">
            <el-form-item label="引用格式">
              <el-select v-model="form.citation_format" style="width: 100%">
                <el-option
                  v-for="o in FORMAT_OPTIONS"
                  :key="o.value"
                  :label="o.label"
                  :value="o.value"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="引用准确性">
              <el-select v-model="form.citation_accuracy" style="width: 100%">
                <el-option
                  v-for="o in ACCURACY_OPTIONS"
                  :key="o.value"
                  :label="o.label"
                  :value="o.value"
                />
              </el-select>
            </el-form-item>
          </div>
          <el-form-item label="竞品名（逗号分隔）">
            <el-input v-model="form.competitors" placeholder="竞品A, 竞品B" />
          </el-form-item>
          <el-form-item label="引用 URL（每行一个）">
            <el-input v-model="form.cited_urls" type="textarea" :rows="3" />
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="form.note" />
          </el-form-item>
          <div class="actions">
            <el-button :loading="probing" @click="onProbe">用 AI 探测</el-button>
            <el-button :loading="batchProbing" type="warning" plain @click="onProbeBatch">
              多引擎探测
            </el-button>
            <el-button @click="onSuggest">AI 标注建议</el-button>
            <el-button @click="onExtractUrls">抽取 URL</el-button>
            <el-button @click="onCheckCitations">校验引用</el-button>
            <el-button type="primary" :loading="saving" @click="onSave">保存快照</el-button>
          </div>
          <p class="hint">
            探测 / 多引擎探测只填草稿；多引擎共用租户 LLM，按引擎人设模拟，非真实各厂 API。
          </p>
        </el-form>

        <div v-if="batchDrafts.length" class="batch">
          <div class="panel-title">多引擎草稿</div>
          <div v-for="d in batchDrafts" :key="d.engine" class="batch-item">
            <div class="batch-head">
              <strong>{{ engineDisplay(d.engine) }}</strong>
              <span v-if="d.ok && d.simulated" class="tag">模拟</span>
              <span v-if="!d.ok" class="tag bad">失败</span>
              <span v-if="d._saved" class="tag ok">已保存</span>
            </div>
            <p v-if="d.error" class="err-line">{{ d.error }}</p>
            <p v-else class="snip">{{ snippet(d.raw_text) }}</p>
            <div v-if="d.ok" class="actions">
              <el-button size="small" @click="loadDraftIntoForm(d)">填入表单</el-button>
              <el-button
                size="small"
                type="primary"
                :disabled="d._saved"
                :loading="saving"
                @click="saveBatchItem(d)"
              >
                确认保存
              </el-button>
            </div>
          </div>
        </div>
      </section>

      <section class="panel panel-list gd-card">
        <div class="list-toolbar">
          <div class="panel-title" style="margin: 0">快照列表</div>
          <el-select v-model="filterEngine" clearable placeholder="全部引擎" style="width: 140px">
            <el-option
              v-for="e in engines"
              :key="e.engine_key"
              :label="e.display_name || engineDisplay(e.engine_key)"
              :value="e.engine_key"
            />
          </el-select>
          <el-button v-if="filterPromptId" @click="clearPromptFilter">清除问题过滤</el-button>
          <el-button v-if="filterDomain" @click="clearDomainFilter">
            清除域名 {{ filterDomain }}
          </el-button>
          <el-button v-if="filterPatrolRunId" type="warning" plain @click="clearPatrolFilter">
            清除巡检 #{{ filterPatrolRunId }}
          </el-button>
          <el-button size="small" :disabled="!snapshots.length" @click="exportSnapshots">导出</el-button>
        </div>
        <p class="hint">
          {{ filterPromptId ? `过滤意图词 #${filterPromptId}` : '显示全部快照' }}
          <template v-if="filterEngine"> · {{ engineDisplay(filterEngine) }}</template>
          <template v-if="filterDomain"> · 引用含 {{ filterDomain }}</template>
          <template v-if="filterPatrolRunId"> · 巡检运行 #{{ filterPatrolRunId }}</template>
          · 共 {{ snapshots.length }} 条
          <template v-if="sampleComposition?.label"> · {{ sampleComposition.label }}</template>
        </p>
        <SampleCredibilityAlert :composition="sampleComposition" />
        <el-alert
          v-if="snapshots.length && emptyReason?.key === 'no_mention'"
          type="warning"
          show-icon
          class="mb"
          :title="emptyReason.title"
          :description="emptyReason.detail"
        />
        <div v-if="!snapshots.length && !loading" class="geo-empty" style="margin: 8px 0 12px">
          <div class="empty-title">
            {{
              filterPatrolRunId
                ? `采集 #${filterPatrolRunId} 暂无关联快照`
                : emptyReason?.title || '暂无回答快照'
            }}
          </div>
          <div>
            {{
              filterPatrolRunId
                ? '可能是旧任务未写关联，或当时没勾选自动落库。'
                : emptyReason?.detail || '左侧登记一条，或点「立即采集并落库」。'
            }}
          </div>
          <div class="empty-actions">
            <button
              type="button"
              class="gd-btn primary"
              :disabled="collecting"
              @click="startCollect"
            >
              {{ collecting ? '采集中…' : (emptyReason?.action || '立即采集并落库') }}
            </button>
            <router-link class="el-button el-button--small is-plain" to="/geo/engines">
              检查引擎
            </router-link>
            <router-link class="el-button el-button--small is-plain" to="/geo/prompts">
              管理意图词
            </router-link>
          </div>
        </div>
        <div class="table-wrap">
          <el-table
            :data="snapPager.pagedItems"
            size="small"
            empty-text=" "
            stripe
            class="snap-table"
            style="width: 100%"
          >
            <el-table-column label="问题 / 摘要" min-width="220" show-overflow-tooltip>
              <template #default="{ row }">
                <div class="q-title">{{ row.prompt_question || `#${row.prompt_id}` }}</div>
                <div class="snip">{{ snippet(row.raw_text, 90) }}</div>
              </template>
            </el-table-column>
            <el-table-column label="引擎" width="100" show-overflow-tooltip>
              <template #default="{ row }">{{ engineDisplay(row.engine) }}</template>
            </el-table-column>
            <el-table-column label="样本" width="100" align="center">
              <template #default="{ row }">
                <el-tag
                  v-if="row.simulated"
                  size="small"
                  type="warning"
                  effect="light"
                >模拟</el-tag>
                <el-tag
                  v-else-if="row.sample_mode === 'openai_compat'"
                  size="small"
                  type="success"
                  effect="light"
                >真采样</el-tag>
                <el-tag v-else size="small" type="info" effect="light">人工</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="提及本品" width="100" align="center">
              <template #default="{ row }">
                <el-button size="small" text type="primary" @click="toggleMention(row)">
                  {{ row.mentions_brand ? '是' : '否' }}·切换
                </el-button>
              </template>
            </el-table-column>
            <el-table-column label="本品位置" width="128" align="center">
              <template #default="{ row }">
                <el-select
                  size="small"
                  :model-value="row.brand_position || 'unknown'"
                  style="width: 116px"
                  @change="(v) => patchSnapField(row, { brand_position: v })"
                >
                  <el-option
                    v-for="o in POSITION_OPTIONS"
                    :key="o.value"
                    :label="o.label"
                    :value="o.value"
                  />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="引用格式" width="128" align="center">
              <template #default="{ row }">
                <el-select
                  size="small"
                  :model-value="row.citation_format || 'unknown'"
                  style="width: 116px"
                  @change="(v) => patchSnapField(row, { citation_format: v })"
                >
                  <el-option
                    v-for="o in FORMAT_OPTIONS"
                    :key="o.value"
                    :label="o.label"
                    :value="o.value"
                  />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="引用准确性" width="118" align="center">
              <template #default="{ row }">
                <el-select
                  size="small"
                  :model-value="row.citation_accuracy || 'unknown'"
                  style="width: 106px"
                  @change="(v) => patchSnapField(row, { citation_accuracy: v })"
                >
                  <el-option
                    v-for="o in ACCURACY_OPTIONS"
                    :key="o.value"
                    :label="o.label"
                    :value="o.value"
                  />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="情感" width="110" align="center">
              <template #default="{ row }">
                <el-select
                  size="small"
                  :model-value="row.sentiment || 'unknown'"
                  style="width: 96px"
                  @change="(v) => patchSnapField(row, { sentiment: v })"
                >
                  <el-option
                    v-for="o in SENTIMENT_OPTIONS"
                    :key="o.value"
                    :label="o.label"
                    :value="o.value"
                  />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="竞品" min-width="140">
              <template #default="{ row }">
                <el-input
                  size="small"
                  :model-value="compsText(row)"
                  placeholder="逗号分隔"
                  @change="(v) => saveCompetitors(row, v)"
                />
              </template>
            </el-table-column>
            <el-table-column label="观测时间" width="108" show-overflow-tooltip>
              <template #default="{ row }">{{ fmtCaptured(row.captured_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="72" fixed="right">
              <template #default="{ row }">
                <el-button size="small" text type="danger" @click="removeSnapshot(row)">
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
        <div class="geo-pager">
          <el-pagination
            background
            layout="total, sizes, prev, pager, next"
            :total="snapPager.total"
            :page-size="snapPager.pageSize"
            :current-page="snapPager.page"
            :page-sizes="[10, 20, 50, 100]"
            @current-change="snapPager.onPageChange"
            @size-change="snapPager.onSizeChange"
          />
        </div>

        <div v-if="queueMode && prompts.length" class="queue">
          <div class="panel-title">队列快捷</div>
          <button
            v-for="p in prompts"
            :key="p.id"
            type="button"
            class="queue-item"
            @click="setPromptFilter(p.id)"
          >
            #{{ p.id }} · {{ p.question }}
          </button>
        </div>
      </section>
    </div>
    </div>
  </GeoWorkbenchPage>
</template>

<style scoped>
.geo-vis { padding: 0 0 8px; }
.mb { margin-bottom: 14px; }
.collect-bar {
  padding: 16px 18px;
  margin-bottom: 16px;
}
.collect-copy strong {
  display: block;
  font-size: 14px;
  color: #1e2330;
}
.collect-copy p {
  margin: 6px 0 0;
  font-size: 12px;
  color: #6b7280;
  line-height: 1.5;
}
.collect-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin-top: 12px;
}
.collect-schedule {
  margin-top: 12px;
  font-size: 12px;
  color: #6b7280;
}
.collect-schedule summary {
  cursor: pointer;
  font-weight: 600;
}
.schedule-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin-top: 10px;
}
.run-list {
  margin: 10px 0 0;
  padding-left: 18px;
  line-height: 1.6;
}
.eval-kpis { margin-bottom: 16px; }
.layout {
  display: grid;
  /* 左表单收窄，右列表吃满剩余宽度，避免半宽挤扁表格首字被裁切 */
  grid-template-columns: minmax(300px, 380px) minmax(0, 1fr);
  gap: 14px;
  align-items: start;
}
.panel {
  background: #fff;
  border: 1px solid #e8eaf0;
  border-radius: 12px;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.05), 0 8px 24px rgba(16, 24, 40, 0.04);
  padding: 16px 18px;
  min-width: 0;
  overflow: hidden;
}
.panel-list {
  overflow: visible;
}
.panel-title { font-size: 14px; font-weight: 600; color: #374151; margin-bottom: 12px; }
.row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
.hint { margin: 0 0 8px; font-size: 12px; color: #9ca3af; line-height: 1.5; }
.list-toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
.table-wrap {
  width: 100%;
  max-width: 100%;
  overflow-x: auto;
  overflow-y: visible;
  -webkit-overflow-scrolling: touch;
  border: 1px solid #f0f0f0;
  border-radius: 8px;
}
.snap-table {
  min-width: 720px;
}
.snap-table :deep(.el-table__cell) {
  vertical-align: top;
}
.q-title {
  font-size: 13px;
  font-weight: 600;
  color: #1f2937;
  line-height: 1.4;
  word-break: break-word;
  white-space: normal;
}
.snip {
  font-size: 12px;
  color: #9ca3af;
  margin: 4px 0 0;
  line-height: 1.4;
  word-break: break-word;
  white-space: normal;
}
.batch { margin-top: 18px; border-top: 1px solid #e5e7eb; padding-top: 14px; }
.batch-item {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 8px;
  background: #f9fafb;
}
.batch-head { display: flex; gap: 8px; align-items: center; }
.tag {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  background: #e0e7ff;
  color: #3730a3;
}
.tag.bad { background: #fef2f2; color: #b91c1c; }
.tag.ok { background: #ecfdf5; color: #047857; }
.err-line { color: #b91c1c; font-size: 12px; margin: 6px 0; }
.queue { margin-top: 16px; }
.queue-item {
  display: block;
  width: 100%;
  text-align: left;
  border: 1px solid #e5e7eb;
  background: #fff;
  border-radius: 6px;
  padding: 8px 10px;
  margin-bottom: 6px;
  cursor: pointer;
  font-size: 13px;
}
.queue-item:hover { border-color: #93c5fd; background: #eff6ff; }
@media (max-width: 1100px) {
  .layout { grid-template-columns: minmax(280px, 340px) minmax(0, 1fr); }
}
@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; }
  .row2 { grid-template-columns: 1fr; }
  .snap-table { min-width: 640px; }
}
</style>
