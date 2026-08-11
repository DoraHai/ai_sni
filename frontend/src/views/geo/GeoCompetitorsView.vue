<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  createGeoCompetitorReport,
  fetchGeoCompetitorCompare,
  fetchGeoCompetitorDaily,
  fetchGeoCompetitorInsights,
  fetchGeoCompetitorTrace,
  listCompetitorAliases,
  listGeoDailyMetrics,
  putCompetitorAliases,
  rebuildGeoDailyMetrics,
} from '../../api/geoContent'
import { useClientPager } from '../../composables/useClientPager'
import { useObservationPeriod } from '../../composables/useObservationPeriod'
import { session } from '../../store/session'
import {
  applyAliasMap,
  findAliasClusters,
  loadAliasMapAsync,
  saveAliasMapAsync,
} from '../../utils/competitorAlias'

const router = useRouter()
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
const aliasMap = ref({})
const displayItems = computed(() => applyAliasMap(rawItems.value, aliasMap.value))
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
const expandedUrl = ref('')
const historyItems = ref([])
const sourceTableRef = ref(null)

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

function historyKey() {
  return `geo_competitor_reports_v1_${tenantId.value || 0}`
}

function loadHistory(competitor) {
  try {
    const all = JSON.parse(localStorage.getItem(historyKey()) || '[]')
    historyItems.value = competitor
      ? all.filter((x) => x.competitor === competitor)
      : all
  } catch {
    historyItems.value = []
  }
}

