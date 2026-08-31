<script setup>
/**
 * AI 提问管理：业务 → 关键词（优化单元）→ AI 提问。对齐原型 prompts.html。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createGeoBusiness,
  createGeoContentTask,
  createGeoPrompt,
  createGeoUnit,
  expandGeoPromptCandidates,
  listGeoAnswerSnapshots,
  listGeoBusinesses,
  listGeoPrompts,
  listGeoTrackingEngines,
  listGeoUnits,
  patchGeoBusiness,
  patchGeoPrompt,
  patchGeoUnit,
  promoteGeoPromptCandidates,
  importGeoPromptsCsv,
} from '../../api/geoContent'
import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
import { useClientPager } from '../../composables/useClientPager'
import { useGeoTenant } from '../../composables/useGeoTenant'
import { downloadCsv, engineDisplay, engineLabelOf, labelOf, SENTIMENT_LABEL } from '../../utils/geoReportLabels'
import { groupSnapshotsByPrompt, positionRank, sentimentShare, splitByMidpoint, summarizeSnapshots } from '../../utils/geoSnapshotSummary'

const LAYERS = ['business', 'keyword', 'question']
const router = useRouter()
const route = useRoute()
const { tenantId } = useGeoTenant()

const loading = ref(false)
const error = ref('')
const businesses = ref([])
const units = ref([])
const prompts = ref([])
const engines = ref([])
const snapByPrompt = ref(new Map())
const promptSnapRows = ref(new Map())
const qSearch = ref('')
const selectedIds = ref([])
const batchOpen = ref(false)
const dialogOpen = ref(false)
const dialogMode = ref('create')
const saving = ref(false)
const editTarget = ref(null)
const form = ref({
  name: '',
  question: '',
  business_id: null,
  unit_id: null,
})
const createTab = ref('manual')
const recItems = ref([])
const recSelected = ref({})
const recLoading = ref(false)
const recMeta = ref(null)
const creatingTaskId = ref(null)
const evalTarget = ref(null)
const csvInput = ref(null)
const importingCsv = ref(false)

function queryVal(key) {
  const v = route.query[key]
  return Array.isArray(v) ? v[0] : v
}

function queryNum(key) {
  const n = Number(queryVal(key))
  return Number.isFinite(n) && n > 0 ? n : null
}

const layer = computed(() => {
  const raw = String(queryVal('layer') || '')
  if (LAYERS.includes(raw)) return raw
  if (queryNum('unit_id') || queryVal('tag')) return 'question'
  if (queryNum('business_id')) return 'keyword'
  return 'business'
})

const selectedBusinessId = computed(() => queryNum('business_id'))
const selectedUnitId = computed(() => queryNum('unit_id'))
const tagFilter = computed(() => String(queryVal('tag') || '').trim())

const selectedBusiness = computed(
  () => businesses.value.find((b) => b.id === selectedBusinessId.value) || null,
)
const selectedUnit = computed(
  () => units.value.find((u) => u.id === selectedUnitId.value) || null,
)

const keywordUnits = computed(() => {
  const bid = selectedBusinessId.value
  if (!bid) return units.value
  return units.value.filter((u) => u.business_id === bid)
})

const filteredRows = computed(() => {
  const q = qSearch.value.trim().toLowerCase()
  if (layer.value === 'business') {
    return businesses.value.filter((b) => !q || String(b.name || '').toLowerCase().includes(q))
  }
  if (layer.value === 'keyword') {
    return keywordUnits.value.filter((u) => {
      const hay = `${u.keyword || ''} ${u.name || ''}`.toLowerCase()
      return !q || hay.includes(q)
    })
  }
  let rows = prompts.value
  if (tagFilter.value) {
    rows = rows.filter((r) => Array.isArray(r.tags) && r.tags.includes(tagFilter.value))
  }
  if (q) rows = rows.filter((r) => String(r.question || '').toLowerCase().includes(q))
  return rows
})

const pager = useClientPager(filteredRows, { pageSize: 10 })

const tableMeta = computed(() => {
  if (layer.value === 'business') {
    return {
      title: '业务列表',
      action: '+ 新增业务',
      search: '搜索业务...',
      total: `业务总数：${filteredRows.value.length} 个`,
      footer: `共 ${filteredRows.value.length} 个业务`,
    }
  }
  if (layer.value === 'keyword') {
    return {
      title: '关键词列表',
      action: '+ 新增关键词',
      search: '搜索关键词...',
      total: `关键词总数：${filteredRows.value.length} 个`,
      footer: `共 ${filteredRows.value.length} 个关键词`,
    }
  }
  return {
    title: 'AI 提问列表',
    action: '+ 新增提问',
    search: '搜索提问...',
    total: `AI 提问总数：${filteredRows.value.length} 条`,
    footer: `共 ${filteredRows.value.length} 条`,
  }
})

const contextSummary = computed(() => {
  if (layer.value === 'business') return ''
  const biz = selectedBusiness.value?.name || '未选择'
  if (layer.value === 'keyword') return { prefix: '当前页面的关键词属于业务', biz, kw: '' }
  const kw = selectedUnit.value?.keyword || selectedUnit.value?.name || '未选择'
  return { prefix: '当前页面的问题属于业务', biz, kw }
})

const enabledEngines = computed(() => (engines.value || []).filter((e) => e.enabled))

const allPageSelected = computed(() => {
  const rows = pager.pagedItems || []
  return rows.length > 0 && rows.every((r) => selectedIds.value.includes(r.id))
})

function bizName(id) {
  return businesses.value.find((b) => b.id === id)?.name || (id ? `#${id}` : '—')
}

function unitLabel(row) {
  return row?.keyword || row?.name || (row?.id ? `#${row.id}` : '—')
}

function fmtTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso).slice(0, 16).replace('T', ' ')
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

function statusMeta(row) {
  if (row?.status === 'archived') return { zh: '已暂停', paused: true }
  return { zh: '监控中', paused: false }
}

function clipText(s, n = 80) {
  const t = String(s || '').replace(/\s+/g, ' ').trim()
  if (!t) return ''
  return t.length > n ? `${t.slice(0, n)}…` : t
}

function evalKindLabel(kind, rate) {
  if (kind === 'insufficient') return '样本不足'
  if (kind === 'positive') return `正向 ${rate}%`
  if (kind === 'negative') return `负向 ${rate}%`
  return `中立 ${rate}%`
}

const evalDrawer = computed(() => {
  const row = evalTarget.value
  if (!row) return null
  const snaps = promptSnapRows.value.get(row.id) || []
  const sum = snapByPrompt.value.get(row.id) || summarizeSnapshots(snaps)
  const labeled = snaps.filter((s) => ['positive', 'neutral', 'negative'].includes(s.sentiment))
  const sent = sentimentShare(labeled)
  const { prev, cur } = splitByMidpoint(labeled)
  const prevSent = sentimentShare(prev)
  const curSent = sentimentShare(cur)
  const byEngine = new Map()
  for (const s of snaps) {
    const key = s.engine || 'other'
    if (!byEngine.has(key)) byEngine.set(key, [])
    byEngine.get(key).push(s)
  }
  const engineRows = [...byEngine.entries()].map(([engine, rows]) => {
    const share = sentimentShare(rows)
    const latest = [...rows].sort((a, b) =>
      String(b.captured_at || '').localeCompare(String(a.captured_at || '')),
    )[0]
    let kind = 'insufficient'
    let rate = null
    if (share.n >= 3) {
      const top = [
        ['positive', share.positive],
        ['neutral', share.neutral],
        ['negative', share.negative],
      ].sort((a, b) => (b[1] || 0) - (a[1] || 0))[0]
      kind = top[0]
      rate = Math.round((top[1] || 0) * 100)
    }
    return {
      engine,
      name: engineDisplay(engine),
      kind,
      rate,
      samples: share.n,
      quote: clipText(latest?.raw_text, 72),
      raw: latest?.raw_text || '',
      rank: positionRank(latest?.brand_position),
    }
  })
  return {
    question: row.question,
    biz: selectedBusiness.value?.name || '—',
    kw: selectedUnit.value?.keyword || selectedUnit.value?.name || '—',
    engineCount: enabledEngines.value.length,
    mention: sum.mentionRate == null ? null : Math.round(sum.mentionRate * 100),
    snapN: sum.n || snaps.length,
    sampleN: sent.n,
    sent,
    posPct: sent.positive == null ? null : Math.round(sent.positive * 100),
    neuPct: sent.neutral == null ? null : Math.round(sent.neutral * 100),
    negPct: sent.negative == null ? null : Math.round(sent.negative * 100),
    from: prevSent.positive == null ? null : Math.round(prevSent.positive * 100),
    to: curSent.positive == null ? null : Math.round(curSent.positive * 100),
    engines: engineRows,
    evidence: snaps.filter((s) => s.raw_text).slice(0, 8).map((s) => ({
      model: engineDisplay(s.engine),
      time: fmtTime(s.captured_at),
      quote: clipText(s.raw_text, 64),
      raw: s.raw_text,
      tone: s.sentiment && s.sentiment !== 'unknown' ? labelOf(SENTIMENT_LABEL, s.sentiment) : '—',
      rank: positionRank(s.brand_position) ?? '—',
    })),
    insufficient: sent.n < 3,
  }
})

function mentionOf(row) {
  const sum = snapByPrompt.value.get(row.id)
  if (sum?.mentionRate == null) return null
  return {
    pct: Math.round(sum.mentionRate * 100),
    n: sum.n || 0,
  }
}

function lastWatchAt(row) {
  return snapByPrompt.value.get(row.id)?.latestAt || row.last_snapshot_at || row.updated_at
}

function evalMeta(row) {
  const rows = (promptSnapRows.value.get(row.id) || []).filter(
    (s) => s.sentiment && s.sentiment !== 'unknown',
  )
  const sent = sentimentShare(rows)
  if (!sent.n) return { label: '样本不足', tone: 'insufficient', n: 0 }
  if (sent.n < 3) return { label: '样本不足', tone: 'insufficient', n: sent.n }
  const entries = [
    ['positive', '正面', sent.positive],
    ['neutral', '中性', sent.neutral],
    ['negative', '负面', sent.negative],
  ].sort((a, b) => (b[2] || 0) - (a[2] || 0))
  const top = entries[0]
  return {
    label: `${top[1]} ${Math.round((top[2] || 0) * 100)}%`,
    tone: top[0] === 'positive' ? 'pos' : top[0] === 'negative' ? 'neg' : '',
    n: sent.n,
  }
}

function openMention(row) {
  router.push({ path: '/geo/visibility', query: { prompt_id: String(row.id) } })
}

function openEval(row) {
  evalTarget.value = row
}

function closeEval() {
  evalTarget.value = null
}

function showEvalQuote(raw) {
  if (!raw) return
  ElMessageBox.alert(raw, '原始回答', { confirmButtonText: '关闭' })
}

function engineDots() {
  const list = enabledEngines.value
  if (!list.length) return []
  return list.slice(0, 2).map((e, i) => ({
    glyph: String(engineLabelOf(e) || e.engine_key || '?').slice(0, 1),
    tone: i === 1 ? 'blue' : '',
  }))
}

function extraEngineCount() {
  return Math.max(0, enabledEngines.value.length - 2)
}

function replaceQuery(patch, drop = []) {
  const next = { ...route.query, ...patch }
  for (const key of drop) delete next[key]
  Object.keys(next).forEach((k) => {
    if (next[k] == null || next[k] === '') delete next[k]
  })
  router.replace({ path: '/geo/prompts', query: next })
}

function goLayer(next, extra = {}) {
  const q = { layer: next, ...extra }
  if (next === 'keyword' && !q.business_id && !selectedBusinessId.value && businesses.value[0]) {
    q.business_id = String(businesses.value[0].id)
  } else if (next !== 'business' && selectedBusinessId.value && !q.business_id) {
    q.business_id = String(selectedBusinessId.value)
  }
  if (next === 'question') {
    if (!q.unit_id && !selectedUnitId.value) {
      const first = (q.business_id
        ? units.value.filter((u) => String(u.business_id) === String(q.business_id))
        : units.value)[0]
      if (first) q.unit_id = String(first.id)
    } else if (selectedUnitId.value && !q.unit_id) {
      q.unit_id = String(selectedUnitId.value)
    }
  }
  const drop = []
  if (next === 'business') drop.push('unit_id')
  replaceQuery(q, drop)
}

function drillBusiness(row) {
  goLayer('keyword', { business_id: String(row.id) })
}

function drillKeyword(row) {
  goLayer('question', {
    business_id: String(row.business_id || selectedBusinessId.value || ''),
    unit_id: String(row.id),
  })
}

async function loadCore() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    businesses.value = []
    units.value = []
    return
  }
  loading.value = true
  error.value = ''
  try {
    const [b, u, e] = await Promise.all([
      listGeoBusinesses(tenantId.value),
      listGeoUnits(tenantId.value),
      listGeoTrackingEngines(tenantId.value, true).catch(() => ({ items: [] })),
    ])
    businesses.value = b.items || []
    units.value = u.items || []
    engines.value = e.items || []
    if (layer.value === 'keyword' && !selectedBusinessId.value && businesses.value[0]) {
      replaceQuery({
        layer: 'keyword',
        business_id: String(businesses.value[0].id),
      })
    }
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function loadQuestions() {
  if (!tenantId.value || layer.value !== 'question') {
    prompts.value = []
    snapByPrompt.value = new Map()
    promptSnapRows.value = new Map()
    return
  }
  loading.value = true
  error.value = ''
  try {
    const params = {}
    if (selectedUnitId.value && !tagFilter.value) params.unit_id = selectedUnitId.value
    else if (selectedBusinessId.value && !tagFilter.value) params.business_id = selectedBusinessId.value
    const [data, snaps] = await Promise.all([
      listGeoPrompts(tenantId.value, params),
      listGeoAnswerSnapshots(tenantId.value, { limit: 300 }).catch(() => ({ items: [] })),
    ])
    prompts.value = data.items || []
    const items = snaps.items || snaps.snapshots || []
    snapByPrompt.value = groupSnapshotsByPrompt(items)
    const grouped = new Map()
    for (const s of items) {
      if (!s.prompt_id) continue
      if (!grouped.has(s.prompt_id)) grouped.set(s.prompt_id, [])
      grouped.get(s.prompt_id).push(s)
    }
    promptSnapRows.value = grouped
  } catch (e) {
    error.value = e.message || '加载提问失败'
    prompts.value = []
  } finally {
    loading.value = false
  }
}

async function loadAll() {
  await loadCore()
  await loadQuestions()
}

async function importPromptCsv(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file || !tenantId.value) return
  importingCsv.value = true
  try {
    const result = await importGeoPromptsCsv(tenantId.value, file)
    const count = Number(result.count ?? result.items?.length ?? 0)
    const errors = result.errors || []
    ElMessage.success(`CSV 导入完成：${count} 条`)
    if (errors.length) ElMessage.warning(`另有 ${errors.length} 条未导入，请检查 CSV 格式`)
    await loadAll()
  } catch (e) {
    ElMessage.error(e.message || 'CSV 导入失败')
  } finally {
    importingCsv.value = false
  }
}

function openCreate() {
  editTarget.value = null
  dialogMode.value = 'create'
  if (layer.value === 'keyword' && !selectedBusinessId.value && !businesses.value.length) {
    ElMessage.warning('请先新增业务')
    goLayer('business')
    return
  }
  if (layer.value === 'question') {
    const unit = selectedUnit.value || keywordUnits.value[0] || units.value[0]
    if (!unit) {
      ElMessage.warning('请先新增关键词')
      goLayer('keyword')
      return
    }
    form.value = {
      name: '',
      question: '',
      business_id: unit.business_id || selectedBusinessId.value,
      unit_id: unit.id,
    }
  } else {
    form.value = {
      name: '',
      question: '',
      business_id: selectedBusinessId.value || businesses.value[0]?.id || null,
      unit_id: null,
    }
  }
  createTab.value = 'manual'
  recItems.value = []
  recSelected.value = {}
  recMeta.value = null
  dialogOpen.value = true
}

function openEdit(row) {
  editTarget.value = row
  dialogMode.value = 'edit'
  createTab.value = 'manual'
  form.value = {
    name: layer.value === 'keyword' ? unitLabel(row) : row.name || row.question || '',
    question: row.question || '',
    business_id: row.business_id || selectedBusinessId.value,
    unit_id: row.unit_id || row.id,
  }
  dialogOpen.value = true
}

const dialogTitle = computed(() => {
  const edit = dialogMode.value === 'edit'
  if (layer.value === 'business') return edit ? '编辑业务' : '新增业务'
  if (layer.value === 'keyword') return edit ? '编辑关键词' : '新增关键词'
  return edit ? '编辑 AI 提问' : '新增 AI 提问'
})

const dialogSub = computed(() => {
  if (layer.value === 'business') return '新增后可继续维护该业务下的关键词和 AI 提问'
  if (layer.value === 'keyword') {
    const name = selectedBusiness.value?.name || bizName(form.value.business_id)
    return name ? `写入业务「${name}」下` : '写入当前业务下'
  }
  return '为当前关键词添加需要持续监控的用户提问。'
})

const unitsForForm = computed(() => {
  const bid = Number(form.value.business_id)
  if (!bid) return units.value
  return units.value.filter((u) => Number(u.business_id) === bid)
})

const recImportable = computed(() =>
  recItems.value.filter((it) => !it.in_bank && String(it.question || it.term || '').trim().length >= 4),
)
const recPicked = computed(() => recImportable.value.filter((it) => recSelected.value[recKey(it)]))
const recSubmitDisabled = computed(() => {
  if (saving.value || recLoading.value) return true
  if (layer.value === 'question' && dialogMode.value === 'create' && createTab.value === 'ai') {
    return recPicked.value.length === 0
  }
  return false
})
const recSubmitLabel = computed(() => {
  if (dialogMode.value === 'edit') return '确认保存'
  if (layer.value === 'question' && createTab.value === 'ai') {
    const n = recPicked.value.length
    return n ? `添加 ${n} 个提问` : '添加提问'
  }
  return '确认创建'
})

function recKey(it) {
  return String(it.question || it.term || '').trim()
}

function recPri(it) {
  if (it.in_bank) return { zh: '已有', cls: 'low' }
  if (it.vs_last_run === 'new') return { zh: '新↑', cls: 'high' }
  return { zh: '可导入', cls: 'mid' }
}

async function runRecommend() {
  if (!tenantId.value || recLoading.value) return
  const unit = units.value.find((u) => u.id === Number(form.value.unit_id))
  const seed = unitLabel(unit)
  recLoading.value = true
  recItems.value = []
  recSelected.value = {}
  recMeta.value = null
  try {
    const data = await expandGeoPromptCandidates({
      tenant_id: tenantId.value,
      market: 'cn',
      max_terms: 40,
      seed_from_tenant: true,
      products: seed && seed !== '—' ? [seed] : [],
      persist: true,
    })
    const items = data.items || []
    recItems.value = items
    recMeta.value = {
      total: data.total,
      new_count: data.new_count,
      filtered: items.filter((it) => it.in_bank).length,
    }
    const picked = {}
    for (const it of items) {
      if (!it.in_bank) picked[recKey(it)] = true
    }
    recSelected.value = picked
    if (!items.length) ElMessage.info('暂时没有新的推荐提问')
  } catch (e) {
    ElMessage.error(e.message || '生成推荐失败')
  } finally {
    recLoading.value = false
  }
}

function onAiTab() {
  createTab.value = 'ai'
  if (!recItems.value.length && !recLoading.value) runRecommend()
}

function onFormUnitChange() {
  form.value.unit_id = unitsForForm.value[0]?.id || null
  if (createTab.value === 'ai' && dialogMode.value === 'create') {
    recItems.value = []
    recSelected.value = {}
    runRecommend()
  }
}

function toggleRec(it, ev) {
  if (it.in_bank) return
  recSelected.value = { ...recSelected.value, [recKey(it)]: ev.target.checked }
}

async function submitDialog() {
  if (!tenantId.value) return
  saving.value = true
  try {
    if (layer.value === 'business') {
      const name = String(form.value.name || '').trim()
      if (!name) {
        ElMessage.warning('请填写业务名称')
        return
      }
      if (editTarget.value) {
        await patchGeoBusiness(tenantId.value, editTarget.value.id, { name })
        ElMessage.success('已保存')
      } else {
        await createGeoBusiness({ tenant_id: tenantId.value, name })
        ElMessage.success('业务已创建')
      }
    } else if (layer.value === 'keyword') {
      const name = String(form.value.name || '').trim()
      const businessId = form.value.business_id || selectedBusinessId.value
      if (!businessId || !name) {
        ElMessage.warning('请填写关键词')
        return
      }
      if (editTarget.value) {
        await patchGeoUnit(tenantId.value, editTarget.value.id, { name, keyword: name, business_id: businessId })
        ElMessage.success('已保存')
      } else {
        await createGeoUnit({
          tenant_id: tenantId.value,
          business_id: businessId,
          name,
          keyword: name,
        })
        ElMessage.success('关键词已创建')
      }
    } else {
      const unitId = Number(form.value.unit_id) || null
      if (!unitId) {
        ElMessage.warning('请选择关键词')
        return
      }
      if (dialogMode.value === 'create' && createTab.value === 'ai') {
        const picked = recPicked.value
        if (!picked.length) {
          ElMessage.warning('请先勾选要导入的提问')
          return
        }
        const r = await promoteGeoPromptCandidates({
          tenant_id: tenantId.value,
          items: picked.slice(0, 50).map((it) => ({
            question: recKey(it),
            question_group: it.question_group || null,
            market: 'cn',
            priority: 10,
            tags: ['from_expand'],
            is_brand_probe: !!it.is_brand_probe,
            unit_id: unitId,
          })),
        })
        ElMessage.success(
          `已添加 ${r.created ?? picked.length} 个 AI 提问` + (r.skipped ? `（跳过重复 ${r.skipped}）` : ''),
        )
      } else {
        const question = String(form.value.question || '').trim()
        if (question.length < 4) {
          ElMessage.warning('请填写至少 4 个字的用户提问')
          return
        }
        if (editTarget.value) {
          await patchGeoPrompt(tenantId.value, editTarget.value.id, { question, unit_id: unitId })
          ElMessage.success('已保存')
        } else {
          await createGeoPrompt({
            tenant_id: tenantId.value,
            question,
            unit_id: unitId,
            source: 'manual',
            priority: 10,
          })
          ElMessage.success(`提问已加入「${unitLabel(units.value.find((u) => u.id === unitId))}」`)
        }
      }
    }
    dialogOpen.value = false
    await loadAll()
  } catch (e) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function createArticle(row) {
  if (!tenantId.value || !row?.id || creatingTaskId.value) return
  creatingTaskId.value = row.id
  try {
    const task = await createGeoContentTask({
      tenant_id: tenantId.value,
      prompt_id: row.id,
      title: row.question,
    })
    ElMessage.success(`已创建优化文章 #${task.id}`)
    router.push(`/geo/tasks/${task.id}`)
  } catch (e) {
    ElMessage.error(e.message || '创建失败')
  } finally {
    creatingTaskId.value = null
  }
}

async function setStatus(row, status) {
  try {
    if (layer.value === 'business') await patchGeoBusiness(tenantId.value, row.id, { status })
    else if (layer.value === 'keyword') await patchGeoUnit(tenantId.value, row.id, { status })
    else await patchGeoPrompt(tenantId.value, row.id, { status })
    ElMessage.success(status === 'archived' ? '已暂停监控' : '已开启监控')
    await loadAll()
  } catch (e) {
    ElMessage.error(e.message || '更新失败')
  }
}

async function removeRow(row) {
  const label = layer.value === 'question' ? row.question : layer.value === 'keyword' ? unitLabel(row) : row.name
  try {
    await ElMessageBox.confirm(`暂停并移出列表「${label}」？数据不会物理删除。`, '删除', {
      type: 'warning',
      confirmButtonText: '删除',
    })
    await setStatus(row, 'archived')
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error(e.message || '删除失败')
  }
}

function toggleAll(ev) {
  const on = ev.target.checked
  const ids = (pager.pagedItems || []).map((r) => r.id)
  if (on) selectedIds.value = [...new Set([...selectedIds.value, ...ids])]
  else selectedIds.value = selectedIds.value.filter((id) => !ids.includes(id))
}

function toggleOne(id, ev) {
  const on = ev.target.checked
  if (on) selectedIds.value = [...new Set([...selectedIds.value, id])]
  else selectedIds.value = selectedIds.value.filter((x) => x !== id)
}

function selectedRows() {
  const pool = filteredRows.value
  return pool.filter((r) => selectedIds.value.includes(r.id))
}

async function batchAction(kind) {
  batchOpen.value = false
  const rows = selectedRows()
  if (!rows.length) {
    ElMessage.warning('请先勾选行')
    return
  }
  try {
    if (kind === 'export') {
      if (layer.value === 'business') {
        downloadCsv(
          'geo-businesses.csv',
          ['业务名称', '关键词数', 'AI提问数', '状态', '最近更新'],
          rows.map((r) => [r.name, r.unit_count ?? 0, r.prompt_count ?? 0, statusMeta(r).zh, fmtTime(r.updated_at)]),
        )
      } else if (layer.value === 'keyword') {
        downloadCsv(
          'geo-keywords.csv',
          ['关键词', '所属业务', 'AI提问数', '状态', '最近更新'],
          rows.map((r) => [unitLabel(r), bizName(r.business_id), r.prompt_count ?? 0, statusMeta(r).zh, fmtTime(r.updated_at)]),
        )
      } else {
        downloadCsv(
          'geo-questions.csv',
          ['AI提问', '提及率', '状态', '最后监控时间'],
          rows.map((r) => {
            const m = mentionOf(r)
            return [r.question, m == null ? '' : `${m.pct}%`, statusMeta(r).zh, fmtTime(lastWatchAt(r))]
          }),
        )
      }
      ElMessage.success(`已导出 ${rows.length} 条`)
      return
    }
    const status = kind === 'enable' ? 'active' : 'archived'
    if (kind === 'delete') {
      await ElMessageBox.confirm(`将暂停选中的 ${rows.length} 条？数据不会物理删除。`, '批量删除', {
        type: 'warning',
        confirmButtonText: '删除',
      })
    }
    for (const row of rows) {
      if (layer.value === 'business') await patchGeoBusiness(tenantId.value, row.id, { status })
      else if (layer.value === 'keyword') await patchGeoUnit(tenantId.value, row.id, { status })
      else await patchGeoPrompt(tenantId.value, row.id, { status })
    }
    ElMessage.success(kind === 'enable' ? '已开启监控' : '已暂停监控')
    selectedIds.value = []
    await loadAll()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error(e.message || '批量操作失败')
  }
}

function onDocClick(ev) {
  if (!ev.target.closest?.('.batch-menu-wrap')) batchOpen.value = false
}

watch([tenantId], loadAll)
watch([layer, selectedBusinessId, selectedUnitId, tagFilter], () => {
  selectedIds.value = []
  pager.resetPage()
  if (layer.value === 'question') loadQuestions()
})
watch([qSearch], () => pager.resetPage())
onMounted(() => {
  document.addEventListener('click', onDocClick)
  loadAll()
})
onUnmounted(() => document.removeEventListener('click', onDocClick))
</script>

<template>
  <GeoWorkbenchPage
    title="AI 提问管理"
    :show-period="false"
    sub="维护 AI 监控的业务、关键词和提问，追踪大模型中的回答表现"
    :loading="loading"
  >
    <div class="prompt-page">
      <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

      <section class="context-strip">
        <div class="context-left">
          <span v-if="layer !== 'business'" class="context-summary">
            {{ contextSummary.prefix }}
            <b>{{ contextSummary.biz }}</b>
            <template v-if="contextSummary.kw"> / 关键词 <b>{{ contextSummary.kw }}</b></template>
          </span>
        </div>
        <div class="context-right">
          <span class="context-label">{{ tableMeta.total.split('：')[0] }}：<b>{{ tableMeta.total.split('：')[1] }}</b></span>
          <button class="mini-btn" type="button" @click="loadAll">⟳ 刷新</button>
        </div>
      </section>

      <section class="layer-tabs">
        <div
          class="layer-tab"
          :class="{ active: layer === 'business' }"
          role="button"
          tabindex="0"
          @click="goLayer('business')"
          @keydown.enter.prevent="goLayer('business')"
        >
          <span class="tab-ico">▣</span>
          <div><b>业务</b><span>管理监控的业务领域</span></div>
        </div>
        <div
          class="layer-tab"
          :class="{ active: layer === 'keyword' }"
          role="button"
          tabindex="0"
          @click="goLayer('keyword')"
          @keydown.enter.prevent="goLayer('keyword')"
        >
          <span class="tab-ico">◇</span>
          <div><b>关键词</b><span>管理所选业务下的关键词</span></div>
        </div>
        <div
          class="layer-tab"
          :class="{ active: layer === 'question' }"
          role="button"
          tabindex="0"
          @click="goLayer('question')"
          @keydown.enter.prevent="goLayer('question')"
        >
          <span class="tab-ico">▤</span>
          <div><b>AI 提问</b><span>管理所选关键词下的提问</span></div>
        </div>
        <div></div>
      </section>

      <section class="prompt-workspace">
        <div class="table-card">
          <div class="section-head">
            <h3>{{ tableMeta.title }}</h3>
            <div class="actions">
              <input v-model="qSearch" class="search" :placeholder="tableMeta.search">
              <button class="mini-btn primary" type="button" @click="openCreate">{{ tableMeta.action }}</button>
              <button
                v-if="layer === 'question'"
                class="mini-btn"
                type="button"
                :disabled="importingCsv"
                @click="csvInput?.click()"
              >
                {{ importingCsv ? '导入中…' : 'CSV 导入' }}
              </button>
              <input ref="csvInput" type="file" accept=".csv,text/csv" hidden @change="importPromptCsv" />
              <div class="batch-menu-wrap">
                <button
                  class="mini-btn batch-trigger"
                  type="button"
                  :aria-expanded="batchOpen"
                  @click.stop="batchOpen = !batchOpen"
                >
                  <span>☆ 批量操作</span>
                  <span class="chevron" aria-hidden="true" />
                </button>
                <div v-show="batchOpen" class="batch-menu">
                  <div class="batch-option" role="menuitem" @click="batchAction('enable')">批量开启监控</div>
                  <div class="batch-option" role="menuitem" @click="batchAction('pause')">批量暂停监控</div>
                  <div class="batch-option" role="menuitem" @click="batchAction('export')">导出选中项</div>
                  <div class="batch-option danger" role="menuitem" @click="batchAction('delete')">批量删除</div>
                </div>
              </div>
            </div>
          </div>

          <table class="prompt-table">
            <thead>
              <tr v-if="layer === 'business'">
                <th><input type="checkbox" :checked="allPageSelected" @change="toggleAll"></th>
                <th>业务名称</th>
                <th>关键词数</th>
                <th>AI 提问数</th>
                <th>监控模型</th>
                <th>状态</th>
                <th>最近更新</th>
                <th>操作</th>
              </tr>
              <tr v-else-if="layer === 'keyword'">
                <th><input type="checkbox" :checked="allPageSelected" @change="toggleAll"></th>
                <th>关键词</th>
                <th>所属业务</th>
                <th>AI 提问数</th>
                <th>状态</th>
                <th>最近更新</th>
                <th>操作</th>
              </tr>
              <tr v-else>
                <th><input type="checkbox" :checked="allPageSelected" @change="toggleAll"></th>
                <th>AI 提问（Prompt）</th>
                <th>
                  <span title="在已采集的 AI 回答中，明确提到当前品牌的比例。无样本显示 —。">
                    AI 提及率<span class="th-help">?</span>
                  </span>
                </th>
                <th>
                  <span title="只统计能识别出针对本品牌评价倾向的回答。样本不足时不展示占比，可点进评价分析。">
                    AI评价<span class="th-help">?</span>
                  </span>
                </th>
                <th>监控状态</th>
                <th>监控模型</th>
                <th>最后监控时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!pager.pagedItems.length">
                <td :colspan="layer === 'keyword' ? 7 : 8" class="empty-cell">
                  <template v-if="layer === 'business'">还没有业务。点右上角新增。</template>
                  <template v-else-if="layer === 'keyword'">该业务下还没有关键词。</template>
                  <template v-else>该关键词下还没有提问。</template>
                </td>
              </tr>
              <tr v-for="row in pager.pagedItems" :key="row.id">
                <td><input type="checkbox" :checked="selectedIds.includes(row.id)" @change="toggleOne(row.id, $event)"></td>
                <template v-if="layer === 'business'">
                  <td class="kw">
                    <button type="button" class="kw-link" @click="drillBusiness(row)">{{ row.name }}</button>
                  </td>
                  <td>{{ row.unit_count ?? 0 }}</td>
                  <td>{{ row.prompt_count ?? 0 }}</td>
                  <td>
                    <span class="model-dots">
                      <span v-for="(dot, i) in engineDots()" :key="i" class="model-dot" :class="dot.tone">{{ dot.glyph }}</span>
                      <span v-if="extraEngineCount()" class="plus-model">+{{ extraEngineCount() }}</span>
                      <span v-if="!engineDots().length">—</span>
                    </span>
                  </td>
                  <td><span class="status" :class="{ paused: statusMeta(row).paused }">{{ statusMeta(row).zh }}</span></td>
                  <td>{{ fmtTime(row.updated_at) }}</td>
                </template>
                <template v-else-if="layer === 'keyword'">
                  <td class="kw">
                    <button type="button" class="kw-link" @click="drillKeyword(row)">{{ unitLabel(row) }}</button>
                  </td>
                  <td>{{ bizName(row.business_id) }}</td>
                  <td>{{ row.prompt_count ?? 0 }}</td>
                  <td><span class="status" :class="{ paused: statusMeta(row).paused }">{{ statusMeta(row).zh }}</span></td>
                  <td>{{ fmtTime(row.updated_at) }}</td>
                </template>
                <template v-else>
                  <td class="kw">{{ row.question }}</td>
                  <td>
                    <button
                      v-if="mentionOf(row)"
                      type="button"
                      class="mention-rate"
                      @click="openMention(row)"
                    >{{ mentionOf(row).pct }}%<small> · {{ mentionOf(row).n }} 条</small></button>
                    <span v-else>—</span>
                  </td>
                  <td>
                    <button
                      type="button"
                      class="eval-pill"
                      :class="evalMeta(row).tone"
                      @click="openEval(row)"
                    >{{ evalMeta(row).label }}</button>
                  </td>
                  <td><span class="status" :class="{ paused: statusMeta(row).paused }">{{ statusMeta(row).zh }}</span></td>
                  <td>
                    <span class="model-dots">
                      <span v-for="(dot, i) in engineDots()" :key="i" class="model-dot" :class="dot.tone">{{ dot.glyph }}</span>
                      <span v-if="extraEngineCount()" class="plus-model">+{{ extraEngineCount() }}</span>
                      <span v-if="!engineDots().length">—</span>
                    </span>
                  </td>
                  <td>{{ fmtTime(lastWatchAt(row)) }}</td>
                </template>
                <td>
                  <span class="table-actions">
                    <button
                      v-if="layer === 'question'"
                      type="button"
                      class="text-action"
                      :disabled="creatingTaskId === row.id"
                      @click="createArticle(row)"
                    >{{ creatingTaskId === row.id ? '创建中…' : '建文章' }}</button>
                    <span class="icon-action" title="编辑" role="button" @click="openEdit(row)">
                      <svg viewBox="0 0 24 24"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>
                    </span>
                    <span class="icon-action danger" title="删除" role="button" @click="removeRow(row)">
                      <svg viewBox="0 0 24 24"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v5"/><path d="M14 11v5"/></svg>
                    </span>
                  </span>
                </td>
              </tr>
            </tbody>
          </table>

          <div class="table-footer">
            <span>{{ tableMeta.footer }}</span>
            <div class="pagination">
              <el-pagination
                background
                layout="prev, pager, next, sizes"
                :total="pager.total"
                :page-size="pager.pageSize"
                :page-sizes="[10, 20, 50]"
                :current-page="pager.page"
                @current-change="pager.onPageChange"
                @size-change="pager.onSizeChange"
              />
            </div>
          </div>
        </div>
      </section>

    <div v-if="dialogOpen" class="prompt-create-mask" @click.self="dialogOpen = false">
      <div class="prompt-create" role="dialog" aria-modal="true">
        <header class="prompt-create-head">
          <div>
            <h2>{{ dialogTitle }}</h2>
            <p>{{ dialogSub }}</p>
          </div>
          <button type="button" class="eval-close" aria-label="关闭" @click="dialogOpen = false">×</button>
        </header>
        <div class="prompt-create-body">
          <div v-if="layer === 'business'" class="prompt-field">
            <label>业务名称 <em>*</em></label>
            <input v-model="form.name" placeholder="例如：CRM软件">
          </div>
          <template v-else-if="layer === 'keyword'">
            <div class="prompt-field">
              <label>所属业务</label>
              <select v-model="form.business_id" :disabled="dialogMode === 'create' && !!selectedBusinessId">
                <option v-for="b in businesses" :key="b.id" :value="b.id">{{ b.name }}</option>
              </select>
            </div>
            <div class="prompt-field">
              <label>关键词 <em>*</em></label>
              <input v-model="form.name" placeholder="例如：CRM系统">
            </div>
          </template>
          <template v-else>
            <div class="create-tabs" v-if="dialogMode === 'create'">
              <button type="button" class="create-tab" :class="{ active: createTab === 'manual' }" @click="createTab = 'manual'">手动新增</button>
              <button type="button" class="create-tab" :class="{ active: createTab === 'ai' }" @click="onAiTab">AI 推荐</button>
            </div>
            <div class="create-ctx">
              <div>
                <span>当前业务：</span>
                <select v-model="form.business_id" @change="onFormUnitChange">
                  <option v-for="b in businesses" :key="b.id" :value="b.id">{{ b.name }}</option>
                </select>
                <span>当前关键词：</span>
                <select v-model="form.unit_id" @change="createTab === 'ai' && dialogMode === 'create' && runRecommend()">
                  <option v-for="u in unitsForForm" :key="u.id" :value="u.id">{{ unitLabel(u) }}</option>
                </select>
              </div>
            </div>
            <template v-if="createTab === 'ai' && dialogMode === 'create'">
              <p class="create-hint">
                基于当前业务、关键词和品牌资料生成值得监控的提问，勾选后导入。
                <template v-if="recMeta">已过滤库内 {{ recMeta.filtered }} 条</template>
              </p>
              <div v-if="recLoading" class="rec-empty">正在生成推荐…</div>
              <div v-else-if="!recItems.length" class="rec-empty">
                暂时没有推荐提问
                <div style="margin-top:10px">
                  <button type="button" class="mini-btn" @click="runRecommend">重新生成</button>
                  <button type="button" class="mini-btn" @click="createTab = 'manual'">手动新增</button>
                </div>
              </div>
              <div v-else class="rec-list">
                <label
                  v-for="it in recItems"
                  :key="recKey(it)"
                  class="rec-item"
                  :class="{ disabled: it.in_bank }"
                >
                  <input
                    type="checkbox"
                    :disabled="!!it.in_bank"
                    :checked="!!recSelected[recKey(it)]"
                    @change="toggleRec(it, $event)"
                  >
                  <div>
                    <b>{{ recKey(it) }}</b>
                    <small>{{ it.question_group || '提问' }} · {{ it.in_bank ? '库内已有' : '尚未监控' }}</small>
                  </div>
                  <span class="rec-pri" :class="recPri(it).cls">{{ recPri(it).zh }}</span>
                </label>
              </div>
            </template>
            <template v-else>
              <div class="prompt-field">
                <label>用户提问 <em>*</em></label>
                <textarea v-model="form.question" placeholder="例如：有哪些适合中小企业的智能客服系统？" />
              </div>
              <p class="create-hint">请输入真实用户可能向 ChatGPT、DeepSeek、豆包等 AI 提出的自然语言问题。</p>
            </template>
          </template>
        </div>
        <footer class="prompt-create-foot">
          <div v-if="layer === 'question' && createTab === 'ai' && dialogMode === 'create'" class="left">
            已选择 {{ recPicked.length }} / {{ recImportable.length }}
          </div>
          <button
            v-if="layer === 'question' && createTab === 'ai' && dialogMode === 'create'"
            type="button"
            class="mini-btn"
            :disabled="recLoading"
            @click="runRecommend"
          >换一批</button>
          <button type="button" class="mini-btn" @click="dialogOpen = false">取消</button>
          <button type="button" class="mini-btn primary" :disabled="recSubmitDisabled" @click="submitDialog">{{ recSubmitLabel }}</button>
        </footer>
      </div>
    </div>

    <div v-if="evalDrawer" class="eval-mask" @click.self="closeEval">
      <aside class="eval-drawer" role="dialog" aria-modal="true" aria-labelledby="evalDrawerTitle">
        <header class="eval-drawer-head">
          <div>
            <h2 id="evalDrawerTitle">AI评价分析</h2>
            <p>{{ evalDrawer.question }}</p>
          </div>
          <button type="button" class="eval-close" aria-label="关闭" @click="closeEval">×</button>
        </header>
        <div class="eval-drawer-body">
          <div class="eval-meta">
            <div><span>所属业务</span><b>{{ evalDrawer.biz }}</b></div>
            <div><span>关键词</span><b>{{ evalDrawer.kw }}</b></div>
            <div><span>统计周期</span><b>已采集快照</b></div>
            <div><span>监控模型</span><b>{{ evalDrawer.engineCount || '—' }}</b></div>
            <div><span>AI提及率</span><b>{{ evalDrawer.mention == null ? '—' : evalDrawer.mention + '%' }}</b></div>
            <div><span>有效品牌评价样本</span><b>{{ evalDrawer.sampleN }}</b></div>
          </div>
          <p class="eval-joint">
            AI提及率回答「有没有提到品牌」（{{ evalDrawer.snapN }} 条快照）；AI评价回答「提到以后怎么看品牌」。
          </p>

          <section class="eval-sec">
            <h4>AI整体怎么评价品牌？</h4>
            <template v-if="evalDrawer.insufficient">
              <p>有效品牌评价样本仅 {{ evalDrawer.sampleN }} 条，暂不输出正向/中立/负向占比，避免小样本误导。</p>
            </template>
            <template v-else>
              <div class="eval-bar"><span>正向</span><i><span :style="{ width: evalDrawer.posPct + '%', background: '#16a34a' }" /></i><b>{{ evalDrawer.posPct }}%</b></div>
              <div class="eval-bar"><span>中立</span><i><span :style="{ width: evalDrawer.neuPct + '%', background: '#94a3b8' }" /></i><b>{{ evalDrawer.neuPct }}%</b></div>
              <div class="eval-bar"><span>负向</span><i><span :style="{ width: evalDrawer.negPct + '%', background: '#dc2626' }" /></i><b>{{ evalDrawer.negPct }}%</b></div>
            </template>
          </section>

          <section class="eval-sec">
            <h4>不同 AI 的评价是否一致？</h4>
            <p v-if="!evalDrawer.engines.length">该提问还没有回答快照。</p>
            <div v-for="item in evalDrawer.engines" :key="item.engine" class="eval-engine">
              <div class="eval-engine-hd">
                <b>{{ item.name }}</b>
                <span class="eval-pill" :class="item.kind === 'positive' ? 'pos' : item.kind === 'negative' ? 'neg' : 'insufficient'">{{ evalKindLabel(item.kind, item.rate) }}</span>
              </div>
              <p v-if="item.kind === 'insufficient'">当前仅获得 {{ item.samples }} 条有效品牌评价。</p>
              <p v-else>最新回答：「{{ item.quote || '—' }}」<template v-if="item.rank"> · 品牌位置 {{ item.rank }}</template></p>
              <button v-if="item.raw" type="button" class="mini-btn" @click="showEvalQuote(item.raw)">查看原始回答</button>
            </div>
          </section>

          <section class="eval-sec">
            <h4>最近评价有没有变化？</h4>
            <p v-if="evalDrawer.from == null || evalDrawer.to == null">样本不足，暂看不出前后变化。</p>
            <p v-else>
              观察期内正向评价：{{ evalDrawer.from }}% → {{ evalDrawer.to }}%
              {{ evalDrawer.to - evalDrawer.from >= 0 ? '+' : '' }}{{ evalDrawer.to - evalDrawer.from }}%
            </p>
          </section>

          <section class="eval-sec">
            <h4>评价依据</h4>
            <p>主题标签和改善建议需要从回答里抽取，当前尚未接入，先展示已标注的快照。</p>
            <table v-if="evalDrawer.evidence.length" class="eval-evidence">
              <thead>
                <tr><th>AI模型</th><th>原始回答片段</th><th>评价</th><th>位置</th><th /></tr>
              </thead>
              <tbody>
                <tr v-for="(item, i) in evalDrawer.evidence" :key="i">
                  <td>{{ item.model }}<div class="subtle">{{ item.time }}</div></td>
                  <td>{{ item.quote }}</td>
                  <td>{{ item.tone }}</td>
                  <td>{{ item.rank }}</td>
                  <td><button type="button" class="mini-btn" @click="showEvalQuote(item.raw)">查看完整回答</button></td>
                </tr>
              </tbody>
            </table>
          </section>
        </div>
        <footer class="eval-drawer-foot">
          <button type="button" class="mini-btn" :disabled="creatingTaskId === evalTarget?.id" @click="createArticle(evalTarget)">
            {{ creatingTaskId === evalTarget?.id ? '创建中…' : '生成 GEO 文章' }}
          </button>
          <router-link class="mini-btn primary" to="/geo/knowledge">补充知识库</router-link>
        </footer>
      </aside>
    </div>
    </div>
  </GeoWorkbenchPage>
</template>

<style scoped>
.prompt-page {
  --accent: #7c3aed;
  --accent-soft: #f5f0ff;
  --text: #1e2330;
  --muted: #6b7280;
  --border: #e8eaf0;
  padding: 0 0 8px;
}
.mb { margin-bottom: 12px; }
.layer-tabs {
  display: grid;
  grid-template-columns: repeat(3, 1fr) minmax(220px, .9fr);
  margin-top: 14px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  min-height: 78px;
}
.layer-tab {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px 24px;
  border-right: 1px solid var(--border);
  position: relative;
  cursor: pointer;
}
.layer-tab:hover { background: #faf9ff; }
.layer-tab.active { background: linear-gradient(180deg, #fff, rgba(124, 58, 237, .035)); }
.layer-tab.active b { color: var(--accent); }
.layer-tab.active::after {
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 2px;
  background: var(--accent);
}
.tab-ico {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--accent);
  background: var(--accent-soft);
  font-size: 16px;
}
.layer-tab b { display: block; font-size: 15px; color: var(--text); }
.layer-tab span { display: block; margin-top: 5px; font-size: 12px; color: var(--muted); }
.context-strip {
  margin-top: 0;
  min-height: 54px;
  border: 1px solid rgba(124, 58, 237, .20);
  border-radius: 7px;
  background: linear-gradient(90deg, rgba(124, 58, 237, .06), rgba(255, 255, 255, .96));
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 10px 16px;
}
.context-left, .context-right { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.context-label { color: var(--muted); font-size: 13px; font-weight: 700; }
.context-label b { color: var(--text); }
.context-summary { color: var(--muted); font-size: 13px; font-weight: 700; }
.context-summary b { color: var(--text); font-weight: 800; }
.prompt-workspace { margin-top: 18px; }
.table-card {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: 0 12px 28px rgba(15, 23, 42, .05);
  overflow: hidden;
}
.section-head {
  min-height: 54px;
  padding: 10px 18px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}
.section-head h3 { margin: 0; font-size: 16px; }
.section-head .actions { margin-left: auto; display: flex; gap: 10px; }
.section-head .search {
  width: 220px;
  height: 32px;
  border: 1px solid #1e2330;
  border-radius: 7px;
  padding: 0 10px;
  background: #fff;
  color: var(--text);
  font: inherit;
  font-size: 13px;
  outline: none;
}
.section-head .search:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}
.mini-btn {
  height: 32px;
  padding: 0 12px;
  border: 1px solid var(--border);
  background: #fff;
  border-radius: 7px;
  color: var(--text);
  font-weight: 700;
  cursor: pointer;
}
.mini-btn:hover { border-color: #c7d2fe; background: #faf9ff; color: #7c3aed; }
.mini-btn.primary {
  background: #7c3aed;
  border-color: #7c3aed;
  color: #fff;
}
.mini-btn.primary:hover { background: #6d28d9; border-color: #6d28d9; color: #fff; }
.mini-btn:disabled,
.mini-btn.primary:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.batch-menu-wrap { position: relative; }
.batch-trigger { display: inline-flex; align-items: center; gap: 7px; }
.batch-trigger .chevron {
  width: 7px;
  height: 7px;
  border-right: 2px solid currentColor;
  border-bottom: 2px solid currentColor;
  transform: rotate(45deg) translateY(-2px);
}
.batch-menu {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  z-index: 30;
  width: 168px;
  padding: 6px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: #fff;
  box-shadow: 0 18px 40px rgba(15, 23, 42, .14);
}
.batch-option {
  height: 34px;
  padding: 0 10px;
  border-radius: 7px;
  display: flex;
  align-items: center;
  color: var(--text);
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}
.batch-option:hover { background: var(--accent-soft); color: var(--accent); }
.batch-option.danger:hover { background: #fff1f2; color: #ef4444; }
.prompt-table { width: 100%; border-collapse: collapse; }
.prompt-table th, .prompt-table td {
  padding: 13px 18px;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
  text-align: left;
  white-space: nowrap;
}
.prompt-table th { color: var(--muted); font-weight: 800; background: #fbfcff; }
.prompt-table tbody tr:hover { background: #faf9ff; }
.prompt-table input[type="checkbox"] { width: 15px; height: 15px; }
.th-help {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  margin-left: 6px;
  border: 1px solid #cbd5e1;
  border-radius: 999px;
  color: #64748b;
  background: #fff;
  font-size: 11px;
  font-weight: 800;
  vertical-align: middle;
}
.mention-rate {
  border: 0;
  padding: 0;
  background: none;
  color: #2563eb;
  font: inherit;
  font-weight: 800;
  cursor: pointer;
}
.mention-rate small { font-weight: 600; color: #64748b; }
.kw-link {
  border: 0;
  background: transparent;
  padding: 0;
  color: #2563eb;
  font: inherit;
  font-weight: 800;
  cursor: pointer;
}
.kw-link:hover { color: #1d4ed8; text-decoration: underline; text-underline-offset: 3px; }
.status {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 9px;
  border-radius: 999px;
  color: #0f8f54;
  background: #e8f8ef;
  font-weight: 800;
  font-size: 12px;
}
.status.paused { color: #64748b; background: #f1f5f9; }
.model-dots { display: inline-flex; align-items: center; gap: 5px; }
.model-dot {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 900;
  color: #fff;
  background: #111827;
}
.model-dot.blue { background: #2563eb; }
.plus-model { color: var(--accent); font-size: 12px; font-weight: 800; }
.table-actions { display: inline-flex; align-items: center; gap: 14px; }
.text-action {
  border: 0;
  padding: 0;
  background: none;
  color: #7c3aed;
  font: inherit;
  font-size: 12.5px;
  font-weight: 750;
  cursor: pointer;
  white-space: nowrap;
}
.text-action:hover { color: #6d28d9; }
.text-action:disabled { color: #94a3b8; cursor: wait; }
.icon-action {
  width: 18px;
  height: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #64748b;
  cursor: pointer;
}
.icon-action svg {
  width: 16px;
  height: 16px;
  stroke: currentColor;
  stroke-width: 2;
  fill: none;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.icon-action:hover { color: #2563eb; }
.icon-action.danger:hover { color: #ef4444; }
.table-footer {
  min-height: 54px;
  padding: 8px 18px;
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--muted);
  font-size: 13px;
}
.pagination { margin-left: auto; }
.empty-cell { text-align: center; color: var(--muted); padding: 22px !important; }
.eval-pill {
  border: 0;
  height: 22px;
  padding: 0 9px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 800;
  cursor: pointer;
}
.eval-pill.insufficient { color: #64748b; background: #f1f5f9; }
.eval-pill.pos { color: #15803d; background: #dcfce7; }
.eval-pill.neg { color: #b91c1c; background: #fee2e2; }
.prompt-create-mask {
  position: fixed;
  inset: 0;
  z-index: 13010;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(17, 24, 39, .45);
}
.prompt-create {
  width: min(560px, 94vw);
  max-height: min(86vh, 720px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 24px 70px rgba(17, 24, 39, .28);
}
.prompt-create-head {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 18px 20px;
  border-bottom: 1px solid var(--border);
}
.prompt-create-head h2 { margin: 0; font-size: 16px; }
.prompt-create-head p { margin: 4px 0 0; color: var(--muted); font-size: 12px; }
.eval-close {
  margin-left: auto;
  width: 30px;
  height: 30px;
  border: 0;
  border-radius: 6px;
  background: #f3f5f8;
  color: #687184;
  font-size: 18px;
  cursor: pointer;
}
.prompt-create-body { padding: 18px 20px; overflow: auto; }
.prompt-field { display: grid; gap: 6px; margin-bottom: 14px; }
.prompt-field label { color: #4f596b; font-size: 12px; font-weight: 650; }
.prompt-field label em { color: #dc2626; font-style: normal; }
.prompt-field input,
.prompt-field textarea,
.prompt-field select {
  width: 100%;
  padding: 9px 10px;
  border: 1px solid #1e2330;
  border-radius: 7px;
  background: #fff;
  color: var(--text);
  font: inherit;
  font-size: 13px;
  outline: none;
  appearance: auto;
}
.prompt-field input:focus,
.prompt-field textarea:focus,
.prompt-field select:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}
.prompt-field textarea { min-height: 88px; resize: vertical; line-height: 1.55; }
.create-ctx {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
  padding: 9px 12px;
  border: 1px solid #eee7ff;
  border-radius: 7px;
  background: #faf8ff;
  font-size: 12.5px;
}
.create-ctx span { color: var(--muted); margin-right: 6px; }
.create-ctx select {
  margin-right: 12px;
  height: 28px;
  border: 1px solid #1e2330;
  border-radius: 6px;
  padding: 0 8px;
  background: #fff;
  outline: none;
}
.create-hint { margin: 0 0 12px; color: var(--muted); font-size: 12px; line-height: 1.6; }
.create-tabs {
  display: flex;
  gap: 0;
  margin-bottom: 14px;
  border: 1px solid var(--border);
  border-radius: 7px;
  overflow: hidden;
}
.create-tab {
  flex: 1;
  height: 34px;
  border: 0;
  background: #fff;
  color: var(--muted);
  font: inherit;
  font-size: 12.5px;
  font-weight: 750;
  cursor: pointer;
}
.create-tab.active { color: #7c3aed; background: #f5f0ff; }
.rec-list {
  display: grid;
  gap: 0;
  border: 1px solid #1e2330;
  border-radius: 8px;
  overflow: hidden;
  max-height: 320px;
  overflow-y: auto;
}
.rec-item {
  display: grid;
  grid-template-columns: 18px 1fr auto;
  gap: 10px;
  align-items: flex-start;
  padding: 10px 12px;
  border-bottom: 1px solid #edf0f5;
  font-size: 13px;
  cursor: pointer;
}
.rec-item:last-child { border-bottom: 0; }
.rec-item:hover { background: #faf9ff; }
.rec-item.disabled { cursor: default; opacity: 0.7; }
.rec-item b { display: block; font-size: 13px; }
.rec-item small { display: block; margin-top: 3px; color: var(--muted); font-size: 11.5px; }
.rec-pri { font-size: 11px; font-weight: 800; white-space: nowrap; }
.rec-pri.high { color: #b45309; }
.rec-pri.mid { color: #64748b; }
.rec-pri.low { color: #94a3b8; }
.rec-empty {
  padding: 28px 16px;
  text-align: center;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.7;
}
.prompt-create-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 13px 20px;
  border-top: 1px solid var(--border);
  background: #fafbfc;
}
.prompt-create-foot .left {
  margin-right: auto;
  display: flex;
  align-items: center;
  color: var(--muted);
  font-size: 12px;
}
.eval-mask {
  position: fixed;
  inset: 0;
  z-index: 13000;
  background: rgba(17, 24, 39, .34);
}
.eval-drawer {
  position: absolute;
  top: 0;
  right: 0;
  width: min(580px, 94vw);
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #fff;
  border-left: 1px solid var(--border);
  box-shadow: -18px 0 54px rgba(18, 25, 39, .16);
}
.eval-drawer-head {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 18px 20px;
  border-bottom: 1px solid var(--border);
}
.eval-drawer-head h2 { margin: 0; font-size: 16px; }
.eval-drawer-head p { margin: 4px 0 0; color: var(--muted); font-size: 12px; }
.eval-drawer-body { flex: 1; overflow: auto; padding: 16px 20px 24px; }
.eval-meta {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px 16px;
  margin-bottom: 16px;
  font-size: 12.5px;
}
.eval-meta span { color: var(--muted); }
.eval-joint { margin: 0 0 16px; color: var(--muted); font-size: 12.5px; line-height: 1.7; }
.eval-sec { margin: 0 0 18px; }
.eval-sec h4 { margin: 0 0 10px; font-size: 13px; }
.eval-sec p { margin: 8px 0 0; color: var(--muted); font-size: 12.5px; line-height: 1.7; }
.eval-bar {
  display: grid;
  grid-template-columns: 42px 1fr 42px;
  gap: 8px;
  align-items: center;
  margin: 6px 0;
  font-size: 12px;
}
.eval-bar i { display: block; height: 8px; border-radius: 99px; background: #edf0f5; overflow: hidden; }
.eval-bar i span { display: block; height: 100%; border-radius: 99px; }
.eval-engine { padding: 10px 0; border-bottom: 1px solid #edf0f5; font-size: 12.5px; }
.eval-engine:last-child { border-bottom: 0; }
.eval-engine-hd { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 4px; }
.eval-evidence { width: 100%; border-collapse: collapse; font-size: 12px; }
.eval-evidence th,
.eval-evidence td { padding: 8px 6px; border-bottom: 1px solid #edf0f5; text-align: left; vertical-align: top; }
.eval-evidence .subtle { margin-top: 2px; color: var(--muted); font-size: 11px; }
.eval-drawer-foot {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
  padding: 13px 20px;
  border-top: 1px solid var(--border);
  background: #fafbfc;
}
.eval-drawer-foot .mini-btn.primary {
  display: inline-flex;
  align-items: center;
  text-decoration: none;
}
@media (max-width: 1280px) {
  .layer-tabs { grid-template-columns: 1fr; }
}
</style>
