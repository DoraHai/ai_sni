<script setup>
import { geoSnapshotLink } from '../../utils/geoRoutes'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  archiveGeoCompetitorReport,
  confirmGeoCompetitorReport,
  createGeoCompetitorRecTasks,
  createGeoCompetitorReport,
  createTaskFromCompetitorReport,
  exportGeoCompetitorReport,
  fetchGeoCompetitorCompare,
  fetchGeoCompetitorDaily,
  fetchGeoCompetitorInsights,
  fetchGeoCompetitorTrace,
  getGeoCompetitorReport,
  listCompetitorAliases,
  listGeoBusinesses,
  listGeoCompetitorReports,
  listOptimizationPeriods,
  patchGeoCompetitorReport,
  putCompetitorAliases,
  restoreGeoCompetitorReport,
  saveGeoCompetitorReport,
  searchGeoCompetitorWeb,
} from '../../api/geoContent'
import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
import SampleCredibilityAlert from '../../components/SampleCredibilityAlert.vue'
import { useClientPager } from '../../composables/useClientPager'
import { useObservationPeriod } from '../../composables/useObservationPeriod'
import { session } from '../../store/session'
import {
  applyAliasMap,
  findAliasClusters,
  loadAliasMapAsync,
  saveAliasMapAsync,
} from '../../utils/competitorAlias'
import { engineDisplay, fmtPct } from '../../utils/geoReportLabels'
import { heatTone } from '../../utils/geoSnapshotSummary'
import { getGeoPrototypePageSurface } from '../../utils/geoEditorSurface'

const router = useRouter()
const prototypeSurface = getGeoPrototypePageSurface()
const { days: observationDays } = useObservationPeriod()

const tenantId = computed(() =>
  session.tenantId || (import.meta.env.DEV && import.meta.env.VITE_API_KEY ? 1 : null),
)

const loading = ref(false)
const error = ref('')
const rawItems = ref([])
const apiSummary = ref(null)
const compareSummary = ref(null)
const compareItems = ref([])
const comparePager = useClientPager(compareItems, { pageSize: 10 })
const dailyItems = ref([])
const dailyCompetitors = ref([])
const dailyNote = ref('')
const dailyDays = ref(14)
const heatMap = ref({ engines: [], rows: [] })
const aliasMap = ref({})
const displayItems = computed(() => applyAliasMap(rawItems.value, aliasMap.value))
const leadScenes = computed(() =>
  (compareItems.value || [])
    .filter((r) => r.winner === 'brand')
    .slice(0, 5),
)
const lagScenes = computed(() =>
  (compareItems.value || [])
    .filter((r) => r.winner === 'competitor')
    .slice(0, 5),
)
function sceneRank(row, side) {
  const them = row.top_competitor || '竞品'
  const btxt = row.brand_mention_rate == null ? '—' : `${Math.round(row.brand_mention_rate * 100)}%`
  const ctxt = row.top_competitor_rate == null ? '—' : `${Math.round(row.top_competitor_rate * 100)}%`
  if (side === 'brand') return `你 ${btxt} / ${them} ${ctxt}`
  return `${them} ${ctxt} / 你 ${btxt}`
}
// sync local dailyDays with global observation when possible
watch(
  observationDays,
  (d) => {
    if ([7, 14, 30].includes(Number(d))) dailyDays.value = Number(d)
  },
  { immediate: true },
)
const pager = useClientPager(displayItems, { pageSize: 20 })
const aliasClusters = computed(() =>
  findAliasClusters(rawItems.value).filter((c) => {
    const targets = new Set(c.names.map((n) => aliasMap.value[n] || n))
    return targets.size > 1
  }),
)

const summaryCards = computed(() => {
  const rows = displayItems.value
  const platforms = new Set()
  for (const row of rows) {
    for (const k of row.platform_keys || []) platforms.add(k)
  }
  const pending = rows.filter((r) => !rowHasHistory(r)).length
  return {
    competitor_count: rows.length,
    platform_count: platforms.size || apiSummary.value?.platform_count || 0,
    sources_last_7d: apiSummary.value?.sources_last_7d ?? 0,
    reports_pending: pending,
    reports_saved: serverReports.value.length,
  }
})

const drawerOpen = ref(false)
const historyOpen = ref(false)
const traceLoading = ref(false)
const reportLoading = ref(false)
const activeName = ref('')
const trace = ref(null)
const reportStep = ref(0)
const platformFilter = ref('all')
const selectedPlatforms = ref([])
const selectedUrls = ref([])
const insight = ref('')
const action = ref('')
const note = ref('')
const report = ref(null)
const reportSaved = ref(false)
const savedReport = ref(null)
const serverReports = ref([])
const expandedUrl = ref('')
const historyItems = ref([])
const sourceTableRef = ref(null)
const creatingTasks = ref(false)
const confirming = ref(false)
const exporting = ref(false)
const creatingFromReport = ref(false)
const savingEdit = ref(false)
const businesses = ref([])
const periods = ref([])
const reportBusinessId = ref(null)
const reportPeriodId = ref(null)
const archiveStatus = ref('')
const archiveBusinessId = ref(null)
const archivePeriodId = ref(null)
const webSearchLoading = ref(false)
const webSearch = ref(null)
const confirmedExternalUrls = ref([])
let autosaveTimer = null

const maxCite = computed(() =>
  Math.max(1, ...(trace.value?.platforms || []).map((p) => p.cite_count || 0)),
)

const aggregatedSources = computed(() => {
  const raw = trace.value?.sources_agg || []
  if (platformFilter.value === 'all') return raw
  return raw.filter((s) => (s.channel_key || 'other') === platformFilter.value)
})

const reportTitlePreview = computed(
  () => `竞品来源溯源报告 · ${activeName.value || '—'}`,
)

function statusLabel(status) {
  if (status === 'confirmed') return '已确认'
  if (status === 'archived') return '已归档'
  return '草稿'
}

function statusType(status) {
  if (status === 'confirmed') return 'success'
  if (status === 'archived') return 'info'
  return 'warning'
}

async function loadServerReports() {
  if (!tenantId.value) {
    serverReports.value = []
    return
  }
  try {
    const params = {}
    if (archiveStatus.value) params.status = archiveStatus.value
    if (archiveBusinessId.value) params.business_id = archiveBusinessId.value
    if (archivePeriodId.value) params.period_id = archivePeriodId.value
    const data = await listGeoCompetitorReports(tenantId.value, params)
    serverReports.value = data.items || []
  } catch {
    serverReports.value = []
  }
}

async function loadReportScopes() {
  if (!tenantId.value) {
    businesses.value = []
    periods.value = []
    return
  }
  try {
    const [b, p] = await Promise.all([
      listGeoBusinesses(tenantId.value, { status: 'active' }),
      listOptimizationPeriods(tenantId.value).catch(() => ({ items: [] })),
    ])
    businesses.value = b.items || []
    periods.value = p.items || []
    if (!reportBusinessId.value && businesses.value[0]) {
      reportBusinessId.value = businesses.value[0].id
    }
  } catch {
    businesses.value = []
    periods.value = []
  }
}

function loadHistory(competitor) {
  const all = serverReports.value || []
  historyItems.value = competitor
    ? all.filter((x) => x.competitor === competitor)
    : all
}

function hasHistory(name) {
  return (serverReports.value || []).some((x) => x.competitor === name)
}

function rowHasHistory(row) {
  const names = [row.name, ...(row.aliases || [])]
  return names.some((n) => hasHistory(n))
}

