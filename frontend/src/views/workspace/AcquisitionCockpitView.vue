<script setup>
import { computed, nextTick, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import MetricEvidenceCard from './cockpit/MetricEvidenceCard.vue'
import { fetchModules, fetchTenants } from '../../api/auth'
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
import { isSecureCockpitRuntime, resolveTenantModuleCodes } from './cockpit/scope.mjs'
import { completedWeekEnd, geoSummaryCards } from './cockpit/geo-summary.mjs'
import { createSeoSiteSelectionGuard, resolveSeoSiteSelection } from './cockpit/site-selection.mjs'
import { urgencyReply } from './cockpit/status-copy.mjs'

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
const lastReadAt = ref(null)
const dateEnd = ref(shanghaiDate())
const dateStart = ref(shiftDate(dateEnd.value, -6))
const cards = ref([])
const initialConversation = () => [
  { role: 'assistant', text: '我会先说明数据是否完整，再帮你判断现在最该处理什么。你可以直接问，也可以从下面的问题开始。' },
]
const conversation = ref(initialConversation())
const moduleState = ref({ sem: 'waiting', seo: 'waiting', geo: 'waiting' })
const tenantModuleCodes = ref(new Set())
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
const availableModules = computed(() => session.modules.filter(item => tenantModuleCodes.value.has(item.module_code) && moduleMeta[item.module_code]
  && moduleMeta[item.module_code].permission.some(key => session.canView(key))))
const customerName = computed(() => session.tenants.find(item => item.id === session.tenantId)?.name
  || session.user?.display_name || '当前客户')
const unresolvedModules = computed(() => availableModules.value.filter(item => moduleState.value[item.module_code] !== 'ready').length)
const urgentItems = computed(() => cards.value.reduce((sum, item) => sum + (Number.isSafeInteger(item.urgentCount) ? item.urgentCount : 0), 0))
const readyModules = computed(() => availableModules.value.filter(item => moduleState.value[item.module_code] === 'ready').length)
const filteredCards = computed(() => activeModule.value === 'all'
  ? cards.value
  : cards.value.filter(item => item.moduleCode === activeModule.value))
const dataHealth = computed(() => {
  if (!availableModules.value.length) return 0
  return Math.round(readyModules.value / availableModules.value.length * 100)
})
const partialEvidence = computed(() => cards.value.filter(item => ['partial', 'no_data', 'unavailable'].includes(item.state)).length)
const geoWeekEnd = computed(() => completedWeekEnd(dateEnd.value))
const statusLabel = status => ({ ready: '数据已读取', loading: '读取中', needs_scope: '需要选择业务对象', denied: '无查看权限', error: '读取失败', waiting: '等待读取' }[status] || '待确认')
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
function displayTime(value) {
  return value ? new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit' }).format(value) : '尚未读取'
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
    sourceLabel: '百度推广已有关键词报告', updatedLabel: report.coverage.updated_at || '未知',
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
  const ticket = viewState.begin(card.moduleCode || 'sem', card.id)
  if (ticket.publish(card)) cards.value = viewState.snapshot().map(item => item.metric)
}
async function loadSem(generation) {
  if (!session.tenantId || !availableModules.value.some(item => item.module_code === 'sem')) return
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
    if (generation !== prepareGeneration || requestedTenantId !== session.tenantId || requestedAuthRevision !== session.authRevision) return
    session.setModules(modules.modules)
    session.setTenants(tenants.tenants)
    const eligible = modules.modules.filter(item => item.available && moduleMeta[item.module_code]
      && moduleMeta[item.module_code].permission.some(key => session.canView(key)))
    const scoped = await Promise.all(eligible.map(async item => ({
      code: item.module_code,
      tenants: (await fetchTenants(item.module_code)).tenants,
    })))
    if (generation !== prepareGeneration || requestedTenantId !== session.tenantId || requestedAuthRevision !== session.authRevision) return
    tenantModuleCodes.value = resolveTenantModuleCodes({
      modules: modules.modules,
      tenantsByModule: Object.fromEntries(scoped.map(item => [item.code, item.tenants])),
      tenantId: session.tenantId,
      moduleMeta,
      canView: key => session.canView(key),
    })
    await loadAll()
  } catch (error) {
    if (generation !== prepareGeneration || requestedTenantId !== session.tenantId || requestedAuthRevision !== session.authRevision) return
    loading.value = false
    conversation.value.push({ role: 'assistant', text: `工作台身份信息读取失败：${error.message}` })
  }
}
function answerFor(text) {
  if (!availableModules.value.length) return '当前账号没有可查看的获客模块，请联系管理员确认模块和查看权限。'
  if (text.includes('SEM') && moduleState.value.sem === 'ready') return `已按 ${dateStart.value} 至 ${dateEnd.value} 读取 SEM 数据。点击任意数字可以看每日明细和数据依据。`
  if (text.includes('SEO') && moduleState.value.seo === 'ready') return '已读取当前 SEO 网站的内容和页面检查数字。审核、发布、页面检查分别判断，单篇搜索点击仍明确标为未接入。'
  if (text.includes('GEO') && moduleState.value.geo === 'ready') return `已按截至 ${geoWeekEnd.value} 的最近完整自然周读取 GEO 正式指标。模拟回答、人工记录和不合格样本没有算入数字。`
  const urgency = urgencyReply({ unresolvedModules: unresolvedModules.value, businessUrgentItems: urgentItems.value })
  if (urgency) return `${urgency} 我不会把缺失数据当成零。`
  return '当前已开通模块的数据状态正常。你可以点击具体指标，再选择“带着这项数据继续提问”。'
}
async function send(text = question.value) {
  const value = String(text || '').trim()
  if (!value) return
  conversation.value.push({ role: 'user', text: value }, { role: 'assistant', text: answerFor(value) })
  question.value = ''
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
  const path = code === 'sem' ? '/monitor/dashboard' : code === 'seo' ? '/seo/sites' : '/deal-sniper/geo/dashboard.html#/geo/projects'
  if (code === 'geo') window.location.assign(path)
  else router.push(path)
}
function selectSeoSite(event) {
  const value = Number(event.target.value)
  seoSiteSelectionGuard.confirmExplicitSelection(session.tenantId)
  currentSeoSiteId.value = Number.isSafeInteger(value) && value > 0 ? value : null
}
function setViewMode(mode) {
  viewMode.value = mode
  if (mode === 'chat') nextTick(() => messagesEl.value?.scrollTo({ top: messagesEl.value.scrollHeight }))
}
async function toggleFullscreen() {
  try {
    if (!document.fullscreenElement) await shellEl.value?.requestFullscreen?.()
    else await document.exitFullscreen?.()
  } catch {
    fullscreen.value = !fullscreen.value
  }
}
function syncFullscreen() { fullscreen.value = document.fullscreenElement === shellEl.value }

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
  if (activeModule.value !== 'all' && !codes.split(',').includes(activeModule.value)) activeModule.value = 'all'
})
onMounted(() => { document.addEventListener('fullscreenchange', syncFullscreen); prepare() })
onBeforeUnmount(() => { document.removeEventListener('fullscreenchange', syncFullscreen); ++loadGeneration; ++prepareGeneration; workbenchSession?.dispose(); viewState.dispose() })
</script>