function saveReportLocal(payload) {
  const all = (() => {
    try {
      return JSON.parse(localStorage.getItem(historyKey()) || '[]')
    } catch {
      return []
    }
  })()
  const entry = {
    id: `${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
    competitor: activeName.value,
    title: payload.title,
    markdown: payload.markdown,
    generated_at: payload.generated_at,
    source_count: payload.source_count,
    platform_count: payload.platform_count,
  }
  all.unshift(entry)
  localStorage.setItem(historyKey(), JSON.stringify(all.slice(0, 80)))
  reportSaved.value = true
  loadHistory(activeName.value)
}

function hasHistory(name) {
  try {
    const all = JSON.parse(localStorage.getItem(historyKey()) || '[]')
    return all.some((x) => x.competitor === name)
  } catch {
    return false
  }
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
    ])
    rawItems.value = data.items || []
    apiSummary.value = data.summary || null
    compareItems.value = cmp?.items || []
    compareSummary.value = cmp?.summary || null
    let dItems = daily?.items || []
    // 缺日指标时静默补算（不暴露「重算」按钮）
    if (!dItems.length && tenantId.value) {
      try {
        const to = new Date()
        const from = new Date()
        from.setDate(to.getDate() - (Number(dailyDays.value) || 14) + 1)
        const iso = (d) => d.toISOString().slice(0, 10)
        await rebuildGeoDailyMetrics(tenantId.value, {
          dateFrom: iso(from),
          dateTo: iso(to),
        })
        const daily2 = await listGeoDailyMetrics(tenantId.value, {
          date_from: iso(from),
          date_to: iso(to),
          scope_level: 'tenant',
        }).catch(() => null)
        dItems = daily2?.items || []
        dailyNote.value = daily2?.note || daily?.note || ''
        dailyCompetitors.value = daily2?.competitors || daily?.competitors || []
      } catch {
        /* keep empty */
      }
    }
    dailyItems.value = dItems
    if (!dailyCompetitors.value?.length) {
      dailyCompetitors.value = daily?.competitors || []
    }
    if (!dailyNote.value) dailyNote.value = daily?.note || ''
  } catch (e) {
    error.value = e.message || '加载失败'
    rawItems.value = []
    apiSummary.value = null
    compareItems.value = []
    compareSummary.value = null
    dailyItems.value = []
    dailyCompetitors.value = []
  } finally {
    loading.value = false
  }
}

const fmtRate = (v) => {
  if (v == null) return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return `${(n * 100).toFixed(1)}%`
}

function winnerLabel(w) {
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
    selectedUrls.value = (data.sources_agg || []).map((s) => s.url)
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
  if (n === 1 && !selectedUrls.value.length && !selectedPlatforms.value.length) {
    ElMessage.warning('请先选择至少一个平台或来源')
    return
  }
  reportStep.value = n
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
      insight: insight.value || null,
      action: action.value || null,
      note: note.value || null,
    })
    saveReportLocal(report.value)
    reportStep.value = 2
    ElMessage.success('报告已生成并保存到本机历史')
  } catch (e) {
    ElMessage.error(e.message || '生成报告失败')
  } finally {
    reportLoading.value = false
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

function viewHistoryItem(item) {
  report.value = item
  reportSaved.value = true
  reportStep.value = 2
  historyOpen.value = false
}

watch(tenantId, load)
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="geo-page">
    <div class="page-header">
      <div>
        <div class="page-title">竞品监测</div>
        <div class="page-desc">
          从可见度快照的竞品标注与引用 URL 聚合：看谁常被提到、同题谁领先，并支持按日监测与报告导出。
        </div>
      </div>
      <div class="header-actions">
        <el-button :loading="loading" @click="load">刷新</el-button>
        <router-link class="el-button" to="/geo/visibility">登记快照</router-link>
        <router-link class="el-button" to="/geo/citations">引用分析</router-link>
        <router-link class="el-button" to="/geo/evaluation">评价与位置</router-link>
      </div>
    </div>

    <details class="geo-glossary">
      <summary>统计口径（点击展开）</summary>
      <ul>
        <li>竞品名来自快照 competitors 字段（人工或 AI 建议）。</li>
        <li>日监测写入按天汇总表；缺行时刷新静默补算，无需手动重算。</li>
        <li>同题对比：同一意图词下本品提及 vs 竞品提及。</li>
        <li>别名合并仅保存在本机浏览器，用于展示归并，不改库内原始名。</li>
      </ul>
    </details>

    <el-alert v-if="error" :title="error" type="error" :closable="false" class="mb" />

    <div class="geo-kpi-grid">
      <div class="geo-kpi">
        <div class="kpi-label">竞品数</div>
        <div class="kpi-value">{{ summaryCards.competitor_count }}</div>
        <div class="kpi-hint">合并别名后的去重数量</div>
      </div>
      <div class="geo-kpi">
        <div class="kpi-label">被引用平台数</div>
        <div class="kpi-value">{{ summaryCards.platform_count }}</div>
        <div class="kpi-hint">全竞品来源平台去重</div>
      </div>
      <div class="geo-kpi">
        <div class="kpi-label">近 7 天新增来源</div>
        <div class="kpi-value">{{ summaryCards.sources_last_7d }}</div>
        <div class="kpi-hint">竞品快照中的去重 URL</div>
      </div>
      <div class="geo-kpi">
        <div class="kpi-label">待生成报告数</div>
        <div class="kpi-value">{{ summaryCards.reports_pending }}</div>
        <div class="kpi-hint">本机尚未保存报告的竞品</div>
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
        @row-click="(row) => row.prompt_id && router.push({ path: '/geo/visibility', query: { prompt_id: String(row.prompt_id) } })"
      >
        <el-table-column label="提问" min-width="200">
          <template #default="{ row }">
            <div class="q-clamp" :title="row.question">{{ row.question }}</div>
          </template>
        </el-table-column>
        <el-table-column label="本品提及" width="88">
          <template #default="{ row }">{{ fmtRate(row.brand_mention_rate) }}</template>
        </el-table-column>
        <el-table-column label="本品首位" width="88">
          <template #default="{ row }">{{ fmtRate(row.brand_first_rate) }}</template>
        </el-table-column>
        <el-table-column label="最强竞品" min-width="140">
          <template #default="{ row }">
            <span v-if="row.top_competitor">
              {{ row.top_competitor }} · {{ fmtRate(row.top_competitor_rate) }}
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
            去重来源 {{ trace.unique_url_count ?? (trace.sources_agg || []).length }} ·
            平台 {{ (trace.platforms || []).length }}
          </div>

          <el-steps :active="reportStep" finish-status="success" align-center class="mb steps">
            <el-step title="选择平台/来源" />
            <el-step title="洞察与行动" />
            <el-step title="生成并保存" />
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
              无平台数据：请到 AI 可见度补录 cited_urls
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
                <div class="plat-count">{{ p.cite_count }} 次引用</div>
                <div class="plat-bar">
                  <i :style="{ width: `${Math.round((p.cite_count / maxCite) * 100)}%` }" />
                </div>
                <div class="plat-domains">{{ (p.domains || []).slice(0, 2).join(' · ') || '—' }}</div>
              </button>
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
              <div>已选来源 {{ selectedUrls.length }} · 已选平台 {{ selectedPlatforms.length }}</div>
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
              <div>将写入报告：来源 {{ selectedUrls.length }} · 平台 {{ selectedPlatforms.length }}</div>
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
                生成并保存报告
              </el-button>
            </div>
          </div>

          <!-- Step 3 -->
          <div v-show="reportStep === 2">
            <el-result
              :icon="reportSaved ? 'success' : 'info'"
              :title="reportSaved ? '报告已保存' : '报告已生成'"
              :sub-title="report?.title || ''"
            >
              <template #extra>
                <div class="preview-strip mb">
                  来源 {{ report?.source_count ?? selectedUrls.length }} ·
                  平台 {{ report?.platform_count ?? selectedPlatforms.length }} ·
                  {{ reportSaved ? '本机历史已写入' : '未保存' }}
                </div>
                <div class="actions">
                  <el-button type="primary" @click="copyReport()">复制 Markdown</el-button>
                  <el-button @click="downloadReport()">下载 .md</el-button>
                  <el-button @click="openHistory">查看历史报告</el-button>
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

    <el-drawer v-model="historyOpen" title="历史报告（本机）" size="420px">
      <div v-if="!historyItems.length" class="empty-hint">暂无已保存报告</div>
      <div v-for="h in historyItems" :key="h.id" class="hist-card">
        <div class="hist-title">{{ h.title }}</div>
        <div class="hist-meta">
          {{ formatShortTime(h.generated_at) }} · 来源 {{ h.source_count || 0 }}
        </div>
        <div class="actions">
          <el-button size="small" type="primary" link @click="viewHistoryItem(h)">查看</el-button>
          <el-button size="small" link @click="copyReport(h.markdown)">复制</el-button>
          <el-button size="small" link @click="downloadReport(h)">下载</el-button>
        </div>
      </div>
    </el-drawer>
  </div>
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
.hist-card {
  border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px; margin-bottom: 10px; background: #fff;
}
.hist-title { font-size: 13px; font-weight: 600; color: #111827; }
.hist-meta { font-size: 12px; color: #6b7280; margin: 4px 0 8px; }
</style>