function namesForRow(row) {
  const set = new Set([row.name, ...(row.aliases || [])])
  for (const [alias, canonical] of Object.entries(aliasMap.value || {})) {
    if (canonical === row.name) set.add(alias)
  }
  return [...set]
}

function mergeTraces(parts, canonical) {
  const byUrl = new Map()
  const platforms = new Map()
  const engines = new Set()
  const promptIds = new Set()
  let mention = 0
  for (const t of parts) {
    if (!t) continue
    mention += t.mention_count || 0
    for (const e of t.engines || []) engines.add(e)
    for (const s of t.sources_agg || []) {
      const prev = byUrl.get(s.url)
      if (!prev) {
        byUrl.set(s.url, { ...s, observations: [...(s.observations || [])] })
        continue
      }
      prev.cite_count = (prev.cite_count || 0) + (s.cite_count || 0)
      prev.prompt_count = (prev.prompt_count || 0) + (s.prompt_count || 0)
      const eng = new Set([...(prev.engines || []), ...(s.engines || [])])
      prev.engines = [...eng]
      prev.observations = [...(prev.observations || []), ...(s.observations || [])]
      if (
        s.latest_captured_at &&
        (!prev.latest_captured_at || s.latest_captured_at > prev.latest_captured_at)
      ) {
        prev.latest_captured_at = s.latest_captured_at
      }
    }
    for (const p of t.platforms || []) {
      const prev = platforms.get(p.channel_key)
      if (!prev) {
        platforms.set(p.channel_key, {
          ...p,
          domains: [...(p.domains || [])],
        })
        continue
      }
      prev.cite_count = (prev.cite_count || 0) + (p.cite_count || 0)
      const dom = new Set([...(prev.domains || []), ...(p.domains || [])])
      prev.domains = [...dom]
    }
  }
  const sources_agg = [...byUrl.values()].sort(
    (a, b) => (b.cite_count || 0) - (a.cite_count || 0),
  )
  const inferred = []
  const recs = []
  let insight = ''
  let action = ''
  for (const t of parts) {
    if (!t) continue
    for (const p of t.inferred_placements || []) {
      if (!inferred.some((x) => x.channel_key === p.channel_key && x.url === p.url)) {
        inferred.push(p)
      }
    }
    for (const r of t.recommendations || []) {
      if (!recs.some((x) => x.key === r.key)) recs.push(r)
    }
    if (!insight && t.suggested_insight) insight = t.suggested_insight
    if (!action && t.suggested_action) action = t.suggested_action
  }
  return {
    competitor: canonical,
    mention_count: mention,
    prompt_count: promptIds.size || sources_agg.reduce((n, s) => n + (s.prompt_count || 0), 0),
    engines: [...engines],
    sources_agg,
    unique_url_count: sources_agg.length,
    platforms: [...platforms.values()].sort(
      (a, b) => (b.cite_count || 0) - (a.cite_count || 0),
    ),
    inferred_placements: inferred,
    recommendations: recs,
    suggested_insight: insight,
    suggested_action: action,
  }
}

async function mergeCluster(cluster, canonical) {
  const next = { ...aliasMap.value }
  for (const name of cluster.names) {
    if (name === canonical) continue
    next[name] = canonical
  }
  aliasMap.value = next
  try {
    await saveAliasMapAsync(tenantId.value, next, { putCompetitorAliases })
    ElMessage.success(`已合并为「${canonical}」（已同步租户）`)
  } catch (e) {
    ElMessage.warning(e.message || '已本地保存，同步服务器失败')
  }
}

async function unmergeName(alias) {
  const next = { ...aliasMap.value }
  delete next[alias]
  aliasMap.value = next
  try {
    await saveAliasMapAsync(tenantId.value, next, { putCompetitorAliases })
  } catch {
    /* local ok */
  }
}

async function clearAllAliases() {
  aliasMap.value = {}
  try {
    await saveAliasMapAsync(tenantId.value, {}, { putCompetitorAliases })
    ElMessage.success('已清除全部别名合并')
  } catch (e) {
    ElMessage.warning(e.message || '已本地清除')
  }
}

function formatShortTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) {
    const m = String(iso).match(/(\d{2})-(\d{2})[T\s](\d{2}):(\d{2})/)
    if (m) return `${m[1]}-${m[2]} ${m[3]}:${m[4]}`
    return String(iso).slice(0, 16).replace('T', ' ')
  }
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  return `${mm}-${dd} ${hh}:${mi}`
}

function engineTags(engines) {
  const list = engines || []
  return { head: list.slice(0, 2), more: Math.max(0, list.length - 2) }
}

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    return
  }
  loading.value = true
  error.value = ''
  aliasMap.value = await loadAliasMapAsync(tenantId.value, {
    listCompetitorAliases,
  })
  try {
    const [data, cmp, daily] = await Promise.all([
      fetchGeoCompetitorInsights(tenantId.value),
      fetchGeoCompetitorCompare(tenantId.value).catch(() => null),
      fetchGeoCompetitorDaily(tenantId.value, {
        days: dailyDays.value,
        scope_level: 'tenant',
      }).catch(() => null),
      loadServerReports(),
      loadReportScopes(),
    ])
    heatMap.value = data.engine_heatmap || { engines: [], rows: [] }
    rawItems.value = data.items || []
    apiSummary.value = data.summary || null
    compareItems.value = cmp?.items || []
    compareSummary.value = cmp?.summary || null
    dailyItems.value = daily?.items || []
    dailyCompetitors.value = daily?.competitors || []
    dailyNote.value = daily?.note || ''
  } catch (e) {
    error.value = e.message || '加载失败'
    rawItems.value = []
    heatMap.value = { engines: [], rows: [] }
    apiSummary.value = null
    compareItems.value = []
    compareSummary.value = null
    dailyItems.value = []
    dailyCompetitors.value = []
  } finally {
    loading.value = false
  }
}

const sampleComposition = computed(
  () =>
    compareSummary.value?.sample_composition ||
    apiSummary.value?.sample_composition ||
    null,
)
const sampleOk = computed(() => !!sampleComposition.value?.suitable_for_client)

const fmtRate = (v, row) => {
  if (row?.sample_insufficient || row?.rate_display === '样本不足') return '样本不足'
  if (sampleComposition.value && !sampleOk.value) return '样本不足'
  if (v == null) return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return `${(n * 100).toFixed(1)}%`
}

function winnerLabel(w) {
  if (w === 'insufficient') return '样本不足'
  if (w === 'brand') return '本品领先'
  if (w === 'competitor') return '竞品领先'
  return '持平'
}

function resetWizard() {
  reportStep.value = 0
  platformFilter.value = 'all'
  insight.value = ''
  action.value = ''
  note.value = ''
  report.value = null
  reportSaved.value = false
  expandedUrl.value = ''
  webSearch.value = null
  confirmedExternalUrls.value = []
}

async function runWebSearch() {
  if (!tenantId.value || !activeName.value) return
  webSearchLoading.value = true
  try {
    webSearch.value = await searchGeoCompetitorWeb(tenantId.value, activeName.value)
    const n = (webSearch.value.items || []).length
    ElMessage.info(
      n
        ? `找到 ${n} 条外部候选，请勾选确认后再写入报告`
        : webSearch.value.note || '没有检索到候选页',
    )
  } catch (e) {
    webSearch.value = null
    ElMessage.error(e.message || '外部检索失败')
  } finally {
    webSearchLoading.value = false
  }
}

function setExternalUrl(url, on) {
  const set = new Set(confirmedExternalUrls.value)
  if (on) set.add(url)
  else set.delete(url)
  confirmedExternalUrls.value = [...set]
}

function isExternalConfirmed(url) {
  return confirmedExternalUrls.value.includes(url)
}

