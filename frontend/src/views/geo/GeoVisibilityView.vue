<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createGeoAnswerSnapshot,
  listGeoAnswerSnapshots,
  listGeoPrompts,
  listGeoTrackingEngines,
  deleteGeoAnswerSnapshot,
  patchGeoAnswerSnapshot,
  probeGeoAnswerSnapshot,
  probeGeoAnswerSnapshotBatch,
  fetchGeoEvaluationInsights,
  fetchVisibilityPatrolOpsStatus,
  fetchVisibilityPatrolSettings,
  getVisibilityPatrolRun,
  listVisibilityPatrolRuns,
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
const collectForm = ref({
  prefer_real: true,
  auto_persist: true,
  prompt_limit: 20,
  engine_keys: [],
})
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
const patrolScheduleLabel = computed(() => {
  const s = patrolOps.value?.settings
  if (!s) return '尚未加载'
  const on = s.enabled ? '已开启' : '未开启'
  return `${on} · ${s.window_start_hour ?? 8}–${s.window_end_hour ?? 22} 点 · 间隔 ${s.interval_hours ?? 24} 小时 · 每轮上限 ${s.prompt_limit ?? 20}`
})
const hasSimulated = computed(() => snapshots.value.some((s) => s.simulated))

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

const registerOpen = ref(false)
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
    registerOpen.value = false
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

