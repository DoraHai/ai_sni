<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  batchUpdateCategory,
  fetchAdgroupList,
  fetchCampaignList,
  fetchKeywordList,
  matchTypeWriteback,
  pauseKeywordBatch,
  refreshKeywordWorkbench,
  writebackKeyword,
  writebackKeywordBatch,
} from '../../api/keywords'
import { setAdgroupBid, setAdgroupLandingUrl } from '../../api/manage'
import { fetchSuggestions, updateSuggestionStatus } from '../../api/suggestions'
import { session } from '../../store/session'
import MetricLabel from '../../components/MetricLabel.vue'

const TENANT_ID = computed(() => session.tenantId) // 当前客户，顶栏切换器驱动

const router = useRouter()
const route = useRoute()
const loading = ref(false)
const refreshing = ref(false)
const error = ref('')
const data = ref(null)
const selection = ref([])
const suggestionMap = ref({}) // keyword_id -> 该词的 AI 建议（全量 pending，独立于列表分页）
const suggestionList = ref([]) // AI 建议列表（顶部卡片区渲染）
const suggestionPending = ref(0)
const finalPrices = reactive({}) // keyword_id -> 最终执行价（可人工调整，默认=AI建议价/当前价），回写的就是它
const showAdvice = ref(true)
const tableRef = ref(null)
const campaignTableRef = ref(null)
const adgroupTableRef = ref(null)
const stickyScrollRef = ref(null)
const stickyScroll = reactive({
  visible: false,
  width: 0,
  left: 0,
  panelLeft: 0,
  panelWidth: 0,
})
let tableScrollWrap = null
let isSyncingScroll = false

// 视图 tabs：计划列表 / 单元列表 / 关键词列表 / 产品线视图，默认仍进入关键词列表。
const activeView = ref('keywords')
const campaignData = ref(null)
const adgroupData = ref(null)
const adgroupCampaignFilter = ref(null)

async function switchView(view) {
  activeView.value = view
  error.value = ''
  try {
    if (view === 'campaigns' && !campaignData.value) {
      loading.value = true
      campaignData.value = await fetchCampaignList({ tenantId: TENANT_ID.value })
    } else if (view === 'adgroups') {
      loading.value = true
      adgroupData.value = await fetchAdgroupList({
        tenantId: TENANT_ID.value,
        campaignId: adgroupCampaignFilter.value,
      })
    }
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
    scheduleStickyScrollSync()
  }
}

function activeTableComponent() {
  if (activeView.value === 'campaigns') return campaignTableRef.value
  if (activeView.value === 'adgroups') return adgroupTableRef.value
  return tableRef.value
}

function getTableScrollWrap(tableEl) {
  return tableEl?.querySelector?.('.el-table__body-wrapper .el-scrollbar__wrap')
    || tableEl?.querySelector?.('.el-scrollbar__wrap')
    || null
}

function detachTableScroll() {
  if (tableScrollWrap) tableScrollWrap.removeEventListener('scroll', syncStickyScrollPosition)
  tableScrollWrap = null
}

function updateStickyScrollVisibility() {
  const table = activeTableComponent()
  const tableEl = table?.$el || table
  const wrap = getTableScrollWrap(tableEl)
  const sticky = stickyScrollRef.value
  detachTableScroll()

  if (!wrap || !sticky) {
    stickyScroll.visible = false
    return
  }

  const rect = wrap.getBoundingClientRect()
  const hasHorizontalOverflow = wrap.scrollWidth > wrap.clientWidth + 2
  const isTableInViewport = rect.bottom > 96 && rect.top < window.innerHeight - 42

  stickyScroll.width = wrap.scrollWidth
  stickyScroll.panelLeft = Math.max(8, rect.left)
  stickyScroll.panelWidth = Math.max(120, Math.min(rect.width, window.innerWidth - stickyScroll.panelLeft - 8))
  stickyScroll.visible = hasHorizontalOverflow && isTableInViewport

  tableScrollWrap = wrap
  tableScrollWrap.addEventListener('scroll', syncStickyScrollPosition, { passive: true })
  syncStickyScrollPosition()
}

function syncStickyScrollPosition() {
  const sticky = stickyScrollRef.value
  if (!tableScrollWrap || !sticky || isSyncingScroll) return
  isSyncingScroll = true
  sticky.scrollLeft = tableScrollWrap.scrollLeft
  stickyScroll.left = tableScrollWrap.scrollLeft
  requestAnimationFrame(() => { isSyncingScroll = false })
}

function onStickyScroll() {
  const sticky = stickyScrollRef.value
  if (!tableScrollWrap || !sticky || isSyncingScroll) return
  isSyncingScroll = true
  tableScrollWrap.scrollLeft = sticky.scrollLeft
  stickyScroll.left = sticky.scrollLeft
  requestAnimationFrame(() => { isSyncingScroll = false })
}

function scheduleStickyScrollSync() {
  nextTick(() => {
    requestAnimationFrame(updateStickyScrollVisibility)
  })
}

function viewCampaignAdgroups(campaignId) {
  adgroupCampaignFilter.value = campaignId
  switchView('adgroups')
}

const EQUIPMENT_LABELS = { 1: '计算机', 2: '移动' }
const fmtRatio = (v) => (v == null ? '—' : v === 0 ? '0（移动不投）' : v < 0 ? '继承计划' : v)
function landingRows(row) {
  const rows = []
  if (row.mobile_final_url) rows.push({ key: 'mobile', label: '移动端', url: row.mobile_final_url })
  if (row.pc_final_url && row.pc_final_url !== row.mobile_final_url) rows.push({ key: 'pc', label: '网页端', url: row.pc_final_url })
  if (row.pc_final_url && row.pc_final_url === row.mobile_final_url && rows[0]) rows[0].label = '移动/网页'
  return rows
}
const blankToNull = (v) => {
  const s = String(v ?? '').trim()
  return s ? s : null
}

const landingDialog = reactive({
  visible: false,
  submitting: false,
  row: null,
  pcFinalUrl: '',
  mobileFinalUrl: '',
  pcTrackParam: '',
  mobileTrackParam: '',
  pcTrackTemplate: '',
  mobileTrackTemplate: '',
})

function openLanding(row) {
  Object.assign(landingDialog, {
    visible: true,
    submitting: false,
    row,
    pcFinalUrl: row.pc_final_url || '',
    mobileFinalUrl: row.mobile_final_url || '',
    pcTrackParam: row.pc_track_param || '',
    mobileTrackParam: row.mobile_track_param || '',
    pcTrackTemplate: row.pc_track_template || '',
    mobileTrackTemplate: row.mobile_track_template || '',
  })
}

function copyPcToMobile() {
  landingDialog.mobileFinalUrl = landingDialog.pcFinalUrl
  landingDialog.mobileTrackParam = landingDialog.pcTrackParam
  landingDialog.mobileTrackTemplate = landingDialog.pcTrackTemplate
}

async function saveLanding() {
  const row = landingDialog.row
  if (!row) return
  landingDialog.submitting = true
  try {
    const res = await setAdgroupLandingUrl({
      tenantId: TENANT_ID.value,
      adgroupId: row.adgroup_id,
      pcFinalUrl: blankToNull(landingDialog.pcFinalUrl),
      mobileFinalUrl: blankToNull(landingDialog.mobileFinalUrl),
      pcTrackParam: blankToNull(landingDialog.pcTrackParam),
      mobileTrackParam: blankToNull(landingDialog.mobileTrackParam),
      pcTrackTemplate: blankToNull(landingDialog.pcTrackTemplate),
      mobileTrackTemplate: blankToNull(landingDialog.mobileTrackTemplate),
    })
    const tag = res.dry_run ? '（演练：未真改）' : ''
    if (res.status === 'failed') ElMessage.error('失败：' + (res.error_msg || '未知错误'))
    else ElMessage.success(`落地页设置已提交${tag}`)
    landingDialog.visible = false
    await switchView('adgroups')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  } finally {
    landingDialog.submitting = false
  }
}

async function editAdgroupBid(row) {
  const { value } = await ElMessageBox.prompt(
    `单元「${row.adgroup_name}」当前出价 ${fmtMoney(row.max_price)}。\n输入新的单元出价（¥0.01 ~ 999.99，且不超过所属计划日预算）。当前为演练模式，只记台账不真改。`,
    '修改单元出价',
    {
      confirmButtonText: '确认',
      cancelButtonText: '取消',
      inputValue: row.max_price != null ? String(row.max_price) : '',
      inputPattern: /^\d+(\.\d{1,2})?$/,
      inputErrorMessage: '请输入合法金额（最多两位小数）',
    },
  ).catch(() => ({ value: null }))
  if (value == null) return

  const price = Number(value)
  if (!Number.isFinite(price) || price < 0.01 || price > 999.99) {
    ElMessage.warning('单元出价需在 ¥0.01 ~ 999.99 之间')
    return
  }
  try {
    const res = await setAdgroupBid({
      tenantId: TENANT_ID.value,
      adgroupId: row.adgroup_id,
      maxPrice: price,
    })
    const tag = res.dry_run ? '（演练：未真改）' : ''
    if (res.status === 'failed') ElMessage.error('失败：' + (res.error_msg || '未知错误'))
    else ElMessage.success(`单元出价已提交：${fmtMoney(res.old_price)} → ${fmtMoney(res.new_price)}${tag}`)
    await switchView('adgroups')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  }
}