function webSourceLabel(source) {
  if (source === 'web_search') return '检索命中'
  if (source === 'web_search_fallback') return '检索失败回退'
  return source || '外部页'
}

function webTrustType(trust) {
  if (trust === 'official') return 'success'
  if (trust === 'lookalike') return 'danger'
  if (trust === 'marketing' || trust === 'ugc') return 'warning'
  return 'info'
}

async function openTrace(row) {
  if (!tenantId.value || !row?.name) return
  activeName.value = row.name
  drawerOpen.value = true
  traceLoading.value = true
  resetWizard()
  loadHistory(row.name)
  try {
    const names = namesForRow(row)
    const parts = await Promise.all(
      names.map((n) => fetchGeoCompetitorTrace(tenantId.value, n).catch(() => null)),
    )
    const data =
      names.length === 1 && parts[0]
        ? parts[0]
        : mergeTraces(parts.filter(Boolean), row.name)
    trace.value = data
    selectedPlatforms.value = (data.platforms || []).map((p) => p.channel_key)
    selectedUrls.value = (data.sources_agg || []).filter((s) => s.url).map((s) => s.url)
    if (data.suggested_insight) insight.value = data.suggested_insight
    if (data.suggested_action) action.value = data.suggested_action
    await nextTick()
    await nextTick()
    sourceTableRef.value?.clearSelection?.()
    for (const src of data.sources_agg || []) {
      sourceTableRef.value?.toggleRowSelection?.(src, true)
    }
  } catch (e) {
    trace.value = null
    ElMessage.error(e.message || '溯源失败')
  } finally {
    traceLoading.value = false
  }
}

function togglePlatformCard(key) {
  const set = new Set(selectedPlatforms.value)
  if (set.has(key)) set.delete(key)
  else set.add(key)
  selectedPlatforms.value = [...set]
  // Keep URL selection aligned with selected platforms when filtering
  const allowed = new Set(selectedPlatforms.value)
  selectedUrls.value = (trace.value?.sources_agg || [])
    .filter((s) => allowed.has(s.channel_key || 'other'))
    .map((s) => s.url)
  platformFilter.value = key
}

function selectAllPlatforms() {
  selectedPlatforms.value = (trace.value?.platforms || []).map((p) => p.channel_key)
  selectedUrls.value = (trace.value?.sources_agg || []).map((s) => s.url)
  platformFilter.value = 'all'
}

function onSourceSelection(rows) {
  selectedUrls.value = rows.map((r) => r.url)
}

function goStep(n) {
  const hasInferred = (trace.value?.inferred_placements || []).length > 0
  if (
    n === 1
    && !selectedUrls.value.length
    && !selectedPlatforms.value.length
    && !hasInferred
  ) {
    ElMessage.warning('请先选择至少一个平台或来源')
    return
  }
  reportStep.value = n
}

async function createRecTasks(recs) {
  const items = (recs || []).filter((r) => r.prompt_id)
  if (!items.length) {
    ElMessage.warning('这些建议还没有关联意图词，无法建任务')
    return
  }
  creatingTasks.value = true
  try {
    const res = await createGeoCompetitorRecTasks({
      tenant_id: tenantId.value,
      competitor: activeName.value,
      items: items.map((r) => ({
        prompt_id: r.prompt_id,
        title: r.title,
        channel_key: r.channel_key,
        reason: r.reason,
        sample_question: r.sample_question,
      })),
    })
    const n = res.created_count || 0
    const skip = res.skipped_count || 0
    ElMessage.success(
      n
        ? `已建 ${n} 条任务${skip ? `，跳过 ${skip} 条已有任务` : ''}`
        : skip
          ? `未新建：${skip} 条意图词已有任务`
          : '没有可建的任务',
    )
    const first = (res.created || [])[0]
    if (first?.editor_path) router.push(first.editor_path)
  } catch (e) {
    ElMessage.error(e.message || '建任务失败')
  } finally {
    creatingTasks.value = false
  }
}

async function genAndSaveReport() {
  if (!tenantId.value || !activeName.value) return
  reportLoading.value = true
  try {
    report.value = await createGeoCompetitorReport({
      tenant_id: tenantId.value,
      competitor: activeName.value,
      source_urls: selectedUrls.value,
      platform_keys: selectedPlatforms.value,
      confirmed_external_urls: confirmedExternalUrls.value,
      insight: insight.value || null,
      action: action.value || null,
      note: note.value || null,
    })
    savedReport.value = await saveGeoCompetitorReport({
      tenant_id: tenantId.value,
      competitor: activeName.value,
      title: report.value.title,
      business_id: reportBusinessId.value || null,
      period_id: reportPeriodId.value || null,
      insight: insight.value || null,
      action: action.value || null,
      note: note.value || null,
      markdown: report.value.markdown,
      source_urls: selectedUrls.value,
      platform_keys: selectedPlatforms.value,
      evidence: {
        source_count: report.value.source_count,
        platform_count: report.value.platform_count,
        generated_at: report.value.generated_at,
        recommendations: (trace.value?.recommendations || []).slice(0, 8),
        confirmed_external_urls: confirmedExternalUrls.value,
        external_confirmed_count: report.value.external_confirmed_count || 0,
      },
      status: 'draft',
    })
    reportSaved.value = true
    await loadServerReports()
    loadHistory(activeName.value)
    reportStep.value = 2
    ElMessage.success('报告草稿已保存到服务端，可继续修改后确认归档')
  } catch (e) {
    ElMessage.error(e.message || '生成报告失败')
  } finally {
    reportLoading.value = false
  }
}

async function saveReportEdits() {
  if (!tenantId.value || !savedReport.value?.id) return
  savingEdit.value = true
  try {
    savedReport.value = await patchGeoCompetitorReport(tenantId.value, savedReport.value.id, {
      business_id: reportBusinessId.value || null,
      period_id: reportPeriodId.value || null,
      insight: insight.value || null,
      action: action.value || null,
      note: note.value || null,
      markdown: report.value?.markdown || savedReport.value.markdown,
    })
    if (report.value) {
      report.value = { ...report.value, markdown: savedReport.value.markdown }
    }
    ElMessage.success(`已保存第 ${savedReport.value.version_no || ''} 版`)
    await loadServerReports()
  } catch (e) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    savingEdit.value = false
  }
}

async function confirmSavedReport() {
  if (!tenantId.value || !savedReport.value?.id) return
  confirming.value = true
  try {
    savedReport.value = await confirmGeoCompetitorReport(tenantId.value, savedReport.value.id)
    ElMessage.success('报告已确认')
    await loadServerReports()
  } catch (e) {
    ElMessage.error(e.message || '确认失败')
  } finally {
    confirming.value = false
  }
}

async function archiveSavedReport() {
  if (!tenantId.value || !savedReport.value?.id) return
  confirming.value = true
  try {
    savedReport.value = await archiveGeoCompetitorReport(tenantId.value, savedReport.value.id)
    ElMessage.success('报告已归档')
    await loadServerReports()
  } catch (e) {
    ElMessage.error(e.message || '归档失败')
  } finally {
    confirming.value = false
  }
}