watch(registerOpen, (open) => {
  if (open) batchDrafts.value = []
})
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
    title="采集与判断"
    sub="自动采集 AI 引擎回答，按提及、位置和情感判断可见度"
    :loading="loading"
  >
    <template #actions>
      <button type="button" class="gd-btn" @click="reloadAll">刷新</button>
      <button type="button" class="gd-btn" @click="registerOpen = true">登记快照</button>
      <button type="button" class="gd-btn" :disabled="!snapshots.length" @click="exportSnapshots">
        导出 CSV
      </button>
      <button type="button" class="gd-btn primary" :disabled="collecting" @click="startCollect">
        {{ collecting ? '采集中…' : '立即采集' }}
      </button>
    </template>

    <div class="geo-dash">
      <GeoVisibilityNav />

      <el-alert v-if="error" :title="error" type="error" :closable="false" class="mb" />
      <el-alert
        v-if="queueMode"
        type="info"
        :closable="false"
        class="mb"
        :title="`待复核队列 · ${prompts.length} 条（已发布但无快照，或快照早于最近发布）`"
      />

      <div class="gd-card mb">
        <div class="gd-hd">
          <h3>自动采集</h3>
          <span class="more">
            <template v-if="lastRun">
              最近 #{{ lastRun.id }} {{ runStatusLabel(lastRun.status) }}
              · {{ fmtCaptured(lastRun.finished_at || lastRun.created_at) }}
            </template>
            <template v-else>尚未采集</template>
          </span>
        </div>
        <div class="gd-bd collect-bd">
          <p class="hint">
            按已启用引擎提问，自动判断提及、位置和情感。
            定时巡检（只读）：{{ patrolScheduleLabel }}。
            改定时请到
            <router-link to="/geo/models">引擎</router-link>。
          </p>
          <div class="geo-set-row">
            <span>采集引擎</span>
            <el-select
              v-model="collectForm.engine_keys"
              multiple
              collapse-tags
              collapse-tags-tooltip
              placeholder="采集引擎"
              style="width: 320px"
            >
              <el-option
                v-for="e in enabledEngines"
                :key="e.engine_key"
                :label="e.display_name || engineDisplay(e.engine_key)"
                :value="e.engine_key"
              />
            </el-select>
          </div>
          <div class="geo-set-row">
            <span>本次提问上限</span>
            <el-input-number v-model="collectForm.prompt_limit" :min="1" :max="50" />
          </div>
        </div>
      </div>

      <div class="gd-engine-kpis mb">
        <div v-for="c in evalKpis" :key="c.label" class="gd-card gd-stat">
          <div class="label">{{ c.label }}</div>
          <div class="value">{{ c.value }}</div>
          <div class="delta hint">{{ c.hint }}</div>
        </div>
      </div>

      <div class="geo-filter-bar">
        <el-select v-model="filterEngine" clearable placeholder="全部引擎" style="width: 160px">
          <el-option
            v-for="e in engines"
            :key="e.engine_key"
            :label="e.display_name || engineDisplay(e.engine_key)"
            :value="e.engine_key"
          />
        </el-select>
        <button v-if="filterPromptId" type="button" class="gd-btn" @click="clearPromptFilter">
          清除提问 #{{ filterPromptId }}
        </button>
        <button v-if="filterDomain" type="button" class="gd-btn" @click="clearDomainFilter">
          清除域名 {{ filterDomain }}
        </button>
        <button v-if="filterPatrolRunId" type="button" class="gd-btn" @click="clearPatrolFilter">
          清除巡检 #{{ filterPatrolRunId }}
        </button>
        <span class="toolbar-hint">
          共 {{ snapshots.length }} 条
          <template v-if="filterEngine"> · {{ engineDisplay(filterEngine) }}</template>
        </span>
      </div>

      <SampleCredibilityAlert :composition="sampleComposition" />
      <el-alert
        v-if="snapshots.length && emptyReason?.key === 'no_mention'"
        type="warning"
        show-icon
        class="mb"
        :title="emptyReason.title"
        :description="emptyReason.detail"
      />

      <div v-if="!snapshots.length && !loading" class="geo-empty mb">
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
              : emptyReason?.detail || '点「立即采集」或「登记快照」。'
          }}
        </div>
        <div class="empty-actions">
          <button type="button" class="gd-btn primary" :disabled="collecting" @click="startCollect">
            {{ collecting ? '采集中…' : (emptyReason?.action || '立即采集') }}
          </button>
          <router-link class="gd-btn" to="/geo/models">检查引擎</router-link>
          <router-link class="gd-btn" to="/geo/questions">管理意图词</router-link>
        </div>
      </div>

      <div v-if="snapshots.length" class="gd-card">
        <div class="gd-hd">
          <h3>快照列表</h3>
          <span class="more">{{ snapshots.length }} 条</span>
        </div>
        <div class="gd-bd" style="padding: 0">
          <el-table
            :data="snapPager.pagedItems"
            size="small"
            stripe
            class="snap-table"
            style="width: 100%"
          >
            <el-table-column label="问题 / 摘要" min-width="240" show-overflow-tooltip>
              <template #default="{ row }">
                <div class="q-title">{{ row.prompt_question || `#${row.prompt_id}` }}</div>
                <div class="snip">{{ snippet(row.raw_text, 90) }}</div>
              </template>
            </el-table-column>
            <el-table-column label="引擎" width="100" show-overflow-tooltip>
              <template #default="{ row }">{{ engineDisplay(row.engine) }}</template>
            </el-table-column>
            <el-table-column v-if="hasSimulated" label="样本" width="80" align="center">
              <template #default="{ row }">
                <span v-if="row.simulated" class="gd-badge amber">模拟</span>
              </template>
            </el-table-column>
            <el-table-column label="提及" width="108" align="center">
              <template #default="{ row }">
                <span
                  class="gd-badge"
                  :class="row.mentions_brand ? 'green' : 'red'"
                  style="cursor: pointer"
                  @click="toggleMention(row)"
                >
                  {{ row.mentions_brand ? '已提及' : '未提及' }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="位置" width="128" align="center">
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
            <el-table-column label="观测时间" width="108" show-overflow-tooltip>
              <template #default="{ row }">{{ fmtCaptured(row.captured_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="88" align="center">
              <template #default="{ row }">
                <el-button size="small" text type="danger" @click="removeSnapshot(row)">
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
        <div class="geo-pager" style="padding: 12px 16px">
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
      </div>
    </div>

    <el-dialog v-model="registerOpen" title="登记快照" width="560px" class="geo-form-dialog">
      <p class="hint">粘贴或探测回答后保存。列表中可调整提及、位置和情感。</p>
      <el-form label-width="100px" class="geo-dialog-form" @submit.prevent>
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
          <el-input v-model="form.raw_text" type="textarea" :rows="6" placeholder="粘贴模型回答…" />
        </el-form-item>
        <el-form-item label="观测时间">
          <el-input v-model="form.captured_at" placeholder="可留空，默认当前时间" />
        </el-form-item>
        <el-form-item label="提及本品">
          <el-checkbox v-model="form.mentions_brand">提及我方品牌</el-checkbox>
        </el-form-item>
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
        <el-form-item label="竞品">
          <el-input v-model="form.competitors" placeholder="逗号分隔" />
        </el-form-item>
        <el-form-item label="引用 URL">
          <el-input v-model="form.cited_urls" type="textarea" :rows="2" placeholder="每行一个" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.note" />
        </el-form-item>
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
      <template #footer>
        <el-button :loading="probing" @click="onProbe">探测回答</el-button>
        <el-button :loading="batchProbing" @click="onProbeBatch">多引擎探测</el-button>
        <el-button @click="registerOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">保存快照</el-button>
      </template>
    </el-dialog>
  </GeoWorkbenchPage>
</template>

<style scoped>
.mb { margin-bottom: 16px; }
.collect-bd {
  max-width: 640px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.collect-bd :deep(.geo-set-row > span) {
  flex: none;
  white-space: nowrap;
}
.snap-table :deep(.gd-badge) {
  white-space: nowrap;
}
.hint {
  margin: 0 0 8px;
  font-size: 12px;
  color: #6b7280;
  line-height: 1.5;
}
.toolbar-hint {
  margin-left: auto;
  font-size: 12px;
  color: #6b7280;
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
.snap-table :deep(.el-table__cell) { vertical-align: top; }
.panel-title { font-size: 14px; font-weight: 600; color: #374151; margin-bottom: 12px; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.batch { margin-top: 8px; border-top: 1px solid #e5e7eb; padding-top: 14px; }
.batch-item {
  border: 1px solid #e8eaf0;
  border-radius: 9px;
  padding: 10px 12px;
  margin-bottom: 8px;
  background: #f6f7fb;
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
.queue { padding: 0 16px 16px; }
.queue-item {
  display: block;
  width: 100%;
  text-align: left;
  border: 1px solid #e8eaf0;
  background: #fff;
  border-radius: 9px;
  padding: 8px 10px;
  margin-bottom: 6px;
  cursor: pointer;
  font-size: 13px;
}
.queue-item:hover { border-color: #ddd6fe; background: #f5f0ff; }
</style>
