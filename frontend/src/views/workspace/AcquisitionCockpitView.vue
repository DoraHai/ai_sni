<script setup>
import { computed, nextTick, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import MetricEvidenceCard from './cockpit/MetricEvidenceCard.vue'
import ElementsWaterBackground from './cockpit/elements/ElementsWaterBackground.vue'
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
import { appendExplorationPath, compareMetricScope, moveExplorationPath, saveMetricScope } from './cockpit/exploration-state.mjs'
import { semImpressionClickFunnel, semTrendVisualization, seoContentDistribution } from './cockpit/visualization-model.mjs'

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
const explorationHistory = ref([])
const explorationIndex = ref(-1)
const savedMetricScope = ref(null)
const metricComparison = ref(null)
const waterBackgroundRef = ref(null)
const dashboardMode = ref('overview')
const aiState = ref('idle')
const focusQuestion = ref('')
const focusRevision = ref(0)
const initialConversation = () => [
  { role: 'assistant', text: '我会先说明数据是否完整，再帮你判断现在最该处理什么。你可以直接问，也可以从下面的问题开始。' },
]
const conversation = ref(initialConversation())
const moduleState = ref({ sem: 'waiting', seo: 'waiting', geo: 'waiting' })
const tenantModuleCodes = ref(new Set())
const selectableTenants = ref([])
const seoSites = ref([])
const seoSiteSelectionGuard = createSeoSiteSelectionGuard()
const localPreview = import.meta.env.DEV && ['localhost', '127.0.0.1', '::1'].includes(window.location.hostname)
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
const businessGroups = computed(() => cardGroups.value.map(group => ({
  ...group,
  businessCards: buildBusinessCards(group.id),
})))
const aiFocusActive = computed(() => dashboardMode.value !== 'overview' || ['thinking', 'assembling'].includes(aiState.value))
const canGoBack = computed(() => explorationIndex.value > 0)
const canGoForward = computed(() => explorationIndex.value >= 0 && explorationIndex.value < explorationHistory.value.length - 1)
const currentPathLabel = computed(() => {
  const metric = selectedMetric.value?.label || '模块总览'
  const module = activeModule.value === 'all' ? '全域' : (moduleMeta[activeModule.value]?.label || activeModule.value.toUpperCase())
  const showsSeoSite = activeModule.value === 'seo' || selectedMetric.value?.moduleCode === 'seo'
  const site = showsSeoSite ? seoSites.value.find(item => Number(item.id) === Number(currentSeoSiteId.value)) : null
  return `${module} / ${metric}${showsSeoSite ? ` / ${site?.name || '未选网站'}` : ''} / ${dateStart.value} 至 ${dateEnd.value}`
})
const readProgress = computed(() => {
  return readCompletionProgress({ availableCount: availableModules.value.length, completedCount: readyModules.value })
})
const partialEvidence = computed(() => cards.value.filter(item => ['partial', 'no_data', 'unavailable'].includes(item.state)).length)
const boundaryItems = computed(() => evidenceBoundaryCount({ unresolvedModules: unresolvedModules.value, cards: cards.value }))
const analysisModules = computed(() => availableModules.value.map(item => ({
  code: item.module_code,
  label: moduleMeta[item.module_code]?.label || item.module_code.toUpperCase(),
  status: statusLabel(moduleState.value[item.module_code]),
  ready: moduleState.value[item.module_code] === 'ready',
})))
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
  '哪里出现异常？',
  availableModules.value.some(item => item.module_code === 'geo') ? '只看 GEO' : null,
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
  recordExplorationPath('date')
  if (!changed) loadAll()
}
function applyDatePeriod() {
  if (!draftPeriodValid.value) return
  const changed = dateStart.value !== draftDateStart.value || dateEnd.value !== draftDateEnd.value
  dateStart.value = draftDateStart.value
  dateEnd.value = draftDateEnd.value
  recordExplorationPath('date')
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
function outcomeHeadline(card) {
  if (!card) return '经营信号待确认'
  const label = card.label || ''
  if (card.moduleCode === 'sem') return /点击|流量/.test(label) ? 'SEM 流量持续增长' : 'SEM 投放信号稳定'
  if (card.moduleCode === 'seo') return /内容|发布/.test(label) ? 'SEO 内容资产继续积累' : 'SEO 页面资产持续完善'
  if (card.moduleCode === 'geo') return /品牌|提及|可见/.test(label) ? 'GEO 品牌可见度改善' : 'GEO AI 触达信号可核对'
  return `${card.moduleLabel || '全域'} ${label}`
}
function outcomeEvidence(card) {
  if (!card) return '等待更多数据进入核验范围'
  const value = card.display ?? '—'
  const label = card.label || '指标'
  const change = card.changeLabel ? `，${card.changeLabel.replace(/^([↑↓]\s*)/, '')}` : ''
  if (card.moduleCode === 'sem' && /点击/.test(label)) return `点击 ${value}${change}`
  if (card.moduleCode === 'sem' && /展现/.test(label)) return `展现 ${value}${change}`
  if (card.moduleCode === 'seo' && /内容|发布/.test(label)) return `当前已发布 ${value}`
  if (card.moduleCode === 'seo' && /页面/.test(label)) return `有效收录页面 ${value}`
  if (card.moduleCode === 'geo' && /品牌|提及/.test(label)) return `品牌提及率 ${value}${change}`
  if (card.moduleCode === 'geo' && /可见/.test(label)) return `AI 可见度 ${value}${change}`
  return `${label} ${value}${change}`
}
function cardMatches(card, pattern) {
  return pattern.test(card?.label || '')
}
function findModuleCard(moduleCode, pattern) {
  return filteredCards.value.find(card => card.moduleCode === moduleCode && cardMatches(card, pattern))
}
function findAnyModuleCard(moduleCode, pattern) {
  return cards.value.find(card => card.moduleCode === moduleCode && cardMatches(card, pattern))
}
function moduleCards(moduleCode) {
  return filteredCards.value.filter(card => card.moduleCode === moduleCode)
}
function allModuleCards(moduleCode) {
  return cards.value.filter(card => card.moduleCode === moduleCode)
}
function changeValue(card) {
  const text = String(card?.changeLabel || '')
  const match = text.match(/([+-]?\d+(?:\.\d+)?)%/)
  if (!match) return null
  const value = Number(match[1])
  if (!Number.isFinite(value)) return null
  return text.includes('↓') ? -Math.abs(value) : value
}
function cleanChange(card) {
  return String(card?.changeLabel || '').replace(/\s*较上周期\s*$/, '').replace(/^↑\s*/, '↑ ').replace(/^↓\s*/, '↓ ')
}
function aggregateStatus(items) {
  if (items.some(card => ['partial', 'no_data', 'unavailable', 'denied'].includes(card.state))) return '部分数据'
  if (items.some(card => card.state === 'loading')) return '读取中'
  return '数据已读取'
}
function metricItem(card, fallbackLabel = '') {
  return {
    id: card?.id || '',
    label: fallbackLabel || card?.label || '指标',
    value: card?.display ?? '—',
    change: card?.changeLabel ? cleanChange(card) : '',
  }
}
function focusMetricItem(card, fallbackLabel = '', tone = 'blue') {
  const item = metricItem(card, fallbackLabel)
  return { ...item, tone, changeValue: changeValue(card), raw: card }
}
function semBusinessStatement(impression, click, cost) {
  const impressionChange = changeValue(impression)
  const clickChange = changeValue(click)
  const costChange = changeValue(cost)
  if ([impressionChange, clickChange, costChange].every(value => Number.isFinite(value))) {
    if (clickChange > impressionChange && costChange > clickChange) return '流量规模持续扩大，点击增长快于曝光，但消耗同步上升。'
    if (clickChange > impressionChange) return '点击增长快于曝光，流量质量值得继续核对。'
    if (costChange > clickChange) return '消耗增长快于点击，需要核对投放效率。'
  }
  return '投放数据已读取，可继续核对流量规模、点击和消耗之间的关系。'
}
function semInsight(impression, click, cost, cpc) {
  const impressionChange = changeValue(impression)
  const clickChange = changeValue(click)
  const costChange = changeValue(cost)
  const cpcChange = changeValue(cpc)
  if ([impressionChange, clickChange, costChange].every(value => Number.isFinite(value)) && clickChange > impressionChange && costChange > clickChange) {
    return '点击增长快于曝光，但消耗增幅更高，建议进一步查看转化是否同步增长。'
  }
  if (Number.isFinite(cpcChange) && Math.abs(cpcChange) <= 5) return '点击成本整体保持稳定，下一步更适合核对点击后的转化质量。'
  return '当前只能确认投放侧指标变化，转化效果需要进入明细后继续核对。'
}
function seoBusinessStatement(content, indexCard, pending) {
  const hasGrowth = [changeValue(content), changeValue(indexCard)].some(value => Number.isFinite(value) && value > 0)
  if (hasGrowth && pending) return '内容资产持续积累，但仍有页面需要处理。'
  if (hasGrowth) return '内容资产和收录信号正在积累。'
  return 'SEO 数据已读取，可从内容资产、收录和页面问题继续核对。'
}
function seoInsight(content, indexCard, pending) {
  const pendingValue = pending?.display ?? null
  if (content && indexCard && pending) return `内容和收录均在增长，但 ${pendingValue} 个页面仍存在待处理项。`
  if (content && indexCard) return '内容产出和收录有可核对数据，建议继续检查页面质量。'
  return '当前 SEO 结论只基于已读取的内容、收录和页面状态。'
}
function geoBusinessStatement(mention, visibility, boundary) {
  const mentionChange = changeValue(mention)
  const visibilityChange = changeValue(visibility)
  const improving = [mentionChange, visibilityChange].some(value => Number.isFinite(value) && value > 0)
  if (improving && boundary) return '品牌可见度正在改善，但部分数据边界仍需核对。'
  if (improving) return '品牌可见度正在改善，可继续查看引用证据。'
  return 'GEO 品牌数据已读取，可继续核对提及率、可见度和数据完整性。'
}
function geoInsight(mention, visibility, boundary) {
  if (mention && visibility && boundary) return '品牌信号已有可核对结果，但数据完整性会影响最终判断，需要优先补齐边界。'
  if (mention || visibility) return '当前只基于已读取的 AI 可见度与品牌提及数据给出判断。'
  return 'GEO 结论需要更多已核验数据支撑。'
}
function buildSemBusinessCard() {
  const items = moduleCards('sem')
  if (!items.length) return null
  const impression = findModuleCard('sem', /展现|曝光/)
  const click = findModuleCard('sem', /点击量|广告点击|点击/)
  const cost = findModuleCard('sem', /消耗|花费/)
  const cpc = findModuleCard('sem', /CPC|点击价格/)
  const primary = click || impression || items[0]
  return {
    id: 'business-sem-performance',
    moduleCode: 'sem',
    title: 'SEM · 投放表现',
    status: aggregateStatus(items),
    statement: semBusinessStatement(impression, click, cost),
    metrics: [metricItem(impression, '广告展现'), metricItem(click, '广告点击'), metricItem(cost, '广告消耗')].filter(item => item.id),
    support: cpc ? { label: '平均 CPC', value: cpc.display ?? '—', change: cleanChange(cpc), note: Math.abs(changeValue(cpc) || 0) <= 5 ? '点击成本整体保持稳定' : '点击成本变化需要继续核对' } : null,
    insight: semInsight(impression, click, cost, cpc),
    actions: [
      primary ? { label: '查看 SEM 详情 →', target: primary.id } : null,
      primary ? { label: '讨论这项 →', discuss: true, target: primary.id } : null,
    ].filter(Boolean),
    metricIds: items.map(card => card.id),
  }
}
function buildSeoBusinessCard() {
  const items = moduleCards('seo')
  if (!items.length) return null
  const content = findModuleCard('seo', /内容|发布/)
  const indexCard = findModuleCard('seo', /收录/)
  const pending = findModuleCard('seo', /待处理|页面/)
  const primary = pending || content || indexCard || items[0]
  return {
    id: 'business-seo-content',
    moduleCode: 'seo',
    title: 'SEO · 内容表现',
    status: aggregateStatus(items),
    statement: seoBusinessStatement(content, indexCard, pending),
    metrics: [metricItem(content, '已发布内容'), metricItem(indexCard, '新增收录'), metricItem(pending, '待处理页面')].filter(item => item.id),
    insight: seoInsight(content, indexCard, pending),
    actions: [
      primary ? { label: pending ? '查看待处理页面 →' : '查看 SEO 详情 →', target: primary.id } : null,
    ].filter(Boolean),
    metricIds: items.map(card => card.id),
  }
}
function buildGeoBusinessCard() {
  const items = moduleCards('geo')
  if (!items.length) return null
  const mention = findModuleCard('geo', /品牌|提及/)
  const visibility = findModuleCard('geo', /可见/)
  const boundary = items.find(card => ['partial', 'no_data', 'unavailable', 'denied'].includes(card.state))
  const primary = mention || visibility || boundary || items[0]
  return {
    id: 'business-geo-brand',
    moduleCode: 'geo',
    title: 'GEO · 品牌表现',
    status: aggregateStatus(items),
    statement: geoBusinessStatement(mention, visibility, boundary),
    metrics: [metricItem(mention, '品牌提及率'), metricItem(visibility, 'AI 可见度'), boundary ? metricItem(boundary, '数据边界') : null].filter(Boolean).filter(item => item.id),
    insightLabel: '数据状态',
    insight: geoInsight(mention, visibility, boundary),
    statusRows: items.slice(0, 3).map(card => ({ label: card.label, status: statusLabel(card.state) })),
    actions: [
      primary ? { label: '查看引用证据 →', target: primary.id } : null,
    ].filter(Boolean),
    metricIds: items.map(card => card.id),
  }
}
function buildBusinessCards(groupId) {
  if (groupId === 'performance') return [buildSemBusinessCard()].filter(Boolean)
  if (groupId === 'presence') return [buildSeoBusinessCard(), buildGeoBusinessCard()].filter(Boolean)
  return []
}
const semFocus = computed(() => {
  const impression = findAnyModuleCard('sem', /展现|曝光/)
  const click = findAnyModuleCard('sem', /点击量|广告点击|点击/)
  const cost = findAnyModuleCard('sem', /消耗|花费/)
  const cpc = findAnyModuleCard('sem', /CPC|点击价格/)
  return {
    title: 'SEM 本周投放表现',
    statement: semBusinessStatement(impression, click, cost),
    insight: semInsight(impression, click, cost, cpc),
    nodes: [
      focusMetricItem(impression, '广告展现', 'cyan'),
      focusMetricItem(click, '广告点击', 'blue'),
      focusMetricItem(cost, '广告消耗', 'amber'),
      focusMetricItem(cpc, '平均 CPC', 'violet'),
    ].filter(item => item.id),
  }
})
const geoFocus = computed(() => {
  const mention = findAnyModuleCard('geo', /品牌|提及/)
  const visibility = findAnyModuleCard('geo', /可见/)
  const boundary = allModuleCards('geo').find(card => ['partial', 'no_data', 'unavailable', 'denied'].includes(card.state))
  const supporting = allModuleCards('geo').filter(card => ![mention?.id, visibility?.id, boundary?.id].includes(card.id)).slice(0, 3)
  return {
    title: 'GEO AI 品牌可见性',
    statement: geoBusinessStatement(mention, visibility, boundary),
    insight: geoInsight(mention, visibility, boundary),
    core: focusMetricItem(mention || visibility || boundary, mention ? '品牌提及率' : '核心指标', 'violet'),
    nodes: [
      focusMetricItem(visibility, 'AI 可见度', 'blue'),
      boundary ? focusMetricItem(boundary, '数据边界', 'amber') : null,
      ...supporting.map(card => focusMetricItem(card, card.label, 'cyan')),
    ].filter(item => item?.id),
  }
})
const priorityView = computed(() => {
  const seoPending = findAnyModuleCard('seo', /待处理|页面/)
  const geoBoundary = allModuleCards('geo').find(card => ['partial', 'no_data', 'unavailable', 'denied'].includes(card.state))
  const geoMention = findAnyModuleCard('geo', /品牌|提及/)
  const semCost = findAnyModuleCard('sem', /消耗|花费/)
  const semClick = findAnyModuleCard('sem', /点击量|广告点击|点击/)
  const semRisk = semCost && semClick ? {
    id: semCost.id,
    module: 'SEM',
    title: '消耗增长快于点击',
    value: `${cleanChange(semCost) || semCost.display} / ${cleanChange(semClick) || semClick.display}`,
    detail: '建议继续核对转化是否同步增长',
    tone: 'amber',
  } : null
  const geoNode = (geoBoundary || geoMention) ? {
    id: (geoBoundary || geoMention).id,
    module: 'GEO',
    title: geoBoundary ? '数据边界需要核对' : '品牌可见度需要关注',
    value: (geoBoundary || geoMention).display ?? '—',
    detail: geoBoundary ? attentionCopy(geoBoundary) : outcomeEvidence(geoMention),
    tone: 'violet',
  } : null
  const seoNode = seoPending ? {
    id: seoPending.id,
    module: 'SEO',
    title: `${seoPending.display ?? seoPending.urgentCount ?? '—'} 个页面需要处理`,
    value: Number(seoPending.urgentCount) > 0 ? `优先级 ${seoPending.urgentCount}` : (seoPending.display ?? '待核对'),
    detail: attentionCopy(seoPending),
    tone: 'blue',
  } : null
  const nodes = [geoNode, seoNode, semRisk].filter(Boolean).slice(0, 3)
  return {
    count: String(nodes.length).padStart(2, '0'),
    judgement: nodes[0] ? `${nodes[0].module} 是当前最值得优先处理的方向。` : '当前没有系统已识别的紧急事项。',
    nodes,
  }
})
function runBusinessAction(action) {
  if (!action?.target) return
  if (action.discuss) discuss({ metricId: action.target, contextRevision: viewState.revision })
  else focusMetric(action.target, 'business-card')
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
  const visualization = key === 'impression'
    ? semImpressionClickFunnel(report, shown.text, semMetric(report.metrics.click, 'count', report.coverage).text)
    : semTrendVisualization(report, key, point)
  return {
    id: `sem-${key}`, moduleCode: 'sem', moduleLabel: 'SEM', label, display: shown.text, unit: '', state: shown.state === 'coverage_unknown' ? 'partial' : shown.state,
    reason: shown.note, contextRevision: viewState.revision,
    periodLabel: `${report.window.start} 至 ${report.window.end}`,
    sourceLabel: report.is_demo ? '版本化 SEM 内置演示数据' : '百度推广已有关键词报告', updatedLabel: report.coverage.updated_at || '未知',
    visualization,
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
function previewTrend(values, unit = '') {
  return values.map((value, index) => ({
    key: shiftDate(dateEnd.value, index - values.length + 1),
    label: shiftDate(dateEnd.value, index - values.length + 1).slice(5),
    value,
    display: `${unit}${Number(value).toLocaleString('zh-CN')}`,
  }))
}
function previewChange(values, suffix = '') {
  if (!values.length) return ''
  const first = Number(values[0])
  const last = Number(values[values.length - 1])
  if (!Number.isFinite(first) || !Number.isFinite(last) || first === 0) return ''
  const ratio = (last - first) / first * 100
  return `${ratio >= 0 ? '↑ +' : '↓ '}${Math.abs(ratio).toFixed(1)}%${suffix}`
}
function previewVisualization(values) {
  if (!values.length) return null
  return {
    type: 'trend',
    state: 'available',
    points: previewTrend(values),
    coverage: { state: 'covered', missingCount: 0, label: '近 7 天' },
  }
}
function previewCard({ id, moduleCode, label, display, state = 'available', urgentCount = 0, summaryRole = null, values = [], reason = '', sourceLabel = '本地预览数据', changeLabel = null }) {
  return {
    id,
    moduleCode,
    moduleLabel: moduleMeta[moduleCode]?.label || moduleCode.toUpperCase(),
    label,
    display,
    unit: '',
    state,
    urgentCount,
    reason,
    summaryRole,
    contextRevision: viewState.revision,
    periodLabel: `${dateStart.value} 至 ${dateEnd.value}`,
    sourceLabel,
    updatedLabel: '本地预览',
    visualization: previewVisualization(values),
    changeLabel: changeLabel ?? previewChange(values, ' 较上周期'),
    series: previewTrend(values),
    columns: [{ key: 'date', label: '日期' }, { key: 'value', label }],
    rows: previewTrend(values).map(row => ({ date: row.label, value: row.display })),
  }
}
function localPreviewCards() {
  return [
    previewCard({ id: 'sem-impression-preview', moduleCode: 'sem', label: '广告展现量', display: '128,420', summaryRole: 'outcome', values: [92200, 98100, 106400, 112800, 119300, 124900, 128420], reason: '近 7 天曝光持续走高，适合继续观察点击转化是否同步。' }),
    previewCard({ id: 'sem-click-preview', moduleCode: 'sem', label: '广告点击量', display: '6,821', summaryRole: 'outcome', values: [4720, 5020, 5310, 5860, 6110, 6260, 6821], reason: '点击较上周期提升 8.2%，需核对高点击词的转化质量。' }),
    previewCard({ id: 'sem-cost-preview', moduleCode: 'sem', label: '广告消耗', display: '¥12,840', values: [8600, 9100, 9780, 10420, 11210, 11880, 12840], reason: '消耗跟随点击上升，建议检查无效搜索词。' }),
    previewCard({ id: 'sem-cpc-preview', moduleCode: 'sem', label: '平均点击价格 (CPC)', display: '¥1.88', values: [1.81, 1.82, 1.85, 1.86, 1.83, 1.89, 1.88], reason: '均价稳定，当前重点在转化线索质量。' }),
    previewCard({ id: 'seo-content-preview', moduleCode: 'seo', label: '已发布内容', display: '86 篇', summaryRole: 'outcome', values: [64, 67, 70, 74, 78, 82, 86], reason: '内容产出正常，下一步看收录和页面健康度。' }),
    previewCard({ id: 'seo-index-preview', moduleCode: 'seo', label: 'SEO 新增收录', display: '26', summaryRole: 'outcome', values: [8, 10, 12, 15, 19, 22, 26], reason: '收录增长 18.2%，可继续追踪对应页面的搜索曝光。' }),
    previewCard({ id: 'seo-pending-preview', moduleCode: 'seo', label: 'SEO 页面待处理', display: '5', state: 'partial', urgentCount: 2, values: [7, 7, 6, 6, 5, 5, 5], reason: '其中 2 项属于优先处理页面，建议先进入 SEO 站内优化核对。' }),
    previewCard({ id: 'geo-mention-preview', moduleCode: 'geo', label: 'GEO 品牌提及率', display: '38.6%', summaryRole: 'outcome', values: [34.2, 35.1, 36.6, 37.4, 36.9, 38.1, 38.6], reason: '品牌在 AI 回答中的提及率较上周期提升 5.1%。' }),
    previewCard({ id: 'geo-visibility-preview', moduleCode: 'geo', label: 'AI 可见度', display: '35', summaryRole: 'outcome', values: [28, 29, 30, 32, 33, 34, 35], reason: '可见度稳步上升，可继续补充可被引用的内容证据。' }),
    previewCard({ id: 'geo-data-preview', moduleCode: 'geo', label: 'GEO 数据未完整读取', display: '2', state: 'partial', urgentCount: 1, values: [3, 3, 2, 2, 2, 2, 2], reason: '涉及 1 个数据源，正式环境需完成授权或补齐采集范围。' }),
  ]
}
function applyLocalPreviewData() {
  const previewModules = [
    { module_code: 'sem', available: true },
    { module_code: 'seo', available: true },
    { module_code: 'geo', available: true },
  ]
  const previewTenants = [{ id: 1, name: '本地预览客户' }]
  session.setModules(previewModules)
  session.setTenants(previewTenants)
  session.setTenant(1)
  selectableTenants.value = previewTenants
  seoSites.value = [{ id: 1, name: '演示网站', domain: 'www.example.com', status: 'active' }]
  if (!currentSeoSiteId.value) currentSeoSiteId.value = 1
  tenantModuleCodes.value = new Set(['sem', 'seo', 'geo'])
  moduleState.value = { sem: 'ready', seo: 'ready', geo: 'ready' }
  cards.value = localPreviewCards()
  activeSection.value = 'dashboard'
  lastReadAt.value = new Date()
  loading.value = false
  conversation.value = [
    { role: 'assistant', text: '你好！我是你的 AI 数据分析助手。我可以分析 SEM、SEO、GEO 的数据，发现问题，识别机会，并给出可执行建议。' },
  ]
}
function forwardWaterPointer(event, options = {}) {
  waterBackgroundRef.value?.postPointer?.(event, options)
}
function pulseWaterAtElement(element) {
  if (!element) return
  const rect = element.getBoundingClientRect()
  const point = { clientX: rect.left + rect.width / 2, clientY: rect.top + Math.min(rect.height * 0.46, 180) }
  waterBackgroundRef.value?.postPointer?.(point, { down: true, pulse: true })
  window.setTimeout(() => waterBackgroundRef.value?.postPointer?.(point, { down: true, pulse: true }), 130)
}
function pulseWaterAtStage() {
  const stage = document.querySelector('.data-stage')
  if (!stage) return
  const rect = stage.getBoundingClientRect()
  waterBackgroundRef.value?.postPointer?.({
    clientX: rect.left + rect.width * 0.58,
    clientY: rect.top + rect.height * 0.42,
  }, { down: true, pulse: true })
}
const delay = ms => new Promise(resolve => window.setTimeout(resolve, ms))
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
    for (const card of seoSummaryCards({ contents, pages, contextRevision: viewState.revision })) {
      publishCard(card.id === 'seo-contents' && contents
        ? { ...card, visualization: seoContentDistribution(contents) }
        : card)
    }
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
  if (localPreview && !session.isLoggedIn) {
    applyLocalPreviewData()
    return
  }
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
  if (localPreview && !session.isLoggedIn) {
    applyLocalPreviewData()
    return
  }
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
    drawer_metric_id: highlighted[0]?.id || null, actions: defaultCommandActions(),
  }
}
function inferDashboardMode(text = '', command = {}) {
  const upper = String(text).toUpperCase()
  if (/只看\s*GEO|GEO/.test(upper)) return 'geo-focus'
  if (/SEM|投放|点击|消耗|CPC/.test(upper)) return 'sem-focus'
  if (/今天|关注|异常|优先|处理|最需要/.test(text)) return 'priority'
  if (command?.focus_module === 'geo') return 'geo-focus'
  if (command?.focus_module === 'sem') return 'sem-focus'
  return 'priority'
}
function startDashboardAnalysis(text) {
  focusQuestion.value = text
  dashboardMode.value = 'analysis'
  aiState.value = 'thinking'
  highlightedMetricIds.value = []
  nextTick(pulseWaterAtStage)
}
async function orchestrateDashboard(text, command) {
  const mode = inferDashboardMode(text, command)
  dashboardMode.value = mode
  aiState.value = 'assembling'
  focusRevision.value += 1
  await nextTick()
  pulseWaterAtStage()
  await delay(680)
  aiState.value = 'ready'
}
async function returnOverview() {
  aiState.value = 'assembling'
  highlightedMetricIds.value = []
  activeModule.value = 'all'
  focusQuestion.value = ''
  pulseWaterAtStage()
  await delay(420)
  dashboardMode.value = 'overview'
  aiState.value = 'idle'
}
function preferredCard(moduleCode, matcher = /./, fallbackUrgent = false) {
  return cards.value.find(card => card.moduleCode === moduleCode && matcher.test(card.label || ''))
    || (fallbackUrgent ? cards.value.find(card => card.moduleCode === moduleCode && Number(card.urgentCount) > 0) : null)
    || cards.value.find(card => card.moduleCode === moduleCode)
}
function defaultCommandActions() {
  const geo = preferredCard('geo', /品牌|提及|可见/, true)
  const seo = preferredCard('seo', /待处理|页面|内容/, true)
  const sem = preferredCard('sem', /点击|展现|花费/, false)
  return [
    geo ? { type: 'open-metric', target: geo.id, label: '定位 GEO' } : null,
    seo ? { type: 'open-metric', target: seo.id, label: '查看 SEO 待办' } : null,
    sem ? { type: 'open-metric', target: sem.id, label: '查看 SEM' } : null,
  ].filter(Boolean)
}
function recordExplorationPath(source = 'user') {
  const next = appendExplorationPath(explorationHistory.value, explorationIndex.value, {
    metricId: selectedMetricId.value, moduleCode: activeModule.value,
    dateStart: dateStart.value, dateEnd: dateEnd.value, seoSiteId: currentSeoSiteId.value, source,
  })
  explorationHistory.value = next.history
  explorationIndex.value = next.index
}
function chooseModule(code, source = 'user') {
  activeSection.value = 'dashboard'
  if (source === 'user') {
    dashboardMode.value = 'overview'
    aiState.value = 'idle'
    focusQuestion.value = ''
  }
  activeModule.value = code
  selectedMetricId.value = null
  highlightedMetricIds.value = []
  recordExplorationPath(source)
}
function navigateExploration(direction) {
  const next = moveExplorationPath(explorationHistory.value, explorationIndex.value, direction)
  if (!next.path || next.index === explorationIndex.value) return
  explorationIndex.value = next.index
  activeSection.value = 'dashboard'
  activeModule.value = next.path.moduleCode
  dateStart.value = next.path.dateStart
  dateEnd.value = next.path.dateEnd
  draftDateStart.value = next.path.dateStart
  draftDateEnd.value = next.path.dateEnd
  if (next.path.seoSiteId) seoSiteSelectionGuard.confirmExplicitSelection(session.tenantId)
  else seoSiteSelectionGuard.blockAutomaticSelection(session.tenantId)
  currentSeoSiteId.value = next.path.seoSiteId
  selectedMetricId.value = next.path.metricId
  highlightedMetricIds.value = next.path.metricId ? [next.path.metricId] : []
  metricComparison.value = null
}
function saveCurrentMetricScope() {
  savedMetricScope.value = saveMetricScope(selectedMetric.value, {
    tenantId: session.tenantId, dateStart: dateStart.value, dateEnd: dateEnd.value, seoSiteId: currentSeoSiteId.value,
  })
  metricComparison.value = null
}
function compareWithSavedScope() {
  metricComparison.value = compareMetricScope(selectedMetric.value, savedMetricScope.value, { tenantId: session.tenantId, seoSiteId: currentSeoSiteId.value })
}
function applyScreenCommand(command) {
  if (!command) command = localScreenCommand('')
  const allowedModules = new Set(['all', ...availableModules.value.map(item => item.module_code)])
  const allowedIds = new Set(cards.value.map(item => item.id))
  if (!Array.isArray(command.actions) || !command.actions.length) command.actions = defaultCommandActions()
  activeSection.value = 'dashboard'
  activeModule.value = allowedModules.has(command?.focus_module) ? command.focus_module : 'all'
  highlightedMetricIds.value = (command?.highlight?.ids || []).filter(id => allowedIds.has(id)).slice(0, 12)
  selectedMetricId.value = allowedIds.has(command?.drawer_metric_id) ? command.drawer_metric_id : null
  metricComparison.value = null
  recordExplorationPath('ai')
}
async function focusMetric(metricId, source = 'user') {
  if (!cards.value.some(item => item.id === metricId)) return
  selectedMetricId.value = metricId
  highlightedMetricIds.value = [metricId]
  const card = cards.value.find(item => item.id === metricId)
  if (card?.moduleCode) activeModule.value = card.moduleCode
  metricComparison.value = null
  recordExplorationPath(source)
  await nextTick()
  const metricEl = Array.from(document.querySelectorAll('[data-metric-id], [data-metric-ids]')).find(element => {
    if (element.dataset.metricId === metricId) return true
    return String(element.dataset.metricIds || '').split(/\s+/).includes(metricId)
  })
  metricEl?.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' })
  pulseWaterAtElement(metricEl)
  window.setTimeout(() => {
    if (highlightedMetricIds.value.length === 1 && highlightedMetricIds.value[0] === metricId) highlightedMetricIds.value = []
  }, 3000)
}
function scrollToSection(id) {
  document.getElementById(`cockpit-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
function runScreenAction(action) {
  if (!action || !['focus-module', 'open-metric', 'open-module', 'reset-view'].includes(action.type)) return
  if (action.type === 'open-metric') return focusMetric(action.target, 'ai-action')
  if (action.type === 'open-module' && availableModules.value.some(item => item.module_code === action.target)) return openModule(action.target)
  if (action.type === 'focus-module' && availableModules.value.some(item => item.module_code === action.target)) {
    chooseModule(action.target, 'ai-action'); return
  }
  if (action.type === 'reset-view') {
    chooseModule('all', 'ai-action')
  }
}
async function send(text = question.value) {
  const value = String(text || '').trim()
  if (!value || aiBusy.value) return
  conversation.value.push({ role: 'user', text: value })
  question.value = ''
  aiBusy.value = true
  startDashboardAnalysis(value)
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
  await orchestrateDashboard(value, command)
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
  recordExplorationPath('seo-site')
}
function selectTenant(event) {
  const value = Number(event.target.value)
  if (!Number.isSafeInteger(value) || value <= 0 || value === Number(session.tenantId)) return
  currentSeoSiteId.value = null
  explorationHistory.value = []
  explorationIndex.value = -1
  savedMetricScope.value = null
  metricComparison.value = null
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
  if (event.key === '1' && availableModules.value.some(item => item.module_code === 'sem')) chooseModule('sem')
  if (event.key === '2' && availableModules.value.some(item => item.module_code === 'seo')) chooseModule('seo')
  if (event.key === '3' && availableModules.value.some(item => item.module_code === 'geo')) chooseModule('geo')
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
watch(() => session.authRevision, () => {
  explorationHistory.value = []
  explorationIndex.value = -1
  savedMetricScope.value = null
  metricComparison.value = null
  recordExplorationPath('identity')
  prepare()
})
watch(() => availableModules.value.map(item => item.module_code).join(','), (codes) => {
  activeModule.value = normalizeModuleSelection(activeModule.value, codes ? codes.split(',') : [])
})
onMounted(() => {
  activeSection.value = 'dashboard'
  document.addEventListener('fullscreenchange', syncFullscreen)
  document.addEventListener('keydown', onKeydown)
  recordExplorationPath('initial')
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
    <ElementsWaterBackground ref="waterBackgroundRef" class="water-element-backdrop" :speed="0.55" :size="1.22" :particle-amount="0" :opacity="0.72" :hue="-8" :saturation="0.9" :brightness="0.76" />
    <div class="ambient ambient-a"></div><div class="ambient ambient-b"></div><div class="energy-field"></div>
    <aside class="app-rail" aria-label="全域驾驶舱主导航">
      <div class="rail-logo">W</div>
      <button class="active" type="button" aria-label="驾驶舱" @click="router.push('/workspace/cockpit')">⌂<span>驾驶舱</span></button>
      <button type="button" aria-label="SEM" @click="router.push('/monitor/dashboard')">⌕<span>SEM</span></button>
      <button type="button" aria-label="SEO" @click="router.push('/seo/dashboard')">◎<span>SEO</span></button>
      <button type="button" aria-label="GEO" @click="router.push('/geo/diagnosis')">∞<span>GEO</span></button>
      <button type="button" aria-label="欢迎页" @click="router.push('/workspace')">▤<span>欢迎页</span></button>
      <button type="button" aria-label="设置">⚙<span>设置</span></button>
    </aside>
    <header class="command-bar">
      <div class="brand-block">
        <button class="back-link" type="button" @click="router.push('/workspace')">← 功能模块</button>
        <div class="brand-line"><i class="brand-mark">W</i><div><p>用数据发现机会，让增长更确定</p><h1>全域驾驶舱</h1></div></div>
      </div>
      <div class="live-badge" :class="{ replay: demoMode }"><i></i><span>{{ demoMode ? '演示数据' : '数据状态' }}</span><b>{{ displayTime(lastReadAt) }}</b></div>
      <div class="command-controls">
        <label v-if="localPreview || selectableTenants.length > 1">客户
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

    <section class="operations-grid">
      <aside v-if="viewMode !== 'data'" class="agent-panel">
        <div class="agent-head"><div class="agent-orb"><i></i></div><div><span>{{ agentName }} · 获客数据引擎</span><strong>AI 作战指令台</strong></div><em><i></i> {{ agentStatus }}</em></div>
        <div class="context-ribbon"><span>当前关注</span><b>{{ urgentItems ? `${urgentItems} 项待处理事项` : '本周期整体获客表现' }}</b></div>
        <div v-if="conversation[0]" class="message assistant intro-message">
          <small>{{ agentName }}</small><p>{{ conversation[0].text }}</p>
        </div>
        <div class="guide-title">你可以这样问我</div>
        <div class="guides"><button v-for="item in guideQuestions" :key="item" type="button" @click="send(item)">{{ item }}</button></div>
        <div ref="messagesEl" class="messages" aria-live="polite">
          <div v-for="(item, index) in conversation.slice(1)" :key="index + 1" :class="['message', item.role]">
            <small>{{ item.role === 'assistant' ? agentName : '我' }}</small><p>{{ item.text }}</p><span v-if="item.screenCommand" class="screen-applied">已同步调整大屏</span>
            <div v-if="item.screenCommand?.actions?.length" class="message-actions"><button v-for="action in item.screenCommand.actions" :key="`${action.type}-${action.target}`" type="button" @click="runScreenAction(action)">{{ action.label }}</button></div>
          </div>
        </div>
        <form class="composer" @submit.prevent="send()"><textarea v-model="question" rows="3" placeholder="问数据、锁定风险，或直接说“只看 GEO”…"></textarea><button type="submit" :disabled="aiBusy" aria-label="发送指令">{{ aiBusy ? '…' : '↑' }}</button></form>
        <p class="agent-note"><i></i> {{ demoMode ? '当前是演示模式；回答和屏幕联动仅用于产品体验。' : '回答仅使用当前已核验数据；执行前会单独确认范围。' }}</p>
      </aside>

      <div
        v-if="viewMode !== 'chat'"
        class="data-stage"
        @pointermove="forwardWaterPointer"
        @pointerdown="event => forwardWaterPointer(event, { down: true })"
        @pointerleave="event => forwardWaterPointer(event, { leave: true })"
      >
        <div class="mission-heading">
          <div><p>ACQUISITION OVERVIEW</p><h2>全域视野，增长更确定</h2><span>整合 SEM、SEO 与 GEO，发现机会，解决问题，让每一次投入都有回报。</span></div>
          <div class="stage-actions"><button type="button" @click="compactCards = !compactCards">{{ compactCards ? '展开卡片' : '收拢卡片' }}</button><button type="button" @click="setViewMode('data')">专注大盘 ↗</button></div>
        </div>

        <nav class="exploration-path" aria-label="当前查看路径">
          <button type="button" :disabled="!canGoBack" aria-label="返回上一查看路径" @click="navigateExploration(-1)">←</button>
          <button type="button" :disabled="!canGoForward" aria-label="前往下一查看路径" @click="navigateExploration(1)">→</button>
          <span><small>当前查看路径</small><b>{{ currentPathLabel }}</b></span>
        </nav>

        <div v-if="activeSection === 'dashboard'" class="module-tabs" role="tablist" aria-label="指标模块筛选">
          <button :class="{ active: activeModule === 'all' }" type="button" role="tab" :aria-selected="activeModule === 'all'" @click="chooseModule('all')"><span>全域</span><b>{{ cards.length }}</b><small>全部数据</small></button>
          <button v-for="item in availableModules" :key="item.module_code" :class="[{ active: activeModule === item.module_code }, `module-${item.module_code}`]" type="button" role="tab" :aria-selected="activeModule === item.module_code" @click="chooseModule(item.module_code)">
            <span>{{ moduleMeta[item.module_code].label }}</span><b>{{ cards.filter(card => card.moduleCode === item.module_code).length }}</b><small>{{ moduleStatusLabel(item.module_code) }}</small>
          </button>
        </div>

        <section
          v-if="activeSection === 'dashboard' && aiFocusActive"
          :key="`${dashboardMode}-${focusRevision}`"
          class="dynamic-canvas"
          :class="[`mode-${dashboardMode}`, `state-${aiState}`]"
          aria-live="polite"
        >
          <header class="dynamic-topline">
            <div>
              <small>AI DYNAMIC DATA CANVAS</small>
              <h3 v-if="aiState === 'thinking'">正在分析当前获客数据</h3>
              <h3 v-else-if="dashboardMode === 'priority'">今日值得关注</h3>
              <h3 v-else-if="dashboardMode === 'sem-focus'">{{ semFocus.title }}</h3>
              <h3 v-else-if="dashboardMode === 'geo-focus'">{{ geoFocus.title }}</h3>
              <h3 v-else>正在组织数据视图</h3>
              <p>{{ focusQuestion || 'AI 会根据问题重组右侧数据。' }}</p>
            </div>
            <button type="button" @click="returnOverview">返回全域</button>
          </header>

          <div v-if="aiState === 'thinking'" class="analysis-state">
            <div class="analysis-radar" aria-hidden="true"><i></i><i></i><i></i></div>
            <div>
              <b>扫描 SEM / SEO / GEO 当前范围</b>
              <p>正在识别可用数据、待处理项与业务关联。</p>
            </div>
            <div class="analysis-modules">
              <span v-for="item in analysisModules" :key="item.code" :class="{ ready: item.ready }">
                {{ item.label }} <em>{{ item.status }}</em>
              </span>
            </div>
          </div>

          <div v-else-if="dashboardMode === 'priority'" class="priority-view">
            <article class="priority-judgement">
              <small>AI PRIORITY</small>
              <strong>{{ priorityView.count }}</strong>
              <p>{{ priorityView.judgement }}</p>
            </article>
            <div class="priority-node-list">
              <button
                v-for="(node, index) in priorityView.nodes"
                :key="node.id"
                type="button"
                class="priority-node"
                :class="`tone-${node.tone}`"
                :data-metric-id="node.id"
                :style="{ '--delay': `${index * 110}ms` }"
                @click="focusMetric(node.id, 'ai-focus')"
              >
                <em>0{{ index + 1 }}</em>
                <small>{{ node.module }}</small>
                <strong>{{ node.title }}</strong>
                <b>{{ node.value }}</b>
                <span>{{ node.detail }}</span>
              </button>
            </div>
          </div>

          <div v-else-if="dashboardMode === 'sem-focus'" class="relationship-view sem-relationship">
            <p class="focus-statement">{{ semFocus.statement }}</p>
            <div class="sem-node-map">
              <div class="node-center">
                <b>SEM</b>
                <span>本周投放表现</span>
              </div>
              <button
                v-for="(node, index) in semFocus.nodes"
                :key="node.id"
                type="button"
                class="data-node"
                :class="[`node-${index + 1}`, `tone-${node.tone}`]"
                :data-metric-id="node.id"
                :style="{ '--delay': `${index * 120}ms` }"
                @click="focusMetric(node.id, 'ai-focus')"
              >
                <small>{{ node.label }}</small>
                <strong>{{ node.value }}</strong>
                <em v-if="node.changeValue">{{ node.changeValue }}</em>
              </button>
            </div>
            <aside class="focus-insight"><b>AI 判断</b><p>{{ semFocus.insight }}</p></aside>
          </div>

          <div v-else-if="dashboardMode === 'geo-focus'" class="relationship-view geo-relationship">
            <p class="focus-statement">{{ geoFocus.statement }}</p>
            <div class="geo-constellation">
              <button v-if="geoFocus.core.id" type="button" class="geo-core" :data-metric-id="geoFocus.core.id" @click="focusMetric(geoFocus.core.id, 'ai-focus')">
                <small>{{ geoFocus.core.label }}</small>
                <strong>{{ geoFocus.core.value }}</strong>
                <em v-if="geoFocus.core.changeValue">{{ geoFocus.core.changeValue }}</em>
              </button>
              <button
                v-for="(node, index) in geoFocus.nodes"
                :key="node.id"
                type="button"
                class="data-node geo-node"
                :class="[`geo-node-${index + 1}`, `tone-${node.tone}`]"
                :data-metric-id="node.id"
                :style="{ '--delay': `${index * 120}ms` }"
                @click="focusMetric(node.id, 'ai-focus')"
              >
                <small>{{ node.label }}</small>
                <strong>{{ node.value }}</strong>
                <em v-if="node.changeValue">{{ node.changeValue }}</em>
              </button>
            </div>
            <aside class="focus-insight"><b>AI 判断</b><p>{{ geoFocus.insight }}</p></aside>
          </div>
        </section>

        <template v-else-if="activeSection === 'dashboard'">
          <div v-if="filteredCards.length" class="panorama-content" role="tabpanel" :aria-label="activeModule === 'all' ? '全域指标' : `${activeModule.toUpperCase()} 指标`">
            <section class="decision-summary" aria-label="经营摘要">
              <article class="outcome-summary">
                <header><div><small>当前范围</small><h3>正在积累的成果</h3></div><span>{{ panoramaSummary.outcomes.length }} 项可核对</span></header>
                <div v-if="panoramaSummary.outcomes.length" class="summary-items">
                  <button v-for="card in panoramaSummary.outcomes" :key="`outcome-${card.id}`" type="button" @click="focusMetric(card.id)"><small>{{ card.moduleLabel }}</small><strong>{{ outcomeHeadline(card) }}</strong><span>{{ outcomeEvidence(card) }}</span><em>展开依据 ↗</em></button>
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
            <section class="cockpit-bottom-deck" aria-label="驾驶舱快捷入口与数据状态">
              <div class="quick-entry-grid">
                <button type="button" @click="chooseModule('all')"><i>▣</i><span><b>查看经营全景</b><small>快速了解全域获客表现</small></span></button>
                <button type="button" @click="panoramaSummary.attention[0] && focusMetric(panoramaSummary.attention[0].id)"><i>▤</i><span><b>定位待办事项</b><small>集中处理待推进卡片</small></span></button>
                <button type="button" @click="loadAll"><i>◎</i><span><b>刷新数据边界</b><small>重新核对读取状态</small></span></button>
                <button type="button" @click="setViewMode('split')"><i>✦</i><span><b>切换到对话模式</b><small>让 AI 帮你进一步分析</small></span></button>
              </div>
              <aside class="readiness-panel">
                <header><h3>数据读取状态</h3><button type="button" @click="loadAll">重新读取边界 ↗</button></header>
                <div v-for="item in availableModules" :key="`readiness-${item.module_code}`" class="readiness-row">
                  <span>{{ moduleMeta[item.module_code].label }}</span>
                  <b :class="moduleState[item.module_code]">{{ statusLabel(moduleState[item.module_code]) }}</b>
                </div>
                <p>数据未读取不补成 0，所有结论只基于当前已核验范围。</p>
              </aside>
            </section>
            <section v-for="group in businessGroups" :id="`cockpit-${group.id}`" :key="group.id" class="dashboard-section">
              <header class="dashboard-group"><div><small>0{{ businessGroups.indexOf(group) + 1 }}</small><h3>{{ group.title }}</h3><p>{{ group.note }}</p></div><span v-if="demoMode">演示数据 · 不计入正式统计</span></header>
              <div v-if="group.businessCards.length" class="business-card-grid" :class="`business-${group.id}`">
                <article
                  v-for="business in group.businessCards"
                  :key="business.id"
                  class="business-performance-card"
                  :class="[`business-card-${business.moduleCode}`, { 'is-highlighted': business.metricIds.some(id => highlightedMetricIds.includes(id)) }]"
                  :data-metric-ids="business.metricIds.join(' ')"
                >
                  <header>
                    <div>
                      <small>{{ business.title.split(' · ')[0] }}</small>
                      <h4>{{ business.title }}</h4>
                    </div>
                    <span :class="{ partial: business.status !== '数据已读取' }"><i></i>{{ business.status }}</span>
                  </header>
                  <p class="business-statement">{{ business.statement }}</p>
                  <div class="business-metrics">
                    <button v-for="item in business.metrics" :key="item.id" type="button" @click="focusMetric(item.id, 'business-card')">
                      <small>{{ item.label }}</small>
                      <strong>{{ item.value }}</strong>
                      <em v-if="item.change">{{ item.change }}</em>
                    </button>
                  </div>
                  <div v-if="business.support" class="support-metric">
                    <small>{{ business.support.label }}</small>
                    <strong>{{ business.support.value }}</strong>
                    <em v-if="business.support.change">{{ business.support.change }}</em>
                    <span>{{ business.support.note }}</span>
                  </div>
                  <div class="business-insight">
                    <b>{{ business.insightLabel || 'AI 解读' }}</b>
                    <template v-if="business.statusRows?.length">
                      <p>{{ business.insight }}</p>
                      <ul><li v-for="row in business.statusRows" :key="row.label"><span>{{ row.label }}</span><em>{{ row.status }}</em></li></ul>
                    </template>
                    <p v-else>{{ business.insight }}</p>
                  </div>
                  <footer>
                    <button v-for="action in business.actions" :key="`${business.id}-${action.label}`" type="button" @click="runBusinessAction(action)">{{ action.label }}</button>
                  </footer>
                </article>
              </div>
              <div v-else-if="group.cards.length" class="metric-grid evidence-task-grid" :class="{ compact: compactCards }">
                <MetricEvidenceCard v-for="card in group.cards" :key="card.id" :data-metric-id="card.id" :metric="card" :context-revision="viewState.revision" :highlighted="highlightedMetricIds.includes(card.id)" @focus="focusMetric" @discuss="discuss" @retry="loadAll" />
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
      <header><div><small>{{ selectedMetric.moduleLabel }} · 独立查看</small><h2>{{ selectedMetric.label }}</h2></div><button type="button" aria-label="关闭详情" @click="selectedMetricId = null">×</button></header>
      <div class="drawer-value">{{ selectedMetric.display }}</div>
      <p>{{ selectedMetric.reason || `当前指标已锁定，可以继续向${agentName}追问原因和下一步。` }}</p>
      <dl><div><dt>统计范围</dt><dd>{{ selectedMetric.periodLabel }}</dd></div><div><dt>数据来源</dt><dd>{{ selectedMetric.sourceLabel }}</dd></div><div><dt>更新时间</dt><dd>{{ selectedMetric.updatedLabel }}</dd></div></dl>
      <section class="scope-tools" aria-label="范围比较">
        <div><button type="button" @click="saveCurrentMetricScope">保存当前范围</button><button type="button" @click="compareWithSavedScope">与保存范围比较</button></div>
        <p v-if="savedMetricScope">已保存：{{ savedMetricScope.label }} · {{ savedMetricScope.dateStart }} 至 {{ savedMetricScope.dateEnd }}<template v-if="savedMetricScope.moduleCode === 'seo'"> · 网站 #{{ savedMetricScope.seoSiteId || '未选' }}</template></p>
        <p v-if="metricComparison?.status === 'ready'" class="comparison-ready"><span>当前值 <b>{{ metricComparison.currentDisplay }}</b></span><span>保存值 <b>{{ metricComparison.savedDisplay }}</b></span><span>差值 <b>{{ metricComparison.deltaDisplay }}</b></span></p>
        <p v-else-if="metricComparison">{{ metricComparison.message }}</p>
      </section>
      <div class="drawer-actions"><button type="button" @click="discuss({ metricId: selectedMetric.id, contextRevision: viewState.revision }); setViewMode('split')">就这项问{{ agentName }}</button><button type="button" @click="openModule(selectedMetric.moduleCode)">进入模块 ↗</button></div>
    </aside>
    <button v-if="viewMode === 'data'" class="agent-fab" type="button" @click="setViewMode('split')"><i></i><span>打开智能体</span></button>
  </main>
</template>

<style scoped>
.dashboard-group{grid-column:1/-1;display:flex;align-items:center;justify-content:space-between;margin:8px 0 0;padding:12px 0;border-bottom:1px solid #294154;font-size:15px}.dashboard-group small{color:#86a0b5;font-size:11px;font-weight:400}.event-feed{min-height:0!important}.event-list{grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
.exploration-path{display:flex;align-items:center;gap:6px;margin:-4px 0 12px;padding:8px 10px;border:1px solid #203b50;border-radius:11px;background:#091827}.exploration-path button{width:28px;height:28px;border:1px solid #315168;border-radius:7px;background:#102638;color:#b8d2df;cursor:pointer}.exploration-path button:disabled{opacity:.3;cursor:not-allowed}.exploration-path span{display:grid;gap:2px;min-width:0;margin-left:4px}.exploration-path small{color:#648095;font-size:8px}.exploration-path b{overflow:hidden;color:#bcd0de;font-size:9px;text-overflow:ellipsis;white-space:nowrap}.scope-tools{display:grid;gap:8px;margin:0 0 12px;padding:11px;border:1px solid #28465a;border-radius:11px;background:#0b1d2c}.scope-tools>div{display:grid;grid-template-columns:1fr 1fr;gap:7px}.scope-tools button{padding:8px;border:1px solid #356776;border-radius:8px;background:#10323a;color:#aef7ed;font-size:9px;cursor:pointer}.scope-tools p{margin:0;color:#7892a6;font-size:9px;line-height:1.5}.comparison-ready{display:grid!important;grid-template-columns:repeat(3,1fr);gap:6px}.comparison-ready span{display:grid;gap:3px}.comparison-ready b{color:#e4f4fb;font-size:12px}
.command-drawer{overflow-y:auto}
.metric-grid.compact :deep(.evidence-card > .metric-visual){display:none}

*{box-sizing:border-box}.cockpit-shell{--cyan:#59e8d3;--blue:#5798ff;--violet:#9f72ff;--orange:#ff9f5a;position:relative;isolation:isolate;min-height:100vh;padding:18px 22px 28px;overflow:hidden;background-color:#070b16;background-image:radial-gradient(#87a5c015 1px,transparent 1px);background-size:22px 22px;color:#edf6ff;font-variant-numeric:tabular-nums}.ambient{position:fixed;z-index:-2;pointer-events:none;border-radius:50%;filter:blur(36px);opacity:.16}.ambient-a{width:700px;height:700px;right:-220px;top:-360px;background:radial-gradient(circle,#285bd8 0,transparent 68%)}.ambient-b{width:620px;height:620px;left:-360px;bottom:-360px;background:radial-gradient(circle,#006b73 0,transparent 70%)}button,input,select,textarea{font:inherit}.command-bar{display:grid;grid-template-columns:minmax(250px,1fr) auto minmax(680px,1.7fr);align-items:end;gap:18px;position:relative}.brand-block{min-width:0}.back-link{padding:0 0 9px;border:0;background:none;color:#7690a9;font-size:11px;cursor:pointer}.brand-line{display:flex;align-items:center;gap:12px}.brand-mark{display:grid;place-items:center;width:38px;height:38px;border-radius:12px;background:linear-gradient(145deg,#2b6eff,#784cff);box-shadow:0 9px 28px #3d55ff66;font-style:normal;font-weight:800}.brand-line p,.mission-heading p{margin:0;color:#62d6d0;font-size:9px;font-weight:800;letter-spacing:.18em}.brand-line h1{margin:4px 0 0;font-size:21px;letter-spacing:-.02em}.live-badge{align-self:center;display:flex;align-items:center;gap:8px;padding:8px 12px;border:1px solid #254057;border-radius:999px;background:#091827cc;color:#90a6b9;font-size:10px}.live-badge i,.agent-head em i,.agent-note i{width:6px;height:6px;border-radius:50%;background:var(--cyan);box-shadow:0 0 12px var(--cyan);animation:signal 2s ease-in-out infinite}.live-badge.replay{border-color:#8a6b35}.live-badge.replay i{background:#f5a524;box-shadow:0 0 12px #f5a524}.live-badge b{color:#dbeaff;font-weight:600}.live-badge small{color:#60798d}.command-controls{display:flex;justify-content:flex-end;align-items:end;gap:8px}.command-controls label,.period-control{display:grid;gap:5px;color:#7f96aa;font-size:9px}.period-control{min-width:390px}.period-control>span{font-weight:700;color:#9ab0c2}.period-shortcuts{display:flex;gap:4px}.period-shortcuts button,.apply-period{height:25px;padding:0 9px;border:1px solid #284258;border-radius:7px;background:#0a1928;color:#8ba2b5;font-size:9px;cursor:pointer}.period-shortcuts button.active{border-color:#4aa6a3;background:#143d43;color:#cafff7}.apply-period{height:35px;border-color:#386d72;color:#bceee9}.apply-period:disabled{cursor:not-allowed;opacity:.4}.command-controls input,.command-controls select,.refresh-button{height:35px;border:1px solid #284258;border-radius:9px;background:#0a1928;color:#eaf5ff;padding:0 10px}.command-controls select{max-width:210px}.date-range{display:flex;align-items:center;gap:5px}.date-range span{color:#486176}.date-range input{width:118px}.refresh-button{border-color:#327b78;background:linear-gradient(135deg,#176d6b,#1f8376);cursor:pointer;font-size:11px;font-weight:700}.refresh-button span{font-size:15px}.workspace-toolbar{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:4px 12px;margin-top:16px;padding:0 4px;border-bottom:1px solid #1c3042}.page-tabs,.view-tools{display:flex;align-items:center;gap:4px}.page-tabs button{position:relative;padding:11px 14px;border:0;background:none;color:#71899f;font-size:11px;cursor:pointer}.page-tabs button.active{color:#eef8ff}.page-tabs button.active:after{content:'';position:absolute;left:12px;right:12px;bottom:-1px;height:2px;background:linear-gradient(90deg,var(--cyan),var(--blue));box-shadow:0 0 12px var(--cyan)}.page-tabs b{display:inline-grid;place-items:center;min-width:17px;height:17px;margin-left:5px;border-radius:999px;background:#713927;color:#ffc59c;font-size:9px}.page-tabs i{display:inline-block;width:5px;height:5px;margin-left:5px;border-radius:50%;background:var(--orange)}.view-tools{padding-bottom:6px}.view-tools span{margin-right:4px;color:#5f778d;font-size:9px}.view-tools button{display:grid;place-items:center;width:29px;height:27px;border:1px solid transparent;border-radius:7px;background:transparent;color:#738ba1;cursor:pointer}.view-tools button.active,.view-tools button:hover{border-color:#29475d;background:#112436;color:#bceef0}.pulse-strip{display:grid;grid-template-columns:1.5fr repeat(4,1fr);gap:1px;margin-top:14px;overflow:hidden;border:1px solid #21394e;border-radius:16px;background:#20364a;box-shadow:0 18px 52px #02071080}.pulse-strip>div{position:relative;min-height:82px;padding:13px 16px;background:linear-gradient(145deg,#0d1b2b,#0a1624);display:grid;align-content:center;gap:5px;overflow:hidden}.pulse-strip>div:before{content:'';position:absolute;inset:auto 0 0;height:1px;background:linear-gradient(90deg,transparent,#4e7089,transparent)}.pulse-strip span{color:#70879c;font-size:9px}.pulse-strip strong{font-size:23px;line-height:1}.pulse-strip strong small{font-size:11px;color:#647c92}.pulse-strip small{color:#5f778d;font-size:9px}.pulse-strip em{width:72px;height:3px;border-radius:9px;background:linear-gradient(90deg,var(--cyan) var(--progress),#203548 var(--progress));margin-top:4px}.pulse-strip .urgent strong{color:#ffab6d;text-shadow:0 0 22px #ff7b3c66}.pulse-strip .caution strong{color:#e9c276}.customer-cell strong{font-size:17px}.operations-grid{display:grid;grid-template-columns:340px minmax(0,1fr);gap:14px;margin-top:14px;align-items:stretch}.mode-data .operations-grid{grid-template-columns:1fr}.mode-chat .operations-grid{grid-template-columns:minmax(340px,720px);justify-content:center}.agent-panel,.data-stage{min-width:0;border:1px solid #20384c;border-radius:19px;background:linear-gradient(155deg,#0b1928e8,#07121ee8);box-shadow:0 22px 70px #02071180;backdrop-filter:blur(16px)}.agent-panel{display:flex;flex-direction:column;height:calc(100vh - 210px);min-height:600px;position:sticky;top:14px;overflow:hidden}.mode-chat .agent-panel{height:calc(100vh - 220px);position:relative;top:auto}.agent-head{display:flex;align-items:center;gap:11px;padding:15px 16px;border-bottom:1px solid #1c3245}.agent-head>div:nth-child(2){display:grid;gap:2px}.agent-head span{font-size:9px;color:#6e879e}.agent-head strong{font-size:14px}.agent-head em{display:flex;align-items:center;gap:6px;margin-left:auto;color:#69d8cc;font-size:9px;font-style:normal}.agent-orb{position:relative;width:34px;height:34px;border-radius:50%;background:conic-gradient(from 40deg,#9d76ff,#3986ff,#4ce7d1,#9d76ff);box-shadow:0 0 24px #5798ff66;animation:float 3.2s ease-in-out infinite}.agent-orb:after{content:'';position:absolute;inset:5px;border-radius:50%;background:radial-gradient(circle at 36% 28%,#fff 0 6%,#88e9ed 10%,#182c52 54%,#070f1b 70%)}.agent-orb i{position:absolute;z-index:1;inset:-5px;border:1px solid #5ce6d466;border-radius:50%;animation:orbit 5s linear infinite}.context-ribbon{display:flex;align-items:center;gap:8px;margin:12px 14px 0;padding:9px 10px;border:1px solid #244159;border-radius:10px;background:#0c2133}.context-ribbon span{color:#6c879d;font-size:8px}.context-ribbon b{color:#bdd1e2;font-size:10px}.messages{flex:1;overflow:auto;padding:14px;display:flex;flex-direction:column;gap:10px}.message{max-width:92%;padding:10px 12px;border:1px solid #1e3a50;border-radius:4px 13px 13px;background:#102437}.message.user{align-self:flex-end;border-color:#27665f;border-radius:13px 4px 13px 13px;background:#145047}.message small{color:#63d4c9;font-size:8px}.message p{margin:4px 0 0;color:#d7e5f1;font-size:11px;line-height:1.65}.guides{padding:0 13px 9px;display:flex;gap:6px;flex-wrap:wrap}.guides button{border:1px solid #28455b;border-radius:999px;background:#0a1c2b;color:#91a9bc;padding:6px 8px;font-size:9px;cursor:pointer}.guides button:hover{border-color:#52aaad;color:#d6ffff}.composer{position:relative;margin:0 13px}.composer textarea{display:block;width:100%;resize:none;border:1px solid #31526b;border-radius:13px;background:#050e18;color:#eff9ff;padding:11px 48px 11px 11px;font-size:11px;line-height:1.5}.composer textarea:focus{outline:1px solid #50b9ba;box-shadow:0 0 24px #3bd8c622}.composer button{position:absolute;right:8px;bottom:8px;width:32px;height:32px;border:0;border-radius:9px;background:linear-gradient(145deg,#4be0cc,#338de4);color:#04111a;font-size:17px;font-weight:900;cursor:pointer}.agent-note{display:flex;align-items:center;gap:7px;margin:8px 15px 13px;color:#58738a;font-size:8px}.data-stage{padding:17px}.mission-heading{display:flex;justify-content:space-between;align-items:flex-end;gap:18px;margin-bottom:14px}.mission-heading h2{margin:5px 0 3px;font-size:21px}.mission-heading span{color:#70899e;font-size:9px}.stage-actions{display:flex;gap:6px}.stage-actions button{padding:7px 10px;border:1px solid #28455b;border-radius:8px;background:#0c1e2e;color:#8da7ba;font-size:9px;cursor:pointer}.stage-actions button:hover{border-color:#4b8894;color:#d6ffff}.module-tabs{display:grid;grid-template-columns:repeat(4,minmax(100px,1fr));gap:7px;margin-bottom:12px}.module-tabs button{position:relative;display:grid;grid-template-columns:1fr auto;gap:5px 9px;text-align:left;padding:10px 12px;border:1px solid #223d52;border-radius:11px;background:#0b1b2a;color:#dce9f5;cursor:pointer;overflow:hidden}.module-tabs button:after{content:'';position:absolute;inset:auto 0 0;height:2px;background:#526a7c;opacity:.4}.module-tabs button.active{border-color:#3f6b83;background:#10283b;box-shadow:inset 0 0 20px #2a668122}.module-tabs button.active:after{background:var(--cyan);opacity:1;box-shadow:0 0 14px var(--cyan)}.module-tabs .module-sem.active:after{background:var(--orange)}.module-tabs .module-seo.active:after{background:var(--blue)}.module-tabs .module-geo.active:after{background:var(--violet)}.module-tabs span{font-size:10px;font-weight:800}.module-tabs b{font-size:15px}.module-tabs small{grid-column:1/-1;color:#698299;font-size:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.metric-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(225px,1fr));gap:10px;max-height:none;overflow:visible;padding:2px 3px 12px}.mode-data .metric-grid{grid-template-columns:repeat(auto-fit,minmax(260px,1fr));max-height:none}.metric-grid.compact{grid-template-columns:repeat(auto-fit,minmax(185px,1fr))}.metric-grid.compact :deep(.evidence-card){padding:15px;border-radius:16px}.metric-grid.compact :deep(.trend-wrap),.metric-grid.compact :deep(.empty-trend){display:none}.metric-grid.compact :deep(.metric-trigger){padding:14px 0 4px}.metric-grid.compact :deep(.metric-number){font-size:30px}.metric-grid :deep(.evidence-card){background:linear-gradient(155deg,#12263a,#0b1725);border-color:#253f55;border-radius:17px;padding:17px}.metric-grid :deep(.evidence-card:hover){transform:translateY(-2px);border-color:#4b718b;box-shadow:0 14px 40px #02071188}.metric-grid :deep(.metric-number){font-size:clamp(28px,2.6vw,40px)}.metric-grid :deep(.trend){height:70px}.metric-grid :deep(.metric-trigger){padding:15px 0 6px}.data-empty{min-height:320px;border:1px dashed #29475e;border-radius:14px;display:grid;place-content:center;justify-items:center;text-align:center;gap:7px;color:#718ba0}.data-empty i{width:34px;height:34px;border:2px solid #2f5b6d;border-top-color:var(--cyan);border-radius:50%;animation:orbit 2s linear infinite}.data-empty strong{color:#d8e6f2}.data-empty span{font-size:10px}
.key-help{padding-right:8px;border-right:1px solid #1c3042;letter-spacing:.04em}.screen-applied{display:inline-flex;margin-top:7px;padding:3px 7px;border:1px solid #3c6f70;border-radius:999px;color:#77dfd3;font-size:8px}.message-actions{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}.message-actions button{padding:5px 7px;border:1px solid #346278;border-radius:7px;background:#102c3c;color:#a7e9e2;font-size:8px;cursor:pointer}.channel-control-strip{display:grid;grid-template-columns:minmax(150px,1.05fr) minmax(390px,2.4fr) auto;align-items:stretch;gap:8px;margin:0 0 12px;padding:9px;border:1px solid #20394d;border-radius:14px;background:#0a1826cc}.control-summary{display:grid;align-content:center;gap:4px;padding:4px 9px}.control-summary small{color:#6f899d;font-size:8px}.control-summary strong{font-size:14px}.control-summary span{color:#728a9d;font-size:8px}.channel-controls{display:grid;grid-template-columns:repeat(3,minmax(105px,1fr));gap:6px}.channel-control{display:grid;grid-template-columns:1fr auto;gap:3px 8px;min-width:0;padding:9px 10px;border:1px solid #263f52;border-radius:10px;background:#0c1c2a;color:#dbe8f1;text-align:left;cursor:pointer;transition:background .16s,border-color .16s}.channel-control:hover{background:#102536;border-color:#3b5b70}.channel-control.active{background:#132b3c;border-color:#5c8297}.channel-control span{display:flex;align-items:center;gap:6px;font-size:9px;font-weight:800;letter-spacing:.08em}.channel-control span i{width:6px;height:6px;border-radius:50%;background:#7b8f9e}.channel-control b{font-size:12px}.channel-control b small{color:#6f879a;font-size:8px;font-weight:400}.channel-control em{grid-column:1/-1;overflow:hidden;color:#6d8699;font-size:8px;font-style:normal;text-overflow:ellipsis;white-space:nowrap}.channel-sem span i{background:var(--orange)}.channel-seo span i{background:var(--blue)}.channel-geo span i{background:var(--violet)}.show-all-control{align-self:center;padding:8px 9px;border:1px solid #2b485c;border-radius:8px;background:transparent;color:#8da4b6;font-size:8px;cursor:pointer}.battle-layout{display:grid;grid-template-columns:minmax(0,1fr);gap:10px;align-items:start}.event-feed{min-height:280px;border:1px solid #213d51;border-radius:15px;background:#091725bb;overflow:hidden}.event-feed header{display:flex;justify-content:space-between;align-items:center;padding:12px;border-bottom:1px solid #1c3549}.event-feed header div{display:grid;gap:3px}.event-feed header small{color:#61d8cf;font-size:7px;letter-spacing:.14em}.event-feed header strong{font-size:12px}.event-feed header button{border:1px solid #29475b;border-radius:7px;background:#102538;color:#83a1b5;font-size:8px;padding:5px 7px;cursor:pointer}.event-list{display:grid}.event-list button{position:relative;display:grid;grid-template-columns:35px 6px 1fr;gap:7px;padding:11px 10px;border:0;border-bottom:1px solid #162d3e;background:transparent;color:#9cb2c3;text-align:left;cursor:pointer}.event-list button:hover{background:#102638}.event-list time{font-size:8px;color:#557189}.event-list i{width:5px;height:5px;margin-top:3px;border-radius:50%;background:var(--cyan);box-shadow:0 0 9px currentColor}.event-list span{font-size:9px;line-height:1.5}.event-list b{grid-column:3;color:#5d879b;font-size:8px;font-weight:500}.event-sem i{background:var(--orange)}.event-seo i{background:var(--blue)}.event-geo i{background:var(--violet)}.event-feed>p{padding:26px 12px;color:#607a8e;font-size:9px}.event-feed footer{display:flex;align-items:center;gap:7px;padding:10px 12px;color:#607a8e;font-size:8px}.event-feed footer span{width:5px;height:5px;border-radius:50%;background:var(--cyan);box-shadow:0 0 10px var(--cyan);animation:signal 2s infinite}.event-feed footer span.paused{background:#8b96a1;box-shadow:none;animation:none}.command-drawer{position:fixed;z-index:20;right:18px;top:18px;bottom:18px;width:min(420px,calc(100vw - 36px));padding:20px;border:1px solid #3a6075;border-radius:18px;background:#091725ed;box-shadow:-25px 0 80px #000a;backdrop-filter:blur(18px) saturate(1.15);animation:drawerIn .2s ease-out}.command-drawer header{display:flex;justify-content:space-between;align-items:flex-start}.command-drawer header small{color:#68d9d0;font-size:8px;letter-spacing:.12em}.command-drawer h2{margin:5px 0;font-size:19px}.command-drawer header button{width:31px;height:31px;border:1px solid #315066;border-radius:50%;background:#102538;color:#c4d6e2;font-size:19px;cursor:pointer}.drawer-value{margin:26px 0 10px;font-size:46px;font-weight:700;letter-spacing:-.04em}.command-drawer>p{color:#9fb2c1;font-size:11px;line-height:1.7}.command-drawer dl{margin:22px 0;border-top:1px solid #244053}.command-drawer dl div{display:grid;grid-template-columns:72px 1fr;gap:10px;padding:11px 0;border-bottom:1px solid #1e374a}.command-drawer dt{color:#628096;font-size:9px}.command-drawer dd{margin:0;color:#b9cad6;font-size:10px;overflow-wrap:anywhere}.drawer-actions{display:grid;grid-template-columns:1fr 1fr;gap:8px}.drawer-actions button{padding:10px;border:1px solid #356776;border-radius:9px;background:#10323a;color:#aef7ed;font-size:9px;cursor:pointer}.drawer-actions button+button{border-color:#334f68;background:#12263a;color:#b3cadb}
.ledger{display:grid;gap:9px}.ledger article{display:grid;grid-template-columns:44px 8px minmax(0,1fr) auto;align-items:center;gap:13px;padding:15px;border:1px solid #243f54;border-radius:13px;background:#0c1d2d}.ledger article.urgent{border-color:#704831;background:linear-gradient(90deg,#2b1c18,#0c1d2d 35%)}.action-rank{display:grid;place-items:center;height:26px;border-radius:7px;background:#142b3d;color:#7892a7;font-size:9px}.ledger article.urgent .action-rank{background:#68351f;color:#ffd0af}.ledger article>i{width:7px;height:7px;border-radius:50%;background:#e6b56d}.ledger article>i.ready{background:var(--cyan);box-shadow:0 0 12px var(--cyan)}.action-copy{display:grid;gap:4px}.action-copy small{color:#6c879d;font-size:8px}.action-copy b{font-size:12px}.action-copy span{color:#7891a6;font-size:9px}.ledger article>button{border:1px solid #31536a;border-radius:8px;background:#10283a;color:#a9dcd9;padding:8px 10px;font-size:9px;cursor:pointer}.quality-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.quality-grid article{min-height:170px;padding:18px;border:1px solid #263f54;border-radius:15px;background:linear-gradient(145deg,#102337,#091624)}.quality-grid span{color:#7390a5;font-size:9px}.quality-grid strong{display:block;margin:18px 0 12px;font-size:38px}.quality-grid p{color:#7c94a8;font-size:10px;line-height:1.7}.quality-grid .caution strong{color:#e8bc70}.quality-grid .principle{grid-column:1/-1;min-height:auto;background:linear-gradient(100deg,#122b3d,#171b39)}.quality-grid h3{margin:8px 0 0;font-size:22px}.agent-fab{position:fixed;right:28px;bottom:26px;z-index:5;display:flex;align-items:center;gap:9px;padding:11px 15px;border:1px solid #43887f;border-radius:999px;background:#0d2f36;color:#cafff7;box-shadow:0 12px 40px #0008;cursor:pointer}.agent-fab i{width:8px;height:8px;border-radius:50%;background:var(--cyan);box-shadow:0 0 12px var(--cyan)}.is-fullscreen{overflow:auto}.is-fullscreen .operations-grid{min-height:calc(100vh - 205px)}button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:2px solid #78e7de;outline-offset:2px}@keyframes drawerIn{from{opacity:0;transform:translateX(28px)}}@keyframes signal{50%{opacity:.35;transform:scale(.75)}}@keyframes float{50%{transform:translateY(-2px);box-shadow:0 0 32px #5798ff88}}@keyframes orbit{to{transform:rotate(360deg)}}@media(prefers-reduced-motion:reduce){*{animation:none!important;scroll-behavior:auto!important;transition:none!important}}@media(max-width:1180px){.key-help{display:none}.battle-layout{grid-template-columns:1fr}.event-feed{min-height:auto}.event-list{grid-template-columns:repeat(2,1fr)}.command-bar{grid-template-columns:1fr auto}.live-badge{display:none}.command-controls{grid-column:1/-1;justify-content:flex-start}.operations-grid{grid-template-columns:310px minmax(0,1fr)}.pulse-strip{grid-template-columns:1.4fr repeat(2,1fr)}.pulse-strip>div:nth-child(4),.pulse-strip>div:nth-child(5){display:none}.module-tabs{grid-template-columns:repeat(2,1fr)}}@media(max-width:860px){.channel-control-strip{grid-template-columns:1fr}.channel-controls{grid-template-columns:repeat(3,1fr)}.show-all-control{justify-self:start}.battle-layout{grid-template-columns:1fr}.event-list{grid-template-columns:1fr}.cockpit-shell{padding:12px}.operations-grid{grid-template-columns:1fr}.agent-panel{height:auto;min-height:520px;position:relative;top:auto}.data-stage{min-height:540px}.pulse-strip{grid-template-columns:1fr 1fr}.pulse-strip .customer-cell{grid-column:1/-1}.command-controls{flex-wrap:wrap}.metric-grid{max-height:none}.quality-grid{grid-template-columns:1fr}.quality-grid .principle{grid-column:auto}}@media(max-width:560px){.channel-controls{grid-template-columns:1fr}.command-bar{grid-template-columns:1fr}.command-controls label,.period-control,.date-range{width:100%}.period-control{min-width:0}.period-shortcuts button{flex:1}.date-range input{width:calc(50% - 10px)}.workspace-toolbar{align-items:flex-end}.page-tabs{width:100%;justify-content:space-between}.view-tools{width:100%;justify-content:flex-end}.view-tools span{display:none}.page-tabs button{padding:10px 7px}.pulse-strip{grid-template-columns:1fr}.pulse-strip>div:nth-child(4),.pulse-strip>div:nth-child(5){display:none}.module-tabs{grid-template-columns:1fr 1fr}.mission-heading{align-items:flex-start;flex-direction:column}.metric-grid{grid-template-columns:1fr}.ledger article{grid-template-columns:40px 8px 1fr}.ledger article>button{grid-column:3}.brand-line h1{font-size:18px}}
</style>
<style scoped>
/* Final cockpit density pass: keep this block last so older prototype layers cannot re-expand the layout. */
.cockpit-shell{
  grid-template-columns:54px 300px minmax(0,1fr) !important;
  grid-template-rows:44px 40px minmax(0,1fr) !important;
  gap:6px 12px !important;
  padding:8px 12px 12px !important;
}
.command-bar{
  grid-template-columns:300px minmax(0,1fr) !important;
  height:44px !important;
}
.brand-block,.brand-line{height:44px}
.brand-mark{width:30px !important;height:30px !important}
.brand-line h1{font-size:18px !important}
.brand-line p{font-size:9px !important}
.command-controls{
  grid-template-columns:minmax(130px,170px) minmax(180px,220px) minmax(330px,1fr) 96px !important;
  height:38px !important;
  gap:5px !important;
  padding:2px !important;
}
.command-controls label,.period-control{height:34px !important;border-radius:6px !important}
.command-controls label{padding:0 8px !important}
.period-control{grid-template-columns:auto auto minmax(190px,1fr) !important;padding:0 8px !important}
.period-shortcuts{grid-template-columns:repeat(3,40px) !important}
.period-shortcuts button,.date-range input,.apply-period{height:26px !important}
.date-range input{width:92px !important}
.apply-period{width:36px !important}
.refresh-button{width:96px !important;height:34px !important}
.workspace-toolbar{height:40px !important}
.page-tabs,.page-tabs button{height:40px !important}
.page-tabs button{min-width:96px !important;padding:0 14px !important;font-size:11px !important}
.view-tools{height:34px !important;padding:2px 6px !important}
.view-tools .key-help{max-width:170px}
.view-tools button{width:28px !important;height:28px !important}
.operations-grid{
  grid-template-columns:300px minmax(0,1fr) !important;
  gap:12px !important;
}
.agent-panel{
  margin-top:-50px !important;
  height:calc(100vh - 18px) !important;
  min-height:700px !important;
}
.agent-head{padding:14px 14px 10px !important;gap:9px !important}
.agent-orb{width:38px !important;height:38px !important}
.agent-head span,.agent-head em{font-size:10px !important}
.agent-head strong{font-size:16px !important}
.messages{padding:8px 14px !important;gap:10px !important}
.message{padding:10px 12px !important;border-radius:12px !important}
.message p{font-size:12px !important;line-height:1.58 !important}
.guides{padding:0 14px 10px !important;gap:7px !important}
.guides button{min-height:40px !important;padding:8px 10px !important;border-radius:10px !important;font-size:12px !important}
.composer{margin:0 14px !important;padding:8px !important}
.composer textarea{min-height:66px !important;font-size:12px !important}
.agent-note{margin:8px 14px 10px !important}
.data-stage{
  min-height:calc(100vh - 106px) !important;
  padding:0 16px 12px !important;
}
.mission-heading{
  min-height:118px !important;
  margin:0 -16px 8px !important;
  padding:22px 22px 48px !important;
}
.mission-heading h2{font-size:26px !important;margin:6px 0 5px !important}
.mission-heading p{font-size:10px !important}
.mission-heading span{max-width:620px;font-size:13px !important}
.mission-heading:after{top:28px !important;right:26px !important;font-size:12px !important}
.stage-actions{right:18px !important;bottom:16px !important}
.stage-actions button{height:26px !important;padding:0 10px !important;font-size:10px !important}
.module-tabs{
  margin:-42px 0 8px !important;
  gap:7px !important;
}
.module-tabs button{min-height:42px !important;padding:7px 10px !important}
.module-tabs span,.module-tabs small{font-size:10px !important}
.module-tabs b{font-size:16px !important}
.decision-summary{gap:8px !important}
.decision-summary>article{
  min-height:96px !important;
  padding:10px 12px !important;
  border-radius:10px !important;
}
.decision-summary>article>header{margin-bottom:6px !important}
.decision-summary h3{font-size:15px !important}
.decision-summary header small,.decision-summary header>span{font-size:9px !important}
.summary-items{gap:6px !important}
.summary-items button{min-height:62px !important;padding:7px 9px !important;border-radius:8px !important}
.summary-items button>small,.summary-items button>em{font-size:8px !important}
.summary-items button>strong{font-size:20px !important}
.summary-items button>span{font-size:10px !important}
.attention-items{gap:6px !important}
.attention-items button{min-height:42px !important;padding:6px 9px !important;border-radius:8px !important}
.attention-items button>b{font-size:20px !important}
.attention-items button strong{font-size:10px !important}
.attention-items button small{font-size:8px !important}
.decision-summary article>footer{display:none !important}
.dashboard-section{padding-top:2px !important}
.dashboard-group{padding:5px 2px 4px !important;margin-bottom:6px !important}
.dashboard-group h3{font-size:15px !important}
.dashboard-group p{font-size:9px !important}
.metric-grid{
  grid-template-columns:repeat(4,minmax(156px,1fr)) !important;
  gap:8px !important;
}
.metric-grid :deep(.evidence-card){
  min-height:132px !important;
  padding:10px !important;
}
.metric-grid :deep(.metric-title){font-size:12px !important}
.metric-grid :deep(.metric-number){font-size:25px !important}
.metric-grid :deep(.metric-change){font-size:10px !important}
.metric-grid :deep(.trend),.metric-grid :deep(.trend-scrubber){height:34px !important}
.metric-grid :deep(.card-footer){margin-top:4px !important;padding-top:5px !important;font-size:9px !important}
.metric-grid :deep(.card-footer>span){max-width:120px;overflow:hidden;text-overflow:ellipsis}
@media(max-width:1380px){
  .cockpit-shell{grid-template-columns:54px 290px minmax(0,1fr) !important}
  .command-bar,.operations-grid{grid-template-columns:290px minmax(0,1fr) !important}
  .command-controls{grid-template-columns:minmax(116px,145px) minmax(150px,190px) minmax(280px,1fr) 90px !important}
  .period-shortcuts{grid-template-columns:repeat(3,36px) !important}
  .date-range input{width:86px !important}
  .refresh-button{width:90px !important}
}
</style>
<style scoped>
/* True final pass: clean the right rail and remove the blank blue hole. */
.cockpit-shell{
  grid-template-columns:54px 330px minmax(0,1fr) !important;
  grid-template-rows:50px minmax(0,1fr) !important;
  gap:8px 12px !important;
  padding:10px 12px 12px !important;
}
.command-bar{
  grid-column:2 / 4 !important;
  grid-row:1 !important;
  grid-template-columns:330px minmax(0,1fr) !important;
  height:50px !important;
}
.operations-grid{
  grid-column:2 / 4 !important;
  grid-row:2 !important;
  grid-template-columns:330px minmax(0,1fr) !important;
  gap:12px !important;
  margin:0 !important;
}
.agent-panel,
.data-stage{
  height:calc(100vh - 74px) !important;
  min-height:0 !important;
  margin:0 !important;
}
.data-stage{
  padding:0 16px 16px !important;
}
.mission-heading{
  min-height:150px !important;
  margin:0 -16px 12px !important;
  padding:24px 26px 58px !important;
}
.module-tabs{
  margin:-54px 0 10px !important;
  grid-template-columns:1.2fr repeat(3,1fr) !important;
}
.panorama-content{
  display:grid !important;
  grid-template-columns:minmax(0,1fr) 278px !important;
  grid-auto-flow:row dense !important;
  gap:10px 12px !important;
  align-items:start !important;
}
.decision-summary{
  grid-column:1 / -1 !important;
  grid-row:1 !important;
  grid-template-columns:minmax(0,1.08fr) minmax(330px,.92fr) !important;
  gap:10px !important;
}
.decision-summary>article{
  min-height:108px !important;
  padding:10px 12px !important;
}
.summary-items button{
  min-height:58px !important;
}
.attention-items button{
  min-height:42px !important;
}
.dashboard-section{
  grid-column:1 !important;
}
.dashboard-section:nth-of-type(4){
  grid-column:1 !important;
}
.cockpit-bottom-deck{
  grid-column:2 !important;
  grid-row:2 / span 3 !important;
  display:grid !important;
  gap:8px !important;
  align-self:start !important;
  position:sticky !important;
  top:0 !important;
  z-index:2 !important;
}
.quick-entry-grid{
  display:grid !important;
  grid-template-columns:1fr !important;
  gap:7px !important;
}
.quick-entry-grid button{
  min-height:48px !important;
  padding:7px 9px !important;
  grid-template-columns:30px minmax(0,1fr) !important;
  border-radius:8px !important;
  background:rgba(244,250,255,.72) !important;
}
.quick-entry-grid i{
  width:28px !important;
  height:28px !important;
  border-radius:8px !important;
}
.quick-entry-grid b{
  font-size:12px !important;
}
.quick-entry-grid small{
  font-size:10px !important;
}
.readiness-panel{
  padding:10px !important;
  border-radius:9px !important;
  background:rgba(18,61,108,.32) !important;
}
.readiness-panel header{
  margin-bottom:6px !important;
}
.readiness-panel h3{
  font-size:13px !important;
}
.readiness-row{
  height:32px !important;
  margin-top:6px !important;
}
.readiness-panel p{
  margin-top:8px !important;
  font-size:10px !important;
}
.metric-grid{
  grid-template-columns:repeat(4,minmax(0,1fr)) !important;
  gap:8px !important;
}
.metric-grid :deep(.evidence-card){
  min-height:132px !important;
  padding:10px !important;
}
.metric-grid :deep(.metric-trigger){
  padding:8px 0 3px !important;
}
.metric-grid :deep(.metric-number){
  font-size:24px !important;
}
.metric-grid :deep(.trend),
.metric-grid :deep(.trend-scrubber){
  height:32px !important;
}
.metric-grid :deep(.card-actions button:first-child){
  display:none !important;
}
@media(max-width:1380px){
  .cockpit-shell{
    grid-template-columns:54px 310px minmax(0,1fr) !important;
  }
  .command-bar,
  .operations-grid{
    grid-template-columns:310px minmax(0,1fr) !important;
  }
  .panorama-content{
    grid-template-columns:minmax(0,1fr) 258px !important;
  }
  .metric-grid{
    grid-template-columns:repeat(3,minmax(0,1fr)) !important;
  }
}
</style>

<style scoped>
/* True final AI-console reference pass. Keep this after all cockpit overrides. */
.agent-panel{
  display:flex !important;
  flex-direction:column !important;
  height:calc(100vh - 74px) !important;
  min-height:0 !important;
  padding:0 !important;
  overflow:hidden !important;
  border-radius:9px !important;
  border:1px solid rgba(72,137,197,.42) !important;
  background:
    radial-gradient(circle at 16% 100%,rgba(40,125,205,.24),transparent 34%),
    linear-gradient(180deg,#102d55 0%,#06182f 55%,#051123 100%) !important;
  box-shadow:inset 0 1px rgba(255,255,255,.09),0 22px 44px rgba(5,25,58,.34) !important;
}
.agent-panel:before{
  content:'' !important;
  position:absolute !important;
  left:-18px !important;
  right:-18px !important;
  bottom:-26px !important;
  height:150px !important;
  pointer-events:none !important;
  background:
    radial-gradient(ellipse at 24% 92%,rgba(43,144,255,.34),transparent 30%),
    linear-gradient(160deg,transparent 24%,rgba(76,174,255,.14) 46%,transparent 68%) !important;
  opacity:.72 !important;
}
.agent-panel>*{
  position:relative !important;
  z-index:1 !important;
}
.agent-head{
  flex:0 0 auto !important;
  min-height:68px !important;
  padding:18px 18px 8px !important;
  gap:0 !important;
  border-bottom:0 !important;
}
.agent-head .agent-orb{
  display:none !important;
}
.agent-head>div:nth-child(2){
  display:grid !important;
  gap:5px !important;
}
.agent-head span{
  order:2 !important;
  color:#a8bed5 !important;
  font-size:12px !important;
  font-weight:500 !important;
  letter-spacing:0 !important;
}
.agent-head strong{
  order:1 !important;
  color:#fff !important;
  font-size:20px !important;
  line-height:1 !important;
  letter-spacing:.01em !important;
}
.agent-head em{
  position:absolute !important;
  right:18px !important;
  top:21px !important;
  margin:0 !important;
  padding:0 !important;
  color:#bfeee6 !important;
  font-size:11px !important;
  font-weight:600 !important;
}
.context-ribbon{
  display:none !important;
}
.intro-message{
  flex:0 0 auto !important;
  min-height:72px !important;
  max-width:none !important;
  margin:8px 18px 13px 66px !important;
  padding:12px 13px !important;
  border-radius:8px !important;
  border:1px solid rgba(54,96,141,.7) !important;
  background:rgba(31,67,105,.68) !important;
  box-shadow:inset 0 1px rgba(255,255,255,.05) !important;
}
.intro-message:before{
  content:'' !important;
  position:absolute !important;
  left:-50px !important;
  top:50% !important;
  width:38px !important;
  height:38px !important;
  transform:translateY(-50%) !important;
  border-radius:14px !important;
  background:
    radial-gradient(circle at 33% 44%,#fff 0 4px,transparent 5px),
    radial-gradient(circle at 67% 44%,#fff 0 4px,transparent 5px),
    linear-gradient(180deg,#89d8ff,#1f6dff) !important;
  box-shadow:0 0 0 4px rgba(55,139,255,.22),0 10px 24px rgba(10,90,220,.38) !important;
}
.intro-message:after{
  content:'' !important;
  position:absolute !important;
  left:-39px !important;
  top:9px !important;
  width:16px !important;
  height:7px !important;
  border-radius:999px 999px 0 0 !important;
  border-top:2px solid #b9dcff !important;
  border-left:2px solid transparent !important;
  border-right:2px solid transparent !important;
}
.intro-message small{
  display:none !important;
}
.intro-message p{
  margin:0 !important;
  color:#dbeaff !important;
  font-size:12px !important;
  line-height:1.52 !important;
}
.guide-title{
  flex:0 0 auto !important;
  padding:0 18px 8px !important;
  color:#f3f8ff !important;
  font-size:12px !important;
  font-weight:800 !important;
}
.guides{
  flex:0 0 auto !important;
  display:grid !important;
  grid-template-columns:1fr !important;
  gap:7px !important;
  padding:0 18px 12px !important;
}
.guides button{
  position:relative !important;
  display:flex !important;
  align-items:center !important;
  width:100% !important;
  min-height:32px !important;
  padding:0 30px 0 33px !important;
  border-radius:8px !important;
  border:1px solid rgba(79,139,199,.58) !important;
  background:rgba(20,52,86,.78) !important;
  color:#dcecff !important;
  font-size:11px !important;
  font-weight:600 !important;
  text-align:left !important;
  box-shadow:inset 0 1px rgba(255,255,255,.05) !important;
}
.guides button:before{
  content:'+' !important;
  position:absolute !important;
  left:13px !important;
  top:50% !important;
  display:grid !important;
  place-items:center !important;
  width:14px !important;
  height:14px !important;
  margin-top:-7px !important;
  border:1px solid rgba(226,240,255,.9) !important;
  border-radius:50% !important;
  color:#eef8ff !important;
  font-size:10px !important;
  line-height:1 !important;
}
.guides button:after{
  content:'›' !important;
  position:absolute !important;
  right:12px !important;
  top:50% !important;
  transform:translateY(-52%) !important;
  color:#d9ecff !important;
  font-size:20px !important;
  line-height:1 !important;
}
.messages{
  flex:1 1 auto !important;
  min-height:145px !important;
  padding:0 18px 10px !important;
  gap:9px !important;
  overflow:auto !important;
}
.messages .message{
  flex:0 0 auto !important;
}
.message{
  max-width:100% !important;
  padding:10px 12px !important;
  border-radius:8px !important;
  border:1px solid rgba(54,96,141,.72) !important;
  background:rgba(31,67,105,.68) !important;
  box-shadow:inset 0 1px rgba(255,255,255,.05) !important;
}
.message small{
  display:block !important;
  margin-bottom:5px !important;
  color:#5ee5d4 !important;
  font-size:10px !important;
  font-weight:800 !important;
}
.message p{
  margin:0 !important;
  color:#dcecff !important;
  font-size:12px !important;
  line-height:1.5 !important;
  white-space:pre-line !important;
}
.message.user{
  align-self:flex-end !important;
  width:auto !important;
  max-width:78% !important;
  min-width:178px !important;
  padding:10px 12px !important;
  border:1px solid rgba(48,133,255,.9) !important;
  border-radius:8px 8px 0 8px !important;
  background:linear-gradient(135deg,#147dff,#075eea) !important;
  box-shadow:0 12px 22px rgba(7,80,216,.24) !important;
}
.message.user small{
  display:none !important;
}
.message.user p{
  color:#fff !important;
  font-size:12px !important;
  line-height:1.35 !important;
}
.message.user:after{
  content:'10:24' !important;
  float:right !important;
  margin-left:14px !important;
  color:rgba(2,36,93,.68) !important;
  font-size:9px !important;
  line-height:16px !important;
}
.message-actions{
  display:flex !important;
  gap:6px !important;
  margin-top:9px !important;
}
.message-actions button{
  height:24px !important;
  padding:0 7px !important;
  border-radius:5px !important;
  border:1px solid rgba(59,124,211,.86) !important;
  background:rgba(13,55,111,.72) !important;
  color:#c8e5ff !important;
  font-size:9px !important;
  white-space:nowrap !important;
}
.screen-applied{
  display:none !important;
}
.composer{
  flex:0 0 auto !important;
  position:relative !important;
  margin:0 18px 9px !important;
  padding:0 !important;
  border:0 !important;
  background:transparent !important;
}
.composer textarea{
  width:100% !important;
  min-height:66px !important;
  max-height:66px !important;
  padding:12px 54px 12px 14px !important;
  resize:none !important;
  border-radius:10px !important;
  border:1px solid rgba(191,214,239,.86) !important;
  background:#f4f9ff !important;
  color:#61738c !important;
  font-size:12px !important;
  line-height:1.45 !important;
  box-shadow:0 10px 26px rgba(5,17,38,.24) !important;
}
.composer button{
  right:10px !important;
  bottom:9px !important;
  width:34px !important;
  height:34px !important;
  border-radius:8px !important;
  background:#126dff !important;
  color:#fff !important;
  font-size:19px !important;
  box-shadow:0 8px 18px rgba(18,109,255,.32) !important;
}
.agent-note{
  flex:0 0 auto !important;
  margin:0 18px 12px !important;
  color:#83a7c7 !important;
  font-size:9px !important;
  line-height:1.3 !important;
}
@media(max-height:840px){
  .agent-head{min-height:60px !important;padding-top:14px !important}
  .intro-message{min-height:62px !important;margin-bottom:9px !important}
  .intro-message p,.message p{font-size:11px !important}
  .guides{gap:6px !important;padding-bottom:9px !important}
  .guides button{min-height:30px !important}
  .messages{min-height:120px !important;gap:7px !important}
  .composer textarea{min-height:58px !important;max-height:58px !important}
}
</style>

<style scoped>
/* Final left command-console pass: match the dense glass cockpit reference. */
.agent-panel{
  position:sticky !important;
  top:0 !important;
  display:flex !important;
  flex-direction:column !important;
  padding:0 !important;
  overflow:hidden !important;
  border-radius:10px !important;
  border:1px solid rgba(93,157,218,.38) !important;
  background:
    radial-gradient(circle at 22% 100%,rgba(31,116,207,.28),transparent 34%),
    linear-gradient(180deg,rgba(12,40,84,.98),rgba(4,17,39,.99)) !important;
  box-shadow:inset 0 1px rgba(255,255,255,.1),0 22px 46px rgba(7,33,78,.36) !important;
}
.agent-panel:before{
  content:'' !important;
  position:absolute !important;
  left:-26px !important;
  right:-26px !important;
  bottom:-30px !important;
  height:170px !important;
  pointer-events:none !important;
  background:
    radial-gradient(ellipse at 32% 88%,rgba(50,155,255,.42),transparent 30%),
    linear-gradient(170deg,transparent 22%,rgba(70,170,255,.18) 49%,transparent 66%) !important;
  opacity:.72 !important;
}
.agent-panel>*{
  position:relative !important;
  z-index:1 !important;
}
.agent-head{
  min-height:72px !important;
  padding:14px 16px 8px !important;
  gap:10px !important;
  border-bottom:0 !important;
}
.agent-orb{
  width:46px !important;
  height:46px !important;
  flex:0 0 46px !important;
  box-shadow:0 0 0 5px rgba(69,141,235,.2),0 0 28px rgba(89,209,236,.45) !important;
}
.agent-head span{
  font-size:11px !important;
  color:#89a9c9 !important;
  letter-spacing:.01em !important;
}
.agent-head strong{
  margin-top:2px !important;
  font-size:20px !important;
  line-height:1.1 !important;
  color:#f4fbff !important;
  letter-spacing:0 !important;
}
.agent-head em{
  align-self:flex-start !important;
  padding-top:10px !important;
  font-size:12px !important;
  color:#76f3df !important;
  white-space:nowrap !important;
}
.context-ribbon{
  display:none !important;
}
.messages{
  flex:1 1 auto !important;
  min-height:0 !important;
  padding:7px 16px 10px !important;
  gap:10px !important;
  overflow:auto !important;
}
.message{
  max-width:100% !important;
  padding:10px 12px !important;
  border-radius:10px !important;
  border:1px solid rgba(75,144,204,.46) !important;
  background:rgba(30,73,116,.58) !important;
  box-shadow:inset 0 1px rgba(255,255,255,.06) !important;
}
.message.user{
  align-self:flex-end !important;
  max-width:76% !important;
  border-color:#328dff !important;
  border-radius:10px 10px 2px 10px !important;
  background:linear-gradient(135deg,#167fff,#0759e3) !important;
  box-shadow:0 8px 18px rgba(0,77,210,.2) !important;
}
.message small{
  font-size:10px !important;
  font-weight:700 !important;
  color:#5ee5d4 !important;
}
.message.user small{
  display:none !important;
}
.message p{
  margin:3px 0 0 !important;
  color:#eef8ff !important;
  font-size:13px !important;
  line-height:1.52 !important;
  white-space:pre-line !important;
}
.screen-applied{
  display:none !important;
}
.message-actions{
  display:flex !important;
  flex-wrap:wrap !important;
  gap:6px !important;
  margin-top:8px !important;
}
.message-actions button{
  height:28px !important;
  padding:0 8px !important;
  border-radius:6px !important;
  border:1px solid rgba(70,139,220,.84) !important;
  background:rgba(14,67,133,.78) !important;
  color:#cce8ff !important;
  font-size:10px !important;
  cursor:pointer !important;
}
.guide-title{
  flex:0 0 auto !important;
  padding:0 16px 7px !important;
  color:#d7eaff !important;
  font-size:12px !important;
  font-weight:800 !important;
}
.guides{
  flex:0 0 auto !important;
  display:grid !important;
  grid-template-columns:1fr !important;
  gap:7px !important;
  padding:0 16px 10px !important;
}
.guides button{
  position:relative !important;
  display:flex !important;
  align-items:center !important;
  min-height:34px !important;
  padding:0 30px 0 32px !important;
  border-radius:8px !important;
  border:1px solid rgba(73,142,203,.58) !important;
  background:rgba(17,53,91,.74) !important;
  color:#dcecff !important;
  font-size:12px !important;
  text-align:left !important;
  box-shadow:inset 0 1px rgba(255,255,255,.05) !important;
}
.guides button:before{
  content:'+' !important;
  position:absolute !important;
  left:12px !important;
  top:50% !important;
  display:grid !important;
  place-items:center !important;
  width:14px !important;
  height:14px !important;
  margin-top:-7px !important;
  border:1px solid rgba(217,237,255,.8) !important;
  border-radius:50% !important;
  color:#f2fbff !important;
  font-size:10px !important;
  line-height:1 !important;
}
.guides button:after{
  content:'›' !important;
  position:absolute !important;
  right:12px !important;
  top:50% !important;
  transform:translateY(-52%) !important;
  color:#d9ecff !important;
  font-size:20px !important;
  line-height:1 !important;
}
.composer{
  flex:0 0 auto !important;
  position:relative !important;
  margin:0 16px 10px !important;
  padding:0 !important;
}
.composer textarea{
  display:block !important;
  width:100% !important;
  min-height:76px !important;
  max-height:76px !important;
  padding:13px 52px 13px 14px !important;
  resize:none !important;
  border-radius:12px !important;
  border:1px solid rgba(173,204,238,.78) !important;
  background:rgba(244,250,255,.96) !important;
  color:#29415f !important;
  font-size:13px !important;
  line-height:1.45 !important;
  box-shadow:0 10px 24px rgba(4,16,35,.22) !important;
}
.composer button{
  right:10px !important;
  bottom:10px !important;
  width:38px !important;
  height:38px !important;
  border-radius:10px !important;
  background:#116dff !important;
  color:#fff !important;
  font-size:20px !important;
  box-shadow:0 8px 18px rgba(17,109,255,.3) !important;
}
.agent-note{
  flex:0 0 auto !important;
  margin:0 16px 12px !important;
  color:#83a7c7 !important;
  font-size:10px !important;
}
@media(max-height:820px){
  .agent-head{min-height:66px !important;padding-top:12px !important}
  .agent-orb{width:40px !important;height:40px !important;flex-basis:40px !important}
  .agent-head strong{font-size:18px !important}
  .message p{font-size:12px !important;line-height:1.45 !important}
  .guides button{min-height:32px !important}
  .composer textarea{min-height:64px !important;max-height:64px !important}
}
</style>

<style scoped>
/* Final ordering fix for the left AI panel. */
.intro-message{
  flex:0 0 auto !important;
  margin:6px 16px 10px !important;
  max-width:none !important;
  min-height:0 !important;
}
.intro-message p{
  font-size:12px !important;
  line-height:1.48 !important;
}
.guide-title{
  padding-top:0 !important;
}
.guides{
  padding-bottom:8px !important;
}
.messages{
  flex:1 1 auto !important;
  padding-top:4px !important;
  padding-bottom:8px !important;
  overflow:auto !important;
}
.messages .message{
  flex:0 0 auto !important;
}
.messages .message p{
  font-size:12px !important;
  line-height:1.42 !important;
}
.messages .message.user{
  padding:9px 12px !important;
}
.message-actions{
  gap:5px !important;
}
.message-actions button{
  height:25px !important;
  font-size:9px !important;
}
@media(max-height:860px){
  .intro-message{
    margin-bottom:8px !important;
  }
  .guides{
    gap:6px !important;
  }
  .messages{
    gap:8px !important;
  }
}
</style>
<style scoped>
/* One-screen cockpit mode: replace page switching with a compact status rail. */
.cockpit-shell{
  grid-template-rows:44px 34px minmax(0,1fr) !important;
}
.workspace-toolbar{
  height:34px !important;
  margin:0 !important;
  padding:0 !important;
  align-items:center !important;
  border-bottom:1px solid rgba(69,103,146,.38) !important;
}
.page-tabs{
  display:none !important;
}
.cockpit-snapshot{
  display:flex;
  align-items:center;
  gap:8px;
  min-width:0;
  height:30px;
  padding:0 2px;
}
.cockpit-snapshot span{
  display:inline-flex;
  align-items:center;
  height:26px;
  padding:0 10px;
  border:1px solid rgba(126,166,219,.45);
  border-radius:8px;
  background:rgba(239,247,255,.5);
  color:#294a78;
  font-size:11px;
  font-weight:800;
  white-space:nowrap;
}
.cockpit-snapshot span:first-child{
  background:#fff;
  color:#0b67e8;
  box-shadow:0 5px 14px rgba(43,105,178,.12);
}
.view-tools{
  height:30px !important;
  padding:0 8px !important;
  border-radius:10px !important;
}
.data-stage{
  min-height:calc(100vh - 100px) !important;
}
.mission-heading{
  margin-top:0 !important;
}
@media(max-width:860px){
  .cockpit-snapshot{
    flex-wrap:wrap;
    height:auto;
  }
  .cockpit-snapshot span{
    height:24px;
    font-size:10px;
  }
}
</style>
<style scoped>
/* Remove the secondary toolbar row completely. */
.cockpit-shell{
  grid-template-rows:44px minmax(0,1fr) !important;
  gap:6px 12px !important;
}
.workspace-toolbar{
  display:none !important;
}
.operations-grid{
  grid-column:2 / 4 !important;
  grid-row:2 !important;
  margin-top:0 !important;
}
.agent-panel{
  margin-top:0 !important;
  height:calc(100vh - 64px) !important;
  min-height:680px !important;
}
.data-stage{
  min-height:calc(100vh - 64px) !important;
}
@media(max-width:1380px){
  .cockpit-shell{
    grid-template-rows:44px minmax(0,1fr) !important;
  }
  .agent-panel,
  .data-stage{
    min-height:calc(100vh - 64px) !important;
  }
}
</style>
<style scoped>
/* Premium glass cockpit pass: match the reference's luminous control-room texture. */
.cockpit-shell{
  --ink:#061a45;
  --deep:#081b3f;
  --glass:rgba(244,250,255,.72);
  --glass-strong:rgba(255,255,255,.84);
  --edge:rgba(198,221,248,.72);
  --aqua:#15c6ba;
  --blue:#136cff;
  --violet:#8a63ff;
  --rose:#ff3f70;
  color:#082258 !important;
  background:
    radial-gradient(circle at 62% 54%,rgba(40,168,255,.44) 0 2%,transparent 14%),
    radial-gradient(circle at 78% 20%,rgba(255,255,255,.64) 0 8%,transparent 28%),
    radial-gradient(circle at 30% 78%,rgba(47,190,255,.30) 0 10%,transparent 34%),
    linear-gradient(120deg,#dbeeff 0%,#b7d4f0 44%,#6d9ccc 100%) !important;
}
.cockpit-shell:before{
  content:'';
  position:fixed;
  inset:0;
  pointer-events:none;
  z-index:-1;
  opacity:.72;
  background:
    linear-gradient(115deg,transparent 0 34%,rgba(255,255,255,.36) 41%,transparent 50%),
    radial-gradient(ellipse at 72% 46%,rgba(255,255,255,.58),transparent 28%),
    repeating-linear-gradient(108deg,rgba(255,255,255,.08) 0 1px,transparent 1px 18px);
  mix-blend-mode:screen;
}
.energy-field{
  inset:48px 14px 14px 390px !important;
  opacity:1 !important;
  border-radius:12px !important;
  background:
    radial-gradient(ellipse at 46% 50%,rgba(255,255,255,.72),transparent 13%),
    radial-gradient(ellipse at 52% 54%,rgba(4,100,255,.38),transparent 19%),
    linear-gradient(100deg,rgba(9,42,92,.18),rgba(255,255,255,.16),rgba(23,92,162,.24)) !important;
  filter:none !important;
}
.energy-field:before,
.energy-field:after{
  content:'';
  position:absolute;
  left:-4%;
  right:-4%;
  height:230px;
  border-radius:50%;
  pointer-events:none;
  background:
    radial-gradient(ellipse at 50% 50%,transparent 0 48%,rgba(255,255,255,.88) 49%,transparent 52%),
    linear-gradient(90deg,transparent,rgba(43,153,255,.84),rgba(255,255,255,.92),rgba(52,126,255,.76),transparent);
  filter:blur(.4px) drop-shadow(0 0 16px rgba(69,164,255,.45));
  opacity:.58;
}
.energy-field:before{
  top:42px;
  transform:rotate(-5deg) scaleY(.35);
}
.energy-field:after{
  bottom:60px;
  transform:rotate(3deg) scaleY(.30);
  opacity:.48;
}
.ambient{
  opacity:.30 !important;
  filter:blur(46px) !important;
}
.ambient-a{background:radial-gradient(circle,#ffffff 0,#62b7ff 34%,transparent 70%) !important}
.ambient-b{background:radial-gradient(circle,#2be4ff 0,#2369cc 38%,transparent 70%) !important}
.app-rail,
.agent-panel{
  background:linear-gradient(180deg,rgba(8,34,78,.98),rgba(4,17,39,.98)) !important;
  border:1px solid rgba(133,181,240,.22) !important;
  box-shadow:0 22px 42px rgba(5,26,62,.32),inset 0 1px rgba(255,255,255,.08) !important;
}
.command-bar{
  color:#071f55 !important;
}
.command-controls label,
.period-control{
  background:rgba(238,248,255,.78) !important;
  border-color:rgba(114,154,211,.48) !important;
  box-shadow:inset 0 1px rgba(255,255,255,.92),0 8px 22px rgba(61,111,174,.16) !important;
  backdrop-filter:blur(18px) saturate(1.18) !important;
}
.refresh-button{
  background:linear-gradient(135deg,#071b45,#0d3674) !important;
  border-color:rgba(21,60,119,.82) !important;
  box-shadow:0 12px 24px rgba(9,31,75,.26),inset 0 1px rgba(255,255,255,.18) !important;
}
.data-stage{
  position:relative;
  overflow:auto !important;
  border:1px solid rgba(196,222,250,.48) !important;
  background:rgba(196,222,247,.28) !important;
  box-shadow:0 28px 70px rgba(40,88,143,.30),inset 0 1px rgba(255,255,255,.42) !important;
  backdrop-filter:blur(18px) saturate(1.18) !important;
}
.data-stage:before{
  content:'';
  position:absolute;
  inset:0;
  z-index:0;
  pointer-events:none;
  opacity:.92;
  background:
    radial-gradient(ellipse at 55% 48%,rgba(255,255,255,.72),transparent 13%),
    radial-gradient(ellipse at 58% 54%,rgba(0,116,255,.38),transparent 24%),
    linear-gradient(180deg,rgba(255,255,255,.14),rgba(119,176,226,.34));
}
.data-stage>*{
  position:relative;
  z-index:1;
}
.mission-heading{
  overflow:hidden !important;
  border:1px solid rgba(221,239,255,.36) !important;
  background:
    radial-gradient(ellipse at 78% 22%,rgba(255,255,255,.45),transparent 22%),
    linear-gradient(100deg,rgba(241,249,255,.88) 0%,rgba(174,211,244,.60) 42%,rgba(79,140,203,.54) 100%) !important;
  box-shadow:inset 0 1px rgba(255,255,255,.82),0 18px 40px rgba(62,106,160,.18) !important;
}
.mission-heading:before{
  content:'';
  position:absolute;
  inset:-20% -8% auto 22%;
  height:150px;
  background:
    radial-gradient(ellipse at center,transparent 0 45%,rgba(255,255,255,.92) 47%,transparent 52%),
    linear-gradient(90deg,transparent,rgba(22,116,255,.72),rgba(255,255,255,.86),rgba(21,92,188,.64),transparent);
  transform:rotate(-5deg) scaleY(.34);
  filter:drop-shadow(0 0 12px rgba(73,151,255,.44));
  opacity:.68;
}
.mission-heading h2{
  color:#061b55 !important;
  text-shadow:0 1px rgba(255,255,255,.55) !important;
}
.mission-heading p{
  color:#1768e8 !important;
}
.mission-heading span{
  color:#315b94 !important;
}
.stage-actions button{
  background:rgba(255,255,255,.54) !important;
  border-color:rgba(165,199,235,.60) !important;
  color:#315b94 !important;
  backdrop-filter:blur(16px) !important;
}
.module-tabs button,
.decision-summary>article,
.summary-items button,
.attention-items button,
.metric-grid :deep(.evidence-card){
  border:1px solid rgba(194,219,247,.70) !important;
  background:rgba(255,255,255,.76) !important;
  box-shadow:inset 0 1px rgba(255,255,255,.92),0 14px 28px rgba(44,88,145,.18) !important;
  backdrop-filter:blur(18px) saturate(1.1) !important;
}
.module-tabs button{
  color:#09265b !important;
}
.module-tabs button.active{
  color:#fff !important;
  border-color:rgba(83,143,255,.72) !important;
  background:linear-gradient(135deg,#0f78ff,#075ce8 72%,#053ba6) !important;
  box-shadow:0 16px 32px rgba(17,99,232,.32),inset 0 1px rgba(255,255,255,.28) !important;
}
.module-tabs button.active:after{
  height:3px !important;
  background:#18e5d2 !important;
}
.decision-summary>article{
  background:linear-gradient(120deg,rgba(236,255,250,.84),rgba(255,255,255,.68)) !important;
}
.attention-summary{
  background:linear-gradient(120deg,rgba(255,241,246,.88),rgba(255,255,255,.68)) !important;
}
.decision-summary h3,
.metric-grid :deep(.metric-number){
  color:#061b55 !important;
}
.metric-grid :deep(.evidence-card){
  border-radius:8px !important;
  background:linear-gradient(145deg,rgba(255,255,255,.86),rgba(236,247,255,.72)) !important;
}
.metric-grid :deep(.evidence-card:hover){
  transform:translateY(-3px) !important;
  box-shadow:inset 0 1px rgba(255,255,255,.95),0 22px 34px rgba(37,91,164,.24) !important;
}
.metric-grid :deep(.module-name),
.metric-grid :deep(.card-footer button),
.metric-grid :deep(.expand-hint){
  color:#126bff !important;
}
.metric-grid :deep(.read-status){
  color:#02a993 !important;
}
.metric-grid :deep(.trend-line){stroke:#126bff !important}
.metric-grid :deep(.trend-point){fill:#126bff !important}
.metric-grid :deep(.baseline){stroke:#cfdef2 !important}
.dashboard-group{
  border-bottom:0 !important;
  color:#143867 !important;
}
.dashboard-group small{
  color:#0b73ff !important;
}
.dashboard-group h3{
  color:#082258 !important;
}
.dashboard-group p{
  color:#526d94 !important;
}
.composer textarea{
  background:rgba(239,247,255,.96) !important;
  color:#17335c !important;
}
.composer button{
  background:linear-gradient(135deg,#1277ff,#0c4cd8) !important;
  color:#fff !important;
}
@media(max-width:1380px){
  .energy-field{
    inset:48px 12px 14px 360px !important;
  }
}
</style>
<style scoped>
/* Reference-aligned cockpit rebuild: one continuous luminous dashboard, not a white admin panel. */
.cockpit-shell{
  grid-template-columns:54px 340px minmax(0,1fr) !important;
  grid-template-rows:54px minmax(0,1fr) !important;
  gap:8px 12px !important;
  padding:10px 12px 12px !important;
  overflow:hidden !important;
  background:
    radial-gradient(circle at 83% 22%,rgba(255,255,255,.42) 0 8%,transparent 24%),
    radial-gradient(circle at 58% 62%,rgba(36,147,255,.56) 0 5%,transparent 22%),
    radial-gradient(circle at 20% 86%,rgba(12,71,140,.36),transparent 28%),
    linear-gradient(130deg,#dcefff 0%,#b8d3ee 37%,#729fcd 100%) !important;
}
.cockpit-shell:after{
  content:'';
  position:fixed;
  inset:0;
  z-index:-1;
  pointer-events:none;
  opacity:.34;
  background-image:
    linear-gradient(110deg,transparent 0 22%,rgba(255,255,255,.28) 23%,transparent 24% 50%,rgba(33,127,234,.18) 51%,transparent 52%),
    repeating-linear-gradient(0deg,rgba(255,255,255,.08) 0 1px,transparent 1px 28px);
}
.energy-field{
  inset:64px 12px 12px 418px !important;
  z-index:-1 !important;
  border-radius:10px !important;
  background:
    radial-gradient(ellipse at 54% 57%,rgba(255,255,255,.72),transparent 10%),
    radial-gradient(ellipse at 56% 58%,rgba(0,118,255,.46),transparent 21%),
    linear-gradient(180deg,rgba(245,251,255,.30),rgba(79,146,205,.34)) !important;
}
.energy-field:before{
  top:18px !important;
  height:260px !important;
  transform:rotate(-4deg) scaleY(.26) !important;
  opacity:.86 !important;
}
.energy-field:after{
  bottom:122px !important;
  height:210px !important;
  transform:rotate(2deg) scaleY(.30) !important;
  opacity:.72 !important;
}
.app-rail{
  grid-row:1 / 3 !important;
  border-radius:12px !important;
}
.command-bar{
  grid-column:2 / 4 !important;
  grid-row:1 !important;
  grid-template-columns:340px minmax(0,1fr) !important;
  height:54px !important;
  align-items:center !important;
}
.brand-block,
.brand-line{
  height:54px !important;
}
.brand-line h1{
  font-size:22px !important;
}
.brand-line p{
  color:#365f94 !important;
  font-size:11px !important;
  letter-spacing:0 !important;
}
.brand-mark{
  width:36px !important;
  height:36px !important;
  border-radius:50% !important;
  background:linear-gradient(145deg,#1d7dff,#0f4cc9) !important;
}
.command-controls{
  grid-template-columns:minmax(168px,220px) minmax(220px,280px) minmax(460px,1fr) 118px !important;
  align-items:center !important;
  height:44px !important;
  gap:8px !important;
  padding:0 !important;
}
.command-controls label,
.period-control{
  height:42px !important;
  border-radius:6px !important;
  background:rgba(237,247,255,.82) !important;
  border:1px solid rgba(126,160,208,.56) !important;
}
.period-control{
  grid-template-columns:auto auto minmax(250px,1fr) !important;
}
.period-shortcuts{
  grid-template-columns:repeat(3,56px) !important;
}
.refresh-button{
  height:42px !important;
  width:118px !important;
  border-radius:6px !important;
}
.operations-grid{
  grid-column:2 / 4 !important;
  grid-row:2 !important;
  grid-template-columns:340px minmax(0,1fr) !important;
  gap:12px !important;
  min-height:0 !important;
  margin:0 !important;
}
.agent-panel{
  height:calc(100vh - 76px) !important;
  min-height:0 !important;
  margin:0 !important;
  border-radius:9px !important;
  background:
    linear-gradient(180deg,rgba(11,38,82,.97),rgba(5,17,39,.98)),
    radial-gradient(circle at 40% 100%,rgba(25,126,224,.32),transparent 38%) !important;
}
.agent-head{
  padding:16px 16px 12px !important;
}
.agent-head strong{
  font-size:18px !important;
}
.messages{
  padding:10px 16px !important;
}
.message{
  background:rgba(28,70,112,.56) !important;
  border-color:rgba(74,139,195,.46) !important;
}
.guides{
  padding:0 16px 10px !important;
}
.guides button{
  width:100% !important;
  justify-content:space-between !important;
  border-radius:8px !important;
  background:rgba(19,54,93,.70) !important;
  border-color:rgba(72,139,197,.62) !important;
}
.composer{
  margin:0 16px 12px !important;
}
.data-stage{
  height:calc(100vh - 76px) !important;
  min-height:0 !important;
  padding:0 18px 18px !important;
  overflow:auto !important;
  border-radius:10px !important;
  border:1px solid rgba(211,234,255,.46) !important;
  background:rgba(132,179,220,.24) !important;
  box-shadow:inset 0 1px rgba(255,255,255,.40),0 18px 44px rgba(28,72,126,.22) !important;
}
.data-stage:before{
  background:
    radial-gradient(ellipse at 52% 52%,rgba(255,255,255,.76),transparent 12%),
    radial-gradient(ellipse at 56% 56%,rgba(0,118,255,.38),transparent 24%),
    linear-gradient(180deg,rgba(255,255,255,.05),rgba(59,137,207,.20)) !important;
}
.mission-heading{
  min-height:158px !important;
  margin:0 -18px 12px !important;
  padding:26px 26px 62px !important;
  border-radius:10px 10px 0 0 !important;
  background:
    radial-gradient(ellipse at 76% 10%,rgba(255,255,255,.58),transparent 18%),
    linear-gradient(100deg,rgba(239,248,255,.86) 0%,rgba(174,211,245,.58) 44%,rgba(69,130,197,.62) 100%) !important;
}
.mission-heading:before{
  top:-28px !important;
  left:22% !important;
  right:-10% !important;
  height:210px !important;
  opacity:.90 !important;
  transform:rotate(-4deg) scaleY(.26) !important;
}
.mission-heading h2{
  font-size:34px !important;
  line-height:1.05 !important;
}
.mission-heading span{
  font-size:15px !important;
  color:#315f99 !important;
}
.stage-actions{
  right:24px !important;
  bottom:22px !important;
}
.stage-actions button{
  height:30px !important;
  padding:0 14px !important;
  color:#376398 !important;
  background:rgba(255,255,255,.50) !important;
}
.module-tabs{
  margin:-56px 0 12px !important;
  grid-template-columns:1.15fr repeat(3,1fr) !important;
  gap:10px !important;
}
.module-tabs button{
  min-height:52px !important;
  border-radius:7px !important;
  padding:9px 12px !important;
}
.module-tabs span,
.module-tabs small{
  font-size:11px !important;
}
.module-tabs b{
  font-size:20px !important;
}
.panorama-content{
  display:grid !important;
  grid-template-columns:minmax(0,1fr) 300px !important;
  gap:12px !important;
}
.decision-summary{
  grid-column:1 / -1 !important;
  grid-template-columns:minmax(0,1.1fr) minmax(380px,.9fr) !important;
  gap:12px !important;
}
.decision-summary>article{
  min-height:118px !important;
  padding:12px !important;
  border-radius:9px !important;
}
.summary-items{
  grid-template-columns:repeat(3,minmax(0,1fr)) !important;
  gap:8px !important;
}
.summary-items button{
  min-height:70px !important;
}
.attention-items button{
  min-height:48px !important;
}
.dashboard-section{
  grid-column:1 !important;
  padding-top:0 !important;
}
.dashboard-section:nth-of-type(4){
  grid-column:1 / -1 !important;
}
.dashboard-group{
  margin:0 !important;
  padding:10px 2px 8px !important;
}
.dashboard-group h3{
  font-size:17px !important;
}
.metric-grid{
  grid-template-columns:repeat(4,minmax(0,1fr)) !important;
  gap:10px !important;
}
.metric-grid :deep(.evidence-card){
  min-height:146px !important;
  padding:11px 12px !important;
}
.metric-grid :deep(.metric-trigger){
  padding:9px 0 4px !important;
}
.metric-grid :deep(.metric-number){
  font-size:26px !important;
  line-height:1.18 !important;
}
.metric-grid :deep(.trend),
.metric-grid :deep(.trend-scrubber){
  height:42px !important;
}
.metric-grid :deep(.card-footer){
  margin-top:5px !important;
}
.metric-grid :deep(.card-actions button:first-child){
  display:none !important;
}
.cockpit-bottom-deck{
  grid-column:2 !important;
  grid-row:3 / span 4 !important;
  display:grid;
  align-content:start;
  gap:12px;
  min-width:0;
}
.quick-entry-grid{
  display:grid;
  grid-template-columns:1fr;
  gap:8px;
}
.quick-entry-grid button{
  display:grid;
  grid-template-columns:34px minmax(0,1fr);
  align-items:center;
  gap:10px;
  min-height:52px;
  padding:8px 10px;
  border:1px solid rgba(193,220,250,.66);
  border-radius:8px;
  background:rgba(255,255,255,.62);
  color:#09265b;
  text-align:left;
  box-shadow:inset 0 1px rgba(255,255,255,.9),0 12px 24px rgba(46,91,148,.18);
  cursor:pointer;
}
.quick-entry-grid i{
  display:grid;
  place-items:center;
  width:32px;
  height:32px;
  border-radius:9px;
  background:linear-gradient(135deg,#1a7fff,#0c4fd7);
  color:#fff;
  font-style:normal;
}
.quick-entry-grid b,
.readiness-panel h3{
  color:#082258;
  font-size:13px;
}
.quick-entry-grid small{
  display:block;
  margin-top:2px;
  color:#557096;
  font-size:11px;
}
.readiness-panel{
  padding:12px;
  border:1px solid rgba(193,220,250,.66);
  border-radius:10px;
  background:rgba(26,63,105,.30);
  box-shadow:inset 0 1px rgba(255,255,255,.42),0 12px 28px rgba(42,89,146,.18);
  backdrop-filter:blur(18px);
}
.readiness-panel header{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:8px;
  margin-bottom:10px;
}
.readiness-panel h3{
  margin:0;
  color:#fff;
}
.readiness-panel header button{
  border:0;
  background:transparent;
  color:#fff;
  font-size:11px;
  cursor:pointer;
}
.readiness-row{
  display:flex;
  align-items:center;
  justify-content:space-between;
  height:38px;
  margin-top:7px;
  padding:0 10px;
  border-radius:7px;
  background:rgba(255,255,255,.78);
}
.readiness-row span{
  color:#09265b;
  font-weight:700;
  font-size:12px;
}
.readiness-row b{
  color:#05a98d;
  font-size:11px;
}
.readiness-row b.partial,
.readiness-row b.needs_scope,
.readiness-row b.waiting{
  color:#ff8a2a;
}
.readiness-panel p{
  margin:10px 0 0;
  color:#d8eaff;
  font-size:11px;
  line-height:1.5;
}
@media(max-width:1380px){
  .cockpit-shell{
    grid-template-columns:54px 320px minmax(0,1fr) !important;
  }
  .command-bar,
  .operations-grid{
    grid-template-columns:320px minmax(0,1fr) !important;
  }
  .energy-field{
    inset:64px 12px 12px 398px !important;
  }
  .panorama-content{
    grid-template-columns:minmax(0,1fr) 280px !important;
  }
  .metric-grid{
    grid-template-columns:repeat(3,minmax(0,1fr)) !important;
  }
}
@media(max-width:1080px){
  .cockpit-shell,
  .command-bar,
  .operations-grid,
  .panorama-content,
  .decision-summary{
    display:flex !important;
    flex-direction:column !important;
  }
  .app-rail{
    display:none !important;
  }
  .agent-panel,
  .data-stage{
    height:auto !important;
  }
}
</style>
<style scoped>
.cockpit-shell{
  --ink:#071a44;
  --muted:#5c76a6;
  --line:#c7d8f2;
  --panel:#f8fbffde;
  --navy:#061832;
  --blue:#1768ff;
  --cyan:#19dcc2;
  --violet:#7b5cff;
  --rose:#ff5578;
  display:grid;
  grid-template-columns:64px 360px minmax(0,1fr);
  grid-template-rows:auto auto minmax(0,1fr);
  gap:14px;
  min-height:100vh;
  padding:12px 16px 18px;
  overflow:auto;
  background:
    radial-gradient(circle at 70% 34%,#ffffffa8 0 8%,transparent 33%),
    radial-gradient(circle at 72% 64%,#7cc7ff88 0 9%,transparent 28%),
    linear-gradient(135deg,#eaf4ff 0%,#c9ddf5 42%,#91b8df 100%);
  color:var(--ink);
}
.cockpit-shell:before{
  content:'';
  position:fixed;
  inset:0;
  z-index:-3;
  pointer-events:none;
  background:
    radial-gradient(ellipse at 76% 10%,#0d55b455 0,transparent 38%),
    linear-gradient(120deg,transparent 0 47%,#ffffff8a 49%,transparent 52% 100%);
}
.energy-field{
  position:fixed;
  inset:0;
  z-index:-2;
  pointer-events:none;
  overflow:hidden;
}
.energy-field:before,
.energy-field:after{
  content:'';
  position:absolute;
  left:24%;
  right:-8%;
  height:38%;
  border-radius:50%;
  filter:blur(1px);
  background:
    radial-gradient(closest-side at 52% 50%,#ffffffd8,transparent 68%),
    repeating-radial-gradient(ellipse at 50% 50%,transparent 0 42px,#2e85ff38 44px 46px,transparent 49px 72px);
  opacity:.42;
  transform:rotate(-9deg);
}
.energy-field:before{top:4%}
.energy-field:after{bottom:1%;opacity:.32;transform:rotate(8deg)}
.ambient{display:none}
.app-rail{
  grid-row:1 / -1;
  grid-column:1;
  display:flex;
  flex-direction:column;
  align-items:center;
  gap:14px;
  padding:10px 8px;
  border-radius:0 22px 22px 0;
  background:linear-gradient(180deg,#08285f,#071b3e 56%,#061631);
  box-shadow:0 20px 45px #1d4f9950;
  color:#d9eaff;
  position:sticky;
  top:12px;
  height:calc(100vh - 30px);
}
.rail-logo{
  display:grid;
  place-items:center;
  width:36px;
  height:36px;
  border-radius:50%;
  background:linear-gradient(145deg,#1784ff,#1f55df);
  color:#fff;
  font-weight:900;
  box-shadow:0 12px 28px #1679ff66;
}
.app-rail button{
  width:46px;
  min-height:54px;
  display:grid;
  place-items:center;
  gap:4px;
  border:0;
  border-radius:14px;
  background:transparent;
  color:#cfe2ff;
  cursor:pointer;
}
.app-rail button span{font-size:10px}
.app-rail button.active,
.app-rail button:hover{background:#ffffff1b;color:#fff}
.command-bar{
  grid-column:2 / 4;
  display:grid;
  grid-template-columns:minmax(300px,1fr) auto minmax(520px,1.55fr);
  align-items:center;
  gap:14px;
  margin:0;
}
.brand-block{color:#fff}
.back-link{color:#d7e7ff;padding:0 0 7px}
.brand-line{gap:12px}
.brand-mark{
  width:42px;
  height:42px;
  border-radius:50%;
  background:linear-gradient(145deg,#2177ff,#0d48c9);
  box-shadow:0 14px 34px #155dec70;
}
.brand-line p{color:#d9e8ff;letter-spacing:0;font-size:12px}
.brand-line h1{font-size:25px;color:#fff;letter-spacing:.02em}
.live-badge{
  border:1px solid #acc8ec;
  background:#ffffffbf;
  color:#1e3f73;
  box-shadow:0 14px 32px #5d8fc540;
}
.live-badge i{background:#22d5bd}
.command-controls{
  justify-content:flex-end;
  gap:10px;
  padding:0;
}
.command-controls label,
.period-control{
  color:#244676;
  background:#edf5ffcc;
  border:1px solid #b6ccef;
  border-radius:8px;
  padding:5px 9px;
  box-shadow:inset 0 1px #fff;
}
.command-controls select,
.command-controls input{
  background:transparent;
  color:#17386d;
  border:0;
  min-height:26px;
}
.period-control{display:flex;align-items:center;gap:8px}
.period-control>span{font-size:11px;color:#355b91}
.period-shortcuts{display:flex;gap:4px}
.period-shortcuts button,
.apply-period{
  height:28px;
  border:1px solid transparent;
  border-radius:7px;
  background:transparent;
  color:#274a7e;
  padding:0 9px;
}
.period-shortcuts button.active,
.apply-period{
  background:#fff;
  border-color:#a5c0e7;
  color:#0f58d8;
}
.date-range{display:flex;align-items:center;gap:5px}
.refresh-button{
  height:38px;
  border:0;
  border-radius:8px;
  background:#061b42;
  color:#fff;
  padding:0 18px;
  box-shadow:0 14px 28px #0a2c6840;
}
.workspace-toolbar{
  grid-column:3;
  grid-row:2;
  display:flex;
  justify-content:space-between;
  align-items:center;
  margin:0;
  color:#214675;
}
.page-tabs{
  padding:0;
  background:transparent;
  border:0;
}
.page-tabs button{
  min-width:108px;
  height:44px;
  border:0;
  border-radius:12px 12px 0 0;
  background:transparent;
  color:#24456f;
  font-weight:700;
}
.page-tabs button.active{
  color:#0062ff;
  background:#ffffffb5;
  box-shadow:inset 0 -3px #1578ff;
}
.view-tools{
  background:#ffffff8a;
  border:1px solid #bed1ed;
  border-radius:14px;
  padding:5px;
  color:#37577e;
}
.view-tools button{
  width:34px;
  height:34px;
  border:1px solid transparent;
  border-radius:9px;
  background:transparent;
  color:#315276;
}
.view-tools button.active,
.view-tools button:hover{
  border-color:#8eb0dd;
  background:#e8f2ff;
  color:#0b57d0;
}
.operations-grid{
  grid-column:2 / 4;
  grid-row:3;
  display:grid;
  grid-template-columns:360px minmax(0,1fr);
  gap:16px;
  margin:0;
  align-items:start;
}
.mode-data .operations-grid{grid-template-columns:1fr}
.mode-chat .operations-grid{grid-template-columns:minmax(360px,720px);justify-content:start}
.agent-panel{
  position:sticky;
  top:12px;
  height:calc(100vh - 32px);
  min-height:720px;
  border:1px solid #1e4c77;
  border-radius:18px;
  background:
    linear-gradient(180deg,#0b203aee,#07172bee),
    radial-gradient(circle at 40% 0,#2879ff55,transparent 32%);
  color:#edf7ff;
  box-shadow:0 24px 52px #06346c55;
  overflow:hidden;
}
.agent-head{
  padding:22px 18px 16px;
  border:0;
}
.agent-head span{font-size:12px;color:#a7c4e5}
.agent-head strong{font-size:20px}
.agent-head em{font-size:11px;color:#8ff7df}
.agent-head em i,
.agent-note i{
  display:inline-block;
  width:8px;
  height:8px;
  border-radius:50%;
  background:#35e4c5;
  box-shadow:0 0 12px #35e4c5;
}
.agent-orb{
  width:54px;
  height:54px;
  border-radius:18px;
  background:
    radial-gradient(circle at 50% 34%,#ffffff 0 9%,#63d9ff 10% 16%,transparent 17%),
    linear-gradient(145deg,#e8f7ff,#126dff);
}
.context-ribbon{
  margin:0 18px 12px;
  min-height:52px;
  border:1px solid #285b83;
  background:#102b45;
  border-radius:12px;
}
.context-ribbon span{font-size:10px;color:#83a6c5}
.context-ribbon b{font-size:13px;color:#e4f3ff}
.messages{padding:16px 18px;gap:16px}
.message{
  border-radius:16px;
  border:1px solid #214f77;
  background:#16324c;
  color:#e8f5ff;
}
.message.user{
  background:#126bff;
  border-color:#4b9cff;
  color:#fff;
}
.message small{font-size:11px;color:#75efd8}
.message p{font-size:13px;line-height:1.75;color:inherit}
.guides{
  padding:0 18px 12px;
  display:grid;
  gap:8px;
}
.guides button{
  display:flex;
  justify-content:space-between;
  width:100%;
  border:1px solid #2b5f89;
  border-radius:12px;
  background:#132f4a;
  color:#d9eaff;
  padding:11px 13px;
  font-size:13px;
}
.guides button:after{content:'›';font-size:18px}
.composer{
  margin:0 18px;
  padding:10px;
  border-radius:14px;
  background:#eef6ff;
}
.composer textarea{
  min-height:80px;
  border:0;
  border-radius:10px;
  background:transparent;
  color:#17345b;
  padding:8px 44px 8px 8px;
  font-size:13px;
}
.composer button{
  right:16px;
  bottom:16px;
  background:#156dff;
  color:#fff;
  border-radius:10px;
}
.agent-note{
  margin:12px 18px 16px;
  color:#9db8d3;
  font-size:10px;
}
.data-stage{
  min-height:calc(100vh - 150px);
  padding:24px;
  border:1px solid #a8c0df;
  border-radius:16px;
  background:
    linear-gradient(180deg,#ffffff82,#dbeaff6b),
    radial-gradient(ellipse at 72% 8%,#0c53b070,transparent 38%);
  color:var(--ink);
  box-shadow:0 22px 55px #517bab45;
  backdrop-filter:blur(20px);
}
.mission-heading{
  position:relative;
  min-height:164px;
  margin:-24px -24px 18px;
  padding:44px 26px 22px;
  border-radius:16px 16px 0 0;
  overflow:hidden;
  background:
    linear-gradient(105deg,#edf6ff 0 34%,#b4d0ee88 55%,#2e70b980 100%),
    radial-gradient(circle at 85% 35%,#ffffff,transparent 18%);
}
.mission-heading:after{
  content:'Higher Visibility\A Stronger Growth';
  white-space:pre;
  position:absolute;
  right:32px;
  top:42px;
  color:#fff;
  font-style:italic;
  font-size:13px;
  line-height:1.45;
  text-align:right;
}
.mission-heading p{color:#1865de;font-size:12px;letter-spacing:.12em}
.mission-heading h2{
  margin:12px 0 8px;
  font-size:34px;
  line-height:1.15;
  color:#061b55;
}
.mission-heading span{
  display:block;
  max-width:660px;
  color:#31598c;
  font-size:16px;
}
.stage-actions{
  position:absolute;
  right:22px;
  bottom:22px;
}
.stage-actions button{
  border:1px solid #afc6e6;
  background:#ffffff9e;
  color:#31547d;
  border-radius:10px;
}
.module-tabs{
  margin-top:-92px;
  margin-bottom:20px;
  padding:0 4px;
  grid-template-columns:repeat(4,minmax(150px,1fr));
  position:relative;
  z-index:2;
}
.module-tabs button{
  min-height:64px;
  border:1px solid #c2d5ef;
  border-radius:10px;
  background:#f6fbffda;
  color:#071f4f;
  box-shadow:0 12px 22px #4d79aa26;
}
.module-tabs button.active{
  background:linear-gradient(135deg,#0d73ff,#0647d8);
  color:#fff;
  border-color:#408bff;
}
.module-tabs small{color:inherit;opacity:.68;font-size:11px}
.module-tabs b{font-size:18px}
.exploration-path{
  border-color:#bdd2ee;
  background:#f7fbffe0;
  color:#23456d;
}
.exploration-path button{
  background:#e8f2ff;
  color:#225a9e;
  border-color:#bfd4ef;
}
.exploration-path small{color:#7086a1}
.exploration-path b{color:#173962;font-size:12px}
.panorama-content{gap:18px}
.decision-summary{
  grid-template-columns:minmax(0,1.1fr) minmax(320px,.9fr);
  gap:16px;
}
.decision-summary>article{
  min-height:138px;
  border:0;
  border-radius:12px;
  padding:16px;
  color:#092054;
  box-shadow:0 14px 30px #6c8bb12e;
}
.outcome-summary{
  background:linear-gradient(110deg,#e1fff7,#f7ffff)!important;
}
.attention-summary{
  background:linear-gradient(110deg,#fff1f4,#fff9fb)!important;
}
.decision-summary h3{font-size:18px;color:#061b55}
.decision-summary header small{font-size:12px;color:#516b91}
.decision-summary header>span{
  border-color:#a8d9d0;
  color:#0c8b76;
  background:#ffffff99;
}
.attention-summary header>span{
  border-color:#fac4cf;
  color:#e92a55;
}
.summary-items{grid-template-columns:repeat(3,minmax(0,1fr))}
.summary-items button,
.attention-items button{
  border:0;
  border-radius:10px;
  background:#fff;
  box-shadow:0 10px 24px #7190b326;
}
.summary-items button>small{color:#0b5ddf}
.summary-items button>strong{font-size:26px;color:#071f55}
.summary-items button>span{font-size:12px;color:#335178}
.summary-items button>em{color:#126bff}
.attention-items button{
  background:#fff;
  color:#071f55;
}
.attention-items button>b{color:#f02f5f}
.attention-items button small{color:#7b5f69}
.attention-items button>em{color:#f02f5f}
.section-jumps{
  grid-template-columns:repeat(3,1fr);
}
.section-jumps button{
  height:48px;
  border:1px solid #b9d0ef;
  border-radius:10px;
  background:#ffffff99;
  color:#23466f;
}
.dashboard-group{
  border:0;
  padding:8px 2px 12px;
}
.dashboard-group small{color:#126bff}
.dashboard-group h3{font-size:20px;color:#183868}
.dashboard-group p{font-size:12px;color:#6780a2}
.metric-grid{
  grid-template-columns:repeat(auto-fit,minmax(236px,1fr));
  gap:14px;
}
.metric-grid :deep(.evidence-card){
  border:1px solid #bfd1eb;
  border-radius:10px;
  background:#ffffffd9;
  color:#071f55;
  box-shadow:0 16px 32px #6a89ad33;
}
.metric-grid :deep(.evidence-card:hover){
  border-color:#6fa5ec;
  box-shadow:0 20px 42px #4379c93b;
}
.metric-grid :deep(.module-name){color:#0b5ddf}
.metric-grid :deep(.read-status){color:#0ab99b}
.metric-grid :deep(.metric-title){color:#223f67;font-weight:700}
.metric-grid :deep(.metric-number){color:#061b55;font-size:34px}
.metric-grid :deep(.card-footer){
  color:#4a6384;
  border-top-color:#d6e4f5;
}
.metric-grid :deep(.card-footer button),
.metric-grid :deep(.expand-hint){color:#126bff}
.metric-grid :deep(.empty-trend),
.metric-grid :deep(.point-readout),
.metric-grid :deep(.coverage),
.metric-grid :deep(.rate-copy),
.metric-grid :deep(.visual-readout){color:#5a7395}
.metric-grid :deep(.baseline){stroke:#d5e4f6}
.metric-grid :deep(.trend-line){stroke:#126bff}
.metric-grid :deep(.trend-point){fill:#126bff}
.quality-grid article,
.ledger article{
  background:#ffffffba;
  border-color:#bed2ee;
  color:#092054;
  box-shadow:0 14px 28px #6f91bb26;
}
.quality-grid span,
.action-copy small,
.action-copy span{color:#5a7395}
.quality-grid p{color:#5a7395}
.quality-grid strong,
.action-copy b{color:#071f55}
.command-drawer{
  background:#f8fbffee;
  color:#082052;
  border-color:#b8cee8;
}
.command-drawer header small,
.command-drawer dt{color:#5f7a9f}
.command-drawer header button,
.drawer-actions button,
.scope-tools button{
  background:#e9f3ff;
  border-color:#bad0ec;
  color:#0c55ca;
}
.command-drawer dd,
.command-drawer>p,
.scope-tools p{color:#35547a}
.agent-fab{
  background:#071f55;
  color:#fff;
  border:0;
}
@media(max-width:1280px){
  .cockpit-shell{grid-template-columns:58px minmax(300px,330px) minmax(0,1fr);padding:10px}
  .command-bar{grid-template-columns:1fr;grid-column:2 / 4}
  .command-controls{justify-content:flex-start;flex-wrap:wrap}
  .workspace-toolbar{grid-column:2 / 4}
  .operations-grid{grid-template-columns:330px minmax(0,1fr)}
  .module-tabs{grid-template-columns:repeat(2,minmax(150px,1fr));margin-top:-54px}
}
@media(max-width:980px){
  .cockpit-shell{display:block;padding:10px}
  .app-rail{display:none}
  .command-bar,.workspace-toolbar,.operations-grid{display:flex;flex-direction:column;align-items:stretch}
  .agent-panel{position:relative;height:auto;min-height:560px}
  .data-stage{min-height:0}
  .decision-summary{grid-template-columns:1fr}
  .mission-heading{min-height:190px}
  .module-tabs{margin-top:-30px}
}
@media(max-width:640px){
  .command-controls label,.period-control{width:100%}
  .period-control,.date-range{flex-wrap:wrap}
  .mission-heading h2{font-size:28px}
  .summary-items,.section-jumps{grid-template-columns:1fr}
  .module-tabs{grid-template-columns:1fr}
}
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
<style scoped>
.operations-grid{grid-template-columns:360px minmax(0,1fr);gap:16px;margin:0}
.mode-data .operations-grid{grid-template-columns:1fr}
.mode-chat .operations-grid{grid-template-columns:minmax(360px,720px)}
.agent-panel{height:calc(100vh - 32px);min-height:720px}
.decision-summary{grid-template-columns:minmax(0,1.1fr) minmax(320px,.9fr);gap:16px}
.decision-summary>article{min-height:138px;border:0;border-radius:12px;padding:16px;color:#092054;box-shadow:0 14px 30px #6c8bb12e}
.outcome-summary{background:linear-gradient(110deg,#e1fff7,#f7ffff)!important}
.attention-summary{background:linear-gradient(110deg,#fff1f4,#fff9fb)!important}
.decision-summary h3{font-size:18px;color:#061b55}
.decision-summary header small{font-size:12px;color:#516b91}
.decision-summary header>span{border-color:#a8d9d0;color:#0c8b76;background:#ffffff99}
.attention-summary header>span{border-color:#fac4cf;color:#e92a55}
.summary-items button,.attention-items button{border:0;border-radius:10px;background:#fff;color:#071f55;box-shadow:0 10px 24px #7190b326}
.summary-items button>small{color:#0b5ddf}
.summary-items button>strong{font-size:26px;color:#071f55}
.summary-items button>span{font-size:12px;color:#335178}
.summary-items button>em{color:#126bff}
.attention-items button>b{color:#f02f5f}
.attention-items button small{color:#7b5f69}
.attention-items button>em{color:#f02f5f}
.section-jumps button{height:48px;border:1px solid #b9d0ef;border-radius:10px;background:#ffffff99;color:#23466f}
.dashboard-group{border:0;padding:8px 2px 12px}
.dashboard-group small{color:#126bff}
.dashboard-group h3{font-size:20px;color:#183868}
.dashboard-group p{font-size:12px;color:#6780a2}
@media(max-width:1280px){.operations-grid{grid-template-columns:330px minmax(0,1fr)}}
@media(max-width:980px){.operations-grid{grid-template-columns:1fr}.agent-panel{height:auto;min-height:560px}.decision-summary{grid-template-columns:1fr}}
@media(max-width:680px){.summary-items,.section-jumps{grid-template-columns:1fr}.attention-items button{grid-template-columns:34px minmax(0,1fr)}}
</style>
<style scoped>
.cockpit-shell{
  grid-template-columns:64px 360px minmax(0,1fr) !important;
  grid-template-rows:88px 52px minmax(0,1fr) !important;
  gap:14px 16px !important;
  padding:12px 18px 18px !important;
  min-width:1180px;
  overflow:auto !important;
}
.command-bar{
  grid-column:2 / 4 !important;
  grid-row:1 !important;
  grid-template-columns:360px auto minmax(0,1fr) !important;
  align-items:center !important;
  height:88px;
}
.brand-block{
  align-self:center;
  min-width:0;
  padding-left:0;
  color:#0a2557 !important;
}
.back-link{
  color:#6c84a6 !important;
  opacity:1 !important;
}
.brand-line h1,
.brand-line p{
  color:#0a2557 !important;
  text-shadow:none !important;
}
.brand-line p{
  color:#5c74a0 !important;
}
.live-badge{
  justify-self:start;
}
.command-controls{
  min-width:0;
  display:flex !important;
  align-items:center !important;
  justify-content:flex-end !important;
  flex-wrap:nowrap !important;
}
.period-control{
  min-width:0 !important;
  max-width:600px;
}
.date-range input{
  width:118px !important;
}
.refresh-button{
  flex:0 0 auto;
  width:104px;
  height:44px !important;
  white-space:normal;
  line-height:1.15;
}
.workspace-toolbar{
  grid-column:3 !important;
  grid-row:2 !important;
  align-self:end;
  height:52px;
  border-bottom:1px solid #6f8eb9 !important;
}
.page-tabs button{
  height:52px !important;
}
.view-tools{
  flex:0 0 auto;
}
.operations-grid{
  grid-column:2 / 4 !important;
  grid-row:3 !important;
  grid-template-columns:360px minmax(0,1fr) !important;
  gap:16px !important;
  align-items:start !important;
  margin:0 !important;
}
.agent-panel{
  grid-column:auto;
  position:sticky !important;
  top:12px !important;
  height:calc(100vh - 132px) !important;
  min-height:650px !important;
}
.data-stage{
  min-width:0;
  min-height:calc(100vh - 166px) !important;
  padding:20px !important;
  overflow:hidden;
}
.mission-heading{
  display:flex !important;
  align-items:flex-start !important;
  justify-content:space-between !important;
  min-height:188px !important;
  margin:0 0 18px !important;
  padding:34px 26px 28px !important;
  border-radius:16px !important;
}
.mission-heading h2{
  max-width:640px;
  font-size:34px !important;
  line-height:1.12 !important;
}
.mission-heading span{
  max-width:680px;
}
.stage-actions{
  position:absolute !important;
  right:22px !important;
  bottom:22px !important;
}
.exploration-path{
  margin:0 0 12px !important;
}
.module-tabs{
  position:relative !important;
  z-index:1 !important;
  grid-template-columns:repeat(4,minmax(150px,1fr)) !important;
  gap:12px !important;
  margin:0 0 18px !important;
  padding:0 !important;
}
.module-tabs button{
  min-height:72px !important;
}
.decision-summary{
  grid-template-columns:minmax(0,1.2fr) minmax(360px,.8fr) !important;
  gap:16px !important;
}
.decision-summary>article{
  min-height:210px !important;
}
.summary-items{
  grid-template-columns:repeat(3,minmax(0,1fr)) !important;
}
.summary-items button{
  min-height:120px;
}
.attention-items{
  gap:10px !important;
}
.attention-items button{
  min-height:58px;
}
.section-jumps{
  margin-top:2px;
}
.dashboard-section{
  padding-top:10px;
}
.dashboard-group{
  margin:0 0 10px !important;
}
.metric-grid{
  grid-template-columns:repeat(4,minmax(190px,1fr)) !important;
  gap:12px !important;
}
.metric-grid :deep(.evidence-card){
  min-height:190px;
}
.command-drawer{
  z-index:40;
}
@media(max-width:1380px){
  .cockpit-shell{
    grid-template-columns:58px 330px minmax(0,1fr) !important;
    min-width:1080px;
  }
  .command-bar{
    grid-template-columns:330px auto minmax(0,1fr) !important;
  }
  .operations-grid{
    grid-template-columns:330px minmax(0,1fr) !important;
  }
  .period-control{
    max-width:520px;
  }
  .metric-grid{
    grid-template-columns:repeat(3,minmax(200px,1fr)) !important;
  }
}
@media(max-width:980px){
  .cockpit-shell{
    display:block !important;
    min-width:0;
    padding:10px !important;
  }
  .app-rail{
    display:none !important;
  }
  .command-bar,
  .workspace-toolbar,
  .operations-grid{
    display:flex !important;
    flex-direction:column !important;
    height:auto !important;
  }
  .command-controls{
    flex-wrap:wrap !important;
    justify-content:flex-start !important;
  }
  .agent-panel{
    position:relative !important;
    height:auto !important;
    min-height:560px !important;
  }
  .data-stage{
    min-height:0 !important;
  }
  .decision-summary,
  .module-tabs,
  .summary-items,
  .metric-grid{
    grid-template-columns:1fr !important;
  }
}
</style>
<style scoped>
.mission-heading{
  min-height:156px !important;
  padding:28px 24px 64px !important;
  margin-bottom:10px !important;
}
.mission-heading h2{
  font-size:30px !important;
  margin:8px 0 6px !important;
}
.mission-heading p{
  font-size:11px !important;
}
.mission-heading span{
  font-size:14px !important;
}
.stage-actions button{
  height:30px;
  padding:0 12px !important;
  font-size:11px !important;
}
.module-tabs{
  margin:-58px 0 10px !important;
  gap:8px !important;
}
.module-tabs button{
  min-height:50px !important;
  padding:8px 11px !important;
}
.module-tabs span{
  font-size:11px !important;
}
.module-tabs small{
  font-size:10px !important;
}
.panorama-content{
  gap:10px !important;
}
.decision-summary{
  grid-template-columns:minmax(0,1.08fr) minmax(400px,.92fr) !important;
  gap:10px !important;
}
.decision-summary>article{
  min-height:116px !important;
  padding:12px 14px !important;
}
.decision-summary>article>header{
  margin-bottom:8px !important;
}
.decision-summary header small{
  font-size:10px !important;
}
.decision-summary h3{
  font-size:16px !important;
}
.decision-summary header>span{
  padding:3px 8px !important;
  font-size:10px !important;
}
.summary-items{
  gap:8px !important;
}
.summary-items button{
  min-height:74px !important;
  padding:9px 10px !important;
}
.summary-items button>small{
  font-size:9px !important;
}
.summary-items button>strong{
  font-size:22px !important;
  line-height:1.05 !important;
  margin:4px 0 2px !important;
}
.summary-items button>span{
  font-size:11px !important;
}
.summary-items button>em{
  margin-top:4px !important;
  font-size:9px !important;
}
.attention-items{
  gap:8px !important;
}
.attention-items button{
  grid-template-columns:34px minmax(0,1fr) auto !important;
  min-height:46px !important;
  padding:8px 10px !important;
}
.attention-items button>b{
  font-size:22px !important;
}
.attention-items button strong{
  font-size:11px !important;
}
.decision-summary article>footer{
  padding-top:6px !important;
  font-size:9px !important;
}
.dashboard-section{
  padding-top:6px !important;
}
.dashboard-group{
  padding:8px 2px 6px !important;
  margin-bottom:8px !important;
}
.dashboard-group h3{
  font-size:17px !important;
}
.dashboard-group p{
  font-size:10px !important;
}
.metric-grid{
  grid-template-columns:repeat(4,minmax(168px,1fr)) !important;
  gap:10px !important;
  padding-bottom:8px !important;
}
.metric-grid :deep(.evidence-card){
  min-height:150px !important;
  padding:12px !important;
}
.metric-grid :deep(.card-heading){
  gap:8px;
}
.metric-grid :deep(.module-name),
.metric-grid :deep(.read-status){
  font-size:10px !important;
}
.metric-grid :deep(.metric-trigger){
  padding:8px 0 2px !important;
}
.metric-grid :deep(.metric-title){
  font-size:13px !important;
}
.metric-grid :deep(.metric-number){
  font-size:28px !important;
  line-height:1.08 !important;
}
.metric-grid :deep(.metric-change){
  display:block;
  margin-top:4px;
  color:#0ab98f !important;
  font-size:11px !important;
}
.metric-grid :deep(.expand-hint){
  right:0;
  bottom:4px;
  font-size:10px !important;
}
.metric-grid :deep(.metric-visual){
  margin-top:4px !important;
  padding:0 !important;
}
.metric-grid :deep(.trend){
  height:48px !important;
}
.metric-grid :deep(.trend-scrubber){
  height:48px;
}
.metric-grid :deep(.coverage),
.metric-grid :deep(.visual-readout),
.metric-grid :deep(.point-readout){
  display:none !important;
}
.metric-grid :deep(.card-footer){
  margin-top:6px !important;
  padding-top:7px !important;
  font-size:10px !important;
}
.metric-grid :deep(.card-actions){
  gap:8px !important;
}
.metric-grid :deep(.card-actions button:first-child){
  display:none !important;
}
.metric-grid :deep(.card-footer>span){
  white-space:nowrap;
}
.data-stage{
  padding-bottom:10px !important;
}
@media(max-width:1380px){
  .decision-summary{
    grid-template-columns:minmax(0,1fr) minmax(330px,.9fr) !important;
  }
  .metric-grid{
    grid-template-columns:repeat(3,minmax(180px,1fr)) !important;
  }
}
</style>
<style scoped>
.cockpit-shell{
  grid-template-columns:54px 300px minmax(0,1fr) !important;
  grid-template-rows:44px 40px minmax(0,1fr) !important;
  gap:6px 12px !important;
  padding:8px 12px 12px !important;
}
.command-bar{
  grid-template-columns:300px minmax(0,1fr) !important;
  height:44px !important;
}
.brand-block,
.brand-line{
  height:44px;
}
.brand-mark{
  width:30px !important;
  height:30px !important;
}
.brand-line h1{
  font-size:18px !important;
}
.brand-line p{
  font-size:9px !important;
}
.command-controls{
  height:38px !important;
  grid-template-columns:minmax(130px,170px) minmax(180px,220px) minmax(330px,1fr) 96px !important;
  gap:5px !important;
  padding:2px !important;
}
.command-controls label,
.period-control{
  height:34px !important;
  border-radius:6px !important;
}
.command-controls label{
  padding:0 8px !important;
}
.period-control{
  grid-template-columns:auto auto minmax(190px,1fr) !important;
  padding:0 8px !important;
}
.period-shortcuts{
  grid-template-columns:repeat(3,40px) !important;
}
.period-shortcuts button,
.date-range input,
.apply-period{
  height:26px !important;
}
.date-range input{
  width:92px !important;
}
.apply-period{
  width:36px !important;
}
.refresh-button{
  width:96px !important;
  height:34px !important;
}
.workspace-toolbar{
  height:40px !important;
  border-bottom-color:#86a4cc !important;
}
.page-tabs,
.page-tabs button{
  height:40px !important;
}
.page-tabs button{
  min-width:96px !important;
  padding:0 14px !important;
  font-size:11px !important;
}
.view-tools{
  height:34px !important;
  padding:2px 6px !important;
}
.view-tools .key-help{
  max-width:170px;
}
.view-tools button{
  width:28px !important;
  height:28px !important;
}
.operations-grid{
  grid-template-columns:300px minmax(0,1fr) !important;
  gap:12px !important;
}
.agent-panel{
  margin-top:-50px !important;
  height:calc(100vh - 18px) !important;
  min-height:700px !important;
}
.agent-head{
  padding:14px 14px 10px !important;
  gap:9px !important;
}
.agent-orb{
  width:38px !important;
  height:38px !important;
}
.agent-head span{
  font-size:10px !important;
}
.agent-head strong{
  font-size:16px !important;
}
.agent-head em{
  font-size:10px !important;
}
.messages{
  padding:8px 14px !important;
  gap:10px !important;
}
.message{
  max-width:94% !important;
  padding:10px 12px !important;
  border-radius:12px !important;
}
.message p{
  font-size:12px !important;
  line-height:1.58 !important;
}
.guides{
  padding:0 14px 10px !important;
  gap:7px !important;
}
.guides button{
  min-height:40px !important;
  padding:8px 10px !important;
  border-radius:10px !important;
  font-size:12px !important;
}
.composer{
  margin:0 14px !important;
  padding:8px !important;
}
.composer textarea{
  min-height:66px !important;
  font-size:12px !important;
}
.agent-note{
  margin:8px 14px 10px !important;
}
.data-stage{
  min-height:calc(100vh - 106px) !important;
  padding:0 16px 12px !important;
}
.mission-heading{
  min-height:118px !important;
  margin:0 -16px 8px !important;
  padding:22px 22px 48px !important;
}
.mission-heading h2{
  font-size:26px !important;
  margin:6px 0 5px !important;
}
.mission-heading p{
  font-size:10px !important;
}
.mission-heading span{
  max-width:620px;
  font-size:13px !important;
}
.mission-heading:after{
  top:28px !important;
  right:26px !important;
  font-size:12px !important;
}
.stage-actions{
  right:18px !important;
  bottom:16px !important;
}
.stage-actions button{
  height:26px !important;
  padding:0 10px !important;
  font-size:10px !important;
}
.module-tabs{
  margin:-42px 0 8px !important;
  gap:7px !important;
}
.module-tabs button{
  min-height:42px !important;
  padding:7px 10px !important;
}
.module-tabs span,
.module-tabs small{
  font-size:10px !important;
}
.module-tabs b{
  font-size:16px !important;
}
.decision-summary{
  gap:8px !important;
}
.decision-summary>article{
  min-height:96px !important;
  padding:10px 12px !important;
  border-radius:10px !important;
}
.decision-summary>article>header{
  margin-bottom:6px !important;
}
.decision-summary h3{
  font-size:15px !important;
}
.decision-summary header small,
.decision-summary header>span{
  font-size:9px !important;
}
.summary-items{
  gap:6px !important;
}
.summary-items button{
  min-height:62px !important;
  padding:7px 9px !important;
  border-radius:8px !important;
}
.summary-items button>small,
.summary-items button>em{
  font-size:8px !important;
}
.summary-items button>strong{
  font-size:20px !important;
}
.summary-items button>span{
  font-size:10px !important;
}
.attention-items{
  gap:6px !important;
}
.attention-items button{
  min-height:42px !important;
  padding:6px 9px !important;
  border-radius:8px !important;
}
.attention-items button>b{
  font-size:20px !important;
}
.attention-items button strong{
  font-size:10px !important;
}
.attention-items button small{
  font-size:8px !important;
}
.decision-summary article>footer{
  display:none !important;
}
.dashboard-section{
  padding-top:2px !important;
}
.dashboard-group{
  padding:5px 2px 4px !important;
  margin-bottom:6px !important;
}
.dashboard-group h3{
  font-size:15px !important;
}
.dashboard-group p{
  font-size:9px !important;
}
.metric-grid{
  grid-template-columns:repeat(4,minmax(156px,1fr)) !important;
  gap:8px !important;
}
.metric-grid :deep(.evidence-card){
  min-height:132px !important;
  padding:10px !important;
}
.metric-grid :deep(.metric-title){
  font-size:12px !important;
}
.metric-grid :deep(.metric-number){
  font-size:25px !important;
}
.metric-grid :deep(.metric-change){
  font-size:10px !important;
}
.metric-grid :deep(.trend),
.metric-grid :deep(.trend-scrubber){
  height:34px !important;
}
.metric-grid :deep(.card-footer){
  margin-top:4px !important;
  padding-top:5px !important;
  font-size:9px !important;
}
.metric-grid :deep(.card-footer>span){
  max-width:120px;
  overflow:hidden;
  text-overflow:ellipsis;
}
@media(max-width:1380px){
  .cockpit-shell{
    grid-template-columns:54px 290px minmax(0,1fr) !important;
  }
  .command-bar,
  .operations-grid{
    grid-template-columns:290px minmax(0,1fr) !important;
  }
  .command-controls{
    grid-template-columns:minmax(116px,145px) minmax(150px,190px) minmax(280px,1fr) 90px !important;
  }
  .period-shortcuts{
    grid-template-columns:repeat(3,36px) !important;
  }
  .date-range input{
    width:86px !important;
  }
  .refresh-button{
    width:90px !important;
  }
}
</style>
<style scoped>
.cockpit-shell{
  grid-template-rows:74px 54px minmax(0,1fr) !important;
  gap:10px 16px !important;
}
.command-bar{
  height:74px !important;
  grid-template-columns:360px minmax(0,1fr) !important;
}
.brand-block{
  grid-column:1;
}
.brand-line h1{
  font-size:24px !important;
}
.brand-line p{
  font-size:12px !important;
}
.live-badge{
  display:none !important;
}
.command-controls{
  grid-column:2;
  justify-self:end;
  display:grid !important;
  grid-template-columns:minmax(210px,260px) minmax(500px,1fr) 120px;
  gap:10px !important;
  width:min(100%,980px);
  padding:10px !important;
  border:1px solid #b8cdec;
  border-radius:14px;
  background:#eef6ffb8;
  box-shadow:inset 0 1px #fff,0 14px 32px #5b85bc24;
  backdrop-filter:blur(16px);
}
.command-controls label,
.period-control{
  height:42px;
  min-width:0 !important;
  padding:0 12px !important;
  border:0 !important;
  border-radius:10px !important;
  background:#ffffff82 !important;
  box-shadow:none !important;
}
.command-controls label{
  display:grid !important;
  grid-template-columns:auto minmax(0,1fr);
  align-items:center;
  gap:10px !important;
  font-size:12px !important;
  font-weight:700;
}
.command-controls select{
  width:100%;
  min-width:0;
  font-size:12px;
  text-overflow:ellipsis;
}
.period-control{
  display:grid !important;
  grid-template-columns:auto auto minmax(255px,1fr);
  align-items:center !important;
  gap:12px !important;
}
.period-control>span{
  font-size:12px !important;
  font-weight:800 !important;
  white-space:nowrap;
}
.period-shortcuts{
  display:grid !important;
  grid-template-columns:repeat(3,54px);
  gap:4px !important;
}
.period-shortcuts button{
  height:30px !important;
  padding:0 !important;
  font-size:12px !important;
  line-height:1.05;
}
.date-range{
  justify-content:end;
  gap:8px !important;
  min-width:0;
}
.date-range input{
  width:120px !important;
  height:30px !important;
  font-size:12px;
}
.apply-period{
  width:46px;
  height:32px !important;
  padding:0 !important;
}
.refresh-button{
  width:120px !important;
  height:42px !important;
  padding:0 12px !important;
  border-radius:10px !important;
  white-space:nowrap !important;
}
.workspace-toolbar{
  height:54px !important;
  align-self:stretch;
  padding:0 8px 0 0 !important;
  border-bottom:1px solid #8da8cf !important;
}
.page-tabs{
  align-self:end;
  height:54px;
  display:flex !important;
  align-items:flex-end !important;
}
.page-tabs button{
  height:48px !important;
  min-width:112px !important;
  padding:0 18px !important;
}
.view-tools{
  align-self:center;
  height:42px;
  padding:4px 8px !important;
}
.view-tools .key-help{
  display:inline-flex;
  max-width:220px;
  overflow:hidden;
  text-overflow:ellipsis;
  white-space:nowrap;
}
.view-tools button{
  width:32px !important;
  height:32px !important;
}
.data-stage{
  min-height:calc(100vh - 150px) !important;
}
@media(max-width:1380px){
  .command-bar{
    grid-template-columns:330px minmax(0,1fr) !important;
  }
  .command-controls{
    grid-template-columns:minmax(190px,230px) minmax(430px,1fr) 112px;
    width:min(100%,880px);
  }
  .period-control{
    grid-template-columns:auto auto minmax(220px,1fr);
  }
  .period-shortcuts{
    grid-template-columns:repeat(3,48px);
  }
  .date-range input{
    width:108px !important;
  }
  .refresh-button{
    width:112px !important;
  }
}
@media(max-width:1120px){
  .command-bar{
    height:auto !important;
    grid-template-columns:1fr !important;
  }
  .command-controls{
    grid-column:1;
    justify-self:stretch;
    width:100%;
    grid-template-columns:1fr;
  }
  .period-control{
    grid-template-columns:1fr;
    height:auto;
    padding:10px 12px !important;
  }
  .date-range{
    justify-content:start;
  }
  .workspace-toolbar{
    height:auto !important;
    flex-wrap:wrap;
  }
}
</style>
<style scoped>
.cockpit-shell{
  grid-template-columns:54px 330px minmax(0,1fr) !important;
  grid-template-rows:48px 48px minmax(0,1fr) !important;
  gap:8px 14px !important;
  padding:10px 14px 14px !important;
  background:
    radial-gradient(circle at 78% 36%,#eaf6ff 0 8%,transparent 30%),
    radial-gradient(circle at 56% 60%,#7ed7ff73 0 8%,transparent 28%),
    linear-gradient(135deg,#dcecff 0%,#b7d2ee 43%,#7aa9d7 100%) !important;
}
.app-rail{
  width:54px;
  padding:8px 6px !important;
  border-radius:14px !important;
}
.app-rail button{
  width:42px !important;
  min-height:50px !important;
  border-radius:10px !important;
}
.command-bar{
  grid-column:2 / 4 !important;
  grid-row:1 !important;
  grid-template-columns:330px minmax(0,1fr) !important;
  height:48px !important;
}
.brand-block{
  height:48px;
  display:flex;
  align-items:center;
  gap:10px;
}
.back-link{
  display:none !important;
}
.brand-line{
  gap:10px !important;
}
.brand-mark{
  width:34px !important;
  height:34px !important;
  font-size:15px;
}
.brand-line p{
  font-size:10px !important;
  line-height:1;
}
.brand-line h1{
  margin-top:2px !important;
  font-size:20px !important;
  line-height:1.1;
}
.command-controls{
  grid-template-columns:minmax(150px,190px) minmax(190px,230px) minmax(360px,1fr) 104px !important;
  width:min(100%,1040px) !important;
  height:42px;
  padding:4px !important;
  gap:6px !important;
  border-radius:8px !important;
  background:transparent !important;
  border:0 !important;
  box-shadow:none !important;
  backdrop-filter:none !important;
}
.command-controls label,
.period-control{
  height:38px !important;
  border:1px solid #aac3e7 !important;
  border-radius:6px !important;
  background:#edf6ffdb !important;
  box-shadow:inset 0 1px #fff !important;
}
.command-controls label{
  padding:0 10px !important;
  grid-template-columns:auto minmax(0,1fr);
  font-size:11px !important;
}
.command-controls select{
  font-size:11px !important;
}
.period-control{
  grid-template-columns:auto auto minmax(210px,1fr) !important;
  padding:0 9px !important;
  gap:8px !important;
}
.period-control>span{
  font-size:11px !important;
}
.period-shortcuts{
  grid-template-columns:repeat(3,48px) !important;
}
.period-shortcuts button{
  height:28px !important;
  font-size:11px !important;
  border-radius:6px !important;
}
.date-range{
  gap:6px !important;
}
.date-range input{
  width:104px !important;
  height:28px !important;
  font-size:11px !important;
}
.apply-period{
  width:40px !important;
  height:28px !important;
  font-size:11px !important;
}
.refresh-button{
  width:104px !important;
  height:38px !important;
  border-radius:6px !important;
  font-size:12px !important;
}
.workspace-toolbar{
  grid-column:3 !important;
  grid-row:2 !important;
  height:48px !important;
  padding:0 !important;
  border-bottom:1px solid #7e9ec8 !important;
}
.page-tabs{
  height:48px;
}
.page-tabs button{
  height:44px !important;
  min-width:110px !important;
  border-radius:10px 10px 0 0 !important;
  font-size:12px !important;
}
.view-tools{
  height:38px !important;
  border-radius:10px !important;
  padding:3px 7px !important;
  background:#edf6ffb5 !important;
}
.view-tools .key-help{
  max-width:190px;
  font-size:10px;
}
.view-tools span:not(.key-help){
  font-size:10px;
}
.operations-grid{
  grid-column:2 / 4 !important;
  grid-row:3 !important;
  grid-template-columns:330px minmax(0,1fr) !important;
  gap:14px !important;
}
.agent-panel{
  margin-top:-56px;
  height:calc(100vh - 24px) !important;
  min-height:760px !important;
  border-radius:10px !important;
}
.agent-head{
  padding:18px 18px 14px !important;
}
.agent-orb{
  width:42px !important;
  height:42px !important;
}
.agent-head strong{
  font-size:18px !important;
}
.context-ribbon{
  display:none !important;
}
.messages{
  padding-top:8px !important;
}
.data-stage{
  min-height:calc(100vh - 118px) !important;
  padding:0 18px 18px !important;
  border-radius:10px !important;
  background:
    linear-gradient(180deg,#edf7ff78,#cce2f780),
    radial-gradient(ellipse at 56% 28%,#ffffff99,transparent 30%) !important;
  box-shadow:0 18px 42px #4e76a538 !important;
}
.mission-heading{
  min-height:178px !important;
  margin:0 -18px 14px !important;
  padding:30px 24px 78px !important;
  border-radius:10px 10px 0 0 !important;
}
.mission-heading h2{
  font-size:32px !important;
}
.mission-heading span{
  font-size:15px !important;
}
.stage-actions{
  right:20px !important;
  bottom:20px !important;
}
.exploration-path{
  display:none !important;
}
.module-tabs{
  margin:-68px 0 14px !important;
  padding:0 2px !important;
  grid-template-columns:1.15fr repeat(3,1fr) !important;
  gap:10px !important;
}
.module-tabs button{
  min-height:54px !important;
  border-radius:8px !important;
  padding:9px 12px !important;
}
.module-tabs b{
  font-size:18px !important;
}
.decision-summary{
  grid-template-columns:minmax(0,1.08fr) minmax(360px,.92fr) !important;
  gap:14px !important;
}
.decision-summary>article{
  min-height:126px !important;
  padding:14px !important;
}
.decision-summary h3{
  font-size:17px !important;
}
.summary-items button{
  min-height:80px !important;
  padding:10px !important;
}
.summary-items button>strong{
  font-size:23px !important;
  margin:5px 0 2px !important;
}
.attention-items button{
  min-height:50px !important;
  padding:8px 10px !important;
}
.section-jumps{
  display:none !important;
}
.metric-grid{
  grid-template-columns:repeat(4,minmax(176px,1fr)) !important;
  gap:10px !important;
}
.metric-grid :deep(.evidence-card){
  min-height:170px !important;
  border-radius:8px !important;
}
@media(max-width:1380px){
  .cockpit-shell{
    grid-template-columns:54px 320px minmax(0,1fr) !important;
  }
  .command-bar{
    grid-template-columns:320px minmax(0,1fr) !important;
  }
  .operations-grid{
    grid-template-columns:320px minmax(0,1fr) !important;
  }
  .command-controls{
    grid-template-columns:minmax(132px,160px) minmax(160px,200px) minmax(320px,1fr) 100px !important;
  }
  .period-shortcuts{
    grid-template-columns:repeat(3,42px) !important;
  }
  .date-range input{
    width:96px !important;
  }
  .metric-grid{
    grid-template-columns:repeat(3,minmax(190px,1fr)) !important;
  }
}
</style>
<style scoped>
/* Final cockpit density pass: keep this block last so older prototype layers cannot re-expand the layout. */
.cockpit-shell{
  grid-template-columns:54px 300px minmax(0,1fr) !important;
  grid-template-rows:44px 40px minmax(0,1fr) !important;
  gap:6px 12px !important;
  padding:8px 12px 12px !important;
}
.command-bar{grid-template-columns:300px minmax(0,1fr) !important;height:44px !important}
.brand-block,.brand-line{height:44px}
.brand-mark{width:30px !important;height:30px !important}
.brand-line h1{font-size:18px !important}
.brand-line p{font-size:9px !important}
.command-controls{
  grid-template-columns:minmax(130px,170px) minmax(180px,220px) minmax(330px,1fr) 96px !important;
  height:38px !important;
  gap:5px !important;
  padding:2px !important;
}
.command-controls label,.period-control{height:34px !important;border-radius:6px !important}
.command-controls label{padding:0 8px !important}
.period-control{grid-template-columns:auto auto minmax(190px,1fr) !important;padding:0 8px !important}
.period-shortcuts{grid-template-columns:repeat(3,40px) !important}
.period-shortcuts button,.date-range input,.apply-period{height:26px !important}
.date-range input{width:92px !important}
.apply-period{width:36px !important}
.refresh-button{width:96px !important;height:34px !important}
.workspace-toolbar{height:40px !important}
.page-tabs,.page-tabs button{height:40px !important}
.page-tabs button{min-width:96px !important;padding:0 14px !important;font-size:11px !important}
.view-tools{height:34px !important;padding:2px 6px !important}
.view-tools .key-help{max-width:170px}
.view-tools button{width:28px !important;height:28px !important}
.operations-grid{grid-template-columns:300px minmax(0,1fr) !important;gap:12px !important}
.agent-panel{margin-top:-50px !important;height:calc(100vh - 18px) !important;min-height:700px !important}
.agent-head{padding:14px 14px 10px !important;gap:9px !important}
.agent-orb{width:38px !important;height:38px !important}
.agent-head span,.agent-head em{font-size:10px !important}
.agent-head strong{font-size:16px !important}
.messages{padding:8px 14px !important;gap:10px !important}
.message{padding:10px 12px !important;border-radius:12px !important}
.message p{font-size:12px !important;line-height:1.58 !important}
.guides{padding:0 14px 10px !important;gap:7px !important}
.guides button{min-height:40px !important;padding:8px 10px !important;border-radius:10px !important;font-size:12px !important}
.composer{margin:0 14px !important;padding:8px !important}
.composer textarea{min-height:66px !important;font-size:12px !important}
.agent-note{margin:8px 14px 10px !important}
.data-stage{min-height:calc(100vh - 106px) !important;padding:0 16px 12px !important}
.mission-heading{min-height:118px !important;margin:0 -16px 8px !important;padding:22px 22px 48px !important}
.mission-heading h2{font-size:26px !important;margin:6px 0 5px !important}
.mission-heading p{font-size:10px !important}
.mission-heading span{max-width:620px;font-size:13px !important}
.mission-heading:after{top:28px !important;right:26px !important;font-size:12px !important}
.stage-actions{right:18px !important;bottom:16px !important}
.stage-actions button{height:26px !important;padding:0 10px !important;font-size:10px !important}
.module-tabs{margin:-42px 0 8px !important;gap:7px !important}
.module-tabs button{min-height:42px !important;padding:7px 10px !important}
.module-tabs span,.module-tabs small{font-size:10px !important}
.module-tabs b{font-size:16px !important}
.decision-summary{gap:8px !important}
.decision-summary>article{min-height:96px !important;padding:10px 12px !important;border-radius:10px !important}
.decision-summary>article>header{margin-bottom:6px !important}
.decision-summary h3{font-size:15px !important}
.decision-summary header small,.decision-summary header>span{font-size:9px !important}
.summary-items{gap:6px !important}
.summary-items button{min-height:62px !important;padding:7px 9px !important;border-radius:8px !important}
.summary-items button>small,.summary-items button>em{font-size:8px !important}
.summary-items button>strong{font-size:20px !important}
.summary-items button>span{font-size:10px !important}
.attention-items{gap:6px !important}
.attention-items button{min-height:42px !important;padding:6px 9px !important;border-radius:8px !important}
.attention-items button>b{font-size:20px !important}
.attention-items button strong{font-size:10px !important}
.attention-items button small{font-size:8px !important}
.decision-summary article>footer{display:none !important}
.dashboard-section{padding-top:2px !important}
.dashboard-group{padding:5px 2px 4px !important;margin-bottom:6px !important}
.dashboard-group h3{font-size:15px !important}
.dashboard-group p{font-size:9px !important}
.metric-grid{grid-template-columns:repeat(4,minmax(156px,1fr)) !important;gap:8px !important}
.metric-grid :deep(.evidence-card){min-height:132px !important;padding:10px !important}
.metric-grid :deep(.metric-title){font-size:12px !important}
.metric-grid :deep(.metric-number){font-size:25px !important}
.metric-grid :deep(.metric-change){font-size:10px !important}
.metric-grid :deep(.trend),.metric-grid :deep(.trend-scrubber){height:34px !important}
.metric-grid :deep(.card-footer){margin-top:4px !important;padding-top:5px !important;font-size:9px !important}
.metric-grid :deep(.card-footer>span){max-width:120px;overflow:hidden;text-overflow:ellipsis}
@media(max-width:1380px){
  .cockpit-shell{grid-template-columns:54px 290px minmax(0,1fr) !important}
  .command-bar,.operations-grid{grid-template-columns:290px minmax(0,1fr) !important}
  .command-controls{grid-template-columns:minmax(116px,145px) minmax(150px,190px) minmax(280px,1fr) 90px !important}
  .period-shortcuts{grid-template-columns:repeat(3,36px) !important}
  .date-range input{width:86px !important}
  .refresh-button{width:90px !important}
}
</style>
<style scoped>
/* Actual final layout reset: remove the broken right rail and fill the canvas cleanly. */
.cockpit-shell{
  grid-template-columns:54px 330px minmax(0,1fr) !important;
  grid-template-rows:50px minmax(0,1fr) !important;
  gap:8px 12px !important;
  padding:10px 12px 12px !important;
}
.command-bar{
  grid-column:2 / 4 !important;
  grid-row:1 !important;
  grid-template-columns:330px minmax(0,1fr) !important;
  height:50px !important;
}
.operations-grid{
  grid-column:2 / 4 !important;
  grid-row:2 !important;
  grid-template-columns:330px minmax(0,1fr) !important;
  gap:12px !important;
  margin:0 !important;
}
.agent-panel,
.data-stage{
  height:calc(100vh - 74px) !important;
  min-height:0 !important;
  margin:0 !important;
}
.data-stage{
  padding:0 16px 16px !important;
}
.mission-heading{
  min-height:150px !important;
  margin:0 -16px 12px !important;
  padding:24px 26px 58px !important;
}
.module-tabs{
  margin:-54px 0 10px !important;
  grid-template-columns:1.2fr repeat(3,1fr) !important;
}
.panorama-content{
  display:block !important;
}
.cockpit-bottom-deck{
  display:none !important;
}
.decision-summary{
  display:grid !important;
  grid-template-columns:minmax(0,1.08fr) minmax(330px,.92fr) !important;
  gap:10px !important;
  margin-bottom:12px !important;
}
.decision-summary>article{
  min-height:108px !important;
  padding:10px 12px !important;
}
.summary-items button{
  min-height:58px !important;
}
.attention-items button{
  min-height:42px !important;
}
.dashboard-section{
  padding-top:0 !important;
}
.metric-grid{
  grid-template-columns:repeat(4,minmax(0,1fr)) !important;
  gap:10px !important;
}
.metric-grid :deep(.evidence-card){
  min-height:132px !important;
  padding:10px !important;
}
.metric-grid :deep(.metric-trigger){
  padding:8px 0 3px !important;
}
.metric-grid :deep(.metric-number){
  font-size:24px !important;
}
.metric-grid :deep(.trend),
.metric-grid :deep(.trend-scrubber){
  height:32px !important;
}
.metric-grid :deep(.card-actions button:first-child){
  display:none !important;
}
@media(max-width:1380px){
  .cockpit-shell{
    grid-template-columns:54px 310px minmax(0,1fr) !important;
  }
  .command-bar,
  .operations-grid{
    grid-template-columns:310px minmax(0,1fr) !important;
  }
  .metric-grid{
    grid-template-columns:repeat(4,minmax(0,1fr)) !important;
  }
}
</style>
<style scoped>
/* strict-reference-left: must stay at real EOF. */
.agent-panel{
  display:flex !important;
  flex-direction:column !important;
  height:calc(100vh - 74px) !important;
  min-height:0 !important;
  padding:0 !important;
  overflow:hidden !important;
  border-radius:9px !important;
  border:1px solid rgba(72,137,197,.42) !important;
  background:linear-gradient(180deg,#102d55 0%,#06182f 56%,#051123 100%) !important;
  box-shadow:inset 0 1px rgba(255,255,255,.09),0 22px 44px rgba(5,25,58,.34) !important;
}
.agent-panel>*{position:relative !important;z-index:1 !important}
.agent-head{
  flex:0 0 auto !important;
  min-height:64px !important;
  padding:17px 18px 8px !important;
  border:0 !important;
}
.agent-head .agent-orb{display:none !important}
.agent-head>div:nth-child(2){display:grid !important;gap:6px !important}
.agent-head strong{order:1 !important;color:#fff !important;font-size:20px !important;line-height:1 !important}
.agent-head span{order:2 !important;color:#a8bed5 !important;font-size:12px !important;letter-spacing:0 !important}
.agent-head em{
  position:absolute !important;
  top:21px !important;
  right:18px !important;
  margin:0 !important;
  padding:0 !important;
  color:#8af3e3 !important;
  font-size:11px !important;
  font-weight:700 !important;
}
.context-ribbon{display:none !important}
.intro-message{
  position:relative !important;
  flex:0 0 auto !important;
  min-height:68px !important;
  margin:8px 18px 12px 78px !important;
  padding:11px 12px !important;
  max-width:none !important;
  border-radius:8px !important;
  border:1px solid rgba(54,96,141,.72) !important;
  background:rgba(31,67,105,.68) !important;
  overflow:visible !important;
}
.intro-message:before{
  content:'' !important;
  position:absolute !important;
  left:-58px !important;
  top:50% !important;
  width:42px !important;
  height:42px !important;
  transform:translateY(-50%) !important;
  border-radius:16px !important;
  background:
    radial-gradient(circle at 34% 44%,#fff 0 4px,transparent 5px),
    radial-gradient(circle at 66% 44%,#fff 0 4px,transparent 5px),
    linear-gradient(180deg,#93dcff,#1e6dff) !important;
  box-shadow:0 0 0 4px rgba(55,139,255,.24),0 10px 24px rgba(10,90,220,.38) !important;
}
.intro-message small{display:none !important}
.intro-message p{margin:0 !important;color:#dbeaff !important;font-size:12px !important;line-height:1.52 !important}
.guide-title{
  flex:0 0 auto !important;
  padding:0 18px 8px !important;
  color:#f3f8ff !important;
  font-size:12px !important;
  font-weight:800 !important;
}
.guides{
  flex:0 0 auto !important;
  display:grid !important;
  grid-template-columns:1fr !important;
  gap:7px !important;
  padding:0 18px 12px !important;
}
.guides button{
  position:relative !important;
  display:flex !important;
  align-items:center !important;
  min-height:32px !important;
  padding:0 30px 0 42px !important;
  border-radius:8px !important;
  border:1px solid rgba(79,139,199,.58) !important;
  background:rgba(20,52,86,.78) !important;
  color:#dcecff !important;
  font-size:11px !important;
  font-weight:700 !important;
  line-height:1.2 !important;
  text-align:left !important;
}
.guides button:before{
  content:'+' !important;
  position:absolute !important;
  left:14px !important;
  top:50% !important;
  display:grid !important;
  place-items:center !important;
  width:16px !important;
  height:16px !important;
  margin-top:-8px !important;
  border:1px solid rgba(226,240,255,.9) !important;
  border-radius:50% !important;
  color:#eef8ff !important;
  font-size:11px !important;
}
.guides button:after{
  content:'›' !important;
  position:absolute !important;
  right:12px !important;
  top:50% !important;
  transform:translateY(-53%) !important;
  color:#d9ecff !important;
  font-size:20px !important;
}
.messages{
  flex:1 1 auto !important;
  min-height:0 !important;
  padding:0 18px 10px !important;
  gap:9px !important;
  overflow:auto !important;
}
.messages:empty{
  min-height:90px !important;
}
.message{
  position:relative !important;
  max-width:100% !important;
  padding:10px 12px !important;
  border-radius:8px !important;
  border:1px solid rgba(54,96,141,.72) !important;
  background:rgba(31,67,105,.68) !important;
}
.message small{display:block !important;margin-bottom:5px !important;color:#5ee5d4 !important;font-size:10px !important;font-weight:800 !important}
.message p{margin:0 !important;color:#dcecff !important;font-size:11px !important;line-height:1.42 !important;white-space:pre-line !important}
.message.user{
  align-self:flex-end !important;
  max-width:78% !important;
  min-width:178px !important;
  padding:10px 12px !important;
  border-color:rgba(48,133,255,.9) !important;
  border-radius:8px 8px 0 8px !important;
  background:linear-gradient(135deg,#147dff,#075eea) !important;
}
.message.user small{display:none !important}
.message.user p{font-size:12px !important;color:#fff !important}
.message.user:after{content:'10:24' !important;float:right !important;margin-left:14px !important;color:rgba(2,36,93,.68) !important;font-size:9px !important;line-height:16px !important}
.message-actions{display:flex !important;gap:5px !important;margin-top:8px !important}
.message-actions button{height:23px !important;padding:0 6px !important;border-radius:5px !important;border:1px solid rgba(59,124,211,.86) !important;background:rgba(13,55,111,.72) !important;color:#c8e5ff !important;font-size:9px !important}
.screen-applied{display:none !important}
.composer{
  flex:0 0 auto !important;
  position:relative !important;
  margin:0 18px 9px !important;
  padding:0 !important;
  border:0 !important;
  background:transparent !important;
}
.composer textarea{
  min-height:62px !important;
  max-height:62px !important;
  padding:11px 52px 11px 14px !important;
  border-radius:10px !important;
  border:1px solid rgba(191,214,239,.86) !important;
  background:#f4f9ff !important;
  color:#61738c !important;
  font-size:12px !important;
  line-height:1.4 !important;
}
.composer button{
  right:10px !important;
  bottom:8px !important;
  width:34px !important;
  height:34px !important;
  border-radius:8px !important;
  background:#126dff !important;
  color:#fff !important;
}
.agent-note{flex:0 0 auto !important;margin:0 18px 12px !important;color:#83a7c7 !important;font-size:9px !important}
</style>
<style scoped>
/* background-depth-pass: restore the atmospheric cockpit texture from the reference. */
.cockpit-shell{
  background:
    radial-gradient(circle at 56% 62%,rgba(69,145,255,.38) 0 7%,transparent 21%),
    radial-gradient(circle at 84% 8%,rgba(100,166,231,.46),transparent 34%),
    radial-gradient(circle at 8% 86%,rgba(35,125,211,.28),transparent 30%),
    linear-gradient(180deg,#d7eaff 0%,#acd1f0 52%,#83b6df 100%) !important;
}
.data-stage{
  position:relative !important;
  overflow:auto !important;
  isolation:isolate !important;
  border-color:rgba(255,255,255,.46) !important;
  background:
    linear-gradient(180deg,rgba(238,249,255,.42),rgba(124,180,222,.18)),
    radial-gradient(circle at 53% 55%,rgba(47,129,255,.34),transparent 14%),
    linear-gradient(180deg,rgba(186,218,243,.42),rgba(93,159,214,.22)) !important;
  box-shadow:inset 0 1px rgba(255,255,255,.82),0 22px 54px rgba(31,91,143,.22) !important;
}
.data-stage:before{
  content:'' !important;
  position:absolute !important;
  z-index:-2 !important;
  inset:0 !important;
  pointer-events:none !important;
  background:
    linear-gradient(166deg,transparent 12%,rgba(255,255,255,.46) 23%,rgba(39,118,220,.3) 33%,transparent 44%),
    linear-gradient(173deg,transparent 18%,rgba(249,253,255,.58) 31%,rgba(32,120,231,.34) 43%,transparent 56%),
    radial-gradient(ellipse at 50% 53%,rgba(18,111,235,.34) 0 2%,rgba(157,215,255,.4) 3%,transparent 11%),
    radial-gradient(ellipse at 47% 56%,transparent 0 6%,rgba(255,255,255,.42) 7%,transparent 12%) !important;
  filter:blur(.2px) !important;
  opacity:.92 !important;
}
.data-stage:after{
  content:'' !important;
  position:absolute !important;
  z-index:-1 !important;
  left:-4% !important;
  right:-4% !important;
  bottom:-90px !important;
  height:360px !important;
  pointer-events:none !important;
  background:
    radial-gradient(ellipse at 48% 25%,rgba(10,110,255,.38) 0 5%,transparent 18%),
    linear-gradient(158deg,transparent 0 24%,rgba(255,255,255,.3) 33%,rgba(21,99,189,.28) 43%,transparent 57%),
    linear-gradient(18deg,rgba(13,75,142,.14),transparent 42%) !important;
  opacity:.9 !important;
}
.mission-heading{
  position:relative !important;
  overflow:hidden !important;
  background:
    linear-gradient(90deg,rgba(240,250,255,.88) 0%,rgba(201,228,249,.7) 46%,rgba(96,158,219,.7) 100%) !important;
}
.mission-heading:before{
  content:'' !important;
  position:absolute !important;
  inset:-20px -30px auto 34% !important;
  height:156px !important;
  pointer-events:none !important;
  background:
    linear-gradient(168deg,transparent 16%,rgba(255,255,255,.76) 30%,rgba(33,120,227,.46) 39%,transparent 54%),
    linear-gradient(174deg,transparent 20%,rgba(255,255,255,.42) 34%,rgba(45,138,239,.36) 47%,transparent 62%) !important;
  opacity:.9 !important;
}
.module-tabs button,
.summary-items button,
.attention-items button,
.metric-grid :deep(.evidence-card){
  background:rgba(247,252,255,.76) !important;
  border-color:rgba(161,199,232,.72) !important;
  box-shadow:inset 0 1px rgba(255,255,255,.82),0 14px 28px rgba(43,102,158,.13) !important;
  backdrop-filter:blur(12px) !important;
}
.decision-summary>article{
  background:rgba(247,252,255,.62) !important;
  backdrop-filter:blur(14px) !important;
  box-shadow:inset 0 1px rgba(255,255,255,.76),0 16px 30px rgba(48,111,164,.16) !important;
}
.summary-card{
  background:linear-gradient(180deg,rgba(235,255,248,.78),rgba(240,252,255,.58)) !important;
}
.attention-card{
  background:linear-gradient(180deg,rgba(255,241,247,.78),rgba(255,250,252,.58)) !important;
}
.agent-panel{
  background:
    radial-gradient(ellipse at 16% 98%,rgba(17,106,202,.36),transparent 31%),
    linear-gradient(180deg,#102d55 0%,#071c36 48%,#041123 100%) !important;
}
.agent-panel:before{
  content:'' !important;
  position:absolute !important;
  z-index:0 !important;
  left:-70px !important;
  right:-40px !important;
  bottom:-30px !important;
  height:220px !important;
  pointer-events:none !important;
  background:
    radial-gradient(ellipse at 30% 76%,rgba(22,127,232,.46),transparent 28%),
    linear-gradient(163deg,transparent 14%,rgba(115,199,255,.16) 35%,rgba(11,82,167,.18) 47%,transparent 66%),
    linear-gradient(18deg,rgba(30,115,209,.18),transparent 55%) !important;
  opacity:.95 !important;
}
.agent-panel:after{
  content:'' !important;
  position:absolute !important;
  z-index:0 !important;
  inset:0 !important;
  pointer-events:none !important;
  background:linear-gradient(90deg,rgba(255,255,255,.05),transparent 18%,transparent 80%,rgba(255,255,255,.04)) !important;
}
.intro-message,
.guides button,
.message{
  background:rgba(29,66,105,.72) !important;
  backdrop-filter:blur(10px) !important;
}
</style>
<style scoped>
/* threeui-water-integration: use the original Elements / Water Element iframe as the cockpit background. */
.cockpit-shell{
  background:#060708 !important;
}
.water-element-backdrop{
  position:absolute !important;
  inset:0 !important;
  z-index:0 !important;
}
.water-element-backdrop:deep(.threeui-water-background){
  background:#060708 !important;
}
.water-element-backdrop:deep(iframe){
  transform:scale(1.08) !important;
  transform-origin:center !important;
}
.ambient,
.energy-field{
  display:none !important;
}
.command-bar,
.operations-grid{
  position:relative !important;
  z-index:1 !important;
}
.operations-grid{
  pointer-events:auto !important;
}
.agent-panel,
.command-controls,
.stage-actions,
.module-tabs button,
.summary-items button,
.attention-items button,
.metric-grid :deep(.evidence-card),
.ledger article,
.quality-grid article,
.data-empty,
.composer,
.guides button,
.message-actions button{
  pointer-events:auto !important;
}
.data-stage{
  background:transparent !important;
  border:0 !important;
  border-radius:0 !important;
  box-shadow:none !important;
  backdrop-filter:none !important;
  overflow:auto !important;
  pointer-events:auto !important;
}
.panorama-content,
.dashboard-section,
.dashboard-group,
.decision-summary{
  pointer-events:none !important;
}
.data-stage:before,
.data-stage:after,
.mission-heading:before{
  display:none !important;
}
.mission-heading{
  background:linear-gradient(90deg,rgba(236,248,255,.82),rgba(174,213,247,.34),rgba(53,123,204,.25)) !important;
  border-bottom:1px solid rgba(255,255,255,.24) !important;
}
.module-tabs button,
.summary-items button,
.attention-items button,
.metric-grid :deep(.evidence-card),
.decision-summary>article{
  background:rgba(247,252,255,.78) !important;
  border-color:rgba(190,221,247,.72) !important;
  box-shadow:inset 0 1px rgba(255,255,255,.72),0 18px 36px rgba(0,38,91,.18) !important;
  backdrop-filter:blur(16px) saturate(1.16) !important;
}
.agent-panel{
  background:linear-gradient(180deg,rgba(13,35,70,.9),rgba(4,15,32,.92)) !important;
  border-color:rgba(86,157,219,.34) !important;
  box-shadow:inset 0 1px rgba(255,255,255,.08),0 24px 56px rgba(0,14,36,.48) !important;
  backdrop-filter:blur(16px) saturate(1.05) !important;
}
.agent-panel:before{
  display:none !important;
}
.agent-panel:after{
  background:
    linear-gradient(180deg,transparent 0 68%,rgba(28,108,205,.16) 100%),
    radial-gradient(ellipse at 22% 98%,rgba(61,166,255,.26),transparent 36%) !important;
}
.dashboard-group small{
  color:#58b8ff !important;
  text-shadow:0 0 12px rgba(55,150,255,.7) !important;
}
.dashboard-group h3{
  color:#f5fbff !important;
  text-shadow:0 1px 16px rgba(130,205,255,.42) !important;
}
.dashboard-group p{
  color:rgba(232,244,255,.76) !important;
}
.brand-line h1{
  color:#f6fbff !important;
  text-shadow:0 1px 18px rgba(121,197,255,.4) !important;
}
.brand-line p{
  color:rgba(238,248,255,.78) !important;
  text-shadow:0 1px 12px rgba(121,197,255,.28) !important;
}
.metric-grid :deep(.trend-wrap){
  margin-top:4px !important;
}
.metric-grid :deep(.trend){
  height:48px !important;
  opacity:.95 !important;
}
.metric-grid :deep(.baseline){
  stroke:rgba(112,147,182,.24) !important;
  stroke-width:1 !important;
}
.metric-grid :deep(.trend-line){
  stroke:#1477ff !important;
  stroke-width:3 !important;
  stroke-linecap:round !important;
  stroke-linejoin:round !important;
  filter:drop-shadow(0 3px 7px rgba(16,105,255,.28)) !important;
}
.metric-grid :deep(.trend-point){
  fill:#1477ff !important;
  stroke:#eff8ff !important;
  stroke-width:1.5 !important;
}
.metric-grid :deep(.point-readout){
  display:none !important;
}
.water-element-backdrop:after{
  content:'' !important;
  position:absolute !important;
  inset:0 !important;
  pointer-events:none !important;
  background:
    radial-gradient(ellipse at 58% 26%,rgba(4,20,38,.18),transparent 34%),
    radial-gradient(ellipse at 58% 56%,rgba(1,10,20,.5),transparent 42%),
    linear-gradient(90deg,rgba(2,10,22,.68) 0%,rgba(3,14,28,.38) 32%,rgba(4,16,30,.2) 68%,rgba(2,10,22,.5) 100%) !important;
}
.command-bar{
  padding-top:6px !important;
}
.brand-line h1,
.brand-line p,
.back-link{
  color:#f7fbff !important;
}
.back-link{
  opacity:.74 !important;
}
.mission-heading{
  min-height:178px !important;
  padding:30px 36px 42px !important;
  margin:0 0 -30px !important;
  border:1px solid rgba(183,223,255,.24) !important;
  border-bottom-color:rgba(255,255,255,.16) !important;
  border-radius:18px 18px 0 0 !important;
  background:
    linear-gradient(100deg,rgba(233,247,255,.9) 0%,rgba(176,216,248,.44) 47%,rgba(34,104,184,.24) 100%) !important;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.62),0 20px 54px rgba(0,20,52,.22) !important;
}
.mission-heading h2{
  color:#061b55 !important;
  font-size:34px !important;
  letter-spacing:0 !important;
}
.mission-heading p{
  color:#1670ff !important;
}
.mission-heading span{
  color:rgba(18,69,125,.82) !important;
  font-size:15px !important;
}
.stage-actions button{
  background:rgba(255,255,255,.5) !important;
  border-color:rgba(210,232,255,.6) !important;
  color:#31557d !important;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.65) !important;
}
.exploration-path,
.section-jumps,
.cockpit-bottom-deck{
  display:none !important;
}
.module-tabs{
  position:relative !important;
  z-index:24 !important;
  display:grid !important;
  grid-template-columns:repeat(4,minmax(150px,1fr)) !important;
  gap:8px !important;
  margin:0 24px 12px !important;
}
.module-tabs button{
  min-height:64px !important;
  padding:12px 16px !important;
  border-radius:9px !important;
  color:#0a2455 !important;
  background:linear-gradient(180deg,rgba(248,252,255,.84),rgba(232,242,253,.76)) !important;
  border:1px solid rgba(255,255,255,.58) !important;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.7),0 8px 20px rgba(0,30,72,.1) !important;
}
.module-tabs button:hover{
  transform:translateY(-1px) !important;
  border-color:rgba(92,160,255,.52) !important;
}
.module-tabs button.active{
  color:#fff !important;
  background:linear-gradient(135deg,#0e75ff,#0754db 58%,#093f9f) !important;
  border-color:rgba(56,171,255,.72) !important;
  box-shadow:inset 0 1px rgba(255,255,255,.28),0 10px 28px rgba(11,90,218,.3) !important;
}
.module-tabs button:after{
  background:rgba(92,231,223,.9) !important;
  height:3px !important;
}
.module-tabs span{
  font-size:13px !important;
  font-weight:800 !important;
}
.module-tabs b{
  font-size:22px !important;
  font-weight:850 !important;
}
.module-tabs small{
  font-size:12px !important;
  opacity:.72 !important;
}
.panorama-content{
  position:relative !important;
  z-index:18 !important;
  padding:0 24px 36px !important;
}
.decision-summary{
  grid-template-columns:minmax(0,1.08fr) minmax(360px,.92fr) !important;
  gap:14px !important;
  margin-bottom:26px !important;
}
.decision-summary>article{
  min-height:152px !important;
  padding:18px 22px !important;
  border-radius:14px !important;
  color:#071e55 !important;
  background:linear-gradient(180deg,rgba(248,253,255,.9),rgba(231,245,255,.84)) !important;
  border:1px solid rgba(255,255,255,.58) !important;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.72),0 14px 34px rgba(4,34,76,.14) !important;
  backdrop-filter:blur(18px) saturate(1.1) !important;
}
.decision-summary>article:hover{
  transform:none !important;
}
.decision-summary h3{
  color:#071e55 !important;
  font-size:20px !important;
}
.decision-summary header small{
  color:rgba(19,64,116,.62) !important;
  font-size:12px !important;
}
.decision-summary header>span{
  color:#0b927a !important;
  background:rgba(255,255,255,.62) !important;
  border-color:rgba(100,204,188,.46) !important;
}
.summary-items{
  grid-template-columns:repeat(3,minmax(0,1fr)) !important;
  gap:10px !important;
}
.summary-items button{
  min-height:96px !important;
  padding:14px 16px !important;
  border-radius:10px !important;
  color:#08205a !important;
  background:rgba(255,255,255,.78) !important;
}
.summary-items button strong{
  margin:4px 0 3px !important;
  color:#071e55 !important;
  font-size:16px !important;
  letter-spacing:0 !important;
  line-height:1.22 !important;
}
.summary-items button span{
  color:#456488 !important;
  font-size:12px !important;
  line-height:1.35 !important;
}
.summary-items button em{
  margin-top:8px !important;
  color:#1670ff !important;
}
.attention-items button{
  min-height:52px !important;
  border-radius:10px !important;
  background:rgba(255,255,255,.76) !important;
}
.dashboard-section{
  position:relative !important;
  z-index:18 !important;
  margin-top:24px !important;
}
.dashboard-group{
  margin:0 0 12px !important;
}
.dashboard-group h3{
  color:#f7fbff !important;
  font-size:18px !important;
}
.dashboard-group p{
  color:rgba(236,247,255,.72) !important;
}
.metric-grid{
  gap:14px !important;
}
.metric-grid :deep(.evidence-card){
  min-height:216px !important;
  padding:18px 20px !important;
  border-radius:11px !important;
  color:#061b55 !important;
  background:
    linear-gradient(180deg,rgba(249,253,255,.93),rgba(232,243,252,.88)),
    radial-gradient(circle at 14% 0%,rgba(255,255,255,.55),transparent 42%) !important;
  border:1px solid rgba(255,255,255,.56) !important;
  box-shadow:
    0 8px 30px rgba(5,35,70,.12),
    inset 0 1px 0 rgba(255,255,255,.7) !important;
  backdrop-filter:blur(18px) saturate(1.08) !important;
  transition:transform .26s ease,border-color .26s ease,box-shadow .26s ease !important;
}
.metric-grid :deep(.evidence-card:hover){
  transform:translateY(-2px) !important;
  border-color:rgba(71,147,255,.62) !important;
  box-shadow:
    0 12px 34px rgba(3,38,91,.18),
    0 12px 38px rgba(25,122,255,.12),
    inset 0 1px 0 rgba(255,255,255,.78) !important;
}
.metric-grid :deep(.evidence-card:after){
  content:'' !important;
  position:absolute !important;
  left:12px !important;
  right:12px !important;
  bottom:-1px !important;
  height:20px !important;
  pointer-events:none !important;
  background:radial-gradient(ellipse at center,rgba(46,154,255,.14),transparent 70%) !important;
}
.metric-grid :deep(.module-name),
.metric-grid :deep(.metric-title),
.metric-grid :deep(.card-footer){
  color:#23456f !important;
}
.metric-grid :deep(.read-status),
.metric-grid :deep(.metric-change){
  color:#09b994 !important;
}
.metric-grid :deep(.metric-number){
  color:#061b55 !important;
  font-weight:850 !important;
  letter-spacing:0 !important;
}
.metric-grid :deep(.expand-hint),
.metric-grid :deep(.card-footer button){
  color:#1670ff !important;
}
.metric-grid :deep(.card-footer){
  border-top-color:rgba(128,166,200,.26) !important;
}
.metric-grid :deep(.trend){
  height:58px !important;
}
.metric-grid :deep(.baseline){
  stroke:rgba(96,135,172,.22) !important;
}
.metric-grid :deep(.trend-line){
  stroke:#1375ff !important;
  stroke-width:2.4 !important;
  filter:drop-shadow(0 4px 8px rgba(22,112,255,.18)) !important;
}
.metric-grid :deep(.trend-point){
  fill:#1375ff !important;
  stroke:#fff !important;
  stroke-width:1.6 !important;
}
.metric-grid :deep(.evidence-card.is-highlighted){
  border-color:rgba(123,143,255,.8) !important;
  box-shadow:
    0 0 0 1px rgba(107,135,255,.4),
    0 0 0 9px rgba(111,130,255,.1),
    0 18px 48px rgba(33,88,190,.24),
    inset 0 1px 0 rgba(255,255,255,.78) !important;
  animation:metricLocatePulse 3s ease-out 1 !important;
}
.metric-grid :deep(.evidence-card.is-highlighted:before){
  display:none !important;
}
.agent-panel{
  min-height:620px !important;
}
.context-ribbon{
  display:none !important;
}
.intro-message{
  display:flex !important;
  gap:12px !important;
  align-items:center !important;
  margin:14px 16px 8px !important;
  padding:14px 16px !important;
  border-radius:12px !important;
}
.guide-title{
  padding:8px 16px 4px !important;
  color:#f4fbff !important;
}
.guides{
  display:grid !important;
  grid-template-columns:1fr !important;
  padding:0 16px 10px !important;
  gap:8px !important;
}
.guides button{
  min-height:38px !important;
  border-radius:9px !important;
  text-align:left !important;
  padding:8px 12px !important;
  color:#dcecff !important;
  background:rgba(28,70,111,.58) !important;
  border-color:rgba(91,154,213,.48) !important;
}
.messages{
  padding:10px 16px !important;
}
.message{
  border-radius:10px !important;
  background:rgba(26,67,107,.66) !important;
  border-color:rgba(80,143,202,.42) !important;
}
.message.user{
  background:linear-gradient(135deg,#1875ff,#0e5cdd) !important;
  border-color:rgba(111,178,255,.56) !important;
}
.message-actions{
  display:flex !important;
  flex-wrap:wrap !important;
  gap:6px !important;
  margin-top:10px !important;
}
.message-actions button{
  padding:6px 10px !important;
  border-radius:7px !important;
  background:rgba(13,72,154,.68) !important;
  border:1px solid rgba(90,172,255,.48) !important;
  color:#e9f7ff !important;
}
.composer{
  margin-top:auto !important;
}
.business-card-grid{
  display:grid !important;
  gap:14px !important;
  pointer-events:auto !important;
}
.business-performance .business-card-grid,
.business-card-grid.business-performance{
  grid-template-columns:1fr !important;
}
.business-card-grid.business-presence{
  grid-template-columns:repeat(2,minmax(0,1fr)) !important;
}
.business-performance-card{
  position:relative !important;
  min-height:252px !important;
  padding:20px 22px 18px !important;
  border-radius:13px !important;
  color:#061b55 !important;
  background:
    linear-gradient(180deg,rgba(250,253,255,.94),rgba(233,244,253,.89)),
    radial-gradient(circle at 10% -10%,rgba(255,255,255,.74),transparent 42%) !important;
  border:1px solid rgba(255,255,255,.58) !important;
  box-shadow:0 10px 32px rgba(3,34,76,.14),inset 0 1px 0 rgba(255,255,255,.75) !important;
  backdrop-filter:blur(18px) saturate(1.08) !important;
  transition:transform .26s ease,border-color .26s ease,box-shadow .26s ease !important;
  overflow:hidden !important;
}
.business-performance-card:hover{
  transform:translateY(-2px) !important;
  border-color:rgba(73,151,255,.56) !important;
  box-shadow:0 14px 38px rgba(3,38,91,.2),0 12px 38px rgba(25,122,255,.1),inset 0 1px 0 rgba(255,255,255,.8) !important;
}
.business-performance-card.is-highlighted{
  border-color:rgba(123,143,255,.82) !important;
  animation:metricLocatePulse 3s ease-out 1 !important;
}
.business-performance-card header{
  display:flex !important;
  align-items:flex-start !important;
  justify-content:space-between !important;
  gap:16px !important;
  margin-bottom:12px !important;
}
.business-performance-card header div{
  display:grid !important;
  gap:3px !important;
}
.business-performance-card header small{
  color:#1670ff !important;
  font-size:12px !important;
  font-weight:800 !important;
  letter-spacing:.04em !important;
}
.business-performance-card h4{
  margin:0 !important;
  color:#061b55 !important;
  font-size:19px !important;
  line-height:1.2 !important;
}
.business-performance-card header>span{
  display:inline-flex !important;
  align-items:center !important;
  gap:6px !important;
  padding:5px 9px !important;
  border-radius:999px !important;
  color:#0aa98d !important;
  background:rgba(255,255,255,.62) !important;
  border:1px solid rgba(88,201,180,.38) !important;
  font-size:12px !important;
  white-space:nowrap !important;
}
.business-performance-card header>span.partial{
  color:#c17813 !important;
  border-color:rgba(231,175,77,.42) !important;
}
.business-performance-card header>span i{
  width:6px !important;
  height:6px !important;
  border-radius:50% !important;
  background:currentColor !important;
  box-shadow:0 0 10px currentColor !important;
}
.business-statement{
  margin:0 0 18px !important;
  max-width:760px !important;
  color:#2f557e !important;
  font-size:14px !important;
  line-height:1.6 !important;
}
.business-metrics{
  display:grid !important;
  grid-template-columns:repeat(3,minmax(0,1fr)) !important;
  border-top:1px solid rgba(99,142,180,.2) !important;
  border-bottom:1px solid rgba(99,142,180,.2) !important;
}
.business-metrics button{
  min-width:0 !important;
  display:grid !important;
  gap:5px !important;
  padding:14px 18px 13px !important;
  border:0 !important;
  border-right:1px solid rgba(99,142,180,.2) !important;
  background:transparent !important;
  text-align:left !important;
  cursor:pointer !important;
}
.business-metrics button:last-child{
  border-right:0 !important;
}
.business-metrics button:hover{
  background:rgba(255,255,255,.4) !important;
}
.business-metrics small,
.support-metric small{
  color:#315a86 !important;
  font-size:12px !important;
  font-weight:700 !important;
}
.business-metrics strong{
  color:#061b55 !important;
  font-size:28px !important;
  line-height:1.05 !important;
  letter-spacing:0 !important;
}
.business-metrics em,
.support-metric em{
  color:#0ab58f !important;
  font-size:12px !important;
  font-style:normal !important;
  font-weight:700 !important;
}
.support-metric{
  display:grid !important;
  grid-template-columns:auto auto auto minmax(0,1fr) !important;
  align-items:center !important;
  gap:10px !important;
  padding:13px 0 2px !important;
  color:#456488 !important;
}
.support-metric strong{
  color:#061b55 !important;
  font-size:22px !important;
}
.support-metric span{
  color:#456488 !important;
  font-size:12px !important;
}
.business-insight{
  margin-top:16px !important;
  padding:12px 14px !important;
  border-radius:10px !important;
  background:linear-gradient(90deg,rgba(226,242,255,.66),rgba(246,251,255,.44)) !important;
  border:1px solid rgba(177,215,248,.48) !important;
}
.business-insight b{
  display:block !important;
  margin-bottom:5px !important;
  color:#174f91 !important;
  font-size:12px !important;
}
.business-insight p{
  margin:0 !important;
  color:#2d547d !important;
  font-size:12px !important;
  line-height:1.55 !important;
}
.business-insight ul{
  display:grid !important;
  gap:5px !important;
  margin:9px 0 0 !important;
  padding:0 !important;
  list-style:none !important;
}
.business-insight li{
  display:flex !important;
  justify-content:space-between !important;
  gap:12px !important;
  color:#355d89 !important;
  font-size:12px !important;
}
.business-insight li em{
  color:#0aa98d !important;
  font-style:normal !important;
}
.business-performance-card footer{
  display:flex !important;
  justify-content:flex-end !important;
  gap:14px !important;
  margin-top:14px !important;
}
.business-performance-card footer button{
  border:0 !important;
  background:transparent !important;
  color:#1670ff !important;
  font-size:13px !important;
  font-weight:700 !important;
  cursor:pointer !important;
}
.business-card-geo .business-insight{
  background:linear-gradient(90deg,rgba(232,238,255,.66),rgba(246,251,255,.44)) !important;
}
.evidence-task-grid :deep(.trend-wrap){
  display:none !important;
}
.dynamic-canvas{
  position:relative !important;
  z-index:26 !important;
  display:grid !important;
  gap:18px !important;
  min-height:520px !important;
  margin:0 16px 34px !important;
  padding:26px 30px 30px !important;
  border:1px solid rgba(145,194,235,.52) !important;
  border-radius:18px !important;
  color:#f6fbff !important;
  background:
    radial-gradient(circle at 54% 46%,rgba(64,143,244,.16),transparent 34%),
    linear-gradient(155deg,rgba(8,24,43,.72),rgba(3,14,24,.5)) !important;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.22),0 24px 70px rgba(0,17,42,.26) !important;
  overflow:hidden !important;
  backdrop-filter:blur(10px) saturate(1.08) !important;
  animation:focusAssemble .72s cubic-bezier(.2,.8,.2,1) both !important;
}
.dynamic-canvas:before{
  content:'' !important;
  position:absolute !important;
  inset:0 !important;
  pointer-events:none !important;
  background:
    linear-gradient(110deg,transparent 8%,rgba(155,215,255,.18) 38%,transparent 62%),
    radial-gradient(circle at 82% 12%,rgba(86,169,255,.18),transparent 28%) !important;
  opacity:.58 !important;
}
.dynamic-canvas:after{
  content:'' !important;
  position:absolute !important;
  left:28px !important;
  right:28px !important;
  top:50% !important;
  height:1px !important;
  background:linear-gradient(90deg,transparent,rgba(129,207,255,.42),transparent) !important;
  opacity:.7 !important;
}
.dynamic-topline{
  position:relative !important;
  z-index:2 !important;
  display:flex !important;
  align-items:flex-start !important;
  justify-content:space-between !important;
  gap:18px !important;
}
.dynamic-topline small,
.focus-statement + *,
.priority-judgement small{
  letter-spacing:.14em !important;
}
.dynamic-topline small{
  color:#56dcff !important;
  font-size:12px !important;
  font-weight:850 !important;
}
.dynamic-topline h3{
  margin:8px 0 6px !important;
  color:#fff !important;
  font-size:32px !important;
  line-height:1.05 !important;
  letter-spacing:0 !important;
}
.dynamic-topline p{
  margin:0 !important;
  max-width:720px !important;
  color:rgba(220,240,255,.76) !important;
  font-size:14px !important;
}
.dynamic-topline button{
  flex:0 0 auto !important;
  min-width:92px !important;
  height:34px !important;
  border:1px solid rgba(179,221,255,.38) !important;
  border-radius:9px !important;
  color:#e7f5ff !important;
  background:rgba(255,255,255,.1) !important;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.16) !important;
  cursor:pointer !important;
}
.analysis-state{
  position:relative !important;
  z-index:2 !important;
  display:grid !important;
  grid-template-columns:130px minmax(240px,1fr) minmax(260px,.9fr) !important;
  align-items:center !important;
  gap:24px !important;
  min-height:330px !important;
}
.analysis-state b{
  display:block !important;
  margin-bottom:8px !important;
  color:#fff !important;
  font-size:22px !important;
}
.analysis-state p{
  margin:0 !important;
  color:rgba(221,241,255,.72) !important;
}
.analysis-radar{
  position:relative !important;
  width:116px !important;
  height:116px !important;
  border-radius:50% !important;
  background:radial-gradient(circle,rgba(89,232,211,.28),rgba(43,126,255,.12) 42%,transparent 66%) !important;
  border:1px solid rgba(120,218,255,.28) !important;
  box-shadow:0 0 36px rgba(39,154,255,.18) !important;
}
.analysis-radar i{
  position:absolute !important;
  inset:16px !important;
  border:1px solid rgba(132,221,255,.34) !important;
  border-radius:50% !important;
  animation:scanPulse 1.2s ease-out infinite !important;
}
.analysis-radar i:nth-child(2){animation-delay:.2s !important}
.analysis-radar i:nth-child(3){animation-delay:.4s !important}
.analysis-modules{
  display:grid !important;
  gap:10px !important;
}
.analysis-modules span{
  display:flex !important;
  align-items:center !important;
  justify-content:space-between !important;
  padding:12px 14px !important;
  border:1px solid rgba(168,211,244,.28) !important;
  border-radius:10px !important;
  color:#e7f7ff !important;
  background:rgba(255,255,255,.08) !important;
}
.analysis-modules span.ready em{color:#5fe8d5 !important}
.analysis-modules em{
  font-style:normal !important;
  color:#ffd28a !important;
}
.priority-view{
  position:relative !important;
  z-index:2 !important;
  display:grid !important;
  grid-template-columns:minmax(250px,.8fr) minmax(0,1.7fr) !important;
  gap:18px !important;
  align-items:stretch !important;
}
.priority-judgement,
.priority-node,
.data-node,
.geo-core,
.focus-insight{
  border:1px solid rgba(255,255,255,.52) !important;
  background:rgba(245,249,255,.9) !important;
  box-shadow:0 10px 34px rgba(5,35,70,.14),inset 0 1px 0 rgba(255,255,255,.72) !important;
  backdrop-filter:blur(16px) saturate(1.05) !important;
}
.priority-judgement{
  display:grid !important;
  align-content:center !important;
  gap:8px !important;
  min-height:330px !important;
  padding:26px !important;
  border-radius:16px !important;
  background:
    radial-gradient(circle at 24% 20%,rgba(34,128,255,.32),transparent 42%),
    linear-gradient(150deg,rgba(9,31,58,.92),rgba(4,17,31,.86)) !important;
  border-color:rgba(118,195,255,.34) !important;
}
.priority-judgement small{color:#1670ff !important;font-weight:850 !important}
.priority-judgement strong{
  color:#fff !important;
  font-size:70px !important;
  line-height:.9 !important;
  text-shadow:0 16px 40px rgba(0,71,170,.34) !important;
}
.priority-judgement p{
  margin:0 !important;
  color:#eaf7ff !important;
  font-size:18px !important;
  line-height:1.55 !important;
}
.priority-node-list{
  display:grid !important;
  grid-template-columns:repeat(3,minmax(0,1fr)) !important;
  gap:14px !important;
}
.priority-node,
.data-node,
.geo-core{
  position:relative !important;
  display:grid !important;
  align-content:start !important;
  gap:7px !important;
  min-height:190px !important;
  padding:18px !important;
  border-radius:14px !important;
  color:#08205a !important;
  text-align:left !important;
  cursor:pointer !important;
  animation:nodeGenerate .68s cubic-bezier(.2,.8,.2,1) both !important;
  animation-delay:var(--delay,0ms) !important;
}
.priority-node:hover,
.data-node:hover,
.geo-core:hover{
  transform:translateY(-2px) !important;
  border-color:rgba(81,154,255,.62) !important;
  box-shadow:0 16px 42px rgba(15,77,153,.18),0 0 0 1px rgba(75,161,255,.16),inset 0 1px 0 rgba(255,255,255,.76) !important;
}
.priority-node em{
  color:#1670ff !important;
  font-style:normal !important;
  font-weight:850 !important;
}
.priority-node small,
.data-node small,
.geo-core small{
  color:#1670ff !important;
  font-size:12px !important;
  font-weight:850 !important;
}
.priority-node strong{
  color:#061b55 !important;
  font-size:20px !important;
  line-height:1.2 !important;
}
.priority-node b,
.data-node strong,
.geo-core strong{
  color:#061b55 !important;
  font-size:32px !important;
  line-height:1.05 !important;
}
.priority-node span{
  color:#456488 !important;
  font-size:13px !important;
  line-height:1.45 !important;
}
.relationship-view{
  position:relative !important;
  z-index:2 !important;
  display:grid !important;
  grid-template-columns:minmax(0,1.4fr) minmax(260px,.6fr) !important;
  gap:18px !important;
  align-items:stretch !important;
}
.focus-statement{
  grid-column:1/-1 !important;
  margin:0 !important;
  max-width:860px !important;
  color:rgba(235,247,255,.88) !important;
  font-size:17px !important;
  line-height:1.55 !important;
}
.sem-node-map,
.geo-constellation{
  position:relative !important;
  min-height:390px !important;
  border-radius:16px !important;
  border:1px solid rgba(134,198,250,.26) !important;
  background:
    radial-gradient(circle at 50% 48%,rgba(36,132,255,.22),transparent 38%),
    linear-gradient(180deg,rgba(255,255,255,.06),rgba(255,255,255,.02)) !important;
  overflow:hidden !important;
  letter-spacing:0 !important;
}
.sem-node-map:before,
.geo-constellation:before{
  content:'' !important;
  position:absolute !important;
  inset:70px 12% !important;
  border:1px solid rgba(100,205,255,.22) !important;
  border-radius:50% !important;
  opacity:.8 !important;
}
.sem-node-map:after{
  content:'' !important;
  position:absolute !important;
  left:17% !important;
  right:17% !important;
  top:51% !important;
  height:1px !important;
  background:linear-gradient(90deg,transparent,rgba(107,211,255,.65),transparent) !important;
  animation:lineDraw .9s ease both !important;
}
.node-center{
  position:absolute !important;
  left:50% !important;
  top:50% !important;
  z-index:2 !important;
  display:grid !important;
  place-items:center !important;
  width:132px !important;
  height:132px !important;
  transform:translate(-50%,-50%) !important;
  border-radius:50% !important;
  border:1px solid rgba(138,220,255,.5) !important;
  background:radial-gradient(circle,rgba(42,117,255,.42),rgba(7,30,62,.7) 70%) !important;
  box-shadow:0 0 48px rgba(68,157,255,.24) !important;
}
.node-center b{color:#fff !important;font-size:30px !important}
.node-center span{color:rgba(229,245,255,.74) !important;font-size:12px !important}
.data-node{
  position:absolute !important;
  min-height:132px !important;
  width:220px !important;
}
.data-node em,
.geo-core em{
  color:#00b893 !important;
  font-style:normal !important;
  font-weight:800 !important;
}
.node-1{left:6% !important;top:42% !important}
.node-2{right:6% !important;top:42% !important}
.node-3{left:50% !important;bottom:8% !important;transform:translateX(-50%) !important}
.node-4{left:50% !important;top:7% !important;transform:translateX(-50%) !important}
.focus-insight{
  display:grid !important;
  align-content:center !important;
  gap:10px !important;
  min-height:220px !important;
  padding:22px !important;
  border-radius:16px !important;
  color:#08205a !important;
}
.focus-insight b{
  color:#1670ff !important;
  font-size:13px !important;
}
.focus-insight p{
  margin:0 !important;
  color:#274c76 !important;
  font-size:16px !important;
  line-height:1.65 !important;
}
.geo-core{
  position:absolute !important;
  z-index:2 !important;
  left:50% !important;
  top:50% !important;
  width:250px !important;
  min-height:180px !important;
  transform:translate(-50%,-50%) !important;
}
.geo-node-1{left:8% !important;top:16% !important}
.geo-node-2{right:8% !important;top:16% !important}
.geo-node-3{left:8% !important;bottom:12% !important}
.geo-node-4{right:8% !important;bottom:12% !important}
.tone-amber{--node-accent:#f3a745}
.tone-violet{--node-accent:#8f6fff}
.tone-cyan{--node-accent:#23d2c3}
.tone-blue{--node-accent:#1670ff}
.priority-node:before,
.data-node:before,
.geo-core:before{
  content:'' !important;
  position:absolute !important;
  left:0 !important;
  right:0 !important;
  top:0 !important;
  height:3px !important;
  border-radius:14px 14px 0 0 !important;
  background:linear-gradient(90deg,var(--node-accent,#1670ff),transparent) !important;
}
@keyframes focusAssemble{
  from{opacity:0;filter:blur(10px);transform:translateY(18px) scale(.985)}
  to{opacity:1;filter:blur(0);transform:translateY(0) scale(1)}
}
@keyframes nodeGenerate{
  from{opacity:0;filter:blur(8px);transform:translateY(16px) scale(.96)}
  to{opacity:1;filter:blur(0);transform:translateY(0) scale(1)}
}
@keyframes lineDraw{
  from{opacity:0;transform:scaleX(.2)}
  to{opacity:.75;transform:scaleX(1)}
}
@keyframes scanPulse{
  from{opacity:.75;transform:scale(.65)}
  to{opacity:0;transform:scale(1.8)}
}
@media(max-width:1180px){
  .business-card-grid.business-presence{
    grid-template-columns:1fr !important;
  }
  .priority-view,
  .relationship-view,
  .analysis-state{
    grid-template-columns:1fr !important;
  }
  .priority-node-list{
    grid-template-columns:1fr !important;
  }
  .sem-node-map,
  .geo-constellation{
    min-height:620px !important;
  }
}
@media(max-width:760px){
  .business-metrics{
    grid-template-columns:1fr !important;
  }
  .business-metrics button{
    border-right:0 !important;
    border-bottom:1px solid rgba(99,142,180,.2) !important;
  }
  .business-metrics button:last-child{
    border-bottom:0 !important;
  }
  .support-metric{
    grid-template-columns:1fr auto auto !important;
  }
  .support-metric span{
    grid-column:1/-1 !important;
  }
  .dynamic-canvas{
    margin:0 4px 24px !important;
    padding:18px !important;
  }
  .dynamic-topline{
    flex-direction:column !important;
  }
  .dynamic-topline h3{
    font-size:25px !important;
  }
  .data-node,
  .geo-core{
    position:relative !important;
    inset:auto !important;
    width:auto !important;
    transform:none !important;
  }
  .sem-node-map,
  .geo-constellation{
    display:grid !important;
    gap:12px !important;
    min-height:auto !important;
    padding:14px !important;
  }
  .node-center{
    position:relative !important;
    inset:auto !important;
    transform:none !important;
    justify-self:center !important;
  }
}
@keyframes metricLocatePulse{
  0%{box-shadow:0 0 0 0 rgba(113,130,255,.34),0 18px 48px rgba(33,88,190,.2),inset 0 1px 0 rgba(255,255,255,.78)}
  44%{box-shadow:0 0 0 12px rgba(113,130,255,.12),0 22px 56px rgba(33,88,190,.28),inset 0 1px 0 rgba(255,255,255,.78)}
  100%{box-shadow:0 0 0 0 rgba(113,130,255,0),0 8px 30px rgba(5,35,70,.12),inset 0 1px 0 rgba(255,255,255,.7)}
}

/* Final production guard: real customer/date labels can vary, so the filter bar
   must size by content instead of assuming four fixed columns. */
.command-bar{
  grid-template-columns:minmax(300px,420px) minmax(0,1fr) !important;
  overflow:visible !important;
}
.command-controls{
  display:flex !important;
  align-items:center !important;
  justify-content:flex-end !important;
  flex-wrap:nowrap !important;
  gap:8px !important;
  width:100% !important;
  max-width:none !important;
  min-width:0 !important;
  height:44px !important;
  padding:0 !important;
  overflow:visible !important;
  background:transparent !important;
  border:0 !important;
  box-shadow:none !important;
}
.command-controls label,
.period-control,
.refresh-button{
  position:relative !important;
  min-width:0 !important;
  height:38px !important;
  margin:0 !important;
}
.command-controls label{
  flex:0 1 230px !important;
  display:grid !important;
  grid-template-columns:auto minmax(0,1fr) !important;
  align-items:center !important;
  gap:10px !important;
  padding:0 12px !important;
  white-space:nowrap !important;
}
.command-controls select{
  min-width:0 !important;
  width:100% !important;
  overflow:hidden !important;
  text-overflow:ellipsis !important;
}
.period-control{
  flex:1 1 600px !important;
  max-width:720px !important;
  display:flex !important;
  align-items:center !important;
  gap:10px !important;
  padding:0 10px !important;
  white-space:nowrap !important;
}
.period-control>span{
  flex:0 0 auto !important;
}
.period-shortcuts{
  flex:0 0 auto !important;
  display:flex !important;
  align-items:center !important;
  gap:4px !important;
}
.period-shortcuts button{
  flex:0 0 auto !important;
  min-width:42px !important;
  height:28px !important;
  padding:0 8px !important;
}
.date-range{
  flex:1 1 auto !important;
  min-width:270px !important;
  display:flex !important;
  align-items:center !important;
  justify-content:flex-end !important;
  gap:6px !important;
  overflow:hidden !important;
}
.date-range input{
  flex:0 0 112px !important;
  width:112px !important;
  min-width:112px !important;
  height:28px !important;
}
.date-range span{
  flex:0 0 auto !important;
}
.apply-period{
  flex:0 0 42px !important;
  width:42px !important;
  min-width:42px !important;
  height:28px !important;
}
.refresh-button{
  flex:0 0 110px !important;
  width:110px !important;
  min-width:110px !important;
  height:38px !important;
  display:inline-flex !important;
  align-items:center !important;
  justify-content:center !important;
  gap:5px !important;
  white-space:normal !important;
}
@media(max-width:1280px){
  .command-bar{
    grid-template-columns:300px minmax(0,1fr) !important;
  }
  .command-controls{
    flex-wrap:wrap !important;
    align-content:flex-start !important;
    height:auto !important;
  }
  .period-control{
    order:10 !important;
    flex:1 0 100% !important;
    max-width:none !important;
  }
}
</style>
