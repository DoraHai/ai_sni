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
const messagesEl = ref(null)
const question = ref('')
const loading = ref(false)
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
      metricCard(report, 'cost', '推广花费', 'CNY'), metricCard(report, 'impression', '广告展现', 'count'),
      metricCard(report, 'click', '广告点击', 'count'), metricCard(report, 'ctr', '点击率', 'ratio'), phoneCard(report),
    ]) publishCard(card)
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
onMounted(prepare)
onBeforeUnmount(() => { ++loadGeneration; ++prepareGeneration; workbenchSession?.dispose(); viewState.dispose() })
</script>

<template>
  <main class="cockpit-shell" v-loading="loading">
    <header class="command-bar">
      <div><button class="back-link" type="button" @click="router.push('/workspace')">← 返回模块工作台</button><p>G-SNIPERS ACQUISITION DESK</p><h1>G-Snipers 获客工作台</h1><span>获客推广AI智能体</span></div>
      <div class="command-controls">
        <label v-if="availableModules.some(item => item.module_code === 'seo')">SEO 网站
          <select :value="currentSeoSiteId || ''" aria-label="选择 SEO 网站" @change="selectSeoSite">
            <option value="">{{ seoSites.some(site => site.status === 'active') ? '请选择网站' : '暂无可用网站' }}</option>
            <option v-for="site in seoSites" :key="site.id" :value="site.id" :disabled="site.status !== 'active'">
              {{ site.name }} · {{ site.domain }}{{ site.status === 'active' ? '' : '（已停用）' }}
            </option>
          </select>
        </label>
        <label>开始日期<input v-model="dateStart" type="date" :max="dateEnd"></label>
        <label>结束日期<input v-model="dateEnd" type="date" :min="dateStart"></label>
        <button type="button" @click="loadAll">刷新数据</button>
      </div>
    </header>

    <section class="pulse-strip" aria-label="工作台实时状态">
      <div><span>当前客户</span><strong>{{ customerName }}</strong></div>
      <div><span>当前客户已开通</span><strong>{{ availableModules.length }}</strong></div>
      <div><span>数据已就绪</span><strong>{{ readyModules }}</strong></div>
      <div :class="{ urgent: urgentItems }"><span>需要处理</span><strong>{{ urgentItems }}</strong></div>
      <div><span>最近读取</span><strong>{{ displayTime(lastReadAt) }}</strong></div>
    </section>

    <section class="operations-grid">
      <div class="data-stage">
        <div class="section-heading"><div><span>LIVE EVIDENCE</span><h2>获客数据全景</h2></div><small>点击数字查看明细；缺失数据不会补成 0</small></div>
        <div class="module-tabs">
          <button v-for="item in availableModules" :key="item.module_code" type="button" @click="openModule(item.module_code)">
            <b>{{ moduleMeta[item.module_code].label }}</b><span>{{ moduleStatusLabel(item.module_code) }}</span>
          </button>
        </div>
        <div v-if="cards.length" class="metric-grid">
          <MetricEvidenceCard v-for="card in cards" :key="card.id" :metric="card" :context-revision="viewState.revision" @discuss="discuss" @retry="loadAll" />
        </div>
        <div v-else class="data-empty">
          <strong>当前范围尚无可展示数字</strong><span>系统正在核对模块、权限与业务对象，不会显示演示值。</span>
        </div>

        <div class="ledger">
          <div class="section-heading"><div><span>ACTION LEDGER</span><h2>行动台账</h2></div><small>{{ urgentItems }} 项需要处理</small></div>
          <article v-for="item in availableModules" :key="`action-${item.module_code}`">
            <i :class="moduleState[item.module_code]"></i><b>{{ moduleMeta[item.module_code].label }}</b>
            <span>{{ moduleState[item.module_code] === 'ready' ? (moduleUrgent(item.module_code) ? `${moduleUrgent(item.module_code)} 项已有数据依据，建议现在处理` : '本周期数据已读取，可进入模块查看详细任务') : '补齐读取范围或处理数据状态' }}</span>
            <button type="button" @click="openModule(item.module_code)">进入处理 ↗</button>
          </article>
        </div>
      </div>

      <aside class="agent-panel">
        <div class="agent-head"><div class="agent-orb"></div><div><span>获客推广AI智能体</span><strong>作战对话</strong></div><em>引导模式</em></div>
        <div ref="messagesEl" class="messages" aria-live="polite">
          <div v-for="(item, index) in conversation" :key="index" :class="['message', item.role]">
            <small>{{ item.role === 'assistant' ? '智能体' : '我' }}</small><p>{{ item.text }}</p>
          </div>
        </div>
        <div class="guides"><button v-for="item in guideQuestions" :key="item" type="button" @click="send(item)">{{ item }}</button></div>
        <form class="composer" @submit.prevent="send()"><textarea v-model="question" rows="3" placeholder="直接问：现在最需要处理什么？"></textarea><button type="submit">发送指令 ↑</button></form>
        <p class="agent-note">当前回答仅基于本页已核验数据状态；生成式 AI 服务将在后续接口接入。</p>
      </aside>
    </section>
  </main>
</template>