async function exportSaved(format = 'md') {
  const id = savedReport.value?.id
  if (!tenantId.value || !id) {
    downloadReport()
    return
  }
  exporting.value = true
  try {
    const text = await exportGeoCompetitorReport(tenantId.value, id, format)
    const title = savedReport.value.title || report.value?.title || activeName.value
    const safe = String(title || 'competitor').replace(/[\\/:*?"<>|]/g, '_')
    const mime = format === 'md' ? 'text/markdown;charset=utf-8' : 'text/html;charset=utf-8'
    const ext = format === 'html' || format === 'pdf' ? 'html' : 'md'
    const blob = new Blob([text], { type: mime })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${safe}.${ext}`
    a.click()
    URL.revokeObjectURL(url)
    if (format === 'pdf') {
      ElMessage.info('已下载可打印 HTML，用浏览器打开后另存 PDF')
    }
  } catch (e) {
    ElMessage.error(e.message || '导出失败')
  } finally {
    exporting.value = false
  }
}

async function createTaskFromSaved() {
  if (!tenantId.value || !savedReport.value?.id) return
  creatingFromReport.value = true
  try {
    const res = await createTaskFromCompetitorReport(tenantId.value, savedReport.value.id)
    if (res.editor_path) {
      ElMessage.success(res.created ? '已从报告结论创建任务' : res.reason || '已打开已有任务')
      router.push(res.editor_path)
    }
  } catch (e) {
    ElMessage.error(e.message || '建任务失败')
  } finally {
    creatingFromReport.value = false
  }
}

async function copyReport(md) {
  const text = md || report.value?.markdown
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制 Markdown')
  } catch {
    ElMessage.error('复制失败')
  }
}

function downloadReport(payload) {
  const md = payload?.markdown || report.value?.markdown
  const title = payload?.title || report.value?.title || activeName.value
  if (!md) return
  const safe = String(title || 'competitor').replace(/[\\/:*?"<>|]/g, '_')
  const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${safe}.md`
  a.click()
  URL.revokeObjectURL(url)
}

function openHistory() {
  loadHistory(activeName.value)
  historyOpen.value = true
}

function scheduleAutosave() {
  if (!savedReport.value?.id) return
  if (autosaveTimer) clearTimeout(autosaveTimer)
  autosaveTimer = setTimeout(() => {
    saveReportEdits()
  }, 1400)
}

async function restoreVersion(versionNo) {
  if (!tenantId.value || !savedReport.value?.id || !versionNo) return
  savingEdit.value = true
  try {
    savedReport.value = await restoreGeoCompetitorReport(
      tenantId.value,
      savedReport.value.id,
      versionNo,
    )
    insight.value = savedReport.value.insight || ''
    action.value = savedReport.value.action || ''
    note.value = savedReport.value.note || ''
    if (report.value) {
      report.value = { ...report.value, markdown: savedReport.value.markdown }
    } else {
      report.value = savedReport.value
    }
    ElMessage.success(`已回滚到 v${versionNo}，并生成新版本`)
    await loadServerReports()
  } catch (e) {
    ElMessage.error(e.message || '回滚失败')
  } finally {
    savingEdit.value = false
  }
}

async function viewHistoryItem(item) {
  try {
    const full = item.id
      ? await getGeoCompetitorReport(tenantId.value, item.id)
      : item
    report.value = full
    savedReport.value = full
    insight.value = full.insight || ''
    action.value = full.action || ''
    note.value = full.note || ''
    reportBusinessId.value = full.business_id || reportBusinessId.value
    reportPeriodId.value = full.period_id || null
    reportSaved.value = true
    reportStep.value = 2
    historyOpen.value = false
  } catch (e) {
    ElMessage.error(e.message || '打开报告失败')
  }
}

watch([insight, action, note], () => {
  if (savedReport.value?.id && reportStep.value === 2) scheduleAutosave()
})
watch([archiveStatus, archiveBusinessId, archivePeriodId], () => {
  loadServerReports().then(() => loadHistory(activeName.value))
})

watch(tenantId, load)
onMounted(load)
</script>

<template>
  <GeoWorkbenchPage
    title="竞品分析"
    sub="你与竞品在各 AI 引擎中的提及率对比"
    :loading="loading"
  >
    <template #actions>
      <button class="gd-btn" @click="load">刷新</button>
      <button class="gd-btn" @click="router.push('/geo/brand')">管理竞品</button>
    </template>
    <div class="geo-dash geo-page">
    <p class="gd-sub">统计口径：当前活动问题的合格真实快照；概览与同题对比使用全部历史，日序列按所选上海日期统计。服务端名称仅合并大小写和首尾空格；概览的人工别名按快照去重，同题和日序列不套用人工别名。回答中的来源链接不代表竞品拥有该页面；本页不等同于驾驶舱完整自然周指标。</p>

    <details v-if="prototypeSurface.showCompetitorAdvancedAnalysis" class="geo-glossary">
      <summary>统计口径（点击展开）</summary>
      <ul>
        <li>竞品名来自快照 competitors 字段（人工或 AI 建议）。</li>
        <li>日监测按上海日期从合格快照只读计算；刷新不会补写历史数据。</li>
        <li>同题对比：同一意图词下本品提及 vs 竞品提及。</li>
        <li>竞品报告保存在服务端：草稿 → 确认 → 归档，支持版本、导出和从结论建任务。</li>
        <li>人工别名优先保存服务端，本机缓存作兼容；概览按证据去重，不改原始快照。</li>
      </ul>
    </details>

    <el-alert v-if="error" :title="error" type="error" :closable="false" class="mb" />
    <SampleCredibilityAlert
      v-if="prototypeSurface.showCompetitorAdvancedAnalysis"
      :composition="sampleComposition"
      window-label="竞品页与交付摘要同一套样本门槛"
    />

    <div v-if="heatMap.engines.length" class="gd-card" style="margin-bottom:16px">
      <div class="gd-hd">
        <h3>品牌 × AI 引擎 提及率热力图</h3>
        <span class="more">每引擎不足 8 条显示未知；颜色越深提及率越高</span>
      </div>
      <div class="gd-bd" style="padding:0;overflow:auto">
        <table class="gd-heat">
          <thead>
            <tr>
              <th>品牌</th>
              <th v-for="e in heatMap.engines" :key="e">{{ engineDisplay(e) }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in heatMap.rows" :key="r.name" :class="{ 'own-row': r.own }">
              <td>{{ r.own ? '本品牌' : r.name }}</td>
              <td
                v-for="(cell, i) in r.cells"
                :key="i"
                :style="{ background: heatTone(cell).bg, color: heatTone(cell).fg }"
              >{{ fmtPct(cell) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="gd-mid" style="margin-bottom:16px">
      <div class="gd-card">
        <div class="gd-hd"><h3>你领先的提问场景</h3></div>
        <div class="gd-bd">
          <ul class="gd-sources">
            <li
              v-for="r in leadScenes"
              :key="'lead-'+r.prompt_id"
              class="geo-click"
              @click="router.push(geoSnapshotLink({ prompt_id: r.prompt_id }))"
            >
              <span class="gd-badge green">领先</span>
              {{ r.question }}
              <span class="gd-sub" style="margin-left:auto">{{ sceneRank(r, 'brand') }}</span>
            </li>
            <li v-if="!leadScenes.length" class="gd-sub">暂无本品领先的提问</li>
          </ul>
        </div>
      </div>
      <div class="gd-card">
        <div class="gd-hd"><h3>竞品领先的提问场景</h3></div>
        <div class="gd-bd">
          <ul class="gd-sources">
            <li
              v-for="r in lagScenes"
              :key="'lag-'+r.prompt_id"
              class="geo-click"
              @click="router.push(geoSnapshotLink({ prompt_id: r.prompt_id }))"
            >
              <span class="gd-badge red">落后</span>
              {{ r.question }}
              <span class="gd-sub" style="margin-left:auto">{{ sceneRank(r, 'comp') }}</span>
            </li>
            <li v-if="!lagScenes.length" class="gd-sub">暂无竞品领先的提问</li>
          </ul>
        </div>
      </div>
    </div>


    <template v-if="prototypeSurface.showCompetitorAdvancedAnalysis">
    <div class="geo-kpi-grid">
      <div class="geo-kpi">
        <div class="kpi-label">竞品数</div>
        <div class="kpi-value">{{ summaryCards.competitor_count }}</div>
        <div class="kpi-hint">按人工别名及快照去重</div>
      </div>
      <div class="geo-kpi">
        <div class="kpi-label">被引用平台数</div>
        <div class="kpi-value">{{ summaryCards.platform_count }}</div>
        <div class="kpi-hint">全竞品来源平台去重</div>
      </div>
      <div class="geo-kpi">
        <div class="kpi-label">近 7 天出现的来源</div>
        <div class="kpi-value">{{ summaryCards.sources_last_7d }}</div>
        <div class="kpi-hint">滚动 168 小时内的去重 URL，非首次新增</div>
      </div>
      <div class="geo-kpi">
        <div class="kpi-label">待生成报告数</div>
        <div class="kpi-value">{{ summaryCards.reports_pending }}</div>
        <div class="kpi-hint">服务端尚未存档 · 已存 {{ summaryCards.reports_saved || 0 }}</div>
      </div>
    </div>

    <section v-if="compareSummary" class="panel mb">
      <div class="panel-title">同题集 · 本品 vs 竞品</div>
      <div class="compare-sum mb">
        提问 {{ compareSummary.prompt_count || 0 }} ·
        本品领先 {{ compareSummary.brand_lead || 0 }} ·
        竞品领先 {{ compareSummary.competitor_lead || 0 }} ·
        持平 {{ compareSummary.tie || 0 }}
      </div>
      <el-table
        :data="comparePager.pagedItems"
        size="small"
        empty-text="暂无可比对快照"
        class="clickable-rows"
        @row-click="(row) => row.prompt_id && router.push(geoSnapshotLink({ prompt_id: row.prompt_id }))"
      >
        <el-table-column label="提问" min-width="200">
          <template #default="{ row }">
            <div class="q-clamp" :title="row.question">{{ row.question }}</div>
          </template>
        </el-table-column>
        <el-table-column label="本品提及" width="96">
          <template #default="{ row }">{{ fmtRate(row.brand_mention_rate, row) }}</template>
        </el-table-column>
        <el-table-column label="本品首位" width="96">
          <template #default="{ row }">{{ fmtRate(row.brand_first_rate, row) }}</template>
        </el-table-column>
        <el-table-column label="最强竞品" min-width="140">
          <template #default="{ row }">
            <span v-if="row.top_competitor">
              {{ row.top_competitor }} · {{ fmtRate(row.top_competitor_rate, row) }}
            </span>
            <span v-else class="dim">—</span>
          </template>
        </el-table-column>
        <el-table-column label="结果" width="100">
          <template #default="{ row }">
            <el-tag
              size="small"
              :type="row.winner === 'brand' ? 'success' : row.winner === 'competitor' ? 'danger' : 'info'"
            >
              {{ winnerLabel(row.winner) }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
      <div class="geo-pager">
        <el-pagination
          background
          small
          layout="total, prev, pager, next"
          :total="comparePager.total"
          :page-size="comparePager.pageSize"
          :current-page="comparePager.page"
          @current-change="comparePager.onPageChange"
        />
      </div>
    </section>

    <section class="panel mb">
      <div class="panel-title" style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;align-items:center">
        <span>多层级日监测（租户 × 天）</span>
        <span style="display:flex;gap:8px;align-items:center">
          <el-select v-model="dailyDays" style="width:110px" @change="load">
            <el-option :value="7" label="近 7 天" />
            <el-option :value="14" label="近 14 天" />
            <el-option :value="30" label="近 30 天" />
          </el-select>
        </span>
      </div>
      <p class="dim mb">
        {{ dailyNote || '日监测看租户级；缺行时刷新会静默补算。建议与顶栏观察期保持一致。' }}
      </p>
      <div v-if="dailyCompetitors.length" class="mb" style="font-size:13px;color:#4b5563">
        窗口内竞品累计：
        <span v-for="(c, i) in dailyCompetitors.slice(0, 8)" :key="c.name">
          {{ i ? ' · ' : '' }}{{ c.name }} ({{ c.mentions }})
        </span>
      </div>
      <el-table :data="dailyItems" size="small" empty-text="暂无日指标：跑巡检或登记快照后刷新">
        <el-table-column prop="metric_date" label="日期" width="120" />
        <el-table-column label="本品提及率" width="110">
          <template #default="{ row }">{{ fmtRate(row.brand_mention_rate) }}</template>
        </el-table-column>
        <el-table-column label="领先竞品" min-width="160">
          <template #default="{ row }">
            <span v-if="row.top_competitor">
              {{ row.top_competitor }} · {{ fmtRate(row.top_competitor_rate) }}
            </span>
            <span v-else class="dim">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="any_competitor_mentions" label="含竞品快照" width="110" />
        <el-table-column prop="snapshots_visibility" label="可见快照" width="100" />
      </el-table>
    </section>

    <section v-if="aliasClusters.length || Object.keys(aliasMap).length" class="panel alias-panel mb">
      <div class="panel-title-row">
        <div class="panel-title">别名合并</div>
        <el-button
          v-if="Object.keys(aliasMap).length"
          size="small"
          link
          type="danger"
          @click="clearAllAliases"
        >清除全部合并</el-button>
      </div>
      <div v-if="aliasClusters.length" class="alias-list">
        <div v-for="c in aliasClusters" :key="c.key" class="alias-card">
          <div class="alias-flag">疑似同一竞品</div>
          <div class="alias-names">{{ c.names.join(' · ') }}</div>
          <div class="alias-actions">
            <span class="alias-hint">合并到</span>
            <el-button
              v-for="n in c.names"
              :key="n"
              size="small"
              type="primary"
              plain
              @click="mergeCluster(c, n)"
            >{{ n }}</el-button>
          </div>
        </div>
      </div>
      <div v-else class="alias-empty">当前列表无明显别名冲突</div>
      <div v-if="Object.keys(aliasMap).length" class="merged-map">
        <span class="alias-hint">已合并：</span>
        <el-tag
          v-for="(canonical, alias) in aliasMap"
          :key="alias"
          size="small"
          closable
          class="merged-tag"
          @close="unmergeName(alias)"
        >{{ alias }} → {{ canonical }}</el-tag>
      </div>
    </section>

    <section class="panel">
      <div class="panel-title">竞品提及聚合</div>
      <el-table
        :data="pager.pagedItems"
        size="small"
        empty-text="暂无竞品标注 · 在「AI 可见度」保存快照时填写竞品名"
        class="clickable-rows"
        @row-click="(row) => openTrace(row)"
      >
        <el-table-column prop="name" label="竞品" min-width="140">
          <template #default="{ row }">
            <div class="row-link">{{ row.name }}</div>
            <div v-if="(row.aliases || []).length" class="alias-sub">
              含别名 {{ row.aliases.join('、') }}
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="mention_count" label="出现" width="72" />
        <el-table-column prop="source_count" label="来源" width="72" />
        <el-table-column prop="platform_count" label="平台" width="72" />
        <el-table-column prop="prompt_count" label="提问" width="72" />
        <el-table-column label="引擎" min-width="120">
          <template #default="{ row }">
            <template v-if="(row.engines || []).length">
              <el-tag
                v-for="e in engineTags(row.engines).head"
                :key="e"
                size="small"
                class="eng-tag"
              >{{ e }}</el-tag>
              <el-tag v-if="engineTags(row.engines).more" size="small" type="info" class="eng-tag">
                +{{ engineTags(row.engines).more }}
              </el-tag>
            </template>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="最近观测" width="110">
          <template #default="{ row }">{{ formatShortTime(row.latest_captured_at) }}</template>
        </el-table-column>
        <el-table-column label="样例提问" min-width="160">
          <template #default="{ row }">
            <div class="q-clamp" :title="row.sample_prompt_question || ''">
              {{ row.sample_prompt_question || '—' }}
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="168" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link @click.stop="openTrace(row)">
              查看来源（{{ row.source_count || 0 }}）
            </el-button>
            <div class="report-state" :class="rowHasHistory(row) ? 'ok' : 'dim'">
              {{ rowHasHistory(row) ? '已生成报告' : '未生成报告' }}
            </div>
          </template>
        </el-table-column>
      </el-table>
      <div class="geo-pager">
        <el-pagination
          background
          layout="total, sizes, prev, pager, next"
          :total="pager.total"
          :page-size="pager.pageSize"
          :current-page="pager.page"
          :page-sizes="[10, 20, 50, 100]"
          @current-change="pager.onPageChange"
          @size-change="pager.onSizeChange"
        />
      </div>
    </section>

    <el-drawer
      v-model="drawerOpen"
      :title="`竞品溯源 · ${activeName || ''}`"
      size="640px"
      destroy-on-close
    >
      <div v-loading="traceLoading" class="drawer-body">
        <template v-if="trace">
          <div class="stats mb">
            提及 {{ trace.mention_count || 0 }} · 提问 {{ trace.prompt_count || 0 }} ·
            真实引用 {{ trace.cited_url_count ?? (trace.sources_agg || []).length }} ·
            真实平台 {{ (trace.platforms || []).filter((p) => !p.inferred).length }}
            <span v-if="(trace.inferred_placements || []).length" class="infer-flag">
              · 推定阵地 {{ trace.inferred_placements.length }}（不计引用）
            </span>
          </div>

          <el-steps :active="reportStep" finish-status="success" align-center class="mb steps">
            <el-step title="选择平台/来源" />
            <el-step title="洞察与行动" />
            <el-step title="确认并归档" />
          </el-steps>

          <!-- Step 1 -->
          <div v-show="reportStep === 0">
            <div class="section-head">
              <span class="section-title">发布平台（主视图）</span>
              <el-button size="small" link type="primary" @click="selectAllPlatforms">全选</el-button>
              <el-button
                size="small"
                link
                @click="platformFilter = 'all'"
              >查看全部 URL</el-button>
            </div>
            <div v-if="!(trace.platforms || []).length" class="empty-hint mb">
              本次回答没有引用 URL，也没有匹配到竞品阵地库。
            </div>
            <div v-else class="plat-grid mb">
              <button
                v-for="p in trace.platforms"
                :key="p.channel_key"
                type="button"
                class="plat-card"
                :class="{
                  selected: selectedPlatforms.includes(p.channel_key),
                  filtering: platformFilter === p.channel_key,
                }"
                @click="togglePlatformCard(p.channel_key)"
              >
                <div class="plat-name">{{ p.channel_name }}</div>
                <div class="plat-count">
                  {{ p.inferred ? '推定阵地' : `${p.cite_count} 次引用` }}
                </div>
                <div class="plat-bar">
                  <i :style="{ width: `${Math.round((p.cite_count / maxCite) * 100)}%` }" />
                </div>
                <div class="plat-domains">{{ (p.domains || []).slice(0, 2).join(' · ') || '—' }}</div>
              </button>
            </div>

            <div v-if="(trace.inferred_placements || []).length" class="infer-box mb">
              <div class="section-title">推定参考阵地（不是本次 AI 引用）</div>
              <p class="infer-hint">
                这些来自竞品阵地库，不是快照 cited_urls。不能计入来源数，也不能写成「检索到的发布位置」。
              </p>
              <ul class="infer-list">
                <li v-for="(p, i) in trace.inferred_placements" :key="i">
                  <span class="infer-ch">{{ p.channel_name }}</span>
                  <span>{{ p.label }}</span>
                  <a v-if="p.url" :href="p.url" target="_blank" rel="noopener">{{ p.url }}</a>
                  <span v-else class="dim">无稳定公开 URL</span>
                </li>
              </ul>
            </div>

            <div class="web-box mb">
              <div class="section-head">
                <span class="section-title">外部检索候选（不是本次引用）</span>
                <el-button
                  size="small"
                  type="primary"
                  plain
                  :loading="webSearchLoading"
                  @click="runWebSearch"
                >检索公开页</el-button>
              </div>
              <p class="web-hint">
                公开网页检索结果，与快照 cited_urls、推定阵地分栏。勾选确认后才会写入报告附录，不会改来源数。
              </p>
              <div v-if="webSearch?.note" class="web-note">{{ webSearch.note }}</div>
              <div v-if="(webSearch?.errors || []).length" class="web-err">
                检索部分失败：{{ webSearch.errors.slice(0, 2).join('；') }}
              </div>
              <ul v-if="(webSearch?.items || []).length" class="web-list">
                <li v-for="it in webSearch.items" :key="it.url">
                  <el-checkbox
                    :model-value="isExternalConfirmed(it.url)"
                    @change="(v) => setExternalUrl(it.url, v)"
                  >
                    <span class="web-title">{{ it.title }}</span>
                  </el-checkbox>
                  <div class="web-meta">
                    <el-tag
                      size="small"
                      :type="it.source === 'web_search' ? 'success' : 'warning'"
                    >{{ webSourceLabel(it.source) }}</el-tag>
                    <el-tag
                      size="small"
                      :type="webTrustType(it.trust)"
                    >{{ it.label || '未核验域名' }}</el-tag>
                    <a :href="it.url" target="_blank" rel="noopener">{{ it.url }}</a>
                  </div>
                </li>
              </ul>
              <div v-if="confirmedExternalUrls.length" class="web-picked">
                已确认 {{ confirmedExternalUrls.length }} 条，将写入「人工确认的外部检索页」
              </div>
            </div>

            <div v-if="(trace.recommendations || []).length" class="rec-box mb">
              <div class="section-head">
                <span class="section-title">GEO 逆向建议</span>
                <el-button
                  size="small"
                  type="primary"
                  :loading="creatingTasks"
                  @click="createRecTasks(trace.recommendations)"
                >全部建任务</el-button>
              </div>
              <div v-for="r in trace.recommendations" :key="r.key" class="rec-card">
                <div class="rec-title">{{ r.title }}</div>
                <div class="rec-meta">
                  {{ r.form }} · {{ r.question_group }} · {{ r.channel_name || r.channel_key }}
                </div>
                <div class="rec-reason">{{ r.reason }}</div>
                <div class="rec-actions">
                  <el-button
                    size="small"
                    :disabled="!r.prompt_id"
                    :loading="creatingTasks"
                    @click="createRecTasks([r])"
                  >建任务</el-button>
                </div>
              </div>
            </div>

            <div class="section-head">
              <span class="section-title">来源 URL（按地址去重）</span>
              <span class="sec-meta">
                已选 {{ selectedUrls.length }} /
                {{ aggregatedSources.length }}
                <template v-if="platformFilter !== 'all'">
                  · 筛选：{{ platformFilter }}
                </template>
              </span>
            </div>
            <el-table
              ref="sourceTableRef"
              :data="aggregatedSources"
              size="small"
              class="mb"
              row-key="url"
              max-height="320"
              empty-text="无引用 URL"
              @selection-change="onSourceSelection"
            >
              <el-table-column type="selection" width="42" reserve-selection />
              <el-table-column label="URL" min-width="200">
                <template #default="{ row }">
                  <div class="url-main" :title="row.url">{{ row.url }}</div>
                  <div class="url-sub">
                    {{ row.channel_name || row.domain }}
                    <el-button
                      v-if="(row.observations || []).length > 1"
                      link
                      type="primary"
                      size="small"
                      @click="expandedUrl = expandedUrl === row.url ? '' : row.url"
                    >
                      {{ expandedUrl === row.url ? '收起观测' : `展开 ${row.observations.length} 次观测` }}
                    </el-button>
                  </div>
                  <ul v-if="expandedUrl === row.url" class="obs-list">
                    <li v-for="(o, i) in row.observations" :key="i">
                      {{ formatShortTime(o.captured_at) }} · {{ o.engine || '—' }}
                      <span v-if="o.prompt_question"> · {{ o.prompt_question }}</span>
                    </li>
                  </ul>
                </template>
              </el-table-column>
              <el-table-column prop="cite_count" label="引用" width="64" />
              <el-table-column prop="prompt_count" label="提问" width="64" />
              <el-table-column label="引擎" width="110">
                <template #default="{ row }">
                  <el-tag
                    v-for="e in engineTags(row.engines).head"
                    :key="e"
                    size="small"
                    class="eng-tag"
                  >{{ e }}</el-tag>
                  <span v-if="engineTags(row.engines).more" class="more">+{{ engineTags(row.engines).more }}</span>
                </template>
              </el-table-column>
              <el-table-column label="最近" width="100">
                <template #default="{ row }">{{ formatShortTime(row.latest_captured_at) }}</template>
              </el-table-column>
            </el-table>

            <div class="preview-strip mb">
              <div>预览标题：{{ reportTitlePreview }}</div>
              <div>
                已选来源 {{ selectedUrls.length }} · 已选平台 {{ selectedPlatforms.length }}
                · 确认外部页 {{ confirmedExternalUrls.length }}
              </div>
            </div>
            <div class="actions">
              <el-button type="primary" @click="goStep(1)">下一步：补充洞察</el-button>
              <el-button @click="openHistory">查看历史报告</el-button>
            </div>
          </div>

          <!-- Step 2 -->
          <div v-show="reportStep === 1">
            <div class="preview-strip mb">
              <div>{{ reportTitlePreview }}</div>
              <div>
                将写入报告：来源 {{ selectedUrls.length }} · 平台 {{ selectedPlatforms.length }}
                · 确认外部页 {{ confirmedExternalUrls.length }}
              </div>
            </div>
            <el-form label-position="top">
              <el-form-item label="洞察（竞品内容落点与含义）">
                <el-input
                  v-model="insight"
                  type="textarea"
                  :rows="4"
                  placeholder="例：该竞品在知乎高密度出现，问答体为主，偏选型对比场景…"
                />
              </el-form-item>
              <el-form-item label="行动建议">
                <el-input
                  v-model="action"
                  type="textarea"
                  :rows="3"
                  placeholder="例：补齐官网对比页 + 知乎机构号长文；优先覆盖同类提问…"
                />
              </el-form-item>
              <el-form-item label="备注（可选）">
                <el-input v-model="note" type="textarea" :rows="2" />
              </el-form-item>
            </el-form>
            <div class="actions">
              <el-button @click="reportStep = 0">上一步</el-button>
              <el-button type="primary" :loading="reportLoading" @click="genAndSaveReport">
                生成并保存草稿
              </el-button>
            </div>
          </div>

          <!-- Step 3 -->
          <div v-show="reportStep === 2">
            <el-result
              :icon="reportSaved ? 'success' : 'info'"
              :title="reportSaved ? '报告草稿已存档' : '报告已生成'"
              :sub-title="savedReport?.title || report?.title || ''"
            >
              <template #extra>
                <div class="preview-strip mb">
                  来源 {{ report?.source_count ?? selectedUrls.length }} ·
                  平台 {{ report?.platform_count ?? selectedPlatforms.length }} ·
                  状态 {{ statusLabel(savedReport?.status) }} ·
                  版本 v{{ savedReport?.version_no || 1 }}
                </div>
                <el-form v-if="savedReport && report" label-position="top" class="mb">
                  <el-form-item label="归档到业务">
                    <el-select v-model="reportBusinessId" clearable filterable placeholder="选择业务线" style="width:100%">
                      <el-option v-for="b in businesses" :key="b.id" :label="b.name" :value="b.id" />
                    </el-select>
                  </el-form-item>
                  <el-form-item label="优化期次">
                    <el-select v-model="reportPeriodId" clearable filterable placeholder="可选" style="width:100%">
                      <el-option v-for="p in periods" :key="p.id" :label="p.name || ('期次 #' + p.id)" :value="p.id" />
                    </el-select>
                  </el-form-item>
                  <el-form-item label="结论（可改，自动保存）">
                    <el-input v-model="insight" type="textarea" :rows="3" />
                  </el-form-item>
                  <el-form-item label="行动建议（可改，自动保存）">
                    <el-input v-model="action" type="textarea" :rows="2" />
                  </el-form-item>
                  <el-form-item label="报告正文 Markdown">
                    <el-input v-model="report.markdown" type="textarea" :rows="10" @input="scheduleAutosave" />
                  </el-form-item>
                </el-form>
                <div class="actions">
                  <el-button :loading="savingEdit" @click="saveReportEdits">保存修改</el-button>
                  <el-button
                    type="success"
                    :loading="confirming"
                    :disabled="savedReport?.status === 'confirmed'"
                    @click="confirmSavedReport"
                  >确认</el-button>
                  <el-button :loading="confirming" @click="archiveSavedReport">归档</el-button>
                  <el-button
                    type="primary"
                    :loading="creatingFromReport"
                    @click="createTaskFromSaved"
                  >从结论建任务</el-button>
                  <el-button type="primary" plain @click="copyReport()">复制 Markdown</el-button>
                  <el-button :loading="exporting" @click="exportSaved('md')">导出 MD</el-button>
                  <el-button :loading="exporting" @click="exportSaved('html')">导出 HTML</el-button>
                  <el-button :loading="exporting" @click="exportSaved('pdf')">导出 PDF</el-button>
                  <el-button @click="openHistory">历史版本</el-button>
                  <el-button @click="reportStep = 0">继续调整选择</el-button>
                </div>
              </template>
            </el-result>
            <div v-if="report?.markdown" class="report-box">
              <pre class="report-md">{{ report.markdown }}</pre>
            </div>
          </div>
        </template>
        <el-empty v-else-if="!traceLoading" description="暂无溯源数据" />
      </div>
    </el-drawer>
    </template>

    <el-drawer v-model="historyOpen" title="服务端报告档案" size="420px">
      <div class="mb" style="display:flex;gap:8px;flex-wrap:wrap">
        <el-select v-model="archiveStatus" clearable placeholder="状态" style="width:110px">
          <el-option label="草稿" value="draft" />
          <el-option label="已确认" value="confirmed" />
          <el-option label="已归档" value="archived" />
        </el-select>
        <el-select v-model="archiveBusinessId" clearable filterable placeholder="业务" style="width:140px">
          <el-option v-for="b in businesses" :key="b.id" :label="b.name" :value="b.id" />
        </el-select>
        <el-select v-model="archivePeriodId" clearable filterable placeholder="期次" style="width:140px">
          <el-option v-for="p in periods" :key="p.id" :label="p.name || ('#' + p.id)" :value="p.id" />
        </el-select>
      </div>
      <div v-if="savedReport?.versions?.length" class="mb">
        <div class="section-title">当前报告版本</div>
        <div v-for="v in savedReport.versions" :key="v.version_no" class="hist-card">
          <div class="hist-meta">v{{ v.version_no }} · {{ formatShortTime(v.created_at) }}</div>
          <el-button size="small" link type="primary" @click="restoreVersion(v.version_no)">回滚到此版</el-button>
        </div>
      </div>
      <div v-if="!historyItems.length" class="empty-hint">暂无已保存报告</div>
      <div v-for="h in historyItems" :key="h.id" class="hist-card">
        <div class="hist-title">{{ h.title }}</div>
        <div class="hist-meta">
          <el-tag size="small" :type="statusType(h.status)">{{ statusLabel(h.status) }}</el-tag>
          · v{{ h.version_no || 1 }}
          · {{ formatShortTime(h.updated_at || h.created_at) }}
        </div>
        <div class="actions">
          <el-button size="small" type="primary" link @click="viewHistoryItem(h)">查看</el-button>
          <el-button size="small" link @click="copyReport(h.markdown)">复制</el-button>
          <el-button size="small" link @click="downloadReport(h)">下载</el-button>
        </div>
      </div>
    </el-drawer>
    </div>
  </GeoWorkbenchPage>
</template>

<style scoped>
.clickable-rows :deep(tbody tr) { cursor: pointer; }
.row-link { color: #185fa5; font-weight: 600; }
.geo-comp { padding: 4px 2px 24px; }
.page-header {
  display: flex; justify-content: space-between; gap: 16px; margin-bottom: 16px; flex-wrap: wrap;
}
.page-title { font-size: 20px; font-weight: 650; color: #1f2937; }
.page-desc { margin-top: 4px; font-size: 13px; color: #6b7280; max-width: 52rem; line-height: 1.5; }
.header-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.mb { margin-bottom: 14px; }
.panel {
  background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px 18px;
}
.panel-title { font-size: 14px; font-weight: 600; color: #374151; margin-bottom: 12px; }
.panel-title-row {
  display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 12px;
}
.panel-title-row .panel-title { margin-bottom: 0; }
.alias-panel { margin-bottom: 14px; }
.alias-list { display: flex; flex-direction: column; gap: 10px; }
.alias-card {
  border: 1px dashed #fbbf24; background: #fffbeb; border-radius: 8px; padding: 10px 12px;
}
.alias-flag { font-size: 11px; font-weight: 650; color: #b45309; margin-bottom: 4px; }
.alias-names { font-size: 13px; color: #111827; font-weight: 600; }
.alias-actions { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.alias-hint { font-size: 12px; color: #78716c; }
.alias-empty { font-size: 12px; color: #9ca3af; }
.merged-map { margin-top: 10px; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.merged-tag { margin: 0; }
.alias-sub { font-size: 11px; color: #9ca3af; margin-top: 2px; }
.eng-tag { margin-right: 4px; margin-bottom: 2px; }
.q-clamp {
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden; line-height: 1.4; font-size: 12px; color: #4b5563;
}
.report-state { font-size: 11px; margin-top: 2px; }
.report-state.ok { color: #059669; }
.report-state.dim { color: #9ca3af; }
.compare-sum { font-size: 13px; color: #4b5563; }
.dim { color: #9ca3af; }
.drawer-body { padding: 0 4px 24px; }
.stats { font-size: 13px; color: #4b5563; }
.steps { margin-bottom: 18px; }
.section-head {
  display: flex; align-items: center; gap: 10px; margin: 4px 0 10px; flex-wrap: wrap;
}
.section-title { font-size: 13px; font-weight: 600; color: #374151; }
.sec-meta { font-size: 12px; color: #8b93a7; margin-left: auto; }
.plat-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px;
}
.plat-card {
  text-align: left; border: 1px solid #e5e7eb; border-radius: 10px; padding: 10px 12px;
  background: #fff; cursor: pointer; transition: border-color .15s, box-shadow .15s;
}
.plat-card:hover { border-color: #93c5fd; }
.plat-card.selected { border-color: #2563eb; box-shadow: 0 0 0 2px rgba(37, 99, 235, .12); }
.plat-card.filtering { background: #eff6ff; }
.plat-name { font-weight: 650; font-size: 13px; color: #111827; }
.plat-count { font-size: 12px; color: #4b5563; margin-top: 4px; }
.plat-bar {
  height: 6px; background: #f3f4f6; border-radius: 99px; margin: 8px 0 6px; overflow: hidden;
}
.plat-bar i {
  display: block; height: 100%; background: #3b82f6; border-radius: 99px;
}
.plat-domains { font-size: 11px; color: #9ca3af; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.url-main {
  font-size: 12px; color: #111827; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.url-sub { font-size: 11px; color: #6b7280; margin-top: 2px; }
.obs-list {
  margin: 6px 0 0; padding-left: 16px; font-size: 11px; color: #6b7280; line-height: 1.5;
}
.more { font-size: 11px; color: #9ca3af; margin-left: 2px; }
.preview-strip {
  background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 8px;
  padding: 10px 12px; font-size: 12px; color: #374151; line-height: 1.55;
}
.actions { display: flex; gap: 8px; flex-wrap: wrap; }
.report-box {
  border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px 14px; background: #f9fafb; margin-top: 12px;
}
.report-md {
  margin: 0; white-space: pre-wrap; word-break: break-word; font-size: 12px; line-height: 1.55;
  color: #1f2937; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
.empty-hint { font-size: 13px; color: #9ca3af; }
.infer-flag { color: #b45309; }
.infer-box, .rec-box {
  border: 1px solid #fde68a; background: #fffbeb; border-radius: 8px; padding: 10px 12px;
}
.infer-hint { margin: 6px 0 8px; font-size: 12px; color: #92400e; line-height: 1.45; }
.infer-list { margin: 0; padding-left: 18px; font-size: 12px; color: #374151; line-height: 1.6; }
.infer-ch { font-weight: 650; margin-right: 6px; }
.rec-card {
  background: #fff; border: 1px solid #fde68a; border-radius: 8px; padding: 10px 12px; margin-top: 8px;
}
.rec-title { font-size: 13px; font-weight: 650; color: #111827; }
.rec-meta { font-size: 11px; color: #9ca3af; margin: 3px 0 4px; }
.rec-reason { font-size: 12px; color: #4b5563; line-height: 1.45; }
.rec-actions { margin-top: 8px; }
.web-box {
  border: 1px solid #bfdbfe; background: #eff6ff; border-radius: 8px; padding: 10px 12px;
}
.web-hint { margin: 6px 0 8px; font-size: 12px; color: #1e40af; line-height: 1.45; }
.web-note { font-size: 12px; color: #334155; margin-bottom: 6px; line-height: 1.45; }
.web-err { font-size: 12px; color: #b45309; margin-bottom: 6px; line-height: 1.45; }
.web-list { list-style: none; margin: 0; padding: 0; }
.web-list li { padding: 8px 0; border-top: 1px solid #dbeafe; }
.web-title { font-size: 13px; color: #111827; }
.web-meta {
  font-size: 11px; color: #64748b; margin: 4px 0 0 24px;
  display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
}
.web-picked { font-size: 12px; color: #1d4ed8; margin-top: 8px; font-weight: 600; }
.hist-card {
  border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px; margin-bottom: 10px; background: #fff;
}
.hist-title { font-size: 13px; font-weight: 600; color: #111827; }
.hist-meta { font-size: 12px; color: #6b7280; margin: 4px 0 8px; }
</style>