<template>
  <main ref="shellEl" class="cockpit-shell" :class="[`mode-${viewMode}`, { 'is-fullscreen': fullscreen }]" v-loading="loading">
    <div class="ambient ambient-a"></div><div class="ambient ambient-b"></div><div class="scanline"></div>
    <header class="command-bar">
      <div class="brand-block">
        <button class="back-link" type="button" @click="router.push('/workspace')">← 功能模块</button>
        <div class="brand-line"><i class="brand-mark">S</i><div><p>G-SNIPERS · ACQUISITION COMMAND</p><h1>G-Snipers 获客工作台</h1></div></div>
      </div>
      <div class="live-badge"><i></i><span>工作台在线</span><b>{{ displayTime(lastReadAt) }}</b></div>
      <div class="command-controls">
        <label v-if="availableModules.some(item => item.module_code === 'seo')">SEO 网站
          <select :value="currentSeoSiteId || ''" aria-label="选择 SEO 网站" @change="selectSeoSite">
            <option value="">{{ seoSites.some(site => site.status === 'active') ? '请选择网站' : '暂无可用网站' }}</option>
            <option v-for="site in seoSites" :key="site.id" :value="site.id" :disabled="site.status !== 'active'">{{ site.name }} · {{ site.domain }}{{ site.status === 'active' ? '' : '（已停用）' }}</option>
          </select>
        </label>
        <label>数据周期<div class="date-range"><input v-model="dateStart" type="date" :max="dateEnd"><span>—</span><input v-model="dateEnd" type="date" :min="dateStart"></div></label>
        <button class="refresh-button" type="button" @click="loadAll"><span>↻</span> 刷新战况</button>
      </div>
    </header>

    <nav class="workspace-toolbar" aria-label="获客工作台导航">
      <div class="page-tabs">
        <button :class="{ active: activeSection === 'dashboard' }" type="button" @click="activeSection = 'dashboard'">实时战况</button>
        <button :class="{ active: activeSection === 'actions' }" type="button" @click="activeSection = 'actions'">行动台账 <b v-if="urgentItems">{{ urgentItems }}</b></button>
        <button :class="{ active: activeSection === 'quality' }" type="button" @click="activeSection = 'quality'">数据边界 <i v-if="partialEvidence"></i></button>
      </div>
      <div class="view-tools" aria-label="布局控制">
        <span>视图</span>
        <button :class="{ active: viewMode === 'chat' }" type="button" title="对话为主" @click="setViewMode('chat')">▤</button>
        <button :class="{ active: viewMode === 'split' }" type="button" title="协同视图" @click="setViewMode('split')">◫</button>
        <button :class="{ active: viewMode === 'data' }" type="button" title="数据为主" @click="setViewMode('data')">▥</button>
        <button type="button" title="全屏" @click="toggleFullscreen">{{ fullscreen ? '↙' : '⛶' }}</button>
      </div>
    </nav>

    <section class="pulse-strip" aria-label="工作台实时状态">
      <div class="customer-cell"><span>当前作战客户</span><strong>{{ customerName }}</strong><small>{{ availableModules.length }} 个获客模块已开通</small></div>
      <div><span>数据就绪</span><strong>{{ readyModules }}<small>/{{ availableModules.length }}</small></strong><em :style="{ '--progress': `${dataHealth}%` }"></em></div>
      <div :class="{ urgent: urgentItems }"><span>现在要处理</span><strong>{{ urgentItems }}</strong><small>{{ urgentItems ? '请优先查看行动台账' : '暂无紧急数据事项' }}</small></div>
      <div><span>可核对指标</span><strong>{{ cards.length }}</strong><small>均可打开查看来源</small></div>
      <div :class="{ caution: partialEvidence }"><span>边界待说明</span><strong>{{ partialEvidence }}</strong><small>缺失、部分或暂不可用</small></div>
    </section>

    <section class="operations-grid">
      <aside v-if="viewMode !== 'data'" class="agent-panel">
        <div class="agent-head"><div class="agent-orb"><i></i></div><div><span>获客推广AI智能体</span><strong>作战对话</strong></div><em><i></i> 引导中</em></div>
        <div class="context-ribbon"><span>当前关注</span><b>{{ urgentItems ? `${urgentItems} 项待处理事项` : '本周期整体获客表现' }}</b></div>
        <div ref="messagesEl" class="messages" aria-live="polite">
          <div v-for="(item, index) in conversation" :key="index" :class="['message', item.role]">
            <small>{{ item.role === 'assistant' ? '智能体' : '我' }}</small><p>{{ item.text }}</p>
          </div>
        </div>
        <div class="guides"><button v-for="item in guideQuestions.slice(0, 4)" :key="item" type="button" @click="send(item)">{{ item }}</button></div>
        <form class="composer" @submit.prevent="send()"><textarea v-model="question" rows="3" placeholder="问数据、看风险，或直接下达下一步指令…"></textarea><button type="submit" aria-label="发送指令">↑</button></form>
        <p class="agent-note"><i></i> 回答仅使用当前已核验数据；执行前会单独确认范围。</p>
      </aside>

      <div v-if="viewMode !== 'chat'" class="data-stage">
        <div class="mission-heading">
          <div><p>LIVE ACQUISITION PULSE</p><h2>{{ activeSection === 'dashboard' ? '获客数据全景' : activeSection === 'actions' ? '行动指挥台' : '数据可信边界' }}</h2><span>{{ dateStart }} 至 {{ dateEnd }} · 缺失数据不会补成 0</span></div>
          <div class="stage-actions"><button type="button" @click="compactCards = !compactCards">{{ compactCards ? '展开卡片' : '收拢卡片' }}</button><button type="button" @click="setViewMode('data')">专注大盘 ↗</button></div>
        </div>

        <div class="module-tabs" role="tablist" aria-label="模块筛选">
          <button :class="{ active: activeModule === 'all' }" type="button" @click="activeModule = 'all'"><span>全域</span><b>{{ cards.length }}</b><small>全部数据</small></button>
          <button v-for="item in availableModules" :key="item.module_code" :class="[{ active: activeModule === item.module_code }, `module-${item.module_code}`]" type="button" @click="activeModule = item.module_code">
            <span>{{ moduleMeta[item.module_code].label }}</span><b>{{ cards.filter(card => card.moduleCode === item.module_code).length }}</b><small>{{ moduleStatusLabel(item.module_code) }}</small>
          </button>
        </div>

        <template v-if="activeSection === 'dashboard'">
          <div v-if="filteredCards.length" class="metric-grid" :class="{ compact: compactCards }">
            <MetricEvidenceCard v-for="card in filteredCards" :key="card.id" :metric="card" :context-revision="viewState.revision" @discuss="discuss" @retry="loadAll" />
          </div>
          <div v-else class="data-empty"><i></i><strong>当前范围尚无可展示数字</strong><span>系统正在核对模块、权限与业务对象，不会显示演示值。</span></div>
        </template>

        <div v-else-if="activeSection === 'actions'" class="ledger">
          <article v-for="item in availableModules" :key="`action-${item.module_code}`" :class="{ urgent: moduleUrgent(item.module_code) }">
            <div class="action-rank">{{ moduleUrgent(item.module_code) ? '优先' : '跟进' }}</div><i :class="moduleState[item.module_code]"></i>
            <div class="action-copy"><small>{{ moduleMeta[item.module_code].label }} · {{ statusLabel(moduleState[item.module_code]) }}</small><b>{{ moduleState[item.module_code] === 'ready' ? (moduleUrgent(item.module_code) ? `${moduleUrgent(item.module_code)} 项已有数据依据，需要处理` : '本周期数据已读取，继续观察表现') : '读取范围或数据状态需要补齐' }}</b><span>{{ moduleUrgent(item.module_code) ? '先查看依据，再进入模块处理。' : '进入模块查看详细记录与下一步。' }}</span></div>
            <button type="button" @click="openModule(item.module_code)">进入处理 ↗</button>
          </article>
          <div v-if="!availableModules.length" class="data-empty"><strong>当前没有可查看的获客模块</strong><span>请联系管理员确认客户开通状态和账号权限。</span></div>
        </div>

        <div v-else class="quality-grid">
          <article><span>数据读取状态</span><strong>{{ dataHealth }}%</strong><p>{{ readyModules }} 个模块已就绪，{{ unresolvedModules }} 个模块仍需确认。</p></article>
          <article><span>来源可核对</span><strong>{{ cards.length - partialEvidence }}</strong><p>点击任意指标查看统计范围、数据来源、更新时间和逐期明细。</p></article>
          <article :class="{ caution: partialEvidence }"><span>边界待说明</span><strong>{{ partialEvidence }}</strong><p>部分、缺失和暂不可用数据保持原样，不推算成客户事实。</p></article>
          <article class="principle"><span>判断原则</span><h3>先发现，再解释</h3><p>系统先展示可核对的业务数据；分析和行动建议在对话中单独给出。</p></article>
        </div>
      </div>
    </section>
    <button v-if="viewMode === 'data'" class="agent-fab" type="button" @click="setViewMode('split')"><i></i><span>打开智能体</span></button>
  </main>
