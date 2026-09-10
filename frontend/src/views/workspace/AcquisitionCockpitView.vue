<script setup>
import { computed, nextTick, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import MetricEvidenceCard from './cockpit/MetricEvidenceCard.vue'
import { fetchModules, fetchTenants } from '../../api/auth'
import { commandCockpit } from '../../api/assistant'
import { session } from '../../store/session'
import { useWorkbenchSession } from '../../composables/useWorkbenchSession'
import { createReadonlyTransport } from '../../../../integrations/workbench/readonly-transport.mjs'
import { createWorkbenchViewState } from '../../../../integrations/workbench/view-state.mjs'
import { createSemAuthorizedClient } from '../../../../integrations/sem-cockpit/authorization-context.mjs'
import { semMetric } from '../../../../integrations/sem-cockpit/display.mjs'
import { resolveSemDetailBatch, semKeywordCard, semScopeCard, semSearchTermCard } from './cockpit/sem-summary.mjs'
import { createSeoAuthorizedClient } from '../../../../integrations/seo-workbench/authorization-context.mjs'
import { readSeoSiteScope } from '../../../../integrations/seo-workbench/site-scope.mjs'
import { seoSummaryCards } from '../../../../integrations/seo-workbench/summary.mjs'
import { createGeoAuthorizedClient } from '../../../../integrations/geo-workbench/authorization-context.mjs'
import { currentSeoSiteId } from '../seo/seoSiteContext'
import { countUnresolvedModules, hasDataReadPermission, isCurrentCockpitScope, isSecureCockpitRuntime, resolveTenantModuleCodes, selectAvailableModules, selectCockpitTenants } from './cockpit/scope.mjs'
import { completedWeekEnd, completedWeekInclusiveEnd, geoSummaryCards } from './cockpit/geo-summary.mjs'
import { geoDemoCards } from './cockpit/demo-summary.mjs'
import { createSeoSiteSelectionGuard, resolveSeoSiteSelection } from './cockpit/site-selection.mjs'
import { geoReadyReply, urgencyReply } from './cockpit/status-copy.mjs'
import { evidenceBoundaryCount, isCurrentCommandContext, normalizeModuleSelection, readCompletionProgress } from './cockpit/experience-state.mjs'
import { buildPanoramaSummary } from './cockpit/panorama-summary.mjs'

const router = useRouter()
const shellEl = ref(null)
const messagesEl = ref(null)
const question = ref('')
const loading = ref(false)
const viewMode = ref('split')
const activeModule = ref('all')
const activeSection = ref('dashboard')
const compactCards = ref(false)
const fullscreen = ref(false)
const aiBusy = ref(false)
const highlightedMetricIds = ref([])
const selectedMetricId = ref(null)
const lastReadAt = ref(null)
const dateEnd = ref(shanghaiDate())
const dateStart = ref(shiftDate(dateEnd.value, -6))
const draftDateEnd = ref(dateEnd.value)
const draftDateStart = ref(dateStart.value)
const cards = ref([])
const initialConversation = () => [
  { role: 'assistant', text: '我会先说明数据是否完整，再帮你判断现在最该处理什么。你可以直接问，也可以从下面的问题开始。' },
]
const conversation = ref(initialConversation())
const moduleState = ref({ sem: 'waiting', seo: 'waiting', geo: 'waiting' })
const tenantModuleCodes = ref(new Set())
const selectableTenants = ref([])
const seoSites = ref([])
const seoSiteSelectionGuard = createSeoSiteSelectionGuard()
const secureRuntime = isSecureCockpitRuntime(window.location)
const viewState = createWorkbenchViewState()
let workbenchSession
let boundary
let semClient
let seoClient
let geoClient
let loadGeneration = 0
let prepareGeneration = 0

const moduleMeta = {
  sem: { label: 'SEM', permission: ['monitor.dashboard', 'optimize.keywords', 'optimize.searchterms'] },
  seo: { label: 'SEO', permission: ['seo.site', 'seo.content'] },
  geo: { label: 'GEO', permission: ['geo.content'] },
}
const availableModules = computed(() => selectAvailableModules(session.modules, tenantModuleCodes.value, moduleMeta))
const customerName = computed(() => session.tenants.find(item => item.id === session.tenantId)?.name
  || session.user?.display_name || '当前客户')
const unresolvedModules = computed(() => countUnresolvedModules(availableModules.value, moduleState.value))
const urgentItems = computed(() => cards.value.reduce((sum, item) => sum + (Number.isSafeInteger(item.urgentCount) ? item.urgentCount : 0), 0))
const readyModules = computed(() => availableModules.value.filter(item => moduleState.value[item.module_code] === 'ready').length)
const filteredCards = computed(() => activeModule.value === 'all'
  ? cards.value
  : cards.value.filter(item => item.moduleCode === activeModule.value))
const selectedMetric = computed(() => cards.value.find(item => item.id === selectedMetricId.value) || null)
const demoMode = computed(() => session.user?.id === 5 && session.user?.tenant_id === 16 && session.user?.username === 'workbench_test_readonly' && Number(session.tenantId) === 16)
const agentName = computed(() => demoMode.value ? 'AI 演示助手' : 'DeepSeek')
const agentTitle = computed(() => demoMode.value ? '交互演示台' : '作战指令台')
const agentStatus = computed(() => aiBusy.value ? '分析中' : (demoMode.value ? '演示模式' : '可下达指令'))
const panoramaSummary = computed(() => buildPanoramaSummary(filteredCards.value))
const cardGroups = computed(() => panoramaSummary.value.groups)
const readProgress = computed(() => {
  return readCompletionProgress({ availableCount: availableModules.value.length, completedCount: readyModules.value })
})
const partialEvidence = computed(() => cards.value.filter(item => ['partial', 'no_data', 'unavailable'].includes(item.state)).length)
const boundaryItems = computed(() => evidenceBoundaryCount({ unresolvedModules: unresolvedModules.value, cards: cards.value }))
const geoWeekEnd = computed(() => completedWeekEnd(dateEnd.value))
const geoWeekInclusiveEnd = computed(() => completedWeekInclusiveEnd(geoWeekEnd.value))
const activePeriodPreset = computed(() => {
  if (dateEnd.value !== shanghaiDate()) return 'custom'
  const days = Math.round((Date.parse(`${dateEnd.value}T00:00:00Z`) - Date.parse(`${dateStart.value}T00:00:00Z`)) / 86400000) + 1
  return ({ 1: 'today', 7: '7d', 30: '30d' })[days] || 'custom'
})
const draftPeriodValid = computed(() => Boolean(
  draftDateStart.value && draftDateEnd.value
  && draftDateStart.value <= draftDateEnd.value
  && draftDateEnd.value <= shanghaiDate()
  && Date.parse(`${draftDateEnd.value}T00:00:00Z`) - Date.parse(`${draftDateStart.value}T00:00:00Z`) <= 365 * 86400000
))
const statusLabel = status => ({ ready: '数据已读取', loading: '读取中', needs_scope: '需要选择业务对象', denied: '当前账号缺少数据查看权限', error: '读取失败', waiting: '等待读取' }[status] || '待确认')
const moduleUrgent = code => cards.value.filter(item => item.moduleCode === code).reduce((sum, item) => sum + (Number.isSafeInteger(item.urgentCount) ? item.urgentCount : 0), 0)
const moduleStatusLabel = code => moduleState.value[code] === 'ready' && moduleUrgent(code) > 0 ? `${moduleUrgent(code)} 项待处理` : statusLabel(moduleState.value[code])
const guideQuestions = computed(() => [
  '今天最需要我关注什么？',
  availableModules.value.some(item => item.module_code === 'sem') ? 'SEM 花费和点击有什么变化？' : null,
  availableModules.value.some(item => item.module_code === 'seo') ? 'SEO 有多少内容和页面需要处理？' : null,
  availableModules.value.some(item => item.module_code === 'geo') ? 'GEO 本周被 AI 提及了多少次？' : null,
  '哪些事情需要我现在处理？',
].filter(Boolean))

function shanghaiDate() {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(new Date())
}
function shiftDate(value, days) {
  const date = new Date(`${value}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + days)
  return date.toISOString().slice(0, 10)
}
function usePeriodPreset(days) {
  const end = shanghaiDate()
  const start = shiftDate(end, -(days - 1))
  const changed = dateStart.value !== start || dateEnd.value !== end
  draftDateEnd.value = end
  draftDateStart.value = start
  dateEnd.value = draftDateEnd.value
  dateStart.value = draftDateStart.value
  if (!changed) loadAll()
}
function applyDatePeriod() {
  if (!draftPeriodValid.value) return
  const changed = dateStart.value !== draftDateStart.value || dateEnd.value !== draftDateEnd.value
  dateStart.value = draftDateStart.value
  dateEnd.value = draftDateEnd.value
  if (!changed) loadAll()
}
function displayTime(value) {
  return value ? new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit' }).format(value) : '尚未读取'
}
const outcomeSummaryMetricIds = new Set([
  'sem-click',
  'seo-contents', 'seo-pages',
  'geo-demo-mention_rate', 'geo-demo-mention_count', 'geo-demo-own_domain_citation_count',
  'geo-geo.visibility.ai_mention_count_7d', 'geo-geo.visibility.ai_mention_rate_7d',
  'geo-geo.visibility.ai_visibility_score',
])
function attentionCopy(card) {
  if (Number(card?.urgentCount) > 0) return `${card.urgentCount} 项已有数据依据，等待推进`
  return card?.reason || '当前证据仍需补齐或重新读取'
}
function clearCards() { cards.value = [] }
function clearModuleCards(module) {
  viewState.invalidateModule(module)
  cards.value = viewState.snapshot().map(item => item.metric)
}
function resetDerivedConversation() { conversation.value = initialConversation() }
function invalidateEvidence({ clearConversation = false } = {}) {
  ++loadGeneration
  boundary?.invalidate()
  semClient?.invalidate()
  seoClient?.invalidate()
  geoClient?.invalidate()
  viewState.invalidate()
  clearCards()
  seoSites.value = []
  moduleState.value = { sem: 'waiting', seo: 'waiting', geo: 'waiting' }
  lastReadAt.value = null
  if (clearConversation) resetDerivedConversation()
}
function metricCard(report, key, label, unit) {
  const shown = semMetric(report.metrics[key], unit, report.coverage)
  const point = row => semMetric(row[key], unit, { status: row.status, missing_dates: [] }).text
  return {
    id: `sem-${key}`, moduleCode: 'sem', moduleLabel: 'SEM', label, display: shown.text, unit: '', state: shown.state === 'coverage_unknown' ? 'partial' : shown.state,
    reason: shown.note, contextRevision: viewState.revision,
    periodLabel: `${report.window.start} 至 ${report.window.end}`,
    sourceLabel: report.is_demo ? '版本化 SEM 内置演示数据' : '百度推广已有关键词报告', updatedLabel: report.coverage.updated_at || '未知',
    series: report.trend.map(row => ({ label: row.date.slice(5), value: row[key], display: point(row) })),
    columns: [{ key: 'date', label: '日期' }, { key: 'value', label }],
    rows: report.trend.map(row => ({ date: row.date, value: point(row) })),
  }
}
function phoneCard(report) {
  return {
    id: 'sem-phone', moduleCode: 'sem', moduleLabel: 'SEM', label: '电话按钮点击', display: '未接入', state: 'unavailable',
    reason: report.unavailable?.phone_button_clicks || '当前汇总接口没有可靠的电话按钮点击依据。电话按钮点击也不等于有效咨询。',
    contextRevision: viewState.revision, periodLabel: `${report.window.start} 至 ${report.window.end}`,
    sourceLabel: '百度推广报告原始字段', updatedLabel: report.coverage.updated_at || '未知', series: [], columns: [], rows: [],
  }
}
function unavailableSemDetailCard(id, label, error) {
  return {
    id, moduleCode: 'sem', moduleLabel: 'SEM', label, display: '读取失败', state: 'unavailable',
    reason: `${error?.message || '明细接口暂时不可用'}。汇总卡仍保留，明细没有用演示值或零值替代。`,
    contextRevision: viewState.revision, periodLabel: `${dateStart.value} 至 ${dateEnd.value}`,
    sourceLabel: 'SEM 只读明细接口', updatedLabel: '本次读取未完成', series: [], columns: [], rows: [],
  }
}
function publishCard(card) {
  const publishedCard = outcomeSummaryMetricIds.has(card.id) ? { ...card, summaryRole: 'outcome' } : card
  const ticket = viewState.begin(publishedCard.moduleCode || 'sem', publishedCard.id)
  if (ticket.publish(publishedCard)) cards.value = viewState.snapshot().map(item => item.metric)
}
async function loadSem(generation) {
  if (!session.tenantId || !availableModules.value.some(item => item.module_code === 'sem')) return
  if (!hasDataReadPermission('sem', key => session.canView(key), moduleMeta)) {
    moduleState.value.sem = 'denied'
    return
  }
  if (!semClient) {
    moduleState.value.sem = 'error'
    return
  }
  moduleState.value.sem = 'loading'
  try {
    const context = await semClient.connect(session.tenantId)
    if (generation !== loadGeneration) return
    if (!context.allowedReads.includes('report')) {
      moduleState.value.sem = 'denied'
      return
    }
    const report = await semClient.read('report', { start_date: dateStart.value, end_date: dateEnd.value })
    if (generation !== loadGeneration) return
    for (const card of [
      semScopeCard(report, viewState.revision),
      metricCard(report, 'cost', '推广花费', 'CNY'), metricCard(report, 'impression', '广告展现', 'count'),
      metricCard(report, 'click', '广告点击', 'count'), metricCard(report, 'ctr', '点击率', 'ratio'), phoneCard(report),
    ]) publishCard(card)
    const settledDetails = await Promise.allSettled([
      context.allowedReads.includes('keywords')
        ? semClient.read('keywords', { start_date: dateStart.value, end_date: dateEnd.value, page: 1, page_size: 20 })
        : Promise.resolve(null),
      context.allowedReads.includes('searchTerms')
        ? semClient.read('searchTerms', { page: 1, page_size: 50 })
        : Promise.resolve(null),
    ])
    if (generation !== loadGeneration) return
    const details = resolveSemDetailBatch(settledDetails)
    if (details[0].value) publishCard(semKeywordCard(details[0].value, viewState.revision))
    else if (context.allowedReads.includes('keywords')) publishCard(unavailableSemDetailCard('sem-keywords', '关键词资产', details[0].error))
    if (details[1].value) publishCard(semSearchTermCard(details[1].value, viewState.revision))
    else if (context.allowedReads.includes('searchTerms')) publishCard(unavailableSemDetailCard('sem-search-terms', '实际搜索词', details[1].error))
    moduleState.value.sem = 'ready'
    lastReadAt.value = new Date()
  } catch (error) {
    if (generation !== loadGeneration || ['STALE_SESSION', 'STALE_AUTHORIZATION', 'STALE_RESPONSE'].includes(error?.code)) return
    moduleState.value.sem = ['NOT_AUTHORIZED', 'ACCESS_REVOKED'].includes(error?.code) ? 'denied' : 'error'
    conversation.value.push({ role: 'assistant', text: `SEM 数据暂未读取：${error?.message || '请稍后重试'}。我没有用零值或演示数据替代。` })
  }
}
async function loadSeo(generation) {
  if (!session.tenantId || !availableModules.value.some(item => item.module_code === 'seo')) return
  if (!hasDataReadPermission('seo', key => session.canView(key), moduleMeta)) {
    moduleState.value.seo = 'denied'
    return
  }
  const tenantId = session.tenantId
  const siteId = currentSeoSiteId.value
  const authRevision = session.authRevision
  const isCurrent = () => generation === loadGeneration && tenantId === session.tenantId
    && siteId === currentSeoSiteId.value && authRevision === session.authRevision
  if (!seoClient || !boundary) {
    moduleState.value.seo = 'error'
    return
  }
  moduleState.value.seo = 'loading'
  try {
    const scope = await readSeoSiteScope({ transport: boundary.transport, tenantId })
    if (!isCurrent()) return
    seoSites.value = [...scope.sites]
    const selection = resolveSeoSiteSelection({
      sites: scope.sites,
      currentSiteId: siteId,
      allowAutomaticSelection: seoSiteSelectionGuard.allowsAutomaticSelection(tenantId),
    })
    if (selection.reason === 'selected') seoSiteSelectionGuard.confirmExplicitSelection(tenantId)
    if (selection.reason === 'selection_unavailable') seoSiteSelectionGuard.blockAutomaticSelection(tenantId)
    if (selection.siteId !== siteId) {
      currentSeoSiteId.value = selection.siteId
      moduleState.value.seo = 'needs_scope'
      return
    }
    if (!selection.siteId) {
      moduleState.value.seo = 'needs_scope'
      return
    }
    const context = await seoClient.connect({ tenantId, siteId })
    if (!isCurrent()) return
    const [contents, pages] = await Promise.all([
      context.allowedReads.includes('contents') ? seoClient.read('contents', { page: 1, pageSize: 50 }) : Promise.resolve(null),
      context.allowedReads.includes('pages') ? seoClient.read('pages', { page: 1, pageSize: 50 }) : Promise.resolve(null),
    ])
    if (!isCurrent()) return
    for (const card of seoSummaryCards({ contents, pages, contextRevision: viewState.revision })) publishCard(card)
    moduleState.value.seo = 'ready'
    lastReadAt.value = new Date()
  } catch (error) {
    if (!isCurrent() || ['STALE_SESSION', 'STALE_AUTHORIZATION', 'STALE_RESPONSE'].includes(error?.code)) return
    moduleState.value.seo = ['NOT_AUTHORIZED', 'ACCESS_REVOKED', 'SITE_SCOPE_NOT_ALLOWED'].includes(error?.code) ? 'denied' : 'error'
    conversation.value.push({ role: 'assistant', text: `SEO 数据暂未读取：${error?.message || '请稍后重试'}。我没有改用演示数据或推算文章点击。` })
  }
}
async function loadGeo(generation) {
  if (!session.tenantId || !geoWeekEnd.value || !availableModules.value.some(item => item.module_code === 'geo')) return
  if (!hasDataReadPermission('geo', key => session.canView(key), moduleMeta)) {
    moduleState.value.geo = 'denied'
    return
  }
  if (!geoClient) { moduleState.value.geo = 'error'; return }
  const tenantId = session.tenantId
  const weekEnd = geoWeekEnd.value
  const authRevision = session.authRevision
  const isCurrent = () => generation === loadGeneration && tenantId === session.tenantId
    && weekEnd === geoWeekEnd.value && authRevision === session.authRevision
  moduleState.value.geo = 'loading'
  try {
    await geoClient.connect({ tenantId, weekEnd })
    if (!isCurrent()) return
    if (demoMode.value) {
      const read = async resource => {
        const response = await boundary.transport(`/api/v1/geo/integration/read/${resource}?tenant_id=${tenantId}`, { method: 'GET' })
        if (!response.ok) throw new Error('GEO 演示数据读取失败')
        return response.json()
      }
      const [summary, capabilities] = await Promise.all([read('demo-summary'), read('capabilities')])
      if (!isCurrent()) return
      for (const card of geoDemoCards({ summary, capabilities, contextRevision: viewState.revision })) publishCard(card)
      moduleState.value.geo = 'ready'
      lastReadAt.value = new Date()
      return
    }
    await Promise.all([
      geoClient.read('periodContext'), geoClient.read('metrics'), geoClient.read('dictionary'),
    ])
    if (!isCurrent()) return
    const snapshot = geoClient.officialSnapshot()
    for (const card of geoSummaryCards({ snapshot, contextRevision: viewState.revision })) publishCard(card)
    moduleState.value.geo = 'ready'
    lastReadAt.value = new Date()
  } catch (error) {
    if (!isCurrent() || ['STALE_SESSION', 'STALE_AUTHORIZATION', 'STALE_RESPONSE'].includes(error?.code)) return
    moduleState.value.geo = ['NOT_AUTHORIZED', 'NO_GEO_READS', 'TENANT_NOT_ALLOWED', 'GEO_SCOPE_NOT_ALLOWED', 'ACCESS_REVOKED'].includes(error?.code) ? 'denied' : 'error'
    conversation.value.push({ role: 'assistant', text: `GEO 数据暂未读取：${error?.message || '请稍后重试'}。我没有把模拟回答、人工记录或样本不足改成正式数字。` })
  }
}
async function loadAll() {
  invalidateEvidence({ clearConversation: true })
  const generation = loadGeneration
  loading.value = true
  for (const item of availableModules.value) moduleState.value[item.module_code] = ['sem', 'seo', 'geo'].includes(item.module_code) ? 'loading' : 'needs_scope'
  await Promise.allSettled([loadSem(generation), loadSeo(generation), loadGeo(generation)])
  if (generation === loadGeneration) loading.value = false
}
async function prepare() {
  const generation = ++prepareGeneration
  const requestedTenantId = session.tenantId
  const requestedAuthRevision = session.authRevision
  const ticket = { generation, tenantId: requestedTenantId, authRevision: requestedAuthRevision }
  const isCurrent = () => isCurrentCockpitScope(ticket, {
    generation: prepareGeneration,
    tenantId: session.tenantId,
    authRevision: session.authRevision,
  })
  invalidateEvidence({ clearConversation: true })
  tenantModuleCodes.value = new Set()
  loading.value = secureRuntime
  if (!secureRuntime) {
    loading.value = false
    tenantModuleCodes.value = new Set()
    resetDerivedConversation()
    conversation.value.push({ role: 'assistant', text: '本地预览不会读取登录身份或真实业务数据。请在正式 HTTPS 环境查看当前客户数据。' })
    return
  }
  try {
    const [modules, tenants] = await Promise.all([fetchModules(), fetchTenants()])
    if (!isCurrent()) return
    session.setModules(modules.modules)
    session.setTenants(tenants.tenants)
    const eligible = modules.modules.filter(item => item.available && moduleMeta[item.module_code])
    const scoped = await Promise.all(eligible.map(async item => ({
      code: item.module_code,
      tenants: (await fetchTenants(item.module_code)).tenants,
    })))
    if (!isCurrent()) return
    const tenantsByModule = Object.fromEntries(scoped.map(item => [item.code, item.tenants]))
    selectableTenants.value = selectCockpitTenants({
      tenants: tenants.tenants,
      tenantsByModule,
      moduleCodes: eligible.map(item => item.module_code),
    })
    if (!selectableTenants.value.some(item => Number(item.id) === Number(session.tenantId))) {
      session.setTenant(selectableTenants.value[0]?.id ?? null)
      return
    }
    tenantModuleCodes.value = resolveTenantModuleCodes({
      modules: modules.modules,
      tenantsByModule,
      tenantId: session.tenantId,
      moduleMeta,
    })
    await loadAll()
  } catch (error) {
    if (!isCurrent()) return
    loading.value = false
    conversation.value.push({ role: 'assistant', text: `工作台身份信息读取失败：${error.message}` })
  }
}
function answerFor(text) {
  if (!availableModules.value.length) return '当前账号没有可查看的获客模块，请联系管理员确认模块和查看权限。'
  if (text.includes('SEM') && moduleState.value.sem === 'ready') return `已按 ${dateStart.value} 至 ${dateEnd.value} 读取 SEM 数据。点击任意数字可以看每日明细和数据依据。`
  if (text.includes('SEO') && moduleState.value.seo === 'ready') return '已读取当前 SEO 网站的内容和页面检查数字。审核、发布、页面检查分别判断，单篇搜索点击仍明确标为未接入。'
  if (text.includes('GEO') && moduleState.value.geo === 'ready') return geoReadyReply(geoWeekInclusiveEnd.value)
  const urgency = urgencyReply({ unresolvedModules: unresolvedModules.value, businessUrgentItems: urgentItems.value })
  if (urgency) return `${urgency} 我不会把缺失数据当成零。`
  return '当前没有系统已识别的紧急事项。你仍可以点击具体指标核对范围和来源，再选择“带着这项数据继续提问”。'
}
function localScreenCommand(text) {
  const upper = text.toUpperCase()
  const modules = ['sem', 'seo', 'geo'].filter(code => upper.includes(code.toUpperCase()))
  const focus = modules.length === 1 ? modules[0] : 'all'
  const candidates = cards.value.filter(card => !modules.length || modules.includes(card.moduleCode))
  const urgent = /紧急|风险|异常|优先|处理/.test(text)
  const highlighted = (urgent ? candidates.filter(card => Number(card.urgentCount) > 0) : candidates).slice(0, 6)
  return {
    answer: answerFor(text), focus_module: focus,
    highlight: { ids: highlighted.map(card => card.id) },
    drawer_metric_id: highlighted[0]?.id || null, actions: [],
  }
}
function applyScreenCommand(command) {
  const allowedModules = new Set(['all', ...availableModules.value.map(item => item.module_code)])
  const allowedIds = new Set(cards.value.map(item => item.id))
  activeSection.value = 'dashboard'
  activeModule.value = allowedModules.has(command?.focus_module) ? command.focus_module : 'all'
  highlightedMetricIds.value = (command?.highlight?.ids || []).filter(id => allowedIds.has(id)).slice(0, 12)
  selectedMetricId.value = allowedIds.has(command?.drawer_metric_id) ? command.drawer_metric_id : null
}
function focusMetric(metricId) {
  if (!cards.value.some(item => item.id === metricId)) return
  selectedMetricId.value = metricId
  highlightedMetricIds.value = [metricId]
  const card = cards.value.find(item => item.id === metricId)
  if (card?.moduleCode) activeModule.value = card.moduleCode
}
function scrollToSection(id) {
  document.getElementById(`cockpit-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
function runScreenAction(action) {
  if (!action || !['focus-module', 'open-metric', 'open-module', 'reset-view'].includes(action.type)) return
  if (action.type === 'open-metric') return focusMetric(action.target)
  if (action.type === 'open-module' && availableModules.value.some(item => item.module_code === action.target)) return openModule(action.target)
  if (action.type === 'focus-module' && availableModules.value.some(item => item.module_code === action.target)) {
    activeSection.value = 'dashboard'; activeModule.value = action.target; return
  }
  if (action.type === 'reset-view') {
    activeSection.value = 'dashboard'; activeModule.value = 'all'; selectedMetricId.value = null; highlightedMetricIds.value = []
  }
}
async function send(text = question.value) {
  const value = String(text || '').trim()
  if (!value || aiBusy.value) return
  conversation.value.push({ role: 'user', text: value })
  question.value = ''
  aiBusy.value = true
  const requestContext = {
    tenantId: session.tenantId,
    loadGeneration,
    contextRevision: viewState.revision,
  }
  let command
  try {
    command = await commandCockpit({
      tenantId: session.tenantId,
      message: value,
      availableModules: availableModules.value.map(item => item.module_code),
      visibleCards: cards.value.map(card => ({
        id: card.id, module: card.moduleCode, label: card.label, value: card.display,
        state: card.state, period: card.periodLabel, source: card.sourceLabel,
      })),
    })
  } catch {
    command = localScreenCommand(value)
    command.answer = `DeepSeek 暂时不可用，已按当前数据完成本地定位。${command.answer}`
  } finally {
    aiBusy.value = false
  }
  if (!isCurrentCommandContext(requestContext, {
    tenantId: session.tenantId,
    loadGeneration,
    contextRevision: viewState.revision,
  })) return
  applyScreenCommand(command)
  conversation.value.push({ role: 'assistant', text: command.answer || answerFor(value), screenCommand: command })
  await nextTick()
  messagesEl.value?.scrollTo({ top: messagesEl.value.scrollHeight, behavior: 'smooth' })
}
function discuss({ metricId, contextRevision }) {
  const card = cards.value.find(item => item.id === metricId)
  if (!card) return
  const ref = viewState.reference(card.moduleCode || 'sem', metricId, contextRevision)
  if (!ref || !viewState.resolve(ref)) return
  conversation.value.push({ role: 'assistant', text: `已带入“${card.label}”（${card.display}）及其统计范围和来源。你想判断原因、风险，还是下一步动作？`, ref })
}
function openModule(code) {
  const path = code === 'sem' ? '/monitor/dashboard' : code === 'seo' ? '/seo/site' : '/deal-sniper/geo/dashboard.html#/geo/projects'
  if (code === 'geo') window.location.assign(path)
  else router.push(path)
}
function selectSeoSite(event) {
  const value = Number(event.target.value)
  seoSiteSelectionGuard.confirmExplicitSelection(session.tenantId)
  currentSeoSiteId.value = Number.isSafeInteger(value) && value > 0 ? value : null
}
function selectTenant(event) {
  const value = Number(event.target.value)
  if (!Number.isSafeInteger(value) || value <= 0 || value === Number(session.tenantId)) return
  currentSeoSiteId.value = null
  invalidateEvidence({ clearConversation: true })
  session.setTenant(value)
}
function setViewMode(mode) {
  viewMode.value = mode
  if (mode === 'chat') nextTick(() => messagesEl.value?.scrollTo({ top: messagesEl.value.scrollHeight }))
}
async function toggleFullscreen() {
  try {
    if (!document.fullscreenElement) {
      if (typeof shellEl.value?.requestFullscreen === 'function') await shellEl.value.requestFullscreen()
      else fullscreen.value = !fullscreen.value
    } else if (typeof document.exitFullscreen === 'function') await document.exitFullscreen()
    else fullscreen.value = false
  } catch {
    fullscreen.value = !fullscreen.value
  }
}
function syncFullscreen() { fullscreen.value = document.fullscreenElement === shellEl.value }
function onKeydown(event) {
  if (['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target?.tagName)) {
    if (event.key === 'Escape') event.target.blur()
    return
  }
  if (event.key === 'f' || event.key === 'F') toggleFullscreen()
  if (event.key === '1') activeModule.value = availableModules.value.some(item => item.module_code === 'sem') ? 'sem' : activeModule.value
  if (event.key === '2') activeModule.value = availableModules.value.some(item => item.module_code === 'seo') ? 'seo' : activeModule.value
  if (event.key === '3') activeModule.value = availableModules.value.some(item => item.module_code === 'geo') ? 'geo' : activeModule.value
  if (event.key === '/') {
    event.preventDefault()
    setViewMode('split')
    nextTick(() => document.querySelector('.composer textarea')?.focus())
  }
  if (event.key === 'Escape') { selectedMetricId.value = null; highlightedMetricIds.value = [] }
}

try {
  if (secureRuntime) {
    boundary = createReadonlyTransport({ origin: window.location.origin, fetchImpl: window.fetch.bind(window), getSession: () => workbenchSession?.getTransportSession() })
    semClient = createSemAuthorizedClient({ transport: boundary.transport, onClear: () => clearModuleCards('sem') })
    seoClient = createSeoAuthorizedClient({ transport: boundary.transport, onClear: () => clearModuleCards('seo') })
    geoClient = createGeoAuthorizedClient({ transport: boundary.transport, onClear: () => clearModuleCards('geo') })
    workbenchSession = useWorkbenchSession({ session, invalidatables: [boundary, semClient, seoClient, geoClient, viewState] })
  }
} catch {
  // Local HTTP preview deliberately cannot create the authenticated production transport.
  moduleState.value.sem = 'error'
}
watch(() => [session.tenantId, currentSeoSiteId.value, dateStart.value, dateEnd.value], () => { if (session.modules.length) prepare() })
watch(() => session.authRevision, prepare)
watch(() => availableModules.value.map(item => item.module_code).join(','), (codes) => {
  activeModule.value = normalizeModuleSelection(activeModule.value, codes ? codes.split(',') : [])
})
onMounted(() => {
  document.addEventListener('fullscreenchange', syncFullscreen)
  document.addEventListener('keydown', onKeydown)
  prepare()
})
onBeforeUnmount(() => {
  document.removeEventListener('fullscreenchange', syncFullscreen)
  document.removeEventListener('keydown', onKeydown)
  ++loadGeneration; ++prepareGeneration; workbenchSession?.dispose(); viewState.dispose()
})
</script>

<template>
  <main ref="shellEl" class="cockpit-shell" :class="[`mode-${viewMode}`, { 'is-fullscreen': fullscreen }]" v-loading="loading">
    <div class="ambient ambient-a"></div><div class="ambient ambient-b"></div>
    <header class="command-bar">
      <div class="brand-block">
        <button class="back-link" type="button" @click="router.push('/workspace')">← 功能模块</button>
        <div class="brand-line"><i class="brand-mark">S</i><div><p>G-SNIPERS · ACQUISITION COMMAND</p><h1>G-Snipers 获客工作台</h1></div></div>
      </div>
      <div class="live-badge" :class="{ replay: demoMode }"><i></i><span>{{ demoMode ? '演示数据' : '数据状态' }}</span><b>{{ displayTime(lastReadAt) }}</b></div>
      <div class="command-controls">
        <label v-if="selectableTenants.length > 1">客户
          <select :value="session.tenantId || ''" aria-label="选择客户" @change="selectTenant">
            <option v-for="tenant in selectableTenants" :key="tenant.id" :value="tenant.id">{{ tenant.name }}</option>
          </select>
        </label>
        <label v-if="availableModules.some(item => item.module_code === 'seo')">SEO 网站
          <select :value="currentSeoSiteId || ''" aria-label="选择 SEO 网站" @change="selectSeoSite">
            <option value="">{{ seoSites.some(site => site.status === 'active') ? '请选择网站' : '暂无可用网站' }}</option>
            <option v-for="site in seoSites" :key="site.id" :value="site.id" :disabled="site.status !== 'active'">{{ site.name }} · {{ site.domain }}{{ site.status === 'active' ? '' : '（已停用）' }}</option>
          </select>
        </label>
        <div class="period-control" aria-label="选择数据周期">
          <span>数据周期</span>
          <div class="period-shortcuts">
            <button :class="{ active: activePeriodPreset === 'today' }" type="button" @click="usePeriodPreset(1)">今天</button>
            <button :class="{ active: activePeriodPreset === '7d' }" type="button" @click="usePeriodPreset(7)">近 7 天</button>
            <button :class="{ active: activePeriodPreset === '30d' }" type="button" @click="usePeriodPreset(30)">近 30 天</button>
          </div>
          <div class="date-range">
            <input v-model="draftDateStart" type="date" :max="draftDateEnd || shanghaiDate()" aria-label="开始日期">
            <span>—</span>
            <input v-model="draftDateEnd" type="date" :min="draftDateStart" :max="shanghaiDate()" aria-label="结束日期">
            <button class="apply-period" type="button" :disabled="!draftPeriodValid" :title="draftPeriodValid ? '应用自定义周期' : '请选择不超过 366 天且不晚于今天的日期'" @click="applyDatePeriod">应用</button>
          </div>
        </div>
        <button class="refresh-button" type="button" @click="loadAll"><span>↻</span> 刷新战况</button>
      </div>
    </header>

    <nav class="workspace-toolbar" aria-label="获客工作台导航">
      <div class="page-tabs">
        <button :class="{ active: activeSection === 'dashboard' }" type="button" @click="activeSection = 'dashboard'">经营全景</button>
        <button :class="{ active: activeSection === 'actions' }" type="button" @click="activeSection = 'actions'">行动台账 <b v-if="urgentItems">{{ urgentItems }}</b></button>
        <button :class="{ active: activeSection === 'quality' }" type="button" @click="activeSection = 'quality'">数据边界 <i v-if="boundaryItems"></i></button>
      </div>
      <div class="view-tools" aria-label="布局控制">
        <span class="key-help">F 全屏 · 1/2/3 战线 · / 问数</span>
        <span>视图</span>
        <button :class="{ active: viewMode === 'chat' }" type="button" title="对话为主" @click="setViewMode('chat')">▤</button>
        <button :class="{ active: viewMode === 'split' }" type="button" title="协同视图" @click="setViewMode('split')">◫</button>
        <button :class="{ active: viewMode === 'data' }" type="button" title="数据为主" @click="setViewMode('data')">▥</button>
        <button type="button" title="全屏" @click="toggleFullscreen">{{ fullscreen ? '↙' : '⛶' }}</button>
      </div>
    </nav>

    <section class="operations-grid">
      <aside v-if="viewMode !== 'data'" class="agent-panel">
        <div class="agent-head"><div class="agent-orb"><i></i></div><div><span>{{ agentName }} · 获客数据引导</span><strong>{{ agentTitle }}</strong></div><em><i></i> {{ agentStatus }}</em></div>
        <div class="context-ribbon"><span>当前关注</span><b>{{ urgentItems ? `${urgentItems} 项待处理事项` : '本周期整体获客表现' }}</b></div>
        <div ref="messagesEl" class="messages" aria-live="polite">
          <div v-for="(item, index) in conversation" :key="index" :class="['message', item.role]">
            <small>{{ item.role === 'assistant' ? agentName : '我' }}</small><p>{{ item.text }}</p><span v-if="item.screenCommand" class="screen-applied">已同步调整大屏</span>
            <div v-if="item.screenCommand?.actions?.length" class="message-actions"><button v-for="action in item.screenCommand.actions" :key="`${action.type}-${action.target}`" type="button" @click="runScreenAction(action)">{{ action.label }}</button></div>
          </div>
        </div>
        <div class="guides"><button v-for="item in guideQuestions.slice(0, 4)" :key="item" type="button" @click="send(item)">{{ item }}</button></div>
        <form class="composer" @submit.prevent="send()"><textarea v-model="question" rows="3" placeholder="问数据、锁定风险，或直接说“只看 GEO”…"></textarea><button type="submit" :disabled="aiBusy" aria-label="发送指令">{{ aiBusy ? '…' : '↑' }}</button></form>
        <p class="agent-note"><i></i> {{ demoMode ? '当前是演示模式；回答和屏幕联动仅用于产品体验。' : '回答仅使用当前已核验数据；执行前会单独确认范围。' }}</p>
      </aside>

      <div v-if="viewMode !== 'chat'" class="data-stage">
        <div class="mission-heading">
          <div><p>ACQUISITION OVERVIEW</p><h2>{{ activeSection === 'dashboard' ? '获客数据全景' : activeSection === 'actions' ? '行动指挥台' : '数据可信边界' }}</h2><span>{{ customerName }} · {{ dateStart }} 至 {{ dateEnd }} · 缺失数据不会补成 0</span></div>
          <div class="stage-actions"><button type="button" @click="compactCards = !compactCards">{{ compactCards ? '展开卡片' : '收拢卡片' }}</button><button type="button" @click="setViewMode('data')">专注大盘 ↗</button></div>
        </div>

        <div v-if="activeSection === 'dashboard'" class="module-tabs" role="tablist" aria-label="指标模块筛选">
          <button :class="{ active: activeModule === 'all' }" type="button" role="tab" :aria-selected="activeModule === 'all'" @click="activeModule = 'all'"><span>全域</span><b>{{ cards.length }}</b><small>全部数据</small></button>
          <button v-for="item in availableModules" :key="item.module_code" :class="[{ active: activeModule === item.module_code }, `module-${item.module_code}`]" type="button" role="tab" :aria-selected="activeModule === item.module_code" @click="activeModule = item.module_code">
            <span>{{ moduleMeta[item.module_code].label }}</span><b>{{ cards.filter(card => card.moduleCode === item.module_code).length }}</b><small>{{ moduleStatusLabel(item.module_code) }}</small>
          </button>
        </div>

        <template v-if="activeSection === 'dashboard'">
          <div v-if="filteredCards.length" class="panorama-content" role="tabpanel" :aria-label="activeModule === 'all' ? '全域指标' : `${activeModule.toUpperCase()} 指标`">
            <section class="decision-summary" aria-label="经营摘要">
              <article class="outcome-summary">
                <header><div><small>当前范围</small><h3>正在积累的成果</h3></div><span>{{ panoramaSummary.outcomes.length }} 项可核对</span></header>
                <div v-if="panoramaSummary.outcomes.length" class="summary-items">
                  <button v-for="card in panoramaSummary.outcomes" :key="`outcome-${card.id}`" type="button" @click="focusMetric(card.id)"><small>{{ card.moduleLabel }}</small><strong>{{ card.display ?? '—' }}</strong><span>{{ card.label }}</span><em>展开依据 ↗</em></button>
                </div>
                <p v-else>当前筛选范围尚无完整可核对的成果数据。</p>
                <footer>各项指标分别衡量，业务效果仍以对应来源和周期为准。</footer>
              </article>
              <article class="attention-summary">
                <header><div><small>尚未确认不代表有问题</small><h3>需要推进的事</h3></div><span>{{ panoramaSummary.attention.length }} 项</span></header>
                <div v-if="panoramaSummary.attention.length" class="attention-items">
                  <button v-for="card in panoramaSummary.attention" :key="`attention-${card.id}`" type="button" @click="focusMetric(card.id)"><b>{{ Number(card.urgentCount) > 0 ? card.urgentCount : '—' }}</b><span><strong>{{ card.label }}</strong><small>{{ attentionCopy(card) }}</small></span><em>核对 ↗</em></button>
                </div>
                <p v-else>当前没有系统已识别的待推进事项。</p>
                <footer>只展示当前卡片状态，不补造任务、日期或结果。</footer>
              </article>
            </section>
            <nav class="section-jumps" aria-label="经营全景分区"><button v-for="group in cardGroups" :key="`jump-${group.id}`" type="button" @click="scrollToSection(group.id)">{{ group.title }} <small>{{ group.cards.length }}</small></button></nav>
            <section v-for="group in cardGroups" :id="`cockpit-${group.id}`" :key="group.id" class="dashboard-section">
              <header class="dashboard-group"><div><small>0{{ cardGroups.indexOf(group) + 1 }}</small><h3>{{ group.title }}</h3><p>{{ group.note }}</p></div><span v-if="demoMode">演示数据 · 不计入正式统计</span></header>
              <div v-if="group.cards.length" class="metric-grid" :class="{ compact: compactCards }">
                <MetricEvidenceCard v-for="card in group.cards" :key="card.id" :metric="card" :context-revision="viewState.revision" :highlighted="highlightedMetricIds.includes(card.id)" @focus="focusMetric" @discuss="discuss" @retry="loadAll" />
              </div>
              <p v-else class="section-empty">当前筛选范围没有此类指标。</p>
            </section>
          </div>
          <div v-else class="data-empty"><i></i><strong>当前范围尚无可展示数字</strong><span>系统正在核对模块、权限与业务对象，不会显示演示值。</span></div>
        </template>

        <div v-else-if="activeSection === 'actions'" class="ledger">
          <article v-for="item in availableModules" :key="`action-${item.module_code}`" :class="{ urgent: moduleUrgent(item.module_code) }">
            <div class="action-rank">{{ moduleUrgent(item.module_code) ? '优先' : '跟进' }}</div><i :class="moduleState[item.module_code]"></i>
            <div class="action-copy"><small>{{ moduleMeta[item.module_code].label }} · {{ statusLabel(moduleState[item.module_code]) }}</small><b>{{ moduleState[item.module_code] === 'ready' ? (moduleUrgent(item.module_code) ? `${moduleUrgent(item.module_code)} 项已有数据依据，需要处理` : '本周期数据已读取，继续观察表现') : moduleState[item.module_code] === 'denied' ? '当前账号缺少数据查看权限' : '读取范围或数据状态需要补齐' }}</b><span>{{ moduleUrgent(item.module_code) ? '先查看依据，再进入模块处理。' : '进入模块查看详细记录与下一步。' }}</span></div>
            <button type="button" @click="openModule(item.module_code)">进入处理 ↗</button>
          </article>
          <div v-if="!availableModules.length" class="data-empty"><strong>当前没有可查看的获客模块</strong><span>请联系管理员确认客户开通状态和账号权限。</span></div>
        </div>

        <div v-else class="quality-grid">
          <article><span>模块读取进度</span><strong>{{ readProgress }}%</strong><p>{{ readyModules }} 个模块读取完成，{{ unresolvedModules }} 个模块仍需确认；读取完成不代表数据完整。</p></article>
          <article><span>来源可核对</span><strong>{{ cards.length - partialEvidence }}</strong><p>点击任意指标查看统计范围、数据来源、更新时间和逐期明细。</p></article>
          <article :class="{ caution: boundaryItems }"><span>边界待说明</span><strong>{{ boundaryItems }}</strong><p>未完成读取、部分、缺失和暂不可用数据保持原样，不推算成客户事实。</p></article>
          <article class="principle"><span>判断原则</span><h3>先发现，再解释</h3><p>系统先展示可核对的业务数据；分析和行动建议在对话中单独给出。</p></article>
        </div>
      </div>
    </section>
    <aside v-if="selectedMetric" class="command-drawer" aria-live="polite">
      <header><div><small>{{ selectedMetric.moduleLabel }} · TARGET LOCK</small><h2>{{ selectedMetric.label }}</h2></div><button type="button" aria-label="关闭详情" @click="selectedMetricId = null">×</button></header>
      <div class="drawer-value">{{ selectedMetric.display }}</div>
      <p>{{ selectedMetric.reason || `当前指标已锁定，可以继续向${agentName}追问原因和下一步。` }}</p>
      <dl><div><dt>统计范围</dt><dd>{{ selectedMetric.periodLabel }}</dd></div><div><dt>数据来源</dt><dd>{{ selectedMetric.sourceLabel }}</dd></div><div><dt>更新时间</dt><dd>{{ selectedMetric.updatedLabel }}</dd></div></dl>
      <div class="drawer-actions"><button type="button" @click="discuss({ metricId: selectedMetric.id, contextRevision: viewState.revision }); setViewMode('split')">就这项问{{ agentName }}</button><button type="button" @click="openModule(selectedMetric.moduleCode)">进入模块 ↗</button></div>
    </aside>
    <button v-if="viewMode === 'data'" class="agent-fab" type="button" @click="setViewMode('split')"><i></i><span>打开智能体</span></button>
  </main>
</template>

<style scoped>
.dashboard-group{grid-column:1/-1;display:flex;align-items:center;justify-content:space-between;margin:8px 0 0;padding:12px 0;border-bottom:1px solid #294154;font-size:15px}.dashboard-group small{color:#86a0b5;font-size:11px;font-weight:400}.event-feed{min-height:0!important}.event-list{grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}

*{box-sizing:border-box}.cockpit-shell{--cyan:#59e8d3;--blue:#5798ff;--violet:#9f72ff;--orange:#ff9f5a;position:relative;isolation:isolate;min-height:100vh;padding:18px 22px 28px;overflow:hidden;background-color:#070b16;background-image:radial-gradient(#87a5c015 1px,transparent 1px);background-size:22px 22px;color:#edf6ff;font-variant-numeric:tabular-nums}.ambient{position:fixed;z-index:-2;pointer-events:none;border-radius:50%;filter:blur(36px);opacity:.16}.ambient-a{width:700px;height:700px;right:-220px;top:-360px;background:radial-gradient(circle,#285bd8 0,transparent 68%)}.ambient-b{width:620px;height:620px;left:-360px;bottom:-360px;background:radial-gradient(circle,#006b73 0,transparent 70%)}button,input,select,textarea{font:inherit}.command-bar{display:grid;grid-template-columns:minmax(250px,1fr) auto minmax(680px,1.7fr);align-items:end;gap:18px;position:relative}.brand-block{min-width:0}.back-link{padding:0 0 9px;border:0;background:none;color:#7690a9;font-size:11px;cursor:pointer}.brand-line{display:flex;align-items:center;gap:12px}.brand-mark{display:grid;place-items:center;width:38px;height:38px;border-radius:12px;background:linear-gradient(145deg,#2b6eff,#784cff);box-shadow:0 9px 28px #3d55ff66;font-style:normal;font-weight:800}.brand-line p,.mission-heading p{margin:0;color:#62d6d0;font-size:9px;font-weight:800;letter-spacing:.18em}.brand-line h1{margin:4px 0 0;font-size:21px;letter-spacing:-.02em}.live-badge{align-self:center;display:flex;align-items:center;gap:8px;padding:8px 12px;border:1px solid #254057;border-radius:999px;background:#091827cc;color:#90a6b9;font-size:10px}.live-badge i,.agent-head em i,.agent-note i{width:6px;height:6px;border-radius:50%;background:var(--cyan);box-shadow:0 0 12px var(--cyan);animation:signal 2s ease-in-out infinite}.live-badge.replay{border-color:#8a6b35}.live-badge.replay i{background:#f5a524;box-shadow:0 0 12px #f5a524}.live-badge b{color:#dbeaff;font-weight:600}.live-badge small{color:#60798d}.command-controls{display:flex;justify-content:flex-end;align-items:end;gap:8px}.command-controls label,.period-control{display:grid;gap:5px;color:#7f96aa;font-size:9px}.period-control{min-width:390px}.period-control>span{font-weight:700;color:#9ab0c2}.period-shortcuts{display:flex;gap:4px}.period-shortcuts button,.apply-period{height:25px;padding:0 9px;border:1px solid #284258;border-radius:7px;background:#0a1928;color:#8ba2b5;font-size:9px;cursor:pointer}.period-shortcuts button.active{border-color:#4aa6a3;background:#143d43;color:#cafff7}.apply-period{height:35px;border-color:#386d72;color:#bceee9}.apply-period:disabled{cursor:not-allowed;opacity:.4}.command-controls input,.command-controls select,.refresh-button{height:35px;border:1px solid #284258;border-radius:9px;background:#0a1928;color:#eaf5ff;padding:0 10px}.command-controls select{max-width:210px}.date-range{display:flex;align-items:center;gap:5px}.date-range span{color:#486176}.date-range input{width:118px}.refresh-button{border-color:#327b78;background:linear-gradient(135deg,#176d6b,#1f8376);cursor:pointer;font-size:11px;font-weight:700}.refresh-button span{font-size:15px}.workspace-toolbar{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:4px 12px;margin-top:16px;padding:0 4px;border-bottom:1px solid #1c3042}.page-tabs,.view-tools{display:flex;align-items:center;gap:4px}.page-tabs button{position:relative;padding:11px 14px;border:0;background:none;color:#71899f;font-size:11px;cursor:pointer}.page-tabs button.active{color:#eef8ff}.page-tabs button.active:after{content:'';position:absolute;left:12px;right:12px;bottom:-1px;height:2px;background:linear-gradient(90deg,var(--cyan),var(--blue));box-shadow:0 0 12px var(--cyan)}.page-tabs b{display:inline-grid;place-items:center;min-width:17px;height:17px;margin-left:5px;border-radius:999px;background:#713927;color:#ffc59c;font-size:9px}.page-tabs i{display:inline-block;width:5px;height:5px;margin-left:5px;border-radius:50%;background:var(--orange)}.view-tools{padding-bottom:6px}.view-tools span{margin-right:4px;color:#5f778d;font-size:9px}.view-tools button{display:grid;place-items:center;width:29px;height:27px;border:1px solid transparent;border-radius:7px;background:transparent;color:#738ba1;cursor:pointer}.view-tools button.active,.view-tools button:hover{border-color:#29475d;background:#112436;color:#bceef0}.pulse-strip{display:grid;grid-template-columns:1.5fr repeat(4,1fr);gap:1px;margin-top:14px;overflow:hidden;border:1px solid #21394e;border-radius:16px;background:#20364a;box-shadow:0 18px 52px #02071080}.pulse-strip>div{position:relative;min-height:82px;padding:13px 16px;background:linear-gradient(145deg,#0d1b2b,#0a1624);display:grid;align-content:center;gap:5px;overflow:hidden}.pulse-strip>div:before{content:'';position:absolute;inset:auto 0 0;height:1px;background:linear-gradient(90deg,transparent,#4e7089,transparent)}.pulse-strip span{color:#70879c;font-size:9px}.pulse-strip strong{font-size:23px;line-height:1}.pulse-strip strong small{font-size:11px;color:#647c92}.pulse-strip small{color:#5f778d;font-size:9px}.pulse-strip em{width:72px;height:3px;border-radius:9px;background:linear-gradient(90deg,var(--cyan) var(--progress),#203548 var(--progress));margin-top:4px}.pulse-strip .urgent strong{color:#ffab6d;text-shadow:0 0 22px #ff7b3c66}.pulse-strip .caution strong{color:#e9c276}.customer-cell strong{font-size:17px}.operations-grid{display:grid;grid-template-columns:340px minmax(0,1fr);gap:14px;margin-top:14px;align-items:stretch}.mode-data .operations-grid{grid-template-columns:1fr}.mode-chat .operations-grid{grid-template-columns:minmax(340px,720px);justify-content:center}.agent-panel,.data-stage{min-width:0;border:1px solid #20384c;border-radius:19px;background:linear-gradient(155deg,#0b1928e8,#07121ee8);box-shadow:0 22px 70px #02071180;backdrop-filter:blur(16px)}.agent-panel{display:flex;flex-direction:column;height:calc(100vh - 210px);min-height:600px;position:sticky;top:14px;overflow:hidden}.mode-chat .agent-panel{height:calc(100vh - 220px);position:relative;top:auto}.agent-head{display:flex;align-items:center;gap:11px;padding:15px 16px;border-bottom:1px solid #1c3245}.agent-head>div:nth-child(2){display:grid;gap:2px}.agent-head span{font-size:9px;color:#6e879e}.agent-head strong{font-size:14px}.agent-head em{display:flex;align-items:center;gap:6px;margin-left:auto;color:#69d8cc;font-size:9px;font-style:normal}.agent-orb{position:relative;width:34px;height:34px;border-radius:50%;background:conic-gradient(from 40deg,#9d76ff,#3986ff,#4ce7d1,#9d76ff);box-shadow:0 0 24px #5798ff66;animation:float 3.2s ease-in-out infinite}.agent-orb:after{content:'';position:absolute;inset:5px;border-radius:50%;background:radial-gradient(circle at 36% 28%,#fff 0 6%,#88e9ed 10%,#182c52 54%,#070f1b 70%)}.agent-orb i{position:absolute;z-index:1;inset:-5px;border:1px solid #5ce6d466;border-radius:50%;animation:orbit 5s linear infinite}.context-ribbon{display:flex;align-items:center;gap:8px;margin:12px 14px 0;padding:9px 10px;border:1px solid #244159;border-radius:10px;background:#0c2133}.context-ribbon span{color:#6c879d;font-size:8px}.context-ribbon b{color:#bdd1e2;font-size:10px}.messages{flex:1;overflow:auto;padding:14px;display:flex;flex-direction:column;gap:10px}.message{max-width:92%;padding:10px 12px;border:1px solid #1e3a50;border-radius:4px 13px 13px;background:#102437}.message.user{align-self:flex-end;border-color:#27665f;border-radius:13px 4px 13px 13px;background:#145047}.message small{color:#63d4c9;font-size:8px}.message p{margin:4px 0 0;color:#d7e5f1;font-size:11px;line-height:1.65}.guides{padding:0 13px 9px;display:flex;gap:6px;flex-wrap:wrap}.guides button{border:1px solid #28455b;border-radius:999px;background:#0a1c2b;color:#91a9bc;padding:6px 8px;font-size:9px;cursor:pointer}.guides button:hover{border-color:#52aaad;color:#d6ffff}.composer{position:relative;margin:0 13px}.composer textarea{display:block;width:100%;resize:none;border:1px solid #31526b;border-radius:13px;background:#050e18;color:#eff9ff;padding:11px 48px 11px 11px;font-size:11px;line-height:1.5}.composer textarea:focus{outline:1px solid #50b9ba;box-shadow:0 0 24px #3bd8c622}.composer button{position:absolute;right:8px;bottom:8px;width:32px;height:32px;border:0;border-radius:9px;background:linear-gradient(145deg,#4be0cc,#338de4);color:#04111a;font-size:17px;font-weight:900;cursor:pointer}.agent-note{display:flex;align-items:center;gap:7px;margin:8px 15px 13px;color:#58738a;font-size:8px}.data-stage{padding:17px}.mission-heading{display:flex;justify-content:space-between;align-items:flex-end;gap:18px;margin-bottom:14px}.mission-heading h2{margin:5px 0 3px;font-size:21px}.mission-heading span{color:#70899e;font-size:9px}.stage-actions{display:flex;gap:6px}.stage-actions button{padding:7px 10px;border:1px solid #28455b;border-radius:8px;background:#0c1e2e;color:#8da7ba;font-size:9px;cursor:pointer}.stage-actions button:hover{border-color:#4b8894;color:#d6ffff}.module-tabs{display:grid;grid-template-columns:repeat(4,minmax(100px,1fr));gap:7px;margin-bottom:12px}.module-tabs button{position:relative;display:grid;grid-template-columns:1fr auto;gap:5px 9px;text-align:left;padding:10px 12px;border:1px solid #223d52;border-radius:11px;background:#0b1b2a;color:#dce9f5;cursor:pointer;overflow:hidden}.module-tabs button:after{content:'';position:absolute;inset:auto 0 0;height:2px;background:#526a7c;opacity:.4}.module-tabs button.active{border-color:#3f6b83;background:#10283b;box-shadow:inset 0 0 20px #2a668122}.module-tabs button.active:after{background:var(--cyan);opacity:1;box-shadow:0 0 14px var(--cyan)}.module-tabs .module-sem.active:after{background:var(--orange)}.module-tabs .module-seo.active:after{background:var(--blue)}.module-tabs .module-geo.active:after{background:var(--violet)}.module-tabs span{font-size:10px;font-weight:800}.module-tabs b{font-size:15px}.module-tabs small{grid-column:1/-1;color:#698299;font-size:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.metric-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(225px,1fr));gap:10px;max-height:none;overflow:visible;padding:2px 3px 12px}.mode-data .metric-grid{grid-template-columns:repeat(auto-fit,minmax(260px,1fr));max-height:none}.metric-grid.compact{grid-template-columns:repeat(auto-fit,minmax(185px,1fr))}.metric-grid.compact :deep(.evidence-card){padding:15px;border-radius:16px}.metric-grid.compact :deep(.trend-wrap),.metric-grid.compact :deep(.empty-trend){display:none}.metric-grid.compact :deep(.metric-trigger){padding:14px 0 4px}.metric-grid.compact :deep(.metric-number){font-size:30px}.metric-grid :deep(.evidence-card){background:linear-gradient(155deg,#12263a,#0b1725);border-color:#253f55;border-radius:17px;padding:17px}.metric-grid :deep(.evidence-card:hover){transform:translateY(-2px);border-color:#4b718b;box-shadow:0 14px 40px #02071188}.metric-grid :deep(.metric-number){font-size:clamp(28px,2.6vw,40px)}.metric-grid :deep(.trend){height:70px}.metric-grid :deep(.metric-trigger){padding:15px 0 6px}.data-empty{min-height:320px;border:1px dashed #29475e;border-radius:14px;display:grid;place-content:center;justify-items:center;text-align:center;gap:7px;color:#718ba0}.data-empty i{width:34px;height:34px;border:2px solid #2f5b6d;border-top-color:var(--cyan);border-radius:50%;animation:orbit 2s linear infinite}.data-empty strong{color:#d8e6f2}.data-empty span{font-size:10px}
.key-help{padding-right:8px;border-right:1px solid #1c3042;letter-spacing:.04em}.screen-applied{display:inline-flex;margin-top:7px;padding:3px 7px;border:1px solid #3c6f70;border-radius:999px;color:#77dfd3;font-size:8px}.message-actions{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}.message-actions button{padding:5px 7px;border:1px solid #346278;border-radius:7px;background:#102c3c;color:#a7e9e2;font-size:8px;cursor:pointer}.channel-control-strip{display:grid;grid-template-columns:minmax(150px,1.05fr) minmax(390px,2.4fr) auto;align-items:stretch;gap:8px;margin:0 0 12px;padding:9px;border:1px solid #20394d;border-radius:14px;background:#0a1826cc}.control-summary{display:grid;align-content:center;gap:4px;padding:4px 9px}.control-summary small{color:#6f899d;font-size:8px}.control-summary strong{font-size:14px}.control-summary span{color:#728a9d;font-size:8px}.channel-controls{display:grid;grid-template-columns:repeat(3,minmax(105px,1fr));gap:6px}.channel-control{display:grid;grid-template-columns:1fr auto;gap:3px 8px;min-width:0;padding:9px 10px;border:1px solid #263f52;border-radius:10px;background:#0c1c2a;color:#dbe8f1;text-align:left;cursor:pointer;transition:background .16s,border-color .16s}.channel-control:hover{background:#102536;border-color:#3b5b70}.channel-control.active{background:#132b3c;border-color:#5c8297}.channel-control span{display:flex;align-items:center;gap:6px;font-size:9px;font-weight:800;letter-spacing:.08em}.channel-control span i{width:6px;height:6px;border-radius:50%;background:#7b8f9e}.channel-control b{font-size:12px}.channel-control b small{color:#6f879a;font-size:8px;font-weight:400}.channel-control em{grid-column:1/-1;overflow:hidden;color:#6d8699;font-size:8px;font-style:normal;text-overflow:ellipsis;white-space:nowrap}.channel-sem span i{background:var(--orange)}.channel-seo span i{background:var(--blue)}.channel-geo span i{background:var(--violet)}.show-all-control{align-self:center;padding:8px 9px;border:1px solid #2b485c;border-radius:8px;background:transparent;color:#8da4b6;font-size:8px;cursor:pointer}.battle-layout{display:grid;grid-template-columns:minmax(0,1fr);gap:10px;align-items:start}.event-feed{min-height:280px;border:1px solid #213d51;border-radius:15px;background:#091725bb;overflow:hidden}.event-feed header{display:flex;justify-content:space-between;align-items:center;padding:12px;border-bottom:1px solid #1c3549}.event-feed header div{display:grid;gap:3px}.event-feed header small{color:#61d8cf;font-size:7px;letter-spacing:.14em}.event-feed header strong{font-size:12px}.event-feed header button{border:1px solid #29475b;border-radius:7px;background:#102538;color:#83a1b5;font-size:8px;padding:5px 7px;cursor:pointer}.event-list{display:grid}.event-list button{position:relative;display:grid;grid-template-columns:35px 6px 1fr;gap:7px;padding:11px 10px;border:0;border-bottom:1px solid #162d3e;background:transparent;color:#9cb2c3;text-align:left;cursor:pointer}.event-list button:hover{background:#102638}.event-list time{font-size:8px;color:#557189}.event-list i{width:5px;height:5px;margin-top:3px;border-radius:50%;background:var(--cyan);box-shadow:0 0 9px currentColor}.event-list span{font-size:9px;line-height:1.5}.event-list b{grid-column:3;color:#5d879b;font-size:8px;font-weight:500}.event-sem i{background:var(--orange)}.event-seo i{background:var(--blue)}.event-geo i{background:var(--violet)}.event-feed>p{padding:26px 12px;color:#607a8e;font-size:9px}.event-feed footer{display:flex;align-items:center;gap:7px;padding:10px 12px;color:#607a8e;font-size:8px}.event-feed footer span{width:5px;height:5px;border-radius:50%;background:var(--cyan);box-shadow:0 0 10px var(--cyan);animation:signal 2s infinite}.event-feed footer span.paused{background:#8b96a1;box-shadow:none;animation:none}.command-drawer{position:fixed;z-index:20;right:18px;top:18px;bottom:18px;width:min(420px,calc(100vw - 36px));padding:20px;border:1px solid #3a6075;border-radius:18px;background:#091725ed;box-shadow:-25px 0 80px #000a;backdrop-filter:blur(18px) saturate(1.15);animation:drawerIn .2s ease-out}.command-drawer header{display:flex;justify-content:space-between;align-items:flex-start}.command-drawer header small{color:#68d9d0;font-size:8px;letter-spacing:.12em}.command-drawer h2{margin:5px 0;font-size:19px}.command-drawer header button{width:31px;height:31px;border:1px solid #315066;border-radius:50%;background:#102538;color:#c4d6e2;font-size:19px;cursor:pointer}.drawer-value{margin:26px 0 10px;font-size:46px;font-weight:700;letter-spacing:-.04em}.command-drawer>p{color:#9fb2c1;font-size:11px;line-height:1.7}.command-drawer dl{margin:22px 0;border-top:1px solid #244053}.command-drawer dl div{display:grid;grid-template-columns:72px 1fr;gap:10px;padding:11px 0;border-bottom:1px solid #1e374a}.command-drawer dt{color:#628096;font-size:9px}.command-drawer dd{margin:0;color:#b9cad6;font-size:10px;overflow-wrap:anywhere}.drawer-actions{display:grid;grid-template-columns:1fr 1fr;gap:8px}.drawer-actions button{padding:10px;border:1px solid #356776;border-radius:9px;background:#10323a;color:#aef7ed;font-size:9px;cursor:pointer}.drawer-actions button+button{border-color:#334f68;background:#12263a;color:#b3cadb}
.ledger{display:grid;gap:9px}.ledger article{display:grid;grid-template-columns:44px 8px minmax(0,1fr) auto;align-items:center;gap:13px;padding:15px;border:1px solid #243f54;border-radius:13px;background:#0c1d2d}.ledger article.urgent{border-color:#704831;background:linear-gradient(90deg,#2b1c18,#0c1d2d 35%)}.action-rank{display:grid;place-items:center;height:26px;border-radius:7px;background:#142b3d;color:#7892a7;font-size:9px}.ledger article.urgent .action-rank{background:#68351f;color:#ffd0af}.ledger article>i{width:7px;height:7px;border-radius:50%;background:#e6b56d}.ledger article>i.ready{background:var(--cyan);box-shadow:0 0 12px var(--cyan)}.action-copy{display:grid;gap:4px}.action-copy small{color:#6c879d;font-size:8px}.action-copy b{font-size:12px}.action-copy span{color:#7891a6;font-size:9px}.ledger article>button{border:1px solid #31536a;border-radius:8px;background:#10283a;color:#a9dcd9;padding:8px 10px;font-size:9px;cursor:pointer}.quality-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.quality-grid article{min-height:170px;padding:18px;border:1px solid #263f54;border-radius:15px;background:linear-gradient(145deg,#102337,#091624)}.quality-grid span{color:#7390a5;font-size:9px}.quality-grid strong{display:block;margin:18px 0 12px;font-size:38px}.quality-grid p{color:#7c94a8;font-size:10px;line-height:1.7}.quality-grid .caution strong{color:#e8bc70}.quality-grid .principle{grid-column:1/-1;min-height:auto;background:linear-gradient(100deg,#122b3d,#171b39)}.quality-grid h3{margin:8px 0 0;font-size:22px}.agent-fab{position:fixed;right:28px;bottom:26px;z-index:5;display:flex;align-items:center;gap:9px;padding:11px 15px;border:1px solid #43887f;border-radius:999px;background:#0d2f36;color:#cafff7;box-shadow:0 12px 40px #0008;cursor:pointer}.agent-fab i{width:8px;height:8px;border-radius:50%;background:var(--cyan);box-shadow:0 0 12px var(--cyan)}.is-fullscreen{overflow:auto}.is-fullscreen .operations-grid{min-height:calc(100vh - 205px)}button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:2px solid #78e7de;outline-offset:2px}@keyframes drawerIn{from{opacity:0;transform:translateX(28px)}}@keyframes signal{50%{opacity:.35;transform:scale(.75)}}@keyframes float{50%{transform:translateY(-2px);box-shadow:0 0 32px #5798ff88}}@keyframes orbit{to{transform:rotate(360deg)}}@media(prefers-reduced-motion:reduce){*{animation:none!important;scroll-behavior:auto!important;transition:none!important}}@media(max-width:1180px){.key-help{display:none}.battle-layout{grid-template-columns:1fr}.event-feed{min-height:auto}.event-list{grid-template-columns:repeat(2,1fr)}.command-bar{grid-template-columns:1fr auto}.live-badge{display:none}.command-controls{grid-column:1/-1;justify-content:flex-start}.operations-grid{grid-template-columns:310px minmax(0,1fr)}.pulse-strip{grid-template-columns:1.4fr repeat(2,1fr)}.pulse-strip>div:nth-child(4),.pulse-strip>div:nth-child(5){display:none}.module-tabs{grid-template-columns:repeat(2,1fr)}}@media(max-width:860px){.channel-control-strip{grid-template-columns:1fr}.channel-controls{grid-template-columns:repeat(3,1fr)}.show-all-control{justify-self:start}.battle-layout{grid-template-columns:1fr}.event-list{grid-template-columns:1fr}.cockpit-shell{padding:12px}.operations-grid{grid-template-columns:1fr}.agent-panel{height:auto;min-height:520px;position:relative;top:auto}.data-stage{min-height:540px}.pulse-strip{grid-template-columns:1fr 1fr}.pulse-strip .customer-cell{grid-column:1/-1}.command-controls{flex-wrap:wrap}.metric-grid{max-height:none}.quality-grid{grid-template-columns:1fr}.quality-grid .principle{grid-column:auto}}@media(max-width:560px){.channel-controls{grid-template-columns:1fr}.command-bar{grid-template-columns:1fr}.command-controls label,.period-control,.date-range{width:100%}.period-control{min-width:0}.period-shortcuts button{flex:1}.date-range input{width:calc(50% - 10px)}.workspace-toolbar{align-items:flex-end}.page-tabs{width:100%;justify-content:space-between}.view-tools{width:100%;justify-content:flex-end}.view-tools span{display:none}.page-tabs button{padding:10px 7px}.pulse-strip{grid-template-columns:1fr}.pulse-strip>div:nth-child(4),.pulse-strip>div:nth-child(5){display:none}.module-tabs{grid-template-columns:1fr 1fr}.mission-heading{align-items:flex-start;flex-direction:column}.metric-grid{grid-template-columns:1fr}.ledger article{grid-template-columns:40px 8px 1fr}.ledger article>button{grid-column:3}.brand-line h1{font-size:18px}}
</style>
<style scoped>
.operations-grid{grid-template-columns:minmax(300px,3fr) minmax(0,7fr);align-items:start}
.agent-panel{height:calc(100vh - 150px);min-height:620px}
.panorama-content{display:grid;gap:14px}
.decision-summary{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(280px,.85fr);gap:12px}
.decision-summary>article{display:flex;min-height:238px;flex-direction:column;padding:18px;border:1px solid #294356;border-radius:16px;background:linear-gradient(145deg,#102335,#091725)}
.decision-summary>article>header{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:14px}
.decision-summary header div{display:grid;gap:4px}.decision-summary header small{color:#718ca1;font-size:9px}.decision-summary h3{margin:0;font-size:18px}.decision-summary header>span{padding:4px 8px;border:1px solid #315368;border-radius:999px;color:#8aa7ba;font-size:9px}
.outcome-summary{border-color:#2e5d5d!important}.attention-summary{border-color:#5f4937!important}.summary-items{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.summary-items button{display:grid;min-width:0;padding:12px;border:1px solid #2a5260;border-radius:11px;background:#0b1d2b;color:#e9f5fb;text-align:left;cursor:pointer}.summary-items button>small{color:#61c9c1;font-size:8px}.summary-items button>strong{margin:7px 0 3px;overflow:hidden;font-size:24px;text-overflow:ellipsis}.summary-items button>span{overflow:hidden;color:#a6bac8;font-size:10px;text-overflow:ellipsis;white-space:nowrap}.summary-items button>em{margin-top:9px;color:#72dcd1;font-size:9px;font-style:normal}
.attention-items{display:grid;gap:7px}.attention-items button{display:grid;grid-template-columns:38px minmax(0,1fr) auto;align-items:center;gap:10px;padding:10px;border:1px solid #523f33;border-radius:10px;background:#1c1818;color:#edf2f5;text-align:left;cursor:pointer}.attention-items button>b{color:#f0b879;font-size:22px}.attention-items button>span{display:grid;gap:3px}.attention-items button strong{font-size:10px}.attention-items button small{overflow:hidden;color:#9a8e86;font-size:8px;text-overflow:ellipsis;white-space:nowrap}.attention-items button>em{color:#e8b878;font-size:9px;font-style:normal}
.decision-summary article>p{margin:auto 0;color:#7f98aa;font-size:11px}.decision-summary article>footer{margin-top:auto;padding-top:12px;color:#61798b;font-size:9px}
.section-jumps{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.section-jumps button{display:flex;justify-content:space-between;padding:10px 12px;border:1px solid #29465a;border-radius:10px;background:#0b1d2b;color:#b5c7d4;cursor:pointer}.section-jumps small{color:#67d7ca}
.dashboard-section{scroll-margin-top:16px}.dashboard-group{display:flex;align-items:flex-end;justify-content:space-between;margin:0 0 10px;padding:14px 2px 10px;border-bottom:1px solid #294154}.dashboard-group>div{display:grid;grid-template-columns:auto 1fr;align-items:center;gap:2px 9px}.dashboard-group small{grid-row:1/3;color:#5bcfc5;font-size:10px}.dashboard-group h3{margin:0;font-size:16px}.dashboard-group p{grid-column:2;margin:0;color:#718ba0;font-size:9px}.dashboard-group>span{color:#86a0b5;font-size:9px}
.section-empty{margin:0;padding:26px;border:1px dashed #294154;border-radius:12px;color:#6f879a;text-align:center}.metric-grid{grid-template-columns:repeat(auto-fit,minmax(230px,1fr))}
@media(max-width:1050px){.operations-grid{grid-template-columns:1fr}.agent-panel{height:auto;min-height:520px;position:relative}.decision-summary{grid-template-columns:1fr}}
@media(max-width:680px){.summary-items,.section-jumps{grid-template-columns:1fr}.decision-summary{grid-template-columns:1fr}.attention-items button{grid-template-columns:34px minmax(0,1fr)}}
</style>