<style scoped>
.cockpit-shell{box-sizing:border-box;min-height:100vh;padding:22px;background:radial-gradient(circle at 75% 0,#12324a 0,transparent 34%),#07111d;color:#eef7ff;font-variant-numeric:tabular-nums}.command-bar,.pulse-strip,.operations-grid,.section-heading,.agent-head,.module-tabs button,.ledger article{display:flex;align-items:center}.command-bar{justify-content:space-between;gap:24px;margin-bottom:16px}.back-link{margin:0 0 12px;padding:0;border:0;background:none;color:#7ea3b9;font-size:11px;cursor:pointer}.command-bar p,.section-heading span{margin:0;color:#66d9cf;font-size:10px;font-weight:800;letter-spacing:.16em}.command-bar h1{margin:5px 0 2px;font-size:26px}.command-bar>div>span{color:#91a8bc;font-size:12px}.command-controls{display:flex;align-items:end;gap:8px}.command-controls label{display:grid;gap:5px;color:#839bb0;font-size:10px}.command-controls input,.command-controls select,.command-controls button{height:36px;border:1px solid #294259;border-radius:9px;background:#0d1d2c;color:#e9f5ff;padding:0 11px}.command-controls select{max-width:230px}.command-controls button{background:#1e806f;cursor:pointer}.pulse-strip{display:grid;grid-template-columns:1.4fr repeat(4,1fr);gap:1px;overflow:hidden;border:1px solid #233a4e;border-radius:15px;background:#233a4e}.pulse-strip div{min-height:72px;padding:13px 17px;background:#0d1b2a;display:grid;align-content:center;gap:6px}.pulse-strip span{color:#7890a5;font-size:10px}.pulse-strip strong{font-size:20px}.pulse-strip .urgent strong{color:#ffb469}.operations-grid{align-items:stretch;display:grid;grid-template-columns:minmax(0,1fr) 360px;gap:16px;margin-top:16px}.data-stage,.agent-panel{border:1px solid #21394d;border-radius:20px;background:#091725}.data-stage{padding:20px}.section-heading{justify-content:space-between;margin-bottom:13px}.section-heading h2{margin:4px 0 0;font-size:18px}.section-heading small{color:#7890a5}.module-tabs{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;margin-bottom:14px}.module-tabs button{justify-content:space-between;border:1px solid #294258;border-radius:11px;background:#102235;color:#eef7ff;padding:11px 13px;cursor:pointer}.module-tabs span{color:#79a8b8;font-size:10px}.metric-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(235px,1fr));gap:12px}.data-empty{min-height:240px;border:1px dashed #2a455d;border-radius:16px;display:grid;place-content:center;text-align:center;gap:7px;color:#8ca4b8}.data-empty strong{color:#dfeaf4}.ledger{margin-top:20px}.ledger article{gap:12px;padding:13px 4px;border-top:1px solid #1b3042;font-size:12px}.ledger i{width:7px;height:7px;border-radius:50%;background:#edb568}.ledger i.ready{background:#5ed5bd;box-shadow:0 0 12px #5ed5bd}.ledger article span{flex:1;color:#91a6b9}.ledger button{border:0;background:none;color:#70d8cd;cursor:pointer}.agent-panel{display:flex;flex-direction:column;min-height:690px;overflow:hidden}.agent-head{gap:11px;padding:18px;border-bottom:1px solid #1d3447}.agent-head div:nth-child(2){display:grid;gap:3px}.agent-head span{font-size:10px;color:#829bad}.agent-head strong{font-size:16px}.agent-head em{margin-left:auto;color:#66d9cf;font-size:10px;font-style:normal}.agent-orb{width:34px;height:34px;border-radius:50%;background:radial-gradient(circle at 35% 30%,#d5fff8 0 8%,#42d6c2 17%,#146a7d 55%,#0c2438 70%);box-shadow:0 0 22px #4bdcca70;animation:pulse 2.6s ease-in-out infinite}.messages{flex:1;max-height:410px;overflow:auto;padding:18px;display:flex;flex-direction:column;gap:12px}.message{max-width:90%;padding:11px 13px;border-radius:14px;background:#122638}.message.user{align-self:flex-end;background:#1b665e}.message small{color:#70d8cd;font-size:9px}.message p{margin:5px 0 0;font-size:12px;line-height:1.65}.guides{padding:0 15px 10px;display:flex;gap:6px;flex-wrap:wrap}.guides button{border:1px solid #29465d;border-radius:999px;background:#0d2030;color:#a9bfd0;padding:7px 9px;font-size:10px;cursor:pointer}.composer{margin:0 14px;position:relative}.composer textarea{box-sizing:border-box;width:100%;resize:none;border:1px solid #315068;border-radius:14px;background:#07131e;color:#f0f8ff;padding:12px 92px 12px 12px}.composer button{position:absolute;right:8px;bottom:9px;border:0;border-radius:9px;background:#2a9b88;color:#fff;padding:8px 10px;cursor:pointer}.agent-note{margin:8px 16px 14px;color:#607b90;font-size:9px;line-height:1.5}@keyframes pulse{50%{transform:scale(1.07);box-shadow:0 0 34px #4bdcca99}}@media(prefers-reduced-motion:reduce){.agent-orb{animation:none}}@media(max-width:1080px){.operations-grid{grid-template-columns:1fr}.agent-panel{min-height:560px}.messages{max-height:300px}}@media(max-width:720px){.cockpit-shell{padding:12px}.command-bar{align-items:flex-start;flex-direction:column}.command-controls{flex-wrap:wrap}.pulse-strip{grid-template-columns:repeat(2,1fr)}.pulse-strip div:first-child{grid-column:1/-1}.metric-grid{grid-template-columns:1fr}}
</style>