// 已投放天数（首次出现在报告中至今）
function servingDays(row) {
  if (!row.first_seen_date) return null
  const days = Math.floor((Date.now() - new Date(row.first_seen_date)) / 86400000) + 1
  return days > 0 ? days : null
}

// rank-mini 迷你柱：排名越靠前柱越高；> 3 视为差（红柱），最后一根加深
function rankBars(row) {
  const trend = row.rank_trend || []
  const lastIdx = trend.map((v, i) => (v != null ? i : -1)).reduce((a, b) => Math.max(a, b), -1)
  return trend.map((v, i) => ({
    h: v == null ? 2 : Math.max(3, Math.round(14 * Math.max(0, (5 - Math.min(v, 5)) / 4))),
    cls: v == null ? 'empty' : v > 3 ? 'bad' : i === lastIdx ? 'now' : '',
  }))
}

const exporting = ref(false)
async function exportCsv() {
  exporting.value = true
  try {
    const resp = await fetch('/api/v1/keywords/export?' + new URLSearchParams({
      tenant_id: TENANT_ID.value,
      ...(filters.category && { category: filters.category }),
      ...(filters.campaignId != null && { campaign_id: filters.campaignId }),
      ...(filters.pause != null && { pause: filters.pause }),
      ...(filters.serving != null && { serving: filters.serving }),
      ...(filters.q && { q: filters.q }),
      ...(filters.coefWarning && { coef_warning: filters.coefWarning }),
      sort_by: filters.sortBy, order: filters.order,
    }), { headers: session.token ? { Authorization: `Bearer ${session.token}` } : { 'X-API-Key': import.meta.env.VITE_API_KEY || '' } })
    if (!resp.ok) throw new Error('导出失败 HTTP ' + resp.status)
    const blob = await resp.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `keywords_${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    exporting.value = false
  }
}

// 5 类分级配色（原型 3.0：kw-pill / kw-chip 同源色板）
const CATEGORY_COLORS = {
  brand: { fg: '#6B47B5', bg: '#F2EBFB' },
  focus: { fg: '#185FA5', bg: '#EFF4FB' },
  normal: { fg: '#1D9E75', bg: '#E5F4ED' },
  longtail: { fg: '#BA7517', bg: '#FDF6E8' },
  new: { fg: '#6B7280', bg: '#F3F4F6' },
}
const CATEGORY_CHIPS = [
  { code: '', label: '全部', color: '#185FA5' },
  { code: 'brand', label: '品牌词', color: '#6B47B5' },
  { code: 'focus', label: '重点词', color: '#185FA5' },
  { code: 'normal', label: '一般词', color: '#1D9E75' },
  { code: 'longtail', label: '长尾精准', color: '#BA7517' },
  { code: 'new', label: '新词', color: '#6B7280' },
]
const CATEGORY_CODES = new Set(CATEGORY_CHIPS.map((c) => c.code).filter(Boolean))

const MATCH_TYPE_OPTIONS = {
  exact: { matchType: 1, phraseType: 1, label: '精确匹配' },
  phrase: { matchType: 2, phraseType: 1, label: '短语匹配' },
  smart: { matchType: 2, phraseType: 3, label: '智能匹配' },
}

const BATCH_CATEGORY_OPTIONS = [
  { code: 'brand', label: '标记为品牌词' },
  { code: 'focus', label: '标记为重点词' },
  { code: 'normal', label: '标记为一般词' },
  { code: 'longtail', label: '标记为长尾精准词' },
  { code: 'new', label: '标记为新词' },
  { code: 'auto', label: '恢复自动分级' },
]

const filters = reactive({
  category: route.query.category && CATEGORY_CODES.has(String(route.query.category)) ? String(route.query.category) : '',
  campaignId: null,
  pause: null, // null=全部 false=已启用 true=已暂停
  serving: null, // null=全部 true=当前在投 false=当前未投（暂停或时段不投）
  coefWarning: '',
  hasSuggestion: null,
  q: '',
  sortBy: 'impression',
  order: 'desc',
  page: 1,
  pageSize: 20,
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    // 列表与 AI 建议并行拉；建议拉取失败不影响工作台
    const [list, sug] = await Promise.all([
      fetchKeywordList({ tenantId: TENANT_ID.value, ...filters }),
      fetchSuggestions({ tenantId: TENANT_ID.value }).catch(() => null),
    ])
    data.value = list
    if (sug) {
      const m = {}
      const list = []
      for (const s of sug.suggestions || []) {
        if (s.keyword_id) {
          m[s.keyword_id] = s
          list.push(s)
        }
      }
      suggestionMap.value = m
      suggestionList.value = list
      suggestionPending.value = sug.total_pending || 0
    }
    initFinalPrices(list.keywords)
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function refreshData() {
  if (refreshing.value) return
  refreshing.value = true
  error.value = ''
  let syncStatus = 'local'
  try {
    if (session.canEdit('optimize.keywords')) {
      const result = await refreshKeywordWorkbench({ tenantId: TENANT_ID.value })
      syncStatus = result.status
      if (result.status === 'error') {
        throw new Error(result.message || '百度数据同步失败')
      }
      if (result.status === 'busy') {
        ElMessage.info('当前客户的数据正在同步，已为你加载最新可用数据')
      }
    }

    campaignData.value = null
    adgroupData.value = null
    await load()
    if (activeView.value === 'campaigns') {
      await switchView('campaigns')
    } else if (activeView.value === 'adgroups') {
      await switchView('adgroups')
    }
    if (syncStatus === 'ok') ElMessage.success('百度数据同步完成')
    else if (syncStatus !== 'busy') ElMessage.success('已加载最新同步数据')
  } catch (e) {
    error.value = e.message
    ElMessage.error(e.message)
  } finally {
    refreshing.value = false
  }
}

// 最终执行价默认值：有 AI 建议价用建议价，否则用当前出价。每次加载重置当前页。
function initFinalPrices(rows) {
  for (const row of rows || []) {
    const sug = suggestionMap.value[row.keyword_id]
    const def = sug && sug.suggested_bid != null ? Number(sug.suggested_bid) : Number(row.price)
    finalPrices[row.keyword_id] = def != null && !Number.isNaN(def) ? def : null
  }
}

// 筛选变化回第一页重查；搜索框防抖
watch(
  () => [filters.category, filters.campaignId, filters.pause, filters.serving, filters.coefWarning, filters.hasSuggestion],
  () => { filters.page = 1; load() },
)
watch(
  () => route.query.category,
  (category) => {
    const next = category && CATEGORY_CODES.has(String(category)) ? String(category) : ''
    if (next && next !== filters.category) {
      filters.category = next
      activeView.value = 'keywords'
    }
  },
)
let qTimer = null
watch(() => filters.q, () => {
  clearTimeout(qTimer)
  qTimer = setTimeout(() => { filters.page = 1; load() }, 400)
})
watch(() => [filters.page, filters.pageSize], load)

function onSortChange({ prop, order }) {
  const map = {
    total_impression: 'impression',
    price: 'price',
    quality: 'quality',
    clicks_7d: 'clicks_7d',
    cost_7d: 'cost_7d',
  }
  if (!order || !map[prop]) {
    filters.sortBy = 'impression'
    filters.order = 'desc'
  } else {
    filters.sortBy = map[prop]
    filters.order = order === 'ascending' ? 'asc' : 'desc'
  }
  filters.page = 1
  load()
}

function categoryCount(code) {
  if (!data.value) return null
  if (!code) return data.value.totals.keywords
  return data.value.category_counts[code] ?? 0
}

async function onBatchCategory(code) {
  const ids = selection.value.map((r) => r.keyword_id)
  if (!ids.length) return
  const label = BATCH_CATEGORY_OPTIONS.find((o) => o.code === code)?.label || code
  try {
    await ElMessageBox.confirm(`将选中的 ${ids.length} 个关键词「${label}」？`, '批量改分级', {
      confirmButtonText: '确认',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch { return }
  try {
    const res = await batchUpdateCategory({ tenantId: TENANT_ID.value, keywordIds: ids, category: code })
    ElMessage.success(`已更新 ${res.updated} 个关键词`)
    tableRef.value?.clearSelection()
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

function gotoDetail(row) {
  router.push(`/monitor/keywords/${row.keyword_id}?from=workbench`)
}

function _removeSuggestion(kwId) {
  const m = { ...suggestionMap.value }
  delete m[kwId]
  suggestionMap.value = m
  suggestionList.value = suggestionList.value.filter((s) => s.keyword_id !== kwId)
  suggestionPending.value = Math.max(0, suggestionPending.value - 1)
}

// 回写的是「最终执行价」(finalPrices，可人工调整，默认=AI建议价/当前价)，不限于有 AI 建议的词
async function applyWriteback(row) {
  const price = finalPrices[row.keyword_id]
  if (price == null || !(Number(price) > 0)) {
    ElMessage.warning('请先填写有效的最终执行价')
    return
  }
  try {
    await ElMessageBox.confirm(
      `将把「${row.keyword}」出价回写为 ¥${Number(price).toFixed(2)}（当前 ¥${fmtNum(row.price)}）。\n` +
        `系统受 ±20% 渐进调价硬上限保护，并全程记入回写台账。\n` +
        `若当前为演练模式，仅记台账、不会真改线上出价。`,
      '回写出价到百度',
      { confirmButtonText: '确认回写', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  try {
    const res = await writebackKeyword({ keywordId: row.keyword_id, tenantId: TENANT_ID.value, price })
    if (res.dry_run) {
      ElMessage.warning('演练模式：已记入回写台账，未真改线上出价（管理员开启真写后方可生效）')
    } else {
      _removeSuggestion(row.keyword_id)
      ElMessage.success(`已回写百度：¥${Number(price).toFixed(2)}`)
      load()
    }
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  }
}

async function openMatchTypeDialog(row, command) {
  if (!command) return
  const target = MATCH_TYPE_OPTIONS[command]
  if (!target) return
  try {
    await ElMessageBox.confirm(
      `确认将「${row.keyword}」的匹配模式从「${row.match_type || '—'}」改为「${target.label}」？\n` +
        `当前为演练模式时，仅记入回写台账、不会真改线上匹配模式。`,
      '确认修改匹配模式',
      { confirmButtonText: '确认修改', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  try {
    const res = await matchTypeWriteback({
      keywordId: row.keyword_id,
      tenantId: TENANT_ID.value,
      matchType: target.matchType,
      phraseType: target.phraseType,
    })
    if (res.dry_run) {
      ElMessage.warning('演练模式：已记入台账，未真改线上匹配模式')
    } else if (res.status === 'failed') {
      ElMessage.error(res.writeback?.error_msg || '修改匹配模式失败')
    } else {
      ElMessage.success(`已回写百度：${target.label}`)
      load()
    }
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  }
}

async function batchWriteback() {
  // 勾选行的最终执行价批量回写（每行各自的 finalPrices）
  const items = selection.value
    .filter((r) => finalPrices[r.keyword_id] != null && Number(finalPrices[r.keyword_id]) > 0)
    .map((r) => ({ keyword_id: r.keyword_id, price: Number(finalPrices[r.keyword_id]) }))
  if (!items.length) {
    ElMessage.warning('所选关键词没有有效的最终执行价')
    return
  }
  try {
    await ElMessageBox.confirm(
      `将对 ${items.length} 个关键词回写各自的最终执行价（受 ±20% 渐进调价硬上限保护并记台账）。\n` +
        `若当前为演练模式，仅记台账、不会真改线上出价。`,
      '批量回写出价到百度',
      { confirmButtonText: `确认回写 ${items.length} 个`, cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  try {
    const res = await writebackKeywordBatch({ tenantId: TENANT_ID.value, items })
    const parts = []
    if (res.applied.length) parts.push(`已写回 ${res.applied.length}`)
    if (res.simulated.length) parts.push(`演练 ${res.simulated.length}（未真改线上）`)
    if (res.rejected.length) parts.push(`跳过 ${res.rejected.length}（超限/越界）`)
    if (res.failed.length) parts.push(`失败 ${res.failed.length}`)
    const msg = parts.join(' · ') || '没有可回写的关键词'
    if (res.failed.length || res.rejected.length || res.simulated.length) ElMessage.warning(msg)
    else ElMessage.success(msg)
    res.applied.forEach((kwId) => _removeSuggestion(kwId))
    tableRef.value?.clearSelection()
    if (res.applied.length) load()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  }
}

async function togglePause(row) {
  const pause = !row.pause
  const action = pause ? '暂停' : '启用'
  try {
    await ElMessageBox.confirm(
      `将${action}关键词「${row.keyword}」。\n受 dry-run 保护，演练模式下不真改线上。`,
      `确认${action}`,
      { confirmButtonText: `确认${action}`, cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  try {
    const res = await pauseKeywordBatch({ tenantId: TENANT_ID.value, keywordIds: [row.keyword_id], pause })
    const parts = []
    if (res.applied.length) parts.push(`已${action} ${res.applied.length}`)
    if (res.simulated.length) parts.push(`演练 ${res.simulated.length}（未真改线上）`)
    if (res.failed.length) parts.push(`失败 ${res.failed.length}`)
    const msg = parts.join(' · ') || '无可操作关键词'
    if (res.failed.length || res.simulated.length) ElMessage.warning(msg)
    else ElMessage.success(msg)
    if (res.applied.length) load()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  }
}

async function batchPause(pause) {
  const ids = selection.value.map((r) => r.keyword_id)
  if (!ids.length) return
  try {
    await ElMessageBox.confirm(
      `将批量${pause ? '暂停' : '启用'} ${ids.length} 个关键词。\n受 dry-run 保护，演练模式下不真改线上。`,
      pause ? '批量暂停' : '批量启用',
      { confirmButtonText: `确认${pause ? '暂停' : '启用'} ${ids.length} 个`, cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  try {
    const res = await pauseKeywordBatch({ tenantId: TENANT_ID.value, keywordIds: ids, pause })
    const parts = []
    if (res.applied.length) parts.push(`已${pause ? '暂停' : '启用'} ${res.applied.length}`)
    if (res.simulated.length) parts.push(`演练 ${res.simulated.length}（未真改线上）`)
    if (res.failed.length) parts.push(`失败 ${res.failed.length}`)
    const msg = parts.join(' · ') || '无可操作关键词'
    if (res.failed.length || res.simulated.length) ElMessage.warning(msg)
    else ElMessage.success(msg)
    tableRef.value?.clearSelection()
    if (res.applied.length) load()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  }
}

async function ignoreSuggestion(s) {
  try {
    await updateSuggestionStatus(s.id, 'ignored')
    _removeSuggestion(s.keyword_id)
    ElMessage.success('已忽略该建议')
  } catch (e) {
    ElMessage.error(e.message)
  }
}

const fmtMoney = (v) => (v == null ? '—' : '¥ ' + Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 2 }))
const fmtInt = (v) => (v == null ? '—' : Number(v).toLocaleString('zh-CN'))
const fmtPct = (v) => (v == null ? '—' : v.toFixed(2) + '%')
const fmtNum = (v) => (v == null ? '—' : Number(v).toFixed(2))
// 置信度 → 风险标签（置信度高=风险低）
function riskOf(conf) {
  if (conf === 'high') return { label: '低风险', cls: 'low' }
  if (conf === 'low') return { label: '高风险', cls: 'high' }
  return { label: '中风险', cls: 'mid' }
}
function suggestionRiskNote(s) {
  if (s?.signals?.risk_note) return s.signals.risk_note
  if (s?.suggestion_type === 'lower') return '降价可能压低有效流量，执行前请确认该词不是核心业务词。'
  if (s?.suggestion_type === 'raise') return '加价会提高消耗，执行后需观察点击成本、转化和预算占用。'
  return ''
}

const multClass = (w) => (w === 'red' ? 'danger' : w === 'orange' ? 'warn' : '')
// 质量度 1-10：≤ 4 红 / ≤ 6 黄 / 其余绿（原型 qs-bar 分档）
const qualityClass = (q) => (q == null ? '' : q <= 4 ? 'bad' : q <= 6 ? 'mid' : 'good')

const headerStats = computed(() => {
  if (!data.value) return ''
  const t = data.value.totals
  const win = data.value.metrics_window
  const synced = t.last_synced_at
    ? ` · 数据更新于 ${t.last_synced_at.slice(5, 16).replace('T', ' ')}`
    : ''
  const serving = t.serving_now != null
    ? ` · 当前在投 ${fmtInt(t.serving_now)}（${t.current_slot}）`
    : ''
  return `${t.campaigns} 计划 / ${t.adgroups} 单元 / ${fmtInt(t.keywords)} 关键词` + serving +
    (win ? ` · 7 天指标窗口 ${win.start} ~ ${win.end}` : '') + synced + ' · 每 15 分钟自动同步'
})

// 顶栏切换客户后重新拉数
watch(TENANT_ID, () => { filters.page = 1; campaignData.value = null; adgroupData.value = null; activeView.value = 'keywords'; load(); scheduleStickyScrollSync() })
watch(activeView, scheduleStickyScrollSync)
watch(() => [data.value?.keywords?.length, campaignData.value?.campaigns?.length, adgroupData.value?.adgroups?.length, loading.value], scheduleStickyScrollSync)

onMounted(() => {
  load()
  window.addEventListener('resize', updateStickyScrollVisibility)
  window.addEventListener('scroll', updateStickyScrollVisibility, { passive: true })
  scheduleStickyScrollSync()
})

onBeforeUnmount(() => {
  detachTableScroll()
  window.removeEventListener('resize', updateStickyScrollVisibility)
  window.removeEventListener('scroll', updateStickyScrollVisibility)
})
</script>

<template>
  <div class="workbench">
    <el-alert v-if="error" :title="error" type="error" show-icon style="margin-bottom: 12px" />

    <div class="page-header">
      <div class="page-header-main">
        <div class="page-title">关键词工作台</div>
        <div class="page-actions">
          <div class="media-select">
            <span class="media-label">媒体</span>
            <el-select model-value="baidu" style="width: 150px" size="default">
              <el-option label="百度推广" value="baidu" />
              <el-option label="必应（即将开放）" value="bing" disabled />
            </el-select>
          </div>
          <button
            class="pbtn refresh-btn"
            :disabled="refreshing || loading"
            title="后台每 15 分钟自动同步；点击可立即刷新"
            @click="refreshData"
          >
            <span class="refresh-icon" :class="{ spinning: refreshing }">↻</span>
            {{ refreshing ? '同步中…' : '刷新数据' }}
          </button>
          <button class="pbtn" :disabled="exporting" @click="exportCsv">{{ exporting ? '导出中…' : '导出' }}</button>
          <el-tooltip content="导入/新建属写回类操作，按路线图 M2 实现，当前平台对百度只读" placement="bottom">
            <button class="pbtn" disabled>导入关键词</button>
          </el-tooltip>
          <el-tooltip content="调价写回（updateWord）按路线图 M2 实现，当前平台对百度只读" placement="bottom">
            <button class="pbtn" disabled>批量调价</button>
          </el-tooltip>
        </div>
      </div>
      <div class="page-desc">{{ headerStats }}</div>
    </div>

    <!-- 视图 tabs（原型 view-tabs） -->
    <div class="view-tabs">
      <div class="view-tab" :class="{ active: activeView === 'campaigns' }" @click="switchView('campaigns')">
        计划列表<span class="v-count">{{ data?.totals.campaigns ?? '—' }}</span>
      </div>
      <div class="view-tab" :class="{ active: activeView === 'adgroups' }" @click="switchView('adgroups')">
        单元列表<span class="v-count">{{ data?.totals.adgroups ?? '—' }}</span>
      </div>
      <div class="view-tab" :class="{ active: activeView === 'keywords' }" @click="switchView('keywords')">
        关键词列表<span class="v-count">{{ data?.totals.keywords ?? '—' }}</span>
      </div>
      <el-tooltip content="产品线维度（多计划合并视图）待定义分组规则后开放" placement="top">
        <div class="view-tab disabled">产品线视图</div>
      </el-tooltip>
    </div>

    <template v-if="activeView === 'keywords'">
    <!-- 分级 chips（原型 kw-chips：彩点 + 计数） -->
    <div class="kw-chips">
      <div
        v-for="c in CATEGORY_CHIPS"
        :key="c.code"
        class="kw-chip"
        :class="{ active: filters.category === c.code }"
        :style="filters.category === c.code ? { background: c.color, borderColor: 'transparent' } : {}"
        @click="filters.category = c.code"
      >
        <span class="k-dot" :style="{ background: filters.category === c.code ? 'rgba(255,255,255,0.85)' : c.color }" />
        {{ c.label }}
        <span class="k-count">{{ categoryCount(c.code) ?? '—' }}</span>
      </div>
    </div>

    <!-- 筛选行 -->
    <div class="filter-row">
      <el-select v-model="filters.campaignId" placeholder="全部计划" clearable size="default" style="width: 200px">
        <el-option
          v-for="c in data?.campaign_options || []"
          :key="c.campaign_id"
          :label="c.campaign_name"
          :value="c.campaign_id"
        />
      </el-select>
      <el-select v-model="filters.pause" placeholder="全部状态" clearable style="width: 120px">
        <el-option label="已启用" :value="false" />
        <el-option label="已暂停" :value="true" />
      </el-select>
      <el-select v-model="filters.serving" placeholder="当前投放 · 全部" clearable style="width: 150px">
        <el-option label="🟢 当前在投" :value="true" />
        <el-option label="⚪ 当前未投" :value="false" />
      </el-select>
      <el-select v-model="filters.coefWarning" placeholder="系数预警 · 全部" clearable style="width: 180px">
        <el-option label="红色（> 基础 × 4）" value="red" />
        <el-option label="橙色（> 基础 × 3）" value="orange" />
        <el-option label="正常" value="normal" />
      </el-select>
      <el-select v-model="filters.hasSuggestion" placeholder="AI 建议 · 全部" clearable style="width: 150px">
        <el-option label="只看有 AI 建议" :value="true" />
        <el-option label="无 AI 建议" :value="false" />
      </el-select>
      <el-input
        v-model="filters.q"
        placeholder="搜索关键词"
        clearable
        style="width: 220px"
        prefix-icon="Search"
      />
    </div>

    <!-- 批量操作条（常驻，勾选后点亮，原型 bulk-toolbar） -->
    <div v-if="session.canEdit('optimize.keywords')" class="bulk-toolbar" :class="{ active: selection.length }">
      <span class="bt-count">
        已选 <b>{{ selection.length }}</b> 个
        <span v-if="!selection.length" class="bt-hint">· 勾选关键词以启用批量操作</span>
      </span>
      <div class="bt-actions">
        <el-dropdown trigger="click" :disabled="!selection.length" @command="onBatchCategory">
          <button class="bt-btn bt-primary" :disabled="!selection.length">批量改分级 ▾</button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item v-for="o in BATCH_CATEGORY_OPTIONS" :key="o.code" :command="o.code">
                {{ o.label }}
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-tooltip content="对所选关键词回写各自的「最终执行价」（默认=AI建议价，可在表内调整），受 ±20% 硬上限保护并记台账；演练模式下不真改线上" placement="top">
          <button class="bt-btn bt-primary" :disabled="!selection.length" @click="batchWriteback">批量回写</button>
        </el-tooltip>
        <el-tooltip content="批量暂停所选关键词（updateWord 写回，dry-run 保护，演练模式不真改线上）" placement="top">
          <button class="bt-btn" :disabled="!selection.length" @click="batchPause(true)">批量暂停</button>
        </el-tooltip>
        <el-tooltip content="批量启用所选关键词（updateWord 写回，dry-run 保护，演练模式不真改线上）" placement="top">
          <button class="bt-btn" :disabled="!selection.length" @click="batchPause(false)">批量启用</button>
        </el-tooltip>
        <el-tooltip content="写回类操作按路线图 M2 实现" placement="top">
          <button class="bt-btn" disabled>批量加否词</button>
        </el-tooltip>
        <span v-if="selection.length" class="bt-clear" @click="tableRef?.clearSelection()">取消选择</span>
      </div>
    </div>

    <div v-if="suggestionPending" class="ai-note">
      💡 本页含 AI 调价建议（共 <b>{{ suggestionPending }}</b> 条待处理），见下表「AI 建议」列；可「回写出价」一键写回百度（受 ±20% 硬上限保护并记台账，演练模式下不真改线上）。
    </div>

    <div class="table-panel">
      <el-table
        ref="tableRef"
        v-loading="loading"
        :data="data?.keywords || []"
        row-key="keyword_id"
        class="kw-table"
        @selection-change="selection = $event"
        @sort-change="onSortChange"
      >
        <el-table-column type="selection" width="40" reserve-selection />
        <el-table-column label="关键词" width="172" fixed>
          <template #default="{ row }">
            <div class="kw-cell-name">
              <span class="kw-name-text" @click="gotoDetail(row)">{{ row.keyword }}</span>
              <span
                v-if="row.category?.code"
                class="kw-pill"
                :style="{ color: CATEGORY_COLORS[row.category.code]?.fg, background: CATEGORY_COLORS[row.category.code]?.bg }"
              >{{ row.category.label }}<template v-if="row.category.source === 'manual'">·人工</template></span>
            </div>
            <div class="kw-cell-sub">
              <el-dropdown trigger="click" @command="(cmd) => openMatchTypeDialog(row, cmd)">
                <span class="match-type-trigger">
                  {{ row.match_type || '—' }}
                  <span class="match-type-caret">▾</span>
                </span>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="exact">精确匹配</el-dropdown-item>
                    <el-dropdown-item command="phrase">短语匹配</el-dropdown-item>
                    <el-dropdown-item command="smart">智能匹配</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown><template v-if="servingDays(row)"> · 已投放 {{ servingDays(row) }} 天</template>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="所属计划 / 单元" min-width="150">
          <template #default="{ row }">
            <div class="plan-line">{{ row.campaign_name || '—' }}</div>
            <div class="kw-cell-sub">{{ row.adgroup_name || '—' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="价格调整" width="190">
          <template #header>
            价格调整
            <el-tooltip placement="top" content="最终执行价默认填入 AI 建议价（无建议则为当前出价），可人工调整。「回写出价」回写的就是最终执行价，受 ±20% 硬上限保护并记台账，演练模式下不真改线上。">
              <span class="dim">ⓘ</span>
            </el-tooltip>
          </template>
          <template #default="{ row }">
            <div class="pa-row">
              <span class="pa-label">当前出价</span>
              <span class="pa-val">{{ fmtMoney(row.price) }}</span>
              <span v-if="row.effective && row.effective.warning !== 'normal'" class="pa-coef" :class="multClass(row.effective.warning)">×{{ row.effective.multiplier }}⚠</span>
            </div>
            <div v-if="suggestionMap[row.keyword_id] && suggestionMap[row.keyword_id].suggested_bid != null" class="pa-row">
              <span class="pa-label">AI 建议价</span>
              <span class="pa-val ai">{{ fmtMoney(suggestionMap[row.keyword_id].suggested_bid) }}</span>
              <span class="pa-pct" :class="suggestionMap[row.keyword_id].change_pct >= 0 ? 'up' : 'down'">{{ suggestionMap[row.keyword_id].change_pct > 0 ? '↑' : '↓' }}{{ Math.abs(suggestionMap[row.keyword_id].change_pct) }}%</span>
            </div>
            <div class="pa-row">
              <span class="pa-label">最终执行价</span>
              <el-input-number
                v-model="finalPrices[row.keyword_id]"
                :min="0.01"
                :max="999.99"
                :step="0.1"
                :precision="2"
                size="small"
                controls-position="right"
                class="pa-input"
              />
            </div>
          </template>
        </el-table-column>
        <el-table-column label="AI 建议" min-width="220">
          <template #default="{ row }">
            <template v-if="suggestionMap[row.keyword_id]">
              <div class="ai-tags">
                <span class="ai-tag act">{{ suggestionMap[row.keyword_id].type_label }}</span>
                <span class="ai-tag" :class="'risk-' + riskOf(suggestionMap[row.keyword_id].confidence).cls">{{ riskOf(suggestionMap[row.keyword_id].confidence).label }}</span>
              </div>
              <div class="ai-reason-line">{{ suggestionMap[row.keyword_id].reason }}</div>
              <div v-if="suggestionRiskNote(suggestionMap[row.keyword_id])" class="ai-risk-line">
                注意：{{ suggestionRiskNote(suggestionMap[row.keyword_id]) }}
              </div>
            </template>
            <span v-else class="dim">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="quality" label="质量度" width="88" sortable="custom">
          <template #default="{ row }">
            <div v-if="row.quality != null" class="qs-cell">
              <span class="qs-num">{{ row.quality }}</span>
              <span class="qs-bar"><span class="qs-fill" :class="qualityClass(row.quality)" :style="{ width: Math.min(100, row.quality * 10) + '%' }" /></span>
            </div>
            <span v-else class="dim">—</span>
          </template>
        </el-table-column>
        <el-table-column label="点击指标" width="180">
          <template #header>
            点击指标
            <el-tooltip placement="top" content="近 7 天 · 点击 / 点击率(CTR=点击÷展现) / 点击成本(CPC=消费÷点击)">
              <span class="dim">ⓘ</span>
            </el-tooltip>
          </template>
          <template #default="{ row }">
            <div class="mg-row"><span class="mg-label mg-label-w">7天点击</span><span class="mg-val num">{{ fmtInt(row.metrics_7d?.click) }}</span></div>
            <div class="mg-row"><span class="mg-label mg-label-w">点击率（CTR）</span><span class="mg-val num">{{ fmtPct(row.metrics_7d?.ctr) }}</span></div>
            <div class="mg-row"><span class="mg-label mg-label-w">点击成本（CPC）</span><span class="mg-val num">{{ fmtMoney(row.metrics_7d?.cpc) }}</span></div>
          </template>
        </el-table-column>
        <el-table-column label="转化 / 展现" width="132">
          <template #header>
            转化 / 展现
            <el-tooltip placement="top" content="转化=近7天电话按钮点击量（ocpcConversionsDetail2）；转化成本=消费÷转化；展现为累计展现">
              <span class="dim">ⓘ</span>
            </el-tooltip>
          </template>
          <template #default="{ row }">
            <div class="mg-row">
              <span class="mg-label">7天转化</span>
              <span class="mg-val num" :class="{ 'conv-zero': row.metrics_7d?.cost && !row.metrics_7d?.conversions }">{{ fmtInt(row.metrics_7d?.conversions) }}</span>
            </div>
            <div class="mg-row"><span class="mg-label">转化成本</span><span class="mg-val num">{{ fmtMoney(row.metrics_7d?.conv_cost) }}</span></div>
            <div class="mg-row"><span class="mg-label">展现</span><span class="mg-val num">{{ fmtInt(row.total_impression) }}</span></div>
          </template>
        </el-table-column>
        <el-table-column label="投放状态" width="124">
          <template #header>
            投放状态
            <el-tooltip placement="top" :content="'上行=启用/暂停；下行=当前投放（按 词/单元/计划暂停 + 分时段判定） · 当前时段 ' + (data?.totals?.current_slot || '')">
              <span class="dim">ⓘ</span>
            </el-tooltip>
          </template>
          <template #default="{ row }">
            <div class="mg-row">
              <span v-if="row.pause === true" class="status-pill off"><span class="status-dot" />已暂停</span>
              <span v-else-if="row.pause === false" class="status-pill on"><span class="status-dot" />已启用</span>
              <span v-else class="dim">—</span>
            </div>
            <div class="mg-row">
              <span v-if="row.serving?.now" class="status-pill on"><span class="status-dot" />投放中</span>
              <span v-else-if="row.serving" class="status-pill" :class="row.serving.reason === '当前时段不投放' ? 'slot' : 'off'"><span class="status-dot" />{{ row.serving.reason }}</span>
              <span v-else class="dim">—</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="148" fixed="right">
          <template #default="{ row }">
            <div class="op-cell">
              <button class="op-btn primary" @click="applyWriteback(row)">回写出价</button>
              <button class="op-btn" @click="openMatchTypeDialog(row, 'phrase')">改匹配</button>
              <button class="op-btn" @click="togglePause(row)">{{ row.pause ? '启用' : '暂停' }}</button>
              <button v-if="suggestionMap[row.keyword_id]" class="op-btn" @click="ignoreSuggestion(suggestionMap[row.keyword_id])">忽略建议</button>
              <button class="op-btn" @click="gotoDetail(row)">详情</button>
            </div>
          </template>
        </el-table-column>
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
    </template>

    <!-- 计划列表视图 -->
    <div v-if="activeView === 'campaigns'" class="table-panel">
      <el-table ref="campaignTableRef" v-loading="loading" :data="campaignData?.campaigns || []" class="kw-table" row-key="campaign_id">
        <el-table-column label="计划" min-width="200">
          <template #default="{ row }">
            <div class="kw-cell-name">{{ row.campaign_name }}</div>
            <div class="kw-cell-sub">{{ EQUIPMENT_LABELS[row.equipment_type] || '全部设备' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="日预算" width="110" align="right">
          <template #default="{ row }"><span class="num">{{ fmtMoney(row.budget) }}</span></template>
        </el-table-column>
        <el-table-column label="移动比例" width="110" align="right">
          <template #default="{ row }"><span class="num">{{ fmtRatio(row.price_ratio) }}</span></template>
        </el-table-column>
        <el-table-column label="分时段 / 分地域" width="120" align="center">
          <template #default="{ row }">
            <span class="num">{{ row.schedule_entries }}</span> / <span class="num">{{ row.region_entries }}</span>
          </template>
        </el-table-column>
        <el-table-column label="单元数" width="84" align="right">
          <template #default="{ row }"><span class="num">{{ fmtInt(row.adgroup_count) }}</span></template>
        </el-table-column>
        <el-table-column label="关键词数" width="94" align="right">
          <template #default="{ row }"><span class="num">{{ fmtInt(row.keyword_count) }}</span></template>
        </el-table-column>
        <el-table-column label="7天消费" width="100" align="right">
          <template #default="{ row }"><span class="num">{{ fmtMoney(row.metrics_7d?.cost) }}</span></template>
        </el-table-column>
        <el-table-column label="7天点击" width="94" align="right">
          <template #default="{ row }"><span class="num">{{ fmtInt(row.metrics_7d?.click) }}</span></template>
        </el-table-column>
        <el-table-column label="线索数" width="92" align="right">
          <template #header>
            线索数
            <el-tooltip placement="top" content="该计划累计有效线索（手动录入按计划归因 + 百度同步带计划），累计口径">
              <span class="dim">ⓘ</span>
            </el-tooltip>
          </template>
          <template #default="{ row }">
            <span class="num" :class="{ 'lead-has': row.leads_total > 0 }">{{ fmtInt(row.leads_total) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="线索成本" width="104" align="right">
          <template #header>
            线索成本
            <el-tooltip placement="top" content="累计消费 ÷ 累计线索数（该计划）">
              <span class="dim">ⓘ</span>
            </el-tooltip>
          </template>
          <template #default="{ row }"><span class="num">{{ row.lead_cost == null ? '—' : fmtMoney(row.lead_cost) }}</span></template>
        </el-table-column>
        <el-table-column label="状态" width="86">
          <template #default="{ row }">
            <span v-if="row.pause === true" class="status-pill off"><span class="status-dot" />已暂停</span>
            <span v-else-if="row.pause === false" class="status-pill on"><span class="status-dot" />已启用</span>
            <span v-else class="dim">—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="96">
          <template #default="{ row }">
            <button class="row-action" @click="viewCampaignAdgroups(row.campaign_id)">查看单元</button>
          </template>
        </el-table-column>
      </el-table>
      <div class="table-footer"><span>共 {{ fmtInt(campaignData?.total || 0) }} 条 · 按 7 天消费降序</span></div>
    </div>

    <!-- 单元列表视图 -->
    <div v-if="activeView === 'adgroups'" class="table-panel">
      <div v-if="adgroupCampaignFilter" class="panel-filter-line">
        只看计划「{{ campaignData?.campaigns.find(c => c.campaign_id === adgroupCampaignFilter)?.campaign_name || adgroupCampaignFilter }}」的单元
        <button class="row-action" style="margin-left: 10px" @click="adgroupCampaignFilter = null; switchView('adgroups')">查看全部单元</button>
      </div>
      <el-table ref="adgroupTableRef" v-loading="loading" :data="adgroupData?.adgroups || []" class="kw-table" row-key="adgroup_id">
        <el-table-column label="单元" min-width="180">
          <template #default="{ row }">
            <div class="kw-cell-name">{{ row.adgroup_name }}</div>
            <div class="kw-cell-sub">{{ row.campaign_name || '—' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="单元出价" width="132" align="right">
          <template #default="{ row }">
            <div class="bid-cell">
              <span class="num">{{ fmtMoney(row.max_price) }}</span>
              <button class="mini-action" @click="editAdgroupBid(row)">修改</button>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="移动比例" width="110" align="right">
          <template #default="{ row }"><span class="num">{{ fmtRatio(row.price_ratio) }}</span></template>
        </el-table-column>
        <el-table-column label="否词数" width="84" align="right">
          <template #default="{ row }"><span class="num">{{ fmtInt(row.negative_word_count) }}</span></template>
        </el-table-column>
        <el-table-column label="关键词数" width="94" align="right">
          <template #default="{ row }"><span class="num">{{ fmtInt(row.keyword_count) }}</span></template>
        </el-table-column>
        <el-table-column label="落地页" min-width="280">
          <template #default="{ row }">
            <div v-if="landingRows(row).length" class="url-list">
              <div v-for="item in landingRows(row)" :key="item.key" class="url-line">
                <span class="url-tag" :class="item.key">{{ item.label }}</span>
                <span class="url-cell">{{ item.url }}</span>
              </div>
            </div>
            <div v-else class="url-cell empty">未设置</div>
            <div class="kw-cell-sub">
              <template v-if="row.mobile_final_url && row.pc_final_url && row.mobile_final_url !== row.pc_final_url">移动/PC 分开设置</template>
              <template v-else-if="row.mobile_final_url || row.pc_final_url">单元最终访问网址</template>
              <template v-else>从创意或关键词层级继承</template>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="7天消费" width="100" align="right">
          <template #default="{ row }"><span class="num">{{ fmtMoney(row.metrics_7d?.cost) }}</span></template>
        </el-table-column>
        <el-table-column label="7天点击" width="94" align="right">
          <template #default="{ row }"><span class="num">{{ fmtInt(row.metrics_7d?.click) }}</span></template>
        </el-table-column>
        <el-table-column label="7天展现" width="94" align="right">
          <template #default="{ row }"><span class="num">{{ fmtInt(row.metrics_7d?.impression) }}</span></template>
        </el-table-column>
        <el-table-column label="状态" width="86">
          <template #default="{ row }">
            <span v-if="row.pause === true" class="status-pill off"><span class="status-dot" />已暂停</span>
            <span v-else-if="row.pause === false" class="status-pill on"><span class="status-dot" />已启用</span>
            <span v-else class="dim">—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="88" align="center" fixed="right">
          <template #default="{ row }">
            <div class="row-actions compact">
              <button class="row-action" @click="openLanding(row)">落地页</button>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <div class="table-footer"><span>共 {{ fmtInt(adgroupData?.total || 0) }} 条 · 按 7 天消费降序</span></div>
    </div>

    <el-dialog v-model="landingDialog.visible" title="设置单元落地页" width="640px" class="landing-dialog">
      <div class="dialog-context">
        <div class="kw-cell-name">{{ landingDialog.row?.adgroup_name || '单元' }}</div>
        <div class="kw-cell-sub">{{ landingDialog.row?.campaign_name || '—' }}</div>
      </div>
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="当前为演练模式：保存后只记台账，不会真改百度线上。"
        style="margin-bottom: 14px"
      />
      <el-form label-position="top">
        <div class="form-grid">
          <el-form-item label="PC 最终访问网址">
            <el-input v-model="landingDialog.pcFinalUrl" placeholder="https://..." clearable />
          </el-form-item>
          <el-form-item label="移动最终访问网址">
            <el-input v-model="landingDialog.mobileFinalUrl" placeholder="https://..." clearable />
          </el-form-item>
          <el-form-item label="PC 监控后缀">
            <el-input v-model="landingDialog.pcTrackParam" placeholder="utm_source=baidu" clearable />
          </el-form-item>
          <el-form-item label="移动监控后缀">
            <el-input v-model="landingDialog.mobileTrackParam" placeholder="utm_source=baidu" clearable />
          </el-form-item>
          <el-form-item label="PC 第三方追踪模板">
            <el-input v-model="landingDialog.pcTrackTemplate" placeholder="https://example.com?a={lpurl}" clearable />
          </el-form-item>
          <el-form-item label="移动第三方追踪模板">
            <el-input v-model="landingDialog.mobileTrackTemplate" placeholder="https://example.com?a={lpurl}" clearable />
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="copyPcToMobile">复制 PC 到移动</el-button>
        <el-button @click="landingDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="landingDialog.submitting" @click="saveLanding">保存设置</el-button>
      </template>
    </el-dialog>

    <div
      v-show="stickyScroll.visible"
      ref="stickyScrollRef"
      class="sticky-table-scroll"
      :style="{ left: stickyScroll.panelLeft + 'px', width: stickyScroll.panelWidth + 'px' }"
      @scroll="onStickyScroll"
    >
      <div class="sticky-table-scroll-inner" :style="{ width: stickyScroll.width + 'px' }" />
    </div>
  </div>
</template>

<style scoped>
.page-header { margin-bottom: 14px; }
.page-header-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.page-title { font-size: 20px; font-weight: 600; color: var(--sem-text); }
.page-desc { width: 100%; font-size: 12px; line-height: 1.6; color: var(--sem-text-sub); margin-top: 4px; }
.page-actions {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: nowrap;
  gap: 8px;
  white-space: nowrap;
}
.pbtn {
  flex: 0 0 auto;
  padding: 6px 12px; border-radius: 5px; font-size: 12px; font-weight: 500;
  background: #fff; color: #4b5563; border: 1px solid #d1d5db; cursor: pointer;
}
.pbtn:hover:not([disabled]) { color: var(--sem-primary); border-color: #8db7df; background: #f5f9fd; }
.pbtn[disabled] { opacity: 0.4; cursor: not-allowed; }
.refresh-btn { display: inline-flex; align-items: center; gap: 5px; color: var(--sem-primary); }
.refresh-icon { display: inline-block; font-size: 14px; line-height: 1; }
.refresh-icon.spinning { animation: refresh-spin 0.9s linear infinite; }
@keyframes refresh-spin { to { transform: rotate(360deg); } }

/* 视图 tabs（原型 view-tabs） */
.view-tabs {
  display: inline-flex; gap: 4px; background: #fff; border: 1px solid var(--sem-border);
  border-radius: 8px; padding: 4px; margin-bottom: 14px;
}
.view-tab { padding: 7px 16px; border-radius: 5px; font-size: 12px; cursor: pointer; color: var(--sem-text-sub); font-weight: 500; user-select: none; }
.view-tab:hover { background: #f9fafb; color: var(--sem-primary); }
.view-tab.active { background: #eff4fb; color: var(--sem-primary); }
.view-tab.disabled { color: #c0c4cc; cursor: not-allowed; }
.view-tab.disabled:hover { background: none; color: #c0c4cc; }
.v-count { font-size: 10px; color: #9ca3af; margin-left: 4px; }
.view-tab.active .v-count { color: var(--sem-primary); }
.panel-filter-line {
  padding: 10px 16px; font-size: 12px; color: var(--sem-text-sub);
  background: #f4f8fd; border-bottom: 1px solid var(--sem-border);
  display: flex; align-items: center;
}

/* 分级 chips */
.kw-chips { display: flex; gap: 6px; margin-bottom: 14px; flex-wrap: wrap; }
.kw-chip {
  padding: 6px 12px; border-radius: 16px; font-size: 12px; cursor: pointer;
  background: #fff; border: 1px solid var(--sem-border); color: #4b5563;
  display: inline-flex; align-items: center; gap: 6px; transition: all 0.1s; user-select: none;
}
.kw-chip:hover { border-color: var(--sem-primary); }
.kw-chip.active { color: #fff; }
.k-dot { width: 8px; height: 8px; border-radius: 50%; }
.k-count {
  background: rgba(0, 0, 0, 0.06); color: var(--sem-text-sub);
  padding: 0 6px; border-radius: 8px; font-size: 10px; font-weight: 600;
}
.kw-chip.active .k-count { background: rgba(255, 255, 255, 0.25); color: #fff; }

.filter-row { display: flex; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }

/* 批量操作条（常驻 · 勾选点亮） */
.bulk-toolbar {
  background: #fff; border: 1px solid var(--sem-border);
  border-radius: 8px; padding: 9px 14px; margin-bottom: 12px;
  display: flex; align-items: center; gap: 12px; transition: all 0.2s;
}
.bulk-toolbar.active {
  background: linear-gradient(135deg, #185fa5 0%, #2c7cc8 100%);
  border-color: transparent; color: #fff; box-shadow: 0 4px 12px rgba(24, 95, 165, 0.2);
}
.bt-count { font-size: 12px; color: var(--sem-text-sub); }
.bt-count b { color: var(--sem-primary); margin: 0 2px; font-size: 13px; }
.bt-hint { color: #9ca3af; }
.bulk-toolbar.active .bt-count { color: rgba(255, 255, 255, 0.95); }
.bulk-toolbar.active .bt-count b { color: #fff; font-size: 15px; }
.bt-actions { display: flex; gap: 6px; margin-left: auto; align-items: center; flex-wrap: wrap; }
.bt-btn {
  padding: 5px 11px; border-radius: 5px; font-size: 12px; cursor: pointer; font-weight: 500;
  background: #fafbfc; color: #9ca3af; border: 1px solid var(--sem-border);
}
.bt-btn:hover:not(:disabled) { border-color: var(--sem-primary); color: var(--sem-primary); background: #fff; }
.bt-btn:disabled { cursor: not-allowed; }
.bt-btn.bt-primary { background: var(--sem-primary); color: #fff; border-color: var(--sem-primary); font-weight: 600; }
.bt-btn.bt-primary:disabled { background: #fafbfc; color: #9ca3af; border-color: var(--sem-border); font-weight: 500; }
.bulk-toolbar.active .bt-btn { background: rgba(255, 255, 255, 0.15); border-color: rgba(255, 255, 255, 0.35); color: #fff; }
.bulk-toolbar.active .bt-btn:disabled { opacity: 0.35; }
.bulk-toolbar.active .bt-btn.bt-primary { background: #fff; color: var(--sem-primary); border-color: transparent; }
.bt-clear {
  color: rgba(255, 255, 255, 0.85); font-size: 12px; cursor: pointer;
  padding-left: 12px; border-left: 1px solid rgba(255, 255, 255, 0.3);
}
.bt-clear:hover { color: #fff; }

/* 表格面板（原型 table-panel / kw-table 观感） */
.table-panel { background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; overflow: hidden; }
.kw-table { font-size: 12px; }
.sticky-table-scroll {
  position: fixed;
  bottom: 12px;
  z-index: 30;
  height: 16px;
  overflow-x: auto;
  overflow-y: hidden;
  border-radius: 999px;
  background: rgba(248, 250, 252, 0.92);
  border: 1px solid rgba(215, 226, 239, 0.9);
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.12);
  backdrop-filter: blur(8px);
}
.sticky-table-scroll-inner { height: 1px; }
.sticky-table-scroll::-webkit-scrollbar { height: 12px; }
.sticky-table-scroll::-webkit-scrollbar-track {
  background: #eef3f8;
  border-radius: 999px;
}
.sticky-table-scroll::-webkit-scrollbar-thumb {
  background: #b8c8da;
  border: 3px solid #eef3f8;
  border-radius: 999px;
}
.sticky-table-scroll::-webkit-scrollbar-thumb:hover { background: #8ea8c4; }
.kw-table :deep(th.el-table__cell) {
  background: #fafbfc; font-weight: 500; color: var(--sem-text-sub);
  font-size: 11px; padding: 6px 0; white-space: nowrap;
}
.kw-table :deep(td.el-table__cell) { padding: 7px 0; }
.kw-table :deep(.el-table__row:hover > td.el-table__cell) { background: #fafbfc; }
.kw-cell-name { font-weight: 500; cursor: pointer; color: var(--sem-text); }
.kw-cell-name:hover { color: var(--sem-primary); }
.kw-cell-sub { font-size: 10px; color: #9ca3af; margin-top: 2px; }
.match-type-trigger {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  color: #667085;
  cursor: pointer;
  line-height: 1.4;
}
.match-type-trigger:hover { color: var(--sem-primary); }
.match-type-caret { font-size: 9px; }
.plan-line { font-size: 12px; }
.num { font-variant-numeric: tabular-nums; }
.dim { color: #9ca3af; }
.bid-cell {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  min-width: 100%;
}
.mini-action {
  height: 22px;
  padding: 0 7px;
  border-radius: 4px;
  border: 1px solid #d7e2ef;
  background: #fff;
  color: var(--sem-primary);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}
.mini-action:hover { background: #eff4fb; border-color: #b9cde5; }
.url-list { display: grid; gap: 4px; }
.url-line {
  display: grid;
  grid-template-columns: 54px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
}
.url-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 20px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
}
.url-tag.mobile { background: #e5f4ed; color: #15835b; }
.url-tag.pc { background: #e8f1ff; color: #1d5ca8; }
.url-cell {
  color: #1d4f91;
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.url-cell.empty { color: #9ca3af; }

.kw-pill { font-size: 10px; padding: 1px 7px; border-radius: 10px; font-weight: 600; display: inline-block; white-space: nowrap; }

.coef-actual { font-weight: 700; color: var(--sem-text); font-size: 13px; font-variant-numeric: tabular-nums; }
.coef-actual.warn { color: #ba7517; }
.coef-actual.danger { color: var(--sem-danger); }
.coef-multi { font-size: 10px; color: #9ca3af; margin-top: 1px; font-variant-numeric: tabular-nums; }
.coef-multi.warn { color: #ba7517; }
.coef-multi.danger { color: var(--sem-danger); }

.qs-cell { display: flex; align-items: center; gap: 4px; }
.qs-num { font-weight: 600; font-variant-numeric: tabular-nums; }
.qs-bar { width: 36px; height: 4px; background: #f3f4f6; border-radius: 2px; overflow: hidden; display: inline-block; }
.qs-fill { height: 100%; border-radius: 2px; display: block; }
.qs-fill.bad { background: var(--sem-danger); }
.qs-fill.mid { background: #ba7517; }
.qs-fill.good { background: var(--sem-success); }

.status-pill { font-size: 11px; padding: 2px 8px; border-radius: 10px; display: inline-flex; align-items: center; gap: 4px; white-space: nowrap; }
.status-pill.on { background: #e5f4ed; color: var(--sem-success); }
.status-pill.off { background: #f3f4f6; color: var(--sem-text-sub); }
.status-pill.slot { background: #fcf6ea; color: #ba7517; }
.status-pill.slot .status-dot { background: #ba7517; }
.status-dot { width: 5px; height: 5px; border-radius: 50%; }
.status-pill.on .status-dot { background: var(--sem-success); }
.status-pill.off .status-dot { background: #9ca3af; }

.row-actions { display: flex; gap: 4px; }
.row-actions.compact { justify-content: center; flex-wrap: wrap; }
.row-action {
  font-size: 11px; padding: 3px 9px; border-radius: 4px;
  border: 1px solid var(--sem-border); background: #fff; color: #4b5563; cursor: pointer;
}
.row-action:hover:not(:disabled) { border-color: var(--sem-primary); color: var(--sem-primary); }
.row-action:disabled { opacity: 0.4; cursor: not-allowed; }
.dialog-context { margin: -4px 0 14px; }
.form-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  column-gap: 14px;
}
.landing-dialog :deep(.el-form-item__label) {
  color: #6b7280;
  font-size: 12px;
}

/* 排名 + rank-mini 迷你柱（原型 rank-cell） */
.rank-cell { display: flex; align-items: center; gap: 6px; justify-content: flex-end; }
.rank-val { font-weight: 600; }
.rank-val.warn { color: #ba7517; }
.rank-val.danger { color: var(--sem-danger); }
.rank-mini { display: inline-flex; align-items: flex-end; gap: 1px; height: 14px; }
.rank-mini .rb { width: 3px; background: #c5d7ee; border-radius: 1px; display: inline-block; }
.rank-mini .rb.now { background: var(--sem-primary); }
.rank-mini .rb.bad { background: var(--sem-danger); }
.rank-mini .rb.empty { background: #f3f4f6; }

.media-select { flex: 0 0 auto; display: inline-flex; align-items: center; gap: 6px; }
.media-label { font-size: 12px; color: var(--sem-text-sub); }

@media (max-width: 1024px) {
  .page-header-main {
    align-items: flex-start;
    flex-direction: column;
  }

  .page-actions {
    width: 100%;
    justify-content: flex-start;
    overflow-x: auto;
    padding-bottom: 2px;
    scrollbar-width: thin;
  }
}

.table-footer {
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 16px; background: #fafbfc; border-top: 1px solid #f3f4f6;
  font-size: 12px; color: var(--sem-text-sub);
}
/* AI 建议条（行内，关键词单元格下方） */
.kw-advice { margin-top: 5px; padding: 5px 8px; border-radius: 5px; font-size: 12px; line-height: 1.5; display: flex; align-items: center; gap: 8px; background: #f5f7fa; border-left: 3px solid #c0c4cc; }
.kw-advice.p-0 { background: #fef0f0; border-left-color: #f56c6c; }
.kw-advice.p-1 { background: #fdf6ec; border-left-color: #e6a23c; }
.kw-advice.p-2 { background: #ecf5ff; border-left-color: #409eff; }
.adv-text { flex: 1; color: #5a5e66; }
.adv-text b { color: #185fa5; font-weight: 600; }
.adv-actions { flex: none; display: flex; gap: 4px; }
.adv-btn { border: 1px solid #dcdfe6; background: #fff; border-radius: 4px; padding: 1px 8px; font-size: 12px; cursor: pointer; color: #606266; white-space: nowrap; }
.adv-btn:hover { border-color: #185fa5; color: #185fa5; }
.adv-btn.adopt { background: #185fa5; border-color: #185fa5; color: #fff; }
.adv-btn.adopt:hover { opacity: .9; color: #fff; }
/* AI 建议条幅 */
.ai-banner { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; padding: 10px 14px; background: linear-gradient(90deg, #ecf5ff, #f5f9ff); border: 1px solid #d4e6fb; border-radius: 8px; }
.ai-banner .ab-icon { font-size: 16px; }
.ai-banner .ab-title { font-size: 14px; color: #185fa5; }
.ai-banner .ab-title b { font-size: 16px; }
.ai-banner { cursor: pointer; }
.ai-banner .ab-hint { font-size: 12px; color: #909399; }
.ai-banner .ab-toggle { margin-left: auto; font-size: 12px; color: #185fa5; flex: none; }
/* AI 建议横向卡片列表（顶部，理由有整行宽度，不再挤窄列） */
.advice-list { display: flex; flex-direction: column; gap: 8px; margin-bottom: 14px; max-height: 380px; overflow-y: auto; }
.advice-card { display: flex; align-items: flex-start; gap: 12px; padding: 10px 14px; background: #fff; border: 1px solid #ebeef5; border-left: 3px solid #c0c4cc; border-radius: 8px; }
.advice-card.p-0 { border-left-color: #f56c6c; }
.advice-card.p-1 { border-left-color: #e6a23c; }
.advice-card.p-2 { border-left-color: #409eff; }
.ac-pri { flex: none; min-width: 24px; padding-top: 2px; font-size: 12px; font-weight: 600; color: #185fa5; }
.ac-main { flex: 1; min-width: 0; }
.ac-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 3px; }
.ac-kw { font-size: 14px; color: #1f2937; cursor: pointer; }
.ac-kw:hover { color: #185fa5; }
.ac-act { font-size: 13px; color: #185fa5; font-weight: 600; }
.ac-conf { font-size: 12px; color: #909399; }
.ac-camp { font-size: 12px; color: #c0c4cc; }
.ac-reason { font-size: 13px; color: #5a5e66; line-height: 1.5; }
.ac-actions { flex: none; display: flex; gap: 6px; }
.ai-note { margin-bottom: 12px; padding: 9px 14px; background: #ecf5ff; border: 1px solid #d4e6fb; border-radius: 8px; font-size: 13px; color: #185fa5; }
.ai-note b { font-weight: 600; }
/* 价格调整列 */
.pa-row { display: flex; align-items: center; gap: 6px; font-size: 12px; line-height: 1.8; }
.pa-label { flex: none; width: 60px; color: #909399; white-space: nowrap; }
.pa-val { color: #1f2937; font-weight: 500; }
.pa-val.ai { color: #185fa5; }
.pa-pct { font-size: 11px; }
.pa-pct.up { color: #e6a23c; }
.pa-pct.down { color: #1d9e75; }
.pa-coef { font-size: 11px; }
.pa-coef.warn { color: #e6a23c; }
.pa-coef.danger { color: #f56c6c; }
.pa-input { width: 116px; }
/* 分组指标列（点击指标 / 线索展现 / 投放状态） */
.mg-row { display: flex; align-items: center; gap: 8px; font-size: 12px; line-height: 1.9; }
.mg-label { flex: none; width: 52px; color: #909399; white-space: nowrap; }
.mg-val { color: #1f2937; }
.mg-val.conv-zero { color: var(--sem-danger); font-weight: 600; }
.num.lead-has { color: var(--sem-success); font-weight: 600; }
/* AI 建议列 */
.ai-tags { display: flex; gap: 6px; margin-bottom: 4px; }
.ai-tag { padding: 1px 8px; border-radius: 4px; font-size: 11px; font-weight: 500; }
.ai-tag.act { background: #ecf5ff; color: #185fa5; }
.ai-tag.risk-low { background: #e1f5ee; color: #0f6e56; }
.ai-tag.risk-mid { background: #fdf6ec; color: #854f0b; }
.ai-tag.risk-high { background: #fef0f0; color: #a32d2d; }
.ai-reason-line { font-size: 12px; color: #5a5e66; line-height: 1.55; }
.ai-risk-line { margin-top: 5px; font-size: 11px; line-height: 1.45; color: #ba7517; }
/* 操作列 */
.op-cell { display: flex; flex-wrap: wrap; gap: 5px; }
.op-btn { padding: 2px 9px; border: 1px solid #dcdfe6; background: #fff; border-radius: 4px; font-size: 12px; color: #606266; cursor: pointer; white-space: nowrap; }
.op-btn:hover:not(:disabled) { border-color: #185fa5; color: #185fa5; }
.op-btn.primary { background: #185fa5; border-color: #185fa5; color: #fff; }
.op-btn.primary:hover { opacity: .9; }
.op-btn:disabled { color: #c0c4cc; background: #f5f7fa; cursor: not-allowed; }
/* 关键词列：名字 + 分类标签同行 */
.kw-cell-name { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.kw-name-text { cursor: pointer; }
.mg-label-w { width: 88px; }
</style>