</template>

<style scoped>
*{box-sizing:border-box}.cockpit-shell{--cyan:#59e8d3;--blue:#5798ff;--violet:#9f72ff;--orange:#ff9f5a;position:relative;isolation:isolate;min-height:100vh;padding:18px 22px 28px;overflow:hidden;background:#060d18;color:#edf6ff;font-variant-numeric:tabular-nums}.ambient{position:fixed;z-index:-2;pointer-events:none;border-radius:50%;filter:blur(20px);opacity:.3}.ambient-a{width:700px;height:700px;right:-220px;top:-360px;background:radial-gradient(circle,#285bd8 0,transparent 68%)}.ambient-b{width:620px;height:620px;left:-360px;bottom:-360px;background:radial-gradient(circle,#006b73 0,transparent 70%)}.scanline{position:fixed;z-index:-1;inset:0;pointer-events:none;opacity:.035;background:repeating-linear-gradient(180deg,#fff 0 1px,transparent 1px 5px)}button,input,select,textarea{font:inherit}.command-bar{display:grid;grid-template-columns:minmax(260px,1fr) auto minmax(500px,1.35fr);align-items:end;gap:20px;position:relative}.brand-block{min-width:0}.back-link{padding:0 0 9px;border:0;background:none;color:#7690a9;font-size:11px;cursor:pointer}.brand-line{display:flex;align-items:center;gap:12px}.brand-mark{display:grid;place-items:center;width:38px;height:38px;border-radius:12px;background:linear-gradient(145deg,#2b6eff,#784cff);box-shadow:0 9px 28px #3d55ff66;font-style:normal;font-weight:800}.brand-line p,.mission-heading p{margin:0;color:#62d6d0;font-size:9px;font-weight:800;letter-spacing:.18em}.brand-line h1{margin:4px 0 0;font-size:21px;letter-spacing:-.02em}.live-badge{align-self:center;display:flex;align-items:center;gap:8px;padding:8px 12px;border:1px solid #254057;border-radius:999px;background:#091827cc;color:#90a6b9;font-size:10px}.live-badge i,.agent-head em i,.agent-note i{width:6px;height:6px;border-radius:50%;background:var(--cyan);box-shadow:0 0 12px var(--cyan);animation:signal 2s ease-in-out infinite}.live-badge b{color:#dbeaff;font-weight:600}.command-controls{display:flex;justify-content:flex-end;align-items:end;gap:8px}.command-controls label{display:grid;gap:5px;color:#7f96aa;font-size:9px}.command-controls input,.command-controls select,.refresh-button{height:35px;border:1px solid #284258;border-radius:9px;background:#0a1928;color:#eaf5ff;padding:0 10px}.command-controls select{max-width:210px}.date-range{display:flex;align-items:center;gap:5px}.date-range span{color:#486176}.date-range input{width:125px}.refresh-button{border-color:#327b78;background:linear-gradient(135deg,#176d6b,#1f8376);cursor:pointer;font-size:11px;font-weight:700}.refresh-button span{font-size:15px}.workspace-toolbar{display:flex;justify-content:space-between;align-items:center;margin-top:16px;padding:0 4px;border-bottom:1px solid #1c3042}.page-tabs,.view-tools{display:flex;align-items:center;gap:4px}.page-tabs button{position:relative;padding:11px 14px;border:0;background:none;color:#71899f;font-size:11px;cursor:pointer}.page-tabs button.active{color:#eef8ff}.page-tabs button.active:after{content:'';position:absolute;left:12px;right:12px;bottom:-1px;height:2px;background:linear-gradient(90deg,var(--cyan),var(--blue));box-shadow:0 0 12px var(--cyan)}.page-tabs b{display:inline-grid;place-items:center;min-width:17px;height:17px;margin-left:5px;border-radius:999px;background:#713927;color:#ffc59c;font-size:9px}.page-tabs i{display:inline-block;width:5px;height:5px;margin-left:5px;border-radius:50%;background:var(--orange)}.view-tools{padding-bottom:6px}.view-tools span{margin-right:4px;color:#5f778d;font-size:9px}.view-tools button{display:grid;place-items:center;width:29px;height:27px;border:1px solid transparent;border-radius:7px;background:transparent;color:#738ba1;cursor:pointer}.view-tools button.active,.view-tools button:hover{border-color:#29475d;background:#112436;color:#bceef0}.pulse-strip{display:grid;grid-template-columns:1.5fr repeat(4,1fr);gap:1px;margin-top:14px;overflow:hidden;border:1px solid #21394e;border-radius:16px;background:#20364a;box-shadow:0 18px 52px #02071080}.pulse-strip>div{position:relative;min-height:82px;padding:13px 16px;background:linear-gradient(145deg,#0d1b2b,#0a1624);display:grid;align-content:center;gap:5px;overflow:hidden}.pulse-strip>div:before{content:'';position:absolute;inset:auto 0 0;height:1px;background:linear-gradient(90deg,transparent,#4e7089,transparent)}.pulse-strip span{color:#70879c;font-size:9px}.pulse-strip strong{font-size:23px;line-height:1}.pulse-strip strong small{font-size:11px;color:#647c92}.pulse-strip small{color:#5f778d;font-size:9px}.pulse-strip em{width:72px;height:3px;border-radius:9px;background:linear-gradient(90deg,var(--cyan) var(--progress),#203548 var(--progress));margin-top:4px}.pulse-strip .urgent strong{color:#ffab6d;text-shadow:0 0 22px #ff7b3c66}.pulse-strip .caution strong{color:#e9c276}.customer-cell strong{font-size:17px}.operations-grid{display:grid;grid-template-columns:340px minmax(0,1fr);gap:14px;margin-top:14px;align-items:stretch}.mode-data .operations-grid{grid-template-columns:1fr}.mode-chat .operations-grid{grid-template-columns:minmax(340px,720px);justify-content:center}.agent-panel,.data-stage{min-width:0;border:1px solid #20384c;border-radius:19px;background:linear-gradient(155deg,#0b1928e8,#07121ee8);box-shadow:0 22px 70px #02071180;backdrop-filter:blur(16px)}.agent-panel{display:flex;flex-direction:column;height:calc(100vh - 210px);min-height:600px;position:sticky;top:14px;overflow:hidden}.mode-chat .agent-panel{height:calc(100vh - 220px);position:relative;top:auto}.agent-head{display:flex;align-items:center;gap:11px;padding:15px 16px;border-bottom:1px solid #1c3245}.agent-head>div:nth-child(2){display:grid;gap:2px}.agent-head span{font-size:9px;color:#6e879e}.agent-head strong{font-size:14px}.agent-head em{display:flex;align-items:center;gap:6px;margin-left:auto;color:#69d8cc;font-size:9px;font-style:normal}.agent-orb{position:relative;width:34px;height:34px;border-radius:50%;background:conic-gradient(from 40deg,#9d76ff,#3986ff,#4ce7d1,#9d76ff);box-shadow:0 0 24px #5798ff66;animation:float 3.2s ease-in-out infinite}.agent-orb:after{content:'';position:absolute;inset:5px;border-radius:50%;background:radial-gradient(circle at 36% 28%,#fff 0 6%,#88e9ed 10%,#182c52 54%,#070f1b 70%)}.agent-orb i{position:absolute;z-index:1;inset:-5px;border:1px solid #5ce6d466;border-radius:50%;animation:orbit 5s linear infinite}.context-ribbon{display:flex;align-items:center;gap:8px;margin:12px 14px 0;padding:9px 10px;border:1px solid #244159;border-radius:10px;background:#0c2133}.context-ribbon span{color:#6c879d;font-size:8px}.context-ribbon b{color:#bdd1e2;font-size:10px}.messages{flex:1;overflow:auto;padding:14px;display:flex;flex-direction:column;gap:10px}.message{max-width:92%;padding:10px 12px;border:1px solid #1e3a50;border-radius:4px 13px 13px;background:#102437}.message.user{align-self:flex-end;border-color:#27665f;border-radius:13px 4px 13px 13px;background:#145047}.message small{color:#63d4c9;font-size:8px}.message p{margin:4px 0 0;color:#d7e5f1;font-size:11px;line-height:1.65}.guides{padding:0 13px 9px;display:flex;gap:6px;flex-wrap:wrap}.guides button{border:1px solid #28455b;border-radius:999px;background:#0a1c2b;color:#91a9bc;padding:6px 8px;font-size:9px;cursor:pointer}.guides button:hover{border-color:#52aaad;color:#d6ffff}.composer{position:relative;margin:0 13px}.composer textarea{display:block;width:100%;resize:none;border:1px solid #31526b;border-radius:13px;background:#050e18;color:#eff9ff;padding:11px 48px 11px 11px;font-size:11px;line-height:1.5}.composer textarea:focus{outline:1px solid #50b9ba;box-shadow:0 0 24px #3bd8c622}.composer button{position:absolute;right:8px;bottom:8px;width:32px;height:32px;border:0;border-radius:9px;background:linear-gradient(145deg,#4be0cc,#338de4);color:#04111a;font-size:17px;font-weight:900;cursor:pointer}.agent-note{display:flex;align-items:center;gap:7px;margin:8px 15px 13px;color:#58738a;font-size:8px}.data-stage{padding:17px}.mission-heading{display:flex;justify-content:space-between;align-items:flex-end;gap:18px;margin-bottom:14px}.mission-heading h2{margin:5px 0 3px;font-size:21px}.mission-heading span{color:#70899e;font-size:9px}.stage-actions{display:flex;gap:6px}.stage-actions button{padding:7px 10px;border:1px solid #28455b;border-radius:8px;background:#0c1e2e;color:#8da7ba;font-size:9px;cursor:pointer}.stage-actions button:hover{border-color:#4b8894;color:#d6ffff}.module-tabs{display:grid;grid-template-columns:repeat(4,minmax(100px,1fr));gap:7px;margin-bottom:12px}.module-tabs button{position:relative;display:grid;grid-template-columns:1fr auto;gap:5px 9px;text-align:left;padding:10px 12px;border:1px solid #223d52;border-radius:11px;background:#0b1b2a;color:#dce9f5;cursor:pointer;overflow:hidden}.module-tabs button:after{content:'';position:absolute;inset:auto 0 0;height:2px;background:#526a7c;opacity:.4}.module-tabs button.active{border-color:#3f6b83;background:#10283b;box-shadow:inset 0 0 20px #2a668122}.module-tabs button.active:after{background:var(--cyan);opacity:1;box-shadow:0 0 14px var(--cyan)}.module-tabs .module-sem.active:after{background:var(--orange)}.module-tabs .module-seo.active:after{background:var(--blue)}.module-tabs .module-geo.active:after{background:var(--violet)}.module-tabs span{font-size:10px;font-weight:800}.module-tabs b{font-size:15px}.module-tabs small{grid-column:1/-1;color:#698299;font-size:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.metric-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(225px,1fr));gap:10px;max-height:calc(100vh - 395px);overflow:auto;padding:2px 3px 12px}.mode-data .metric-grid{grid-template-columns:repeat(auto-fit,minmax(260px,1fr));max-height:none}.metric-grid.compact{grid-template-columns:repeat(auto-fit,minmax(185px,1fr))}.metric-grid.compact :deep(.evidence-card){padding:15px;border-radius:16px}.metric-grid.compact :deep(.trend-wrap),.metric-grid.compact :deep(.empty-trend){display:none}.metric-grid.compact :deep(.metric-trigger){padding:14px 0 4px}.metric-grid.compact :deep(.metric-number){font-size:30px}.metric-grid :deep(.evidence-card){background:linear-gradient(155deg,#12263a,#0b1725);border-color:#253f55;border-radius:17px;padding:17px}.metric-grid :deep(.evidence-card:hover){transform:translateY(-2px);border-color:#4b718b;box-shadow:0 14px 40px #02071188}.metric-grid :deep(.metric-number){font-size:clamp(28px,2.6vw,40px)}.metric-grid :deep(.trend){height:70px}.metric-grid :deep(.metric-trigger){padding:15px 0 6px}.data-empty{min-height:320px;border:1px dashed #29475e;border-radius:14px;display:grid;place-content:center;justify-items:center;text-align:center;gap:7px;color:#718ba0}.data-empty i{width:34px;height:34px;border:2px solid #2f5b6d;border-top-color:var(--cyan);border-radius:50%;animation:orbit 2s linear infinite}.data-empty strong{color:#d8e6f2}.data-empty span{font-size:10px}.ledger{display:grid;gap:9px}.ledger article{display:grid;grid-template-columns:44px 8px minmax(0,1fr) auto;align-items:center;gap:13px;padding:15px;border:1px solid #243f54;border-radius:13px;background:#0c1d2d}.ledger article.urgent{border-color:#704831;background:linear-gradient(90deg,#2b1c18,#0c1d2d 35%)}.action-rank{display:grid;place-items:center;height:26px;border-radius:7px;background:#142b3d;color:#7892a7;font-size:9px}.ledger article.urgent .action-rank{background:#68351f;color:#ffd0af}.ledger article>i{width:7px;height:7px;border-radius:50%;background:#e6b56d}.ledger article>i.ready{background:var(--cyan);box-shadow:0 0 12px var(--cyan)}.action-copy{display:grid;gap:4px}.action-copy small{color:#6c879d;font-size:8px}.action-copy b{font-size:12px}.action-copy span{color:#7891a6;font-size:9px}.ledger article>button{border:1px solid #31536a;border-radius:8px;background:#10283a;color:#a9dcd9;padding:8px 10px;font-size:9px;cursor:pointer}.quality-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.quality-grid article{min-height:170px;padding:18px;border:1px solid #263f54;border-radius:15px;background:linear-gradient(145deg,#102337,#091624)}.quality-grid span{color:#7390a5;font-size:9px}.quality-grid strong{display:block;margin:18px 0 12px;font-size:38px}.quality-grid p{color:#7c94a8;font-size:10px;line-height:1.7}.quality-grid .caution strong{color:#e8bc70}.quality-grid .principle{grid-column:1/-1;min-height:auto;background:linear-gradient(100deg,#122b3d,#171b39)}.quality-grid h3{margin:8px 0 0;font-size:22px}.agent-fab{position:fixed;right:28px;bottom:26px;z-index:5;display:flex;align-items:center;gap:9px;padding:11px 15px;border:1px solid #43887f;border-radius:999px;background:#0d2f36;color:#cafff7;box-shadow:0 12px 40px #0008;cursor:pointer}.agent-fab i{width:8px;height:8px;border-radius:50%;background:var(--cyan);box-shadow:0 0 12px var(--cyan)}.is-fullscreen{overflow:auto}.is-fullscreen .operations-grid{min-height:calc(100vh - 205px)}button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:2px solid #78e7de;outline-offset:2px}@keyframes signal{50%{opacity:.35;transform:scale(.75)}}@keyframes float{50%{transform:translateY(-2px);box-shadow:0 0 32px #5798ff88}}@keyframes orbit{to{transform:rotate(360deg)}}@media(prefers-reduced-motion:reduce){*{animation:none!important;scroll-behavior:auto!important;transition:none!important}}@media(max-width:1180px){.command-bar{grid-template-columns:1fr auto}.live-badge{display:none}.command-controls{grid-column:1/-1;justify-content:flex-start}.operations-grid{grid-template-columns:310px minmax(0,1fr)}.pulse-strip{grid-template-columns:1.4fr repeat(2,1fr)}.pulse-strip>div:nth-child(4),.pulse-strip>div:nth-child(5){display:none}.module-tabs{grid-template-columns:repeat(2,1fr)}}@media(max-width:860px){.cockpit-shell{padding:12px}.operations-grid{grid-template-columns:1fr}.agent-panel{height:auto;min-height:520px;position:relative;top:auto}.data-stage{min-height:540px}.pulse-strip{grid-template-columns:1fr 1fr}.pulse-strip .customer-cell{grid-column:1/-1}.command-controls{flex-wrap:wrap}.metric-grid{max-height:none}.quality-grid{grid-template-columns:1fr}.quality-grid .principle{grid-column:auto}}@media(max-width:560px){.command-bar{grid-template-columns:1fr}.command-controls label,.date-range{width:100%}.date-range input{width:calc(50% - 10px)}.workspace-toolbar{align-items:flex-end}.view-tools span{display:none}.page-tabs button{padding:10px 7px}.pulse-strip{grid-template-columns:1fr}.pulse-strip>div:nth-child(4),.pulse-strip>div:nth-child(5){display:none}.module-tabs{grid-template-columns:1fr 1fr}.mission-heading{align-items:flex-start;flex-direction:column}.metric-grid{grid-template-columns:1fr}.ledger article{grid-template-columns:40px 8px 1fr}.ledger article>button{grid-column:3}.brand-line h1{font-size:18px}}
</style>
