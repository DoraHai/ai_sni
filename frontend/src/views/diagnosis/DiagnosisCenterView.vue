<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  discoverGeoBrand,
  fetchGeoAudit,
  fetchGeoAuditHistory,
  fetchGeoAssetProfile,
  fetchLatestGeoAudit,
  fetchPageSpeedInsights,
  generateGeoAdvice,
  runDeepSeekSample,
  runCompetitorAudit,
  createGeoTaskFromDiagnosis,
  runGeoAudit,
} from '../../api/geo'
import { fetchTenants } from '../../api/auth'
import { session } from '../../store/session'
import diagnosticLogo from '../../assets/g-snipers-purple-logo.png'
import DiagnosisAssetsView from './DiagnosisAssetsView.vue'

const tenantId = computed(() => session.tenantId || (import.meta.env.DEV && import.meta.env.VITE_API_KEY ? 1 : null))

const url = ref('')
const quickMode = ref('own')
const quickUrl = ref('')
const quickUrlInput = ref(null)
const quickProfile = ref(null)
const quickProfileOpen = ref(false)
const quickProfileLoading = ref(false)
const auditScope = ref('single')
const audit = ref(null)
const pageSpeed = ref(null)
const pageSpeedLoading = ref(false)
const loading = ref(false)
const tenantLoading = ref(false)
const adviceLoading = ref(false)
const samplingLoading = ref(false)
const bridgeLoading = ref(false)
const error = ref('')
const issueFilter = ref('all')
const loadingStage = ref(0)
const activeReport = ref('overview')
const activeAsset = ref('')
const expandedEvidence = ref('')
const sampleQuestions = ref(['', '', ''])
const brandReady = ref(false)
const brandProfile = ref({})
const historyOpen = ref(false)
const historyLoading = ref(false)
const historyItems = ref([])
const historySelectingId = ref(null)
let stageTimer = null
let pageSpeedRequestId = 0

const reportNav = [
  { key: 'overview', label: '网站体检', icon: '◉' },
  { key: 'seo', label: 'SEO 诊断', icon: '⌕' },
  { key: 'geo', label: 'GEO / AI 搜索诊断', icon: '✦' },
  { key: 'issues', label: '问题清单', icon: '!' },
]

const assetNav = [
  {
    label: '基础信息',
    icon: '▰',
    page: 'brand',
    kicker: 'BRAND FOUNDATION',
    description: '统一品牌名称、官网、行业定位和核心业务事实，作为诊断与内容执行的共同底座。',
    fields: ['品牌名称与官网', '行业与业务定位', '核心产品与服务', '品牌介绍与可信信息'],
  },
  {
    label: '目标用户',
    icon: '◎',
    page: 'audience',
    kicker: 'AUDIENCE PROFILE',
    description: '沉淀核心客群、决策角色和真实需求，让 SEO、GEO 与内容策略使用同一套用户定义。',
    fields: ['核心客群', '决策角色', '购买动机', '主要痛点与搜索场景'],
  },
  {
    label: '知识库',
    icon: '▤',
    page: 'knowledge',
    kicker: 'KNOWLEDGE BASE',
    description: '集中管理产品资料、案例、白皮书和常见问题，为诊断证据和内容生成提供可靠事实。',
    fields: ['产品与服务资料', '客户案例', '行业白皮书', 'FAQ 与事实依据'],
  },
]
const currentAsset = computed(() => assetNav.find((item) => item.page === activeAsset.value) || assetNav[0])

const loadingStages = [
  '正在建立安全连接',
  '正在读取页面静态代码',
  '正在检查 SEO 与 Schema 信号',
  '正在生成诊断报告',
]

const ruleNarratives = {
  https: {
    userTitle: '网站连接安全性不足',
    why: '不安全的连接会降低访客、搜索引擎和 AI 抓取工具对网站的信任。',
    direction: '统一启用 HTTPS，并把所有旧地址跳转到安全版本。',
  },
  title: {
    userTitle: '页面主题不够清晰',
    why: '标题是搜索引擎和 AI 判断页面主题的第一信号，含糊或过长都会降低理解效率。',
    direction: '用一句标题说明品牌、业务主题和用户意图。',
  },
  description: {
    userTitle: '页面摘要信息不足',
    why: '缺少清晰摘要时，搜索结果和 AI 很难快速提取页面能为用户提供什么价值。',
    direction: '补充独立、清晰且包含核心卖点的页面摘要。',
  },
  canonical: {
    userTitle: '页面主版本不明确',
    why: '同一内容存在多个地址时，搜索与 AI 信号可能被分散，难以判断应引用哪个页面。',
    direction: '声明唯一的首选页面地址，集中搜索与引用信号。',
  },
  indexable: {
    userTitle: '页面可能无法被搜索引擎收录',
    why: '页面被禁止索引后，搜索引擎和部分 AI 搜索服务可能无法发现这部分内容。',
    direction: '确认公开获客页面没有错误设置 noindex。',
  },
  h1: {
    userTitle: '页面核心主题不唯一',
    why: '缺少唯一主标题会让用户和 AI 难以判断页面最重要的主题。',
    direction: '保留一个清晰的 H1，其余内容使用 H2、H3 分层。',
  },
  heading_depth: {
    userTitle: '内容结构不够清晰',
    why: '结构松散的长页面不利于 AI 提取独立观点、答案和可引用内容块。',
    direction: '按问题、方案、证据和常见问题组织分层标题。',
  },
  substantial: {
    userTitle: '页面有效信息不足',
    why: '内容过少时，AI 缺乏足够事实判断企业能力，也更难形成有依据的推荐。',
    direction: '补充产品事实、适用场景、证据、案例和限制条件。',
  },
  schema: {
    userTitle: '缺少结构化数据支持',
    why: 'AI 搜索工具可能无法准确识别页面中的企业、产品和内容关系。',
    direction: '增加与页面内容一致的 JSON-LD 结构化数据。',
  },
  entity_schema: {
    userTitle: 'AI 无法准确识别品牌实体',
    why: '缺少品牌实体声明时，AI 可能无法确认企业身份、官网归属和品牌关系。',
    direction: '补充 Organization 或 Brand Schema，并关联名称与官网。',
  },
  faq: {
    userTitle: '缺少用户问答内容',
    why: '没有明确的问题和答案，AI 较难从页面中直接提取适合回答用户的内容。',
    direction: '增加真实客户问题及简洁答案，符合条件时补充 FAQ 标记。',
  },
  citations: {
    userTitle: '缺少可核验的外部证据',
    why: '没有来源支撑的结论可信度较弱，AI 在引用或推荐时会更加谨慎。',
    direction: '为关键数据和结论增加权威来源、日期与链接。',
  },
  freshness: {
    userTitle: '内容责任人与时效不明确',
    why: '无法判断作者和更新时间时，用户与 AI 都难以确认内容是否可靠、是否仍然有效。',
    direction: '展示作者或审核人，并标明发布日期和最近更新时间。',
  },
  language: {
    userTitle: '页面语言没有明确声明',
    why: '语言信号缺失可能影响搜索引擎和 AI 对内容语言、地区及受众的判断。',
    direction: '在 HTML 根元素声明准确的页面语言。',
  },
  robots: {
    userTitle: '搜索抓取规则不明确',
    why: '缺少 robots.txt 会让搜索爬虫无法快速确认哪些内容允许访问。',
    direction: '发布清晰的 robots.txt，并检查公开页面没有被误拦截。',
  },
  llms: {
    userTitle: '缺少面向 AI 的站点导览',
    why: 'AI 工具缺少简洁的官网内容入口，可能更难找到品牌介绍和关键页面。',
    direction: '提供 llms.txt，列出品牌定位和最重要的官方页面。',
  },
}

const priorityDirectionDefinitions = [
  { title: '提升品牌识别能力', codes: ['entity_schema', 'title', 'canonical'], description: '让 AI 明确识别企业是谁、官网在哪里，以及品牌与页面的关系。' },
  { title: '增强结构化数据', codes: ['schema', 'entity_schema'], description: '用机器可读数据描述企业、品牌、产品和页面之间的关系。' },
  { title: '完善 AI 可理解内容', codes: ['description', 'h1', 'heading_depth', 'substantial', 'faq'], description: '把产品能力、用户问题和事实证据整理成 AI 易于提取的内容块。' },
  { title: '提升可信与引用能力', codes: ['citations', 'freshness'], description: '补充来源、作者和更新时间，让内容更值得被引用。' },
  { title: '改善搜索与 AI 抓取基础', codes: ['https', 'indexable', 'robots', 'llms', 'language'], description: '确保公开页面能被安全访问、发现、索引并正确识别。' },
]

const businessImpactByCode = {
  https: '官网安全感和访问稳定性下降，客户可能在进入页面前就选择离开。',
  title: '用户和 AI 难以快速判断页面提供什么，降低品牌在相关搜索中的点击与推荐机会。',
  description: '搜索结果无法清楚传达产品价值，潜在客户更难产生点击和进一步了解的意愿。',
  canonical: '品牌官网的权威页面不明确，可能分散搜索权重并出现内容版本混淆。',
  indexable: '页面可能无法进入搜索结果，客户搜索相关需求时看不到你的官网。',
  h1: '用户进入页面后难以快速理解核心产品，也会降低 AI 提取页面主题的准确度。',
  heading_depth: '产品信息层级不清，客户阅读成本增加，AI 也更难提炼卖点和答案。',
  substantial: '页面缺少足够的业务事实，降低品牌被 AI 作为可靠答案引用和推荐的概率。',
  schema: 'AI 无法准确理解页面中的企业、产品与服务关系，品牌信息可能被错误归类。',
  entity_schema: 'AI 无法确认你的企业身份和官网归属，直接降低品牌被识别与推荐的概率。',
  faq: '客户常见疑问没有直接答案，可能流失高意向访问者，也减少 AI 可引用的内容。',
  citations: '缺少可核验依据会削弱品牌专业可信度，AI 更可能选择证据更完整的竞争品牌。',
  freshness: '客户和 AI 无法确认信息是否仍然有效，可能降低对产品、数据和观点的信任。',
  language: '搜索工具可能误判页面面向的地区与人群，影响目标客户发现官网。',
  robots: '搜索与 AI 抓取范围不明确，重要页面可能无法被及时发现。',
  llms: 'AI 缺少快速了解官网的入口，品牌核心信息更容易在生成式搜索中被忽略。',
}

const scoreTone = computed(() => {
  const score = audit.value?.score ?? 0
  if (score >= 80) return 'good'
  if (score >= 60) return 'fair'
  return 'risk'
})

const scoreLabel = computed(() => {
  const score = audit.value?.score ?? 0
  if (score >= 80) return '优秀'
  if (score >= 60) return '基础阶段'
  return '需要优化'
})

const findings = computed(() => audit.value?.findings || [])
const problems = computed(() => audit.value?.problems || [])
const aiSample = computed(() => audit.value?.snapshot?.ai_sampling || null)
const isCompetitorAudit = computed(() => audit.value?.snapshot?.audit_mode === 'competitor')
const siteAudit = computed(() => audit.value?.snapshot?.site_audit || null)
const isSiteAudit = computed(() => audit.value?.snapshot?.audit_scope === 'site')
const sitePages = computed(() => siteAudit.value?.pages || [])
const baiduIndexMetric = computed(() => audit.value?.snapshot?.external_metrics?.baidu_index || {
  status: 'unavailable',
  site_count: null,
  reason: '当前报告尚未查询百度收录量',
  is_estimate: true,
  source_url: 'https://api.chinaz.com/ApiDetails/BaiduPages',
})
const baiduPcKeywordsMetric = computed(() => audit.value?.snapshot?.external_metrics?.baidu_pc_keywords || {
  status: 'unavailable', total: null, keywords: [], reason: 'BD_PC 网站关键词接口待配置',
})
const baiduMobileKeywordsMetric = computed(() => audit.value?.snapshot?.external_metrics?.baidu_mobile_keywords || {
  status: 'unavailable', total: null, keywords: [], reason: 'BD 移动网站关键词接口待配置',
})
const comprehensiveWeightMetric = computed(() => audit.value?.snapshot?.external_metrics?.comprehensive_weight || {
  status: 'unavailable',
  baidu_pc: { weight: null, keyword_count: null, uv: null },
  baidu_mobile: { weight: null, keyword_count: null, uv: null },
  reason: '综合权重接口待配置',
})
const whoisMetric = computed(() => audit.value?.snapshot?.external_metrics?.whois || {
  status: 'unavailable',
  domain_age_years: null,
  creation_date: null,
  expiration_date: null,
  registrar: null,
  reason: 'Whois 查询接口待配置',
})
const seoDomainAgeLabel = computed(() => Number.isFinite(Number(whoisMetric.value.domain_age_years))
  ? `${Number(whoisMetric.value.domain_age_years)}年`
  : '待接入')
const seoDomainAssetSummary = computed(() => {
  if (whoisMetric.value.status !== 'available') return whoisMetric.value.reason
  const created = String(whoisMetric.value.creation_date || '').slice(0, 10)
  const expires = String(whoisMetric.value.expiration_date || '').slice(0, 10)
  if (created && expires) return `注册 ${created} · 到期 ${expires}`
  if (created) return `注册于 ${created}`
  return whoisMetric.value.registrar || '域名资产信息已获取'
})
const seoPcKeywordCount = computed(() => baiduPcKeywordsMetric.value.total)
const seoMobileKeywordCount = computed(() => baiduMobileKeywordsMetric.value.total)
const seoKeywordTotal = computed(() => {
  const values = [seoPcKeywordCount.value, seoMobileKeywordCount.value].filter((item) => Number.isFinite(Number(item)))
  return values.length ? values.reduce((sum, item) => sum + Number(item), 0) : null
})
const seoPcWeight = computed(() => comprehensiveWeightMetric.value.baidu_pc?.weight ?? null)
const seoMobileWeight = computed(() => comprehensiveWeightMetric.value.baidu_mobile?.weight ?? null)
const seoTrafficLabel = computed(() => {
  const pc = comprehensiveWeightMetric.value.baidu_pc?.uv
  const mobile = comprehensiveWeightMetric.value.baidu_mobile?.uv
  if (pc && mobile) return `PC ${pc} · 移动 ${mobile}`
  return pc || mobile || '待配置'
})
const chinazMetricList = computed(() => [
  baiduIndexMetric.value,
  baiduPcKeywordsMetric.value,
  baiduMobileKeywordsMetric.value,
  comprehensiveWeightMetric.value,
  whoisMetric.value,
])
const chinazSourceState = computed(() => {
  const available = chinazMetricList.value.filter((item) => item.status === 'available').length
  if (available === chinazMetricList.value.length) return '站长之家实时数据'
  if (available) return `站长之家数据 · 已接入 ${available}/5 项`
  return '站长之家接口 · 待配置 API Key'
})
const passedCount = computed(() => findings.value.filter((item) => item.passed).length)
const rulePassRate = computed(() => Math.round(passedCount.value / Math.max(findings.value.length, 1) * 100))
const confirmedCompetitors = computed(() =>
  (brandProfile.value?.competitors || []).filter((item) => item.confirmed),
)
const quickProfileContext = computed(() => quickMode.value === 'competitor' ? quickProfile.value : brandProfile.value)
const quickProfileStats = computed(() => {
  const profile = quickProfileContext.value || {}
  return {
    products: Array.isArray(profile.core_products) ? profile.core_products.length : 0,
    proof: Array.isArray(profile.proof_points) ? profile.proof_points.length : 0,
    terms: Array.isArray(profile.brand_terms) ? profile.brand_terms.length : 0,
    competitors: Array.isArray(profile.competitors) ? profile.competitors.filter((item) => item.confirmed).length : 0,
  }
})

const problemCounts = computed(() => ({
  critical: problems.value.filter((item) => item.severity === 'critical').length,
  high: problems.value.filter((item) => item.severity === 'high').length,
  medium: problems.value.filter((item) => item.severity === 'medium').length,
  low: problems.value.filter((item) => item.severity === 'low').length,
}))

const severityRank = { critical: 4, high: 3, medium: 2, low: 1 }

const sortedProblems = computed(() => [...problems.value].sort((a, b) =>
  (severityRank[b.severity] || 0) - (severityRank[a.severity] || 0)
  || Number(b.deduction || 0) - Number(a.deduction || 0),
))

const primaryFindings = computed(() => sortedProblems.value.slice(0, 3))

const readinessConclusion = computed(() => {
  const score = audit.value?.score ?? 0
  if (isCompetitorAudit.value) {
    if (score >= 80) return '该竞品网站公开页面具备较完整的搜索与 AI 理解基础，可作为结构化数据、内容组织和可信信号建设的对标参考。'
    if (score >= 60) return '该竞品网站具备基础搜索能力，但在品牌实体、内容结构或可信证据方面仍存在可观察的公开短板。'
    return '该竞品网站的公开页面存在明显的搜索与 AI 理解缺口；本结果仅用于公开信息对标，不代表其内部经营表现。'
  }
  if (score >= 80) return '你的官网已具备较好的 AI 搜索基础，但仍需持续强化品牌证据，避免在 AI 推荐结果中被信息更完整的竞争品牌取代。'
  if (score >= 60) return '你的官网具备基础搜索能力，但 AI 仍可能无法完整理解企业身份、产品价值和可信证据，导致品牌在相关回答中不被推荐。'
  return '你的官网存在影响搜索发现和 AI 理解的关键缺口；如果不优先修复，客户通过 ChatGPT、DeepSeek 等工具寻找方案时，可能看不到你的品牌。'
})

const aiEraRisk = computed(() => {
  const highCount = problemCounts.value.critical + problemCounts.value.high
  if (isCompetitorAudit.value) {
    if (!problems.value.length) return '该竞品本次抽样的基础规则表现稳定，建议结合自身官网差距判断可借鉴方向。'
    return `本次公开检测发现 ${highCount || problems.value.length} 项值得关注的信号。这里只反映其公开网页状态，不推断真实流量、转化或内部策略。`
  }
  if (!problems.value.length) return 'AI 搜索环境持续变化，建议定期复检，避免品牌信息更新后出现理解偏差。'
  if (highCount) return `当前有 ${highCount} 项高影响问题。若长期不处理，AI 可能无法确认企业身份、理解产品优势，并优先推荐信息更完整的竞争品牌。`
  return '当前问题虽然不会立即阻断访问，但会持续降低官网内容被 AI 理解、引用和推荐的概率。'
})

const priorityDirections = computed(() => priorityDirectionDefinitions
  .map((definition) => {
    const related = sortedProblems.value.filter((item) => definition.codes.includes(item.code))
    const strongest = related[0]
    return {
      ...definition,
      count: related.length,
      rank: strongest ? (severityRank[strongest.severity] || 0) * 100 + Number(strongest.deduction || 0) : 0,
      impact: strongest?.severity || 'low',
    }
  })
  .filter((item) => item.count)
  .sort((a, b) => b.rank - a.rank)
  .slice(0, 3))

const dimensions = computed(() => {
  const definitions = [
    { key: 'technical', label: '技术可访问', categories: ['技术基础'] },
    { key: 'semantic', label: '页面语义', categories: ['页面语义'] },
    { key: 'structure', label: '内容结构', categories: ['内容结构', '内容质量'] },
    { key: 'schema', label: '实体与 Schema', categories: ['结构化数据'] },
    { key: 'citation', label: 'AI 引用就绪度', categories: ['AI 引用就绪度', 'AI 可引用性', 'AI 可访问性'] },
    { key: 'trust', label: '可信信号', categories: ['可信度'] },
  ]
  return definitions.map((definition) => {
    const rows = findings.value.filter((item) => definition.categories.includes(item.category))
    const totalWeight = rows.reduce((sum, item) => sum + Number(item.weight || item.deduction || 0), 0)
    const lost = rows.filter((item) => !item.passed).reduce((sum, item) => sum + Number(item.deduction || 0), 0)
    const score = rows.length ? Math.max(0, Math.round(100 - (lost / Math.max(totalWeight, 1)) * 100)) : 100
    return { ...definition, score, passed: rows.filter((item) => item.passed).length, total: rows.length }
  })
})

const radarPoints = computed(() => {
  const center = 110
  const radius = 82
  return dimensions.value.map((item, index) => {
    const angle = (-90 + index * 60) * Math.PI / 180
    const valueRadius = radius * item.score / 100
    return `${center + Math.cos(angle) * valueRadius},${center + Math.sin(angle) * valueRadius}`
  }).join(' ')
})

const strongestDimension = computed(() =>
  [...dimensions.value].sort((a, b) => b.score - a.score)[0],
)

const weakestDimension = computed(() =>
  [...dimensions.value].sort((a, b) => a.score - b.score)[0],
)

function dimensionTone(score) {
  if (score >= 80) return 'stable'
  if (score >= 60) return 'watch'
  return 'risk'
}

function dimensionStatus(score) {
  if (score >= 80) return '优势项'
  if (score >= 60) return '待增强'
  if (score > 0) return '明显短板'
  return '信号缺失'
}

function findingSection(item) {
  return ['结构化数据', 'AI 引用就绪度', 'AI 可引用性', 'AI 可访问性', '可信度'].includes(item.category)
    ? 'section-geo'
    : 'section-seo'
}

const seoFindings = computed(() => findings.value.filter((item) =>
  ['技术基础', '页面语义', '内容结构', '内容质量'].includes(item.category),
))

const geoFindings = computed(() => findings.value.filter((item) =>
  ['结构化数据', 'AI 引用就绪度', 'AI 可引用性', 'AI 可访问性', '可信度'].includes(item.category),
))

const featuredFindings = computed(() =>
  [...findings.value]
    .sort((a, b) => Number(a.passed) - Number(b.passed) || Number(b.deduction || 0) - Number(a.deduction || 0))
    .slice(0, 3),
)

function evidenceRows(item) {
  const snapshot = audit.value?.snapshot || {}
  if (item.page_evidence?.length) {
    return item.page_evidence.map((page) => ({
      passed: page.passed,
      text: page.passed
        ? `通过 · ${page.title || page.url} · ${page.evidence}`
        : `未通过 · ${page.title || page.url} · 原因：${page.reason || `未满足“${item.title}”规则：${page.evidence}`}`,
    }))
  }
  if (item.code === 'citations') return (snapshot.external_links || []).map((text) => ({ text }))
  if (item.code === 'faq') return (snapshot.question_headings || []).map((text) => ({ text }))
  if (['schema', 'entity_schema'].includes(item.code)) return (snapshot.schema_types || []).map((text) => ({ text }))
  if (item.code === 'heading_depth') {
    return (snapshot.headings || []).map((heading) => ({ text: `H${heading.level} · ${heading.text}` }))
  }
  if (item.code === 'h1') return (snapshot.h1 || []).map((text) => ({ text }))
  return []
}

function evidenceDetails(item) {
  return evidenceRows(item).map((row) => row.text)
}

function failureSummary(item) {
  const failedPages = (item.page_evidence || []).filter((page) => !page.passed)
  if (failedPages.length) {
    return `${failedPages.length} 个页面未满足“${item.title}”规则，展开明细可查看每个页面的具体原因。`
  }
  return item.reason || `未满足“${item.title}”规则：${item.evidence}`
}

function ruleNarrative(item) {
  return ruleNarratives[item?.code] || {
    userTitle: item?.title || '发现一项需要关注的问题',
    why: item?.recommendation || '这项信号会影响搜索工具和 AI 对官网内容的理解。',
    direction: item?.recommendation || '根据检测证据完善对应页面信息。',
  }
}

function businessImpact(item) {
  return businessImpactByCode[item?.code]
    || '这项问题会增加客户理解成本，并降低官网被搜索工具和 AI 正确推荐的机会。'
}

function impactLevel(item) {
  if (item?.passed) return '当前通过'
  if (['critical', 'high'].includes(item?.severity)) return '高影响'
  if (item?.severity === 'medium') return '中等影响'
  return '低影响'
}

function findingLabel(item) {
  if (['critical', 'high'].includes(item?.severity)) return '高影响问题'
  if (item?.severity === 'medium') return '优化机会'
  return '建议优化'
}

function toggleEvidence(item) {
  expandedEvidence.value = expandedEvidence.value === item.code ? '' : item.code
}

async function copyEvidence(item) {
  const text = evidenceDetails(item).join('\n')
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('证据明细已复制')
  } catch {
    ElMessage.error('复制失败，请手动选择内容')
  }
}

const filteredProblems = computed(() => {
  if (issueFilter.value === 'all') return sortedProblems.value
  if (issueFilter.value === 'critical') {
    return sortedProblems.value.filter((item) => ['critical', 'high'].includes(item.severity))
  }
  return sortedProblems.value.filter((item) => issueDomain(item) === issueFilter.value)
})

const diagnosisSummary = computed(() => {
  if (!audit.value) return ''
  const weakest = [...dimensions.value].sort((a, b) => a.score - b.score).slice(0, 2)
  if (!problems.value.length) return '当前页面的基础技术、内容结构和可信信号均通过检查，可以进入更深入的行业内容与真实 AI 可见度监测。'
  return `当前页面已具备一定的 SEO / GEO 基础，但${weakest.map((item) => item.label).join('、')}仍是主要短板。建议优先处理 ${problemCounts.value.critical + problemCounts.value.high} 项高优先级问题，再推进内容与信源建设。`
})

const priorityAction = computed(() => {
  const first = problems.value.find((item) => item.severity === 'critical')
    || problems.value.find((item) => item.severity === 'high')
    || problems.value[0]
  return first?.recommendation || '保持页面信息真实、完整，并定期复检。'
})

function normalizeUrl(value) {
  const input = String(value || '').trim()
  if (!input) return ''
  return /^https?:\/\//i.test(input) ? input : `https://${input}`
}

function startStageProgress() {
  loadingStage.value = 0
  clearInterval(stageTimer)
  stageTimer = window.setInterval(() => {
    if (loadingStage.value < loadingStages.length - 1) loadingStage.value += 1
  }, 2600)
}

function stopStageProgress() {
  clearInterval(stageTimer)
  stageTimer = null
}

async function ensureTenant() {
  if (tenantId.value) return true
  tenantLoading.value = true
  try {
    const result = await fetchTenants()
    session.setTenants(result.tenants || [])
    if (!tenantId.value) {
      error.value = '当前账号还没有可诊断的客户，请先在主平台完成客户配置'
      return false
    }
    return true
  } catch (e) {
    error.value = e.message || '客户信息加载失败，请稍后重试'
    return false
  } finally {
    tenantLoading.value = false
  }
}

async function refreshBrandProfile(website = '') {
  if (!tenantId.value) return false
  try {
    const result = await fetchGeoAssetProfile(tenantId.value, website)
    brandReady.value = Boolean(result.profile_ready)
    brandProfile.value = result.brand || {}
    if (!url.value && result.brand?.website) url.value = result.brand.website
    return brandReady.value
  } catch {
    brandReady.value = false
    brandProfile.value = {}
    return false
  }
}

async function applyAudit(nextAudit) {
  audit.value = nextAudit || null
  if (!nextAudit) return
  if (nextAudit.url) {
    url.value = nextAudit.url
    quickMode.value = 'own'
    quickUrl.value = nextAudit.url
  }
  await refreshBrandProfile(nextAudit.url || url.value)
  auditScope.value = nextAudit.snapshot?.audit_scope === 'site' ? 'site' : 'single'
  if (nextAudit.snapshot?.ai_sampling?.results) {
    sampleQuestions.value = nextAudit.snapshot.ai_sampling.results.map((item) => item.question).slice(0, 3)
    while (sampleQuestions.value.length < 3) sampleQuestions.value.push('')
  } else {
    sampleQuestions.value = ['', '', '']
  }
}

async function loadLatest({ notify = false } = {}) {
  if (!tenantId.value) return
  try {
    const result = await fetchLatestGeoAudit(tenantId.value)
    await applyAudit(result.audit)
    if (notify) ElMessage.success(result.audit ? '已载入最近一次诊断' : '暂无历史诊断')
  } catch {
    if (notify) ElMessage.error('历史诊断读取失败')
  }
}

async function startNewDiagnosis() {
  if (loading.value) return
  if (audit.value) {
    try {
      await ElMessageBox.confirm(
        '当前报告已保存在诊断记录中。新建后将清空当前页面，等待输入新的诊断网址。',
        '新建诊断',
        { confirmButtonText: '继续新建', cancelButtonText: '保留当前报告', type: 'info' },
      )
    } catch {
      return
    }
  }
  audit.value = null
  pageSpeed.value = null
  error.value = ''
  issueFilter.value = 'all'
  expandedEvidence.value = ''
  sampleQuestions.value = ['', '', '']
  quickMode.value = 'own'
  quickUrl.value = ''
  auditScope.value = 'single'
  activeReport.value = 'overview'
  historyOpen.value = false
  window.history.replaceState(null, '', `${window.location.pathname}#section-overview`)
  await nextTick()
  focusQuickInput()
  ElMessage.success('已创建新的诊断任务，请输入官网地址')
}

async function openAuditHistory() {
  if (!tenantId.value) return
  historyOpen.value = true
  historyLoading.value = true
  try {
    const result = await fetchGeoAuditHistory(tenantId.value, 12)
    historyItems.value = result.items || []
  } catch (e) {
    ElMessage.error(e.message || '诊断记录读取失败')
  } finally {
    historyLoading.value = false
  }
}

async function selectHistoricalAudit(item) {
  if (!item?.id || historySelectingId.value) return
  historySelectingId.value = item.id
  try {
    const result = await fetchGeoAudit({ tenantId: tenantId.value, auditId: item.id })
    await applyAudit(result)
    historyOpen.value = false
    pageSpeed.value = null
    await nextTick()
    document.querySelector('#diagnosis-report')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    ElMessage.success('历史诊断已载入')
  } catch (e) {
    ElMessage.error(e.message || '历史诊断载入失败')
  } finally {
    historySelectingId.value = null
  }
}

async function startAudit() {
  error.value = ''
  const normalized = normalizeUrl(url.value)
  if (!normalized) {
    error.value = '请输入需要诊断的网站地址'
    return
  }
  if (!tenantId.value && !await ensureTenant()) return
  if (!await refreshBrandProfile(normalized)) {
    url.value = normalized
    openAsset('brand')
    ElMessage.warning('开始体检前，请先确认当前网站的品牌基础信息')
    return
  }
  loading.value = true
  audit.value = null
  startStageProgress()
  try {
    audit.value = await runGeoAudit({ tenantId: tenantId.value, url: normalized, scope: auditScope.value })
    url.value = audit.value.final_url || normalized
    quickMode.value = 'own'
    quickUrl.value = url.value
    sampleQuestions.value = ['', '', '']
    loadingStage.value = loadingStages.length - 1
    ElMessage.success('网站诊断完成')
    await nextTick()
    document.querySelector('#diagnosis-report')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  } catch (e) {
    error.value = e.message || '诊断失败，请确认网址可公开访问'
  } finally {
    stopStageProgress()
    loading.value = false
  }
}

function selectQuickMode(mode) {
  quickMode.value = mode
  error.value = ''
  quickProfileOpen.value = false
  if (mode === 'own') {
    quickUrl.value = url.value || brandProfile.value?.website || ''
  } else if (!isCompetitorAudit.value) {
    quickUrl.value = ''
    quickProfile.value = null
  }
  nextTick(() => quickUrlInput.value?.focus())
}

function handleQuickUrlInput() {
  if (quickMode.value === 'competitor') {
    quickProfile.value = null
    quickProfileOpen.value = false
  }
}

async function discoverQuickCompetitor({ reveal = true } = {}) {
  const normalized = normalizeUrl(quickUrl.value)
  if (!normalized) {
    error.value = '请输入需要识别的竞品网站地址'
    quickUrlInput.value?.focus()
    return null
  }
  if (!tenantId.value && !await ensureTenant()) return null
  quickProfileLoading.value = true
  try {
    const result = await discoverGeoBrand({ tenantId: tenantId.value, website: normalized })
    quickProfile.value = result.brand || null
    quickUrl.value = result.brand?.website || normalized
    if (reveal) quickProfileOpen.value = true
    return quickProfile.value
  } catch (e) {
    if (reveal) error.value = e.message || '竞品公开资料识别失败'
    return null
  } finally {
    quickProfileLoading.value = false
  }
}

function focusQuickInput() {
  document.querySelector('#quick-audit')?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  nextTick(() => quickUrlInput.value?.focus())
}

async function startQuickAudit() {
  const normalized = normalizeUrl(quickUrl.value)
  if (!normalized) {
    error.value = quickMode.value === 'competitor' ? '请输入需要对标的竞品网站地址' : '请输入需要诊断的网站地址'
    quickUrlInput.value?.focus()
    return
  }
  if (quickMode.value === 'own') {
    url.value = normalized
    await startAudit()
    return
  }
  if (!tenantId.value && !await ensureTenant()) return
  error.value = ''
  loading.value = true
  audit.value = null
  startStageProgress()
  try {
    const [auditResult, profileResult] = await Promise.allSettled([
      runCompetitorAudit({ tenantId: tenantId.value, url: normalized, scope: auditScope.value }),
      discoverQuickCompetitor({ reveal: false }),
    ])
    if (auditResult.status === 'rejected') throw auditResult.reason
    audit.value = auditResult.value
    if (profileResult.status === 'fulfilled' && profileResult.value) quickProfile.value = profileResult.value
    quickUrl.value = audit.value.final_url || normalized
    loadingStage.value = loadingStages.length - 1
    ElMessage.success('竞品公开网站检测完成')
    await nextTick()
    document.querySelector('#diagnosis-report')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  } catch (e) {
    error.value = e.message || '竞品网站检测失败，请确认网址可公开访问'
  } finally {
    stopStageProgress()
    loading.value = false
  }
}

async function createAdvice() {
  if (!audit.value) return
  adviceLoading.value = true
  try {
    audit.value = await generateGeoAdvice({ tenantId: tenantId.value, auditId: audit.value.id })
    ElMessage.success(audit.value.advice_source === 'ai' ? 'AI 行动建议已生成' : '行动建议已生成')
  } catch (e) {
    ElMessage.error(e.message || '行动建议生成失败')
  } finally {
    adviceLoading.value = false
  }
}

async function createDeepSeekSample() {
  if (!audit.value || samplingLoading.value) return
  samplingLoading.value = true
  try {
    audit.value = await runDeepSeekSample({
      tenantId: tenantId.value,
      auditId: audit.value.id,
      questions: sampleQuestions.value.map((item) => item.trim()).filter(Boolean),
    })
    sampleQuestions.value = (audit.value.snapshot?.ai_sampling?.results || []).map((item) => item.question)
    while (sampleQuestions.value.length < 3) sampleQuestions.value.push('')
    ElMessage.success('DeepSeek 品牌提及抽样完成')
  } catch (e) {
    ElMessage.error(e.message || 'DeepSeek 抽样失败，请稍后重试')
  } finally {
    samplingLoading.value = false
  }
}

async function copySampleResponse(item) {
  try {
    await navigator.clipboard.writeText(`问题：${item.question}\n\n${item.response}`)
    ElMessage.success('原始回答已复制')
  } catch {
    ElMessage.error('复制失败，请手动选择内容')
  }
}

async function navigateReport(key) {
  if (!brandReady.value) {
    openAsset('brand')
    ElMessage.warning('完成品牌基础信息后即可进入网站体检')
    return
  }
  activeAsset.value = ''
  await nextTick()
  const target = document.querySelector(`#section-${key}`)
  if (!target) {
    error.value = '请先完成一次网站诊断，再查看对应的报告模块'
    document.querySelector('#section-overview')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    return
  }
  activeReport.value = key
  window.history.replaceState(null, '', `${window.location.pathname}#section-${key}`)
  target.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

async function bridgeToContent(adviceCode) {
  if (!audit.value || !tenantId.value) return
  bridgeLoading.value = true
  try {
    const result = await createGeoTaskFromDiagnosis({
      tenantId: tenantId.value,
      auditId: audit.value.id,
      adviceCode,
    })
    const taskId = result?.id
    if (!taskId) throw new Error('创建成功但未返回任务 ID')

    const geoOrigin = (import.meta.env.VITE_GEO_WORKBENCH_ORIGIN || 'http://127.0.0.1:5176').replace(/\/$/, '')
    const url = new URL(`${geoOrigin}/geo/editor.html`)
    // Merge server deep-link params if present, then force critical query fields
    if (result.editor_path && /^https?:\/\//i.test(result.editor_path)) {
      try {
        const fromApi = new URL(result.editor_path)
        fromApi.searchParams.forEach((v, k) => url.searchParams.set(k, v))
      } catch {
        /* ignore bad editor_path */
      }
    }
    url.searchParams.set('task_id', String(taskId))
    url.searchParams.set('tenant_id', String(tenantId.value))
    url.searchParams.set('api_origin', import.meta.env.VITE_GEO_API_ORIGIN || 'http://127.0.0.1:8011')
    if (import.meta.env.VITE_API_KEY) {
      url.searchParams.set('api_key', import.meta.env.VITE_API_KEY)
    }

    const opened = window.open(url.toString(), '_blank')
    if (!opened) {
      ElMessage.warning('弹窗被拦截，请允许后重试，或手动打开：' + url.toString())
    } else {
      ElMessage.success(`已创建任务 #${taskId}，正在打开编辑器`)
    }
  } catch (e) {
    ElMessage.error(e.message || '创建优化文章失败')
  } finally {
    bridgeLoading.value = false
  }
}

function openAsset(page) {
  activeAsset.value = page
  activeReport.value = ''
  window.history.replaceState(null, '', `${window.location.pathname}#asset-${page}`)
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

async function handleBrandSaved(profile) {
  brandReady.value = true
  brandProfile.value = profile || {}
  url.value = profile?.website || url.value
  quickMode.value = 'own'
  quickUrl.value = url.value
  activeAsset.value = ''
  activeReport.value = 'overview'
  window.history.replaceState(null, '', `${window.location.pathname}#section-overview`)
  await nextTick()
  await startAudit()
}

function severityLabel(value) {
  return { critical: '阻断', high: '高优先', medium: '中优先', low: '建议' }[value] || value
}

function pageScoreTone(score) {
  if (score >= 80) return 'good'
  if (score >= 60) return 'fair'
  return 'risk'
}

function categoryLabel(item) {
  if (['AI 引用就绪度', 'AI 可引用性', 'AI 可访问性'].includes(item.category)) return 'AI 引用就绪度'
  return item.category
}

function issueDomain(item) {
  if (['技术基础', '页面语义'].includes(item.category)) return 'seo'
  if (['结构化数据', 'AI 引用就绪度', 'AI 可引用性', 'AI 可访问性'].includes(item.category)) return 'geo'
  return 'content'
}

function issueDomainLabel(item) {
  return { seo: 'SEO', geo: 'GEO', content: '内容' }[issueDomain(item)]
}

function formatDate(value) {
  if (!value) return '刚刚'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(value))
}

function formatMetricNumber(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—'
  return new Intl.NumberFormat('zh-CN').format(Number(value))
}

function formatCompactMetric(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '待配置'
  const number = Number(value)
  if (number >= 100000000) return `${Number((number / 100000000).toFixed(1))}亿`
  if (number >= 10000) return `${Number((number / 10000).toFixed(1))}万`
  return new Intl.NumberFormat('zh-CN').format(number)
}

function metricSourceLabel(metric, configuredLabel) {
  if (metric?.status === 'available') return `站长之家实时数据 · ${formatDate(metric.queried_at)}`
  return metric?.reason || `${configuredLabel}待配置`
}

function formatCwvMetric(metric, key) {
  if (!metric || metric.value === null || metric.value === undefined) return key === 'inp' ? '暂无真实用户数据' : '暂无数据'
  if (key === 'lcp') return `${Number(metric.value).toFixed(1)}s`
  if (key === 'cls') return Number(metric.value).toFixed(2)
  return `${Math.round(Number(metric.value))}ms`
}

function cwvStatusLabel(metric) {
  if (!metric) return '—'
  return { good: '✓', needs_improvement: '!', poor: '×' }[metric.status] || '—'
}

const pageSpeedSourceLabel = computed(() => {
  if (pageSpeedLoading.value) return '正在运行 Lighthouse 移动端检测…'
  if (!pageSpeed.value) return '尚未检测网站访问体验'
  if (pageSpeed.value.status !== 'available') return pageSpeed.value.reason || 'PageSpeed 暂无数据'
  if (pageSpeed.value.provider === 'local_lighthouse') {
    return '本地 Lighthouse · 移动端实验室数据；INP 需真实用户样本'
  }
  const source = pageSpeed.value.field_data_source === 'url'
    ? '页面级 CrUX 真实用户数据'
    : pageSpeed.value.field_data_source === 'origin'
      ? '域名级 CrUX 真实用户数据'
      : 'Lighthouse 实验室数据（CrUX 样本不足）'
  return `Google PageSpeed Insights · 移动端 · ${source}`
})

async function loadPageSpeed(targetUrl) {
  const normalized = normalizeUrl(targetUrl)
  if (!normalized || !tenantId.value) {
    pageSpeed.value = null
    return
  }
  const requestId = ++pageSpeedRequestId
  pageSpeedLoading.value = true
  try {
    const result = await fetchPageSpeedInsights({
      tenantId: tenantId.value,
      url: normalized,
      strategy: 'mobile',
    })
    if (requestId === pageSpeedRequestId) pageSpeed.value = result
  } catch (e) {
    if (requestId === pageSpeedRequestId) {
      pageSpeed.value = { status: 'error', reason: e.message || 'PageSpeed 检测暂时失败', metrics: {} }
    }
  } finally {
    if (requestId === pageSpeedRequestId) pageSpeedLoading.value = false
  }
}

async function printReport() {
  if (!audit.value) return
  historyOpen.value = false
  ElMessage.closeAll()
  ElMessageBox.close()
  const originalTitle = document.title
  const domain = (() => {
    try { return new URL(audit.value.final_url || audit.value.url).hostname.replace(/^www\./, '') }
    catch { return 'website' }
  })()
  const date = new Date(audit.value.created_at || Date.now()).toISOString().slice(0, 10)
  document.title = `G-Snipers_${domain}_诊断报告_${date}`
  await nextTick()
  const restoreTitle = () => {
    document.title = originalTitle
    window.removeEventListener('afterprint', restoreTitle)
  }
  window.addEventListener('afterprint', restoreTitle)
  window.print()
  window.setTimeout(restoreTitle, 3000)
}

watch(tenantId, () => {
  audit.value = null
  pageSpeed.value = null
  url.value = ''
  quickMode.value = 'own'
  quickUrl.value = ''
  quickProfile.value = null
  quickProfileOpen.value = false
  brandReady.value = false
  brandProfile.value = {}
  loadLatest()
})

watch(
  () => audit.value?.final_url || audit.value?.url || '',
  (targetUrl) => loadPageSpeed(targetUrl),
)

onMounted(async () => {
  await ensureTenant()
  await loadLatest()
  const legacyView = new URLSearchParams(window.location.search).get('view')
  const hashView = window.location.hash.replace('#section-', '')
  const hashAsset = window.location.hash.replace('#asset-', '')
  if (assetNav.some((item) => item.page === hashAsset)) {
    openAsset(hashAsset)
    return
  }
  if (!brandReady.value) {
    openAsset('brand')
    return
  }
  const initialView = reportNav.some((item) => item.key === hashView)
    ? hashView
    : reportNav.some((item) => item.key === legacyView)
      ? legacyView
      : 'overview'
  await nextTick()
  navigateReport(initialView)
})
</script>

<template>
  <main class="diagnosis-center">
    <aside class="diagnosis-sidebar">
      <div class="diagnosis-brand">
        <img class="brand-mark" :src="diagnosticLogo" alt="G-Snipers 获客狙击手" />
        <span><strong>获客狙击手</strong><small>G-SNIPERS · 诊断中心</small></span>
      </div>

      <div class="nav-label">诊断报告</div>
      <button
        v-for="item in reportNav"
        :key="item.key"
        class="sidebar-item"
        :class="{ active: activeReport === item.key }"
        type="button"
        @click="navigateReport(item.key)"
      >
        <span class="sidebar-icon">{{ item.icon }}</span>{{ item.label }}
      </button>

      <div class="nav-label asset-label">品牌资产</div>
      <button
        v-for="item in assetNav"
        :key="item.page"
        class="sidebar-item"
        :class="{ active: activeAsset === item.page }"
        type="button"
        @click="openAsset(item.page)"
      >
        <span class="sidebar-icon">{{ item.icon }}</span>{{ item.label }}
      </button>

      <div class="sidebar-spacer" />
      <a class="sidebar-item module-link" href="/deal-sniper/sem/dashboard"><span>¥</span>去 SEM 模块</a>
      <a class="sidebar-item module-link" href="/deal-sniper/seo/dashboard"><span>⌕</span>去 SEO 模块</a>
      <a class="sidebar-item module-link" href="/deal-sniper/geo/dashboard"><span>✦</span>去 GEO 模块</a>
      <div class="sidebar-bottom">
        <a href="/deal-sniper/hub/dashboard">⌂ 全域驾驶舱</a>
        <a href="/deal-sniper/portal">← 平台门户</a>
      </div>
    </aside>

    <section class="diagnosis-main">
      <header class="diagnosis-topbar">
        <div>
          <span class="topbar-kicker">{{ activeAsset ? `DIAGNOSTIC CENTER / ${currentAsset.kicker}` : 'AI ACQUISITION COMMAND / OVERVIEW' }}</span>
          <h1>{{ activeAsset ? currentAsset.label : '诊断指挥舱' }}</h1>
          <p>{{ activeAsset ? currentAsset.description : '汇聚 SEO、GEO 与可信信号，定位影响获客的关键阻力' }}</p>
        </div>
        <div class="topbar-actions">
          <template v-if="!activeAsset">
            <button type="button" :disabled="loading" @click="startNewDiagnosis">⌁ 新建诊断</button>
            <button type="button" @click="openAuditHistory">↺ 查看最近诊断</button>
            <button type="button" :disabled="!audit" @click="printReport">⇩ 导出报告</button>
          </template>
          <button v-else type="button" @click="navigateReport('overview')">← 返回网站体检</button>
          <span class="avatar">DZ</span>
        </div>
      </header>

      <div v-if="historyOpen" class="history-modal-backdrop" role="presentation" @click.self="historyOpen = false">
        <section class="history-modal" role="dialog" aria-modal="true" aria-labelledby="history-title">
          <header>
            <div>
              <span>DIAGNOSIS ARCHIVE</span>
              <h2 id="history-title">最近诊断记录</h2>
              <p>选择一份已保存的官网报告继续查看；竞品临时对标不会写入记录。</p>
            </div>
            <button type="button" aria-label="关闭诊断记录" @click="historyOpen = false">×</button>
          </header>
          <div v-if="historyLoading" class="history-loading"><i /><span>正在读取诊断记录…</span></div>
          <div v-else-if="!historyItems.length" class="history-empty">
            <b>暂无诊断记录</b>
            <p>完成首次官网诊断后，报告会自动保存在这里。</p>
            <button type="button" @click="historyOpen = false; startNewDiagnosis()">开始首次诊断</button>
          </div>
          <div v-else class="history-list">
            <button
              v-for="item in historyItems"
              :key="item.id"
              type="button"
              :class="{ current: audit?.id === item.id }"
              :disabled="historySelectingId === item.id"
              @click="selectHistoricalAudit(item)"
            >
              <span class="history-score" :class="pageScoreTone(item.score)"><b>{{ item.score ?? '—' }}</b><small>/100</small></span>
              <span class="history-copy">
                <strong>{{ item.page_title || '未设置页面标题' }}</strong>
                <em>{{ item.final_url || item.url }}</em>
                <small>{{ formatDate(item.created_at) }} · {{ item.scope === 'site' ? `全站抽样 ${item.page_count} 页` : '单页诊断' }}</small>
              </span>
              <span class="history-action">{{ historySelectingId === item.id ? '载入中…' : (audit?.id === item.id ? '当前报告' : '查看报告 →') }}</span>
            </button>
          </div>
          <footer><i />最多显示最近 12 次正式官网诊断，按诊断时间倒序排列。</footer>
        </section>
      </div>

      <div v-if="!activeAsset" class="diagnosis-content">
        <div id="section-overview" class="report-overview-anchor" />
        <p v-if="error" class="diagnosis-error-banner">{{ error }}</p>

        <section v-if="!loading" id="quick-audit" class="quick-audit-bar" :class="quickMode">
          <header>
            <div>
              <span>QUICK WEBSITE CHECK</span>
              <strong>{{ quickMode === 'competitor' ? '竞品网站快速对标' : '开始一次新诊断' }}</strong>
            </div>
            <div class="quick-mode-switch" aria-label="切换诊断对象">
              <button type="button" :class="{ active: quickMode === 'own' }" @click="selectQuickMode('own')">我的官网</button>
              <button type="button" :class="{ active: quickMode === 'competitor' }" @click="selectQuickMode('competitor')">竞品网站</button>
            </div>
          </header>
          <div class="quick-audit-form">
            <span aria-hidden="true">⌕</span>
            <input
              ref="quickUrlInput"
              v-model="quickUrl"
              type="url"
              :placeholder="quickMode === 'competitor' ? '输入竞品官网，例如 competitor.com' : '输入官网首页或需要检测的具体页面'"
              :aria-label="quickMode === 'competitor' ? '竞品网站地址' : '本次诊断网址'"
              @input="handleQuickUrlInput"
              @keydown.enter.prevent="startQuickAudit"
            >
            <button type="button" :disabled="!quickUrl" @click="startQuickAudit">
              {{ quickMode === 'competitor' ? '开始对标 →' : '开始诊断 →' }}
            </button>
          </div>
          <footer>
            <div class="quick-scope-switch">
              <label :class="{ active: auditScope === 'single' }"><input v-model="auditScope" type="radio" value="single"> 单页快速诊断</label>
              <label :class="{ active: auditScope === 'site' }"><input v-model="auditScope" type="radio" value="site"> 全站抽样诊断 <small>最多10页</small></label>
            </div>
            <p v-if="quickMode === 'competitor'"><i />仅检测公开网站数据，不写入你的品牌档案，也不覆盖最近一次官网诊断。</p>
            <p v-else><i />本次网址不会自动修改基础信息中的官方网站。</p>
            <button v-if="isCompetitorAudit" class="return-own-report" type="button" @click="loadLatest({ notify: true })">返回我的官网报告</button>
          </footer>

          <section class="quick-profile-context" :class="{ empty: !quickProfileContext?.name }">
            <div class="quick-profile-identity">
              <span>{{ quickMode === 'competitor' ? '临时竞品档案' : '官网基础档案' }}</span>
              <strong>{{ quickProfileContext?.name || (quickMode === 'competitor' ? '尚未识别竞品资料' : '基础信息待完善') }}</strong>
              <small v-if="quickProfileContext?.industry">{{ quickProfileContext.industry }}</small>
              <small v-else>{{ quickMode === 'competitor' ? '识别后可查看全部公开基础字段' : '诊断会读取已保存的基础信息，不会只看网址' }}</small>
            </div>
            <div v-if="quickProfileContext?.name" class="quick-profile-metrics">
              <span><b>{{ quickProfileStats.products }}</b>产品与服务</span>
              <span><b>{{ quickProfileStats.terms }}</b>品牌词</span>
              <span><b>{{ quickProfileStats.proof }}</b>可信证明</span>
              <span v-if="quickMode === 'own'"><b>{{ quickProfileStats.competitors }}</b>已确认竞品</span>
            </div>
            <div class="quick-profile-actions">
              <button v-if="quickMode === 'own'" type="button" @click="openAsset('brand')">查看全部基础信息 →</button>
              <button v-else-if="!quickProfileContext?.name" type="button" :disabled="quickProfileLoading || !quickUrl" @click="discoverQuickCompetitor()">
                {{ quickProfileLoading ? '正在识别…' : '识别竞品资料 →' }}
              </button>
              <button v-else type="button" @click="quickProfileOpen = !quickProfileOpen">{{ quickProfileOpen ? '收起完整资料 ↑' : '查看全部字段 ↓' }}</button>
            </div>
          </section>

          <div v-if="quickMode === 'competitor' && quickProfileContext?.name && quickProfileOpen" class="quick-profile-detail">
            <section><span>品牌名称</span><strong>{{ quickProfileContext.name }}</strong><small>{{ quickProfileContext.evidence?.name || '官网公开信息' }}</small></section>
            <section><span>所属行业</span><strong>{{ quickProfileContext.industry || '官网未明确披露' }}</strong><small>{{ quickProfileContext.evidence?.industry || '待补充判断' }}</small></section>
            <section class="wide"><span>业务定位与品牌介绍</span><p>{{ quickProfileContext.business_desc || '官网未提取到明确的业务定位描述。' }}</p><small>{{ quickProfileContext.evidence?.business_desc || '官网公开信息' }}</small></section>
            <section><span>品牌词</span><div class="quick-profile-tags"><i v-for="item in (quickProfileContext.brand_terms || []).slice(0, 8)" :key="item">{{ item }}</i><em v-if="!quickProfileContext.brand_terms?.length">未识别</em></div></section>
            <section><span>核心产品与服务</span><div class="quick-profile-tags"><i v-for="item in (quickProfileContext.core_products || []).slice(0, 10)" :key="item">{{ item }}</i><em v-if="!quickProfileContext.core_products?.length">未识别</em></div></section>
            <section class="wide"><span>可信信息与证明</span><div class="quick-profile-tags"><i v-for="item in (quickProfileContext.proof_points || []).slice(0, 10)" :key="item">{{ item }}</i><em v-if="!quickProfileContext.proof_points?.length">官网当前未提取到明确的资质、客户、奖项或数据证明</em></div></section>
            <footer><i />以上内容来自竞品公开官网，仅用于本次对标，不会保存到你的品牌档案。</footer>
          </div>
        </section>

        <section v-if="loading" class="loading-report" aria-live="polite">
          <div class="loading-orbit"><span /><i /></div>
          <div>
            <span class="section-index">ANALYSIS IN PROGRESS</span>
            <h2>{{ loadingStages[loadingStage] }}</h2>
            <p>{{ loadingStage + 1 }} / {{ loadingStages.length }} · 请保持当前页面打开</p>
          </div>
          <div class="stage-track">
            <span
              v-for="(stage, index) in loadingStages"
              :key="stage"
              :class="{ done: index <= loadingStage }"
            >{{ index + 1 }}</span>
          </div>
        </section>

        <section v-else-if="!audit" class="preflight-grid">
          <article>
            <span>SEO</span>
            <h3>搜索基础检查</h3>
            <p>索引、Canonical、TDK、标题结构和正文信息量。</p>
            <b>6 类信号</b>
          </article>
          <article>
            <span>GEO</span>
            <h3>AI 就绪度检查</h3>
            <p>Schema、实体表达、问答结构、llms.txt 与直答能力。</p>
            <b>5 类信号</b>
          </article>
          <article>
            <span>TRUST</span>
            <h3>可信与引用检查</h3>
            <p>作者、更新时间、外部证据和可核验信息。</p>
            <b>5 类信号</b>
          </article>
        </section>

        <template v-else>
          <div id="diagnosis-report" class="report-anchor" />

          <section class="print-report-header">
            <div><img :src="diagnosticLogo" alt="G-Snipers"><span><b>G-Snipers 官网 AI 搜索诊断报告</b><small>专业团队审核 · 基于网站公开证据生成</small></span></div>
            <p><strong>{{ audit.page_title || '网站诊断报告' }}</strong><span>{{ audit.final_url || audit.url }}</span></p>
          </section>

          <section class="report-meta">
            <div>
              <span class="live-dot" /> {{ isCompetitorAudit ? '竞品公开检测完成' : '诊断完成' }}
              <strong>{{ audit.page_title || '页面未设置标题' }}</strong>
              <a :href="audit.final_url" target="_blank" rel="noopener">{{ audit.final_url }}</a>
            </div>
            <span>{{ formatDate(audit.created_at) }} · {{ isSiteAudit ? `全站抽样 ${sitePages.length} 页` : '单页诊断' }} · 规则版本 v{{ audit.rule_version || '1.1.0' }}</span>
          </section>

          <nav class="flow-map" :class="{ compact: isCompetitorAudit }" aria-label="诊断报告阅读顺序">
            <a href="#flow-overview"><b>01</b><span>诊断总览<small>得分与能力结构</small></span></a>
            <a href="#flow-diagnosis"><b>02</b><span>SEO / GEO 诊断<small>规则、证据与扣分</small></span></a>
            <a v-if="!isCompetitorAudit" href="#flow-brand"><b>03</b><span>AI 品牌识别<small>品牌、竞品与提及</small></span></a>
            <a href="#flow-action"><b>{{ isCompetitorAudit ? '03' : '04' }}</b><span>{{ isCompetitorAudit ? '竞品问题' : '问题与行动' }}<small>优先级与诊断依据</small></span></a>
          </nav>

          <section class="flow-screen overview-screen">
          <div id="flow-overview" class="flow-stage-heading">
            <span>01</span><div><b>OVERVIEW</b><h2>概览</h2><p>站点健康度、AI 搜索就绪度与关键诊断信号</p></div>
          </div>

          <section class="ai-conclusion-card" :class="scoreTone">
            <div class="conclusion-score">
              <span>AI 搜索准备度</span>
              <div class="readiness-score-gauge">
                <svg viewBox="0 0 240 220" aria-hidden="true">
                  <defs>
                    <linearGradient id="readiness-score-gradient" gradientUnits="userSpaceOnUse" x1="42" y1="190" x2="202" y2="35">
                      <stop offset="0" stop-color="#b9ed92"/>
                      <stop offset=".34" stop-color="#55d97d"/>
                      <stop offset=".7" stop-color="#12bd7d"/>
                      <stop offset="1" stop-color="#078d68"/>
                    </linearGradient>
                  </defs>
                  <circle class="readiness-track" cx="120" cy="111" r="82" pathLength="490" />
                  <circle class="readiness-progress" cx="120" cy="111" r="82" pathLength="490" :stroke-dasharray="`${3.67 * audit.score} 490`" />
                </svg>
                <div><strong>{{ audit.score }}</strong><small>/100</small></div>
              </div>
              <em>{{ scoreLabel }}</em>
              <p v-if="audit.score < 100">距离优秀还有 <b>{{ 100 - audit.score }} 分</b>提升空间</p>
              <p v-else>当前已达到满分基准</p>
              <div class="overview-capability-composition" aria-label="AI 搜索准备度能力组成">
                <div><span>SEO 基础能力</span><strong>68<small>/100</small></strong><i><b style="width:68%" /></i></div>
                <div><span>GEO 理解能力</span><strong>55<small>/100</small></strong><i><b style="width:55%" /></i></div>
                <div><span>AI 引用准备度</span><strong>40<small>/100</small></strong><i><b style="width:40%" /></i></div>
                <p>SEO 是 AI 搜索能力的一部分，但不是最终结果。</p>
              </div>
            </div>
            <div class="conclusion-copy">
              <span class="section-index">AI DIAGNOSTIC RESULT</span>
              <h2>{{ isCompetitorAudit ? '竞品网站公开诊断结果' : '官网 AI 搜索诊断结果' }}</h2>
              <p>{{ readinessConclusion }}</p>
              <div class="ai-risk-note">
                <span>如果不优化</span>
                <p>{{ aiEraRisk }}</p>
              </div>
              <h3 class="findings-label">主要发现</h3>
              <div class="conclusion-findings">
                <article v-for="item in primaryFindings" :key="`conclusion-${item.code}`" :class="item.severity">
                  <span>{{ findingLabel(item) }}</span>
                  <strong>{{ ruleNarrative(item).userTitle }}</strong>
                  <small>{{ businessImpact(item) }}</small>
                </article>
                <article v-if="!primaryFindings.length" class="passed">
                  <span>当前表现良好</span>
                  <strong>16 项基础检查均达到当前规则要求</strong>
                  <small>建议继续监测真实 AI 品牌提及和行业内容竞争力。</small>
                </article>
              </div>
              <aside class="authority-proof" aria-label="诊断报告专业团队背书">
                <div class="authority-proof-brand">
                  <img class="authority-seal" :src="diagnosticLogo" alt="G-Snipers" />
                  <div>
                    <small>PROFESSIONAL TEAM REVIEW</small>
                    <strong>G-Snipers 专业团队出品</strong>
                  </div>
                </div>
                <p>
                  本报告由具备多年企业搜索增长与 AI 获客实战经验的专业团队出品，服务经验覆盖多家世界 500 强企业。诊断结论与建议基于公开技术标准、真实项目方法论及本次网站检测证据综合生成。
                </p>
                <div class="authority-credentials" aria-label="团队经验与诊断依据">
                  <span><i>✓</i> 多年企业实战经验</span>
                  <span><i>✓</i> 多家世界 500 强服务经验</span>
                  <span><i>✓</i> 基于本次网站真实证据</span>
                </div>
              </aside>
            </div>
          </section>

          <div class="overview-dashboard">
            <article class="dashboard-card health-dashboard-card">
              <header>
                <div><h3>16 项基础规则</h3><small>FOUNDATION CHECKS</small></div>
                <details class="score-rules-help">
                  <summary aria-label="查看站点健康度评分规则" title="查看评分规则">?</summary>
                  <section class="score-rules-popover">
                    <header>
                      <div><small>SCORING MODEL</small><h4>站点健康度如何计算</h4></div>
                      <span>规则版本 v{{ audit.rule_version || '1.1.0' }}</span>
                    </header>
                    <p class="score-rules-summary">
                      满分 100 分，共 {{ findings.length }} 项固定权重规则。单页按是否满足规则扣分；全站诊断按首页 3、核心页 2、普通页 1 汇总各项通过率。
                    </p>
                    <div class="score-rule-list">
                      <article v-for="(item, index) in findings" :key="`score-rule-${item.code}`" :class="{ passed: item.passed }">
                        <span>{{ String(index + 1).padStart(2, '0') }}</span>
                        <div>
                          <header><strong>{{ ruleNarrative(item).userTitle }}</strong><em>{{ item.category }}</em></header>
                          <p>{{ ruleNarrative(item).why }}</p>
                          <p class="rule-technical-note">技术规则：{{ item.title }} · {{ item.criterion || item.recommendation }}</p>
                          <small>当前证据：{{ item.evidence }}</small>
                        </div>
                        <b>{{ item.weight || item.deduction }} 分</b>
                      </article>
                    </div>
                    <footer><i /> 已通过 {{ passedCount }} 项 <span>未通过规则按固定权重扣分，已通过项不会从分母中消失。</span></footer>
                  </section>
                </details>
              </header>
              <div class="foundation-stats">
                <article class="passed">
                  <span>通过项</span>
                  <strong>{{ passedCount }}</strong>
                  <small>已达到检测要求</small>
                </article>
                <article class="pending">
                  <span>待优化项</span>
                  <strong>{{ Math.max(0, findings.length - passedCount) }}</strong>
                  <small>影响当前准备度</small>
                </article>
                <article class="risk">
                  <span>高影响问题</span>
                  <strong>{{ problemCounts.critical + problemCounts.high }}</strong>
                  <small>建议优先处理</small>
                </article>
              </div>
              <div class="foundation-summary">
                <div><i :style="{ width: `${rulePassRate}%` }" /></div>
                <p><b>{{ rulePassRate }}%</b> 的规则已通过。总评分由 16 项固定权重规则共同计算，点击右上角问号可查看完整依据。</p>
              </div>
            </article>

            <article class="dashboard-card radar-dashboard-card">
              <header><div><h3>AI 搜索健康度雷达</h3><small>AI SEARCH HEALTH RADAR</small></div><span>···</span></header>
              <div class="dashboard-radar">
                <svg viewBox="0 0 220 220" role="img" aria-label="六维诊断雷达图">
                  <g class="radar-grid">
                    <polygon points="110,28 181,69 181,151 110,192 39,151 39,69" />
                    <polygon points="110,55 158,82 158,138 110,165 62,138 62,82" />
                    <polygon points="110,82 134,96 134,124 110,138 86,124 86,96" />
                    <line x1="110" y1="110" x2="110" y2="28" /><line x1="110" y1="110" x2="181" y2="69" /><line x1="110" y1="110" x2="181" y2="151" />
                    <line x1="110" y1="110" x2="110" y2="192" /><line x1="110" y1="110" x2="39" y2="151" /><line x1="110" y1="110" x2="39" y2="69" />
                  </g>
                  <polygon class="radar-value" :points="radarPoints" />
                  <circle v-for="(item, index) in dimensions" :key="`dashboard-${item.key}`" :cx="radarPoints.split(' ')[index]?.split(',')[0]" :cy="radarPoints.split(' ')[index]?.split(',')[1]" r="3.5" />
                </svg>
                <span v-for="(item, index) in dimensions" :key="`label-${item.key}`" :class="`dashboard-radar-label radar-position-${index + 1}`">{{ item.label }}</span>
              </div>
              <footer><span><i />当前诊断</span><span><i />100 分基准</span></footer>
            </article>

            <article class="dashboard-card metrics-dashboard-card">
              <header><div><h3>核心指标</h3><small>KEY METRICS</small></div><span>···</span></header>
              <div class="dashboard-metrics">
                <section><span>规则通过</span><strong>{{ passedCount }}<small>/{{ findings.length }}</small></strong><i>✓</i><b>{{ Math.round(passedCount / Math.max(findings.length, 1) * 100) }}%</b></section>
                <section><span>高优先问题</span><strong>{{ problemCounts.critical + problemCounts.high }}</strong><i>!</i><b>{{ problemCounts.critical }} 阻断</b></section>
                <section><span>{{ isSiteAudit ? '抽样页面' : '内容单元' }}</span><strong>{{ isSiteAudit ? sitePages.length : (audit.snapshot?.content_units || 0) }}</strong><i>↗</i><b>{{ isSiteAudit ? '全站诊断' : '当前页面' }}</b></section>
                <section><span>已确认竞品</span><strong>{{ confirmedCompetitors.length }}</strong><i>◎</i><b>品牌参照</b></section>
                <section class="baidu-index-metric" :class="{ unavailable: baiduIndexMetric.status !== 'available' }" :title="baiduIndexMetric.methodology || baiduIndexMetric.reason">
                  <span>百度收录量</span>
                  <strong>{{ formatMetricNumber(baiduIndexMetric.site_count) }}</strong>
                  <i>百</i>
                  <b v-if="baiduIndexMetric.status === 'available'">站长之家估算 · {{ formatDate(baiduIndexMetric.queried_at) }}</b>
                  <b v-else>{{ baiduIndexMetric.reason || '暂未获取' }}</b>
                  <a :href="baiduIndexMetric.source_url" target="_blank" rel="noopener">查看数据来源</a>
                </section>
              </div>
            </article>

            <article class="dashboard-card signals-dashboard-card">
              <header><div><h3>六维诊断信号</h3><small>READINESS SIGNALS</small></div><span>···</span></header>
              <div class="signal-chart">
                <div v-for="item in dimensions" :key="`signal-${item.key}`"><span>{{ item.label }}</span><i><b :style="{ width: `${item.score}%` }" /></i><strong>{{ item.score }}</strong></div>
              </div>
            </article>

            <article class="dashboard-card recent-dashboard-card">
              <header><div><h3>当前诊断范围</h3><small>CURRENT DIAGNOSTICS</small></div><span>···</span></header>
              <div class="recent-diagnostics">
                <template v-if="sitePages.length">
                  <div v-for="page in sitePages.slice(0, 3)" :key="`recent-${page.url}`"><i>✓</i><p><strong>{{ page.title || page.url }}</strong><small>{{ page.page_type }} · 权重 {{ page.weight }}</small></p><b>{{ page.score }} 分</b></div>
                </template>
                <div v-else><i>✓</i><p><strong>{{ audit.page_title || audit.final_url }}</strong><small>单页网站诊断</small></p><b>已完成</b></div>
              </div>
            </article>

            <button class="dashboard-cta primary" type="button" :disabled="loading || !url" @click="startAudit"><span>◎</span><p><strong>启动新一轮诊断</strong><small>使用基础信息中的官网重新检查站点健康度</small></p><b>{{ loading ? '诊断进行中…' : '立即诊断 →' }}</b></button>
            <a class="dashboard-cta" href="#flow-action"><span>✦</span><p><strong>智能优化建议</strong><small>根据当前问题形成行动路线</small></p><b>查看建议 →</b></a>

            <article class="dashboard-card suggestions-dashboard-card">
              <header><div><h3>最近优化建议</h3><small>RECENT OPTIMIZATION SUGGESTIONS</small></div><span>···</span></header>
              <div class="dashboard-suggestions">
                <a v-for="item in problems.slice(0, 4)" :key="`suggestion-${item.code}`" href="#flow-action"><i :class="item.severity">{{ item.severity === 'critical' ? '!' : '✓' }}</i><p><strong>{{ item.title }}</strong><small>{{ item.recommendation }}</small></p><b>去处理</b></a>
                <p v-if="!problems.length" class="dashboard-clean">当前没有需要优先处理的问题</p>
              </div>
            </article>
          </div>

          <section v-if="isSiteAudit" class="site-coverage-panel">
            <div class="site-coverage-heading">
              <div><span class="section-index">SITE COVERAGE</span><h2>全站抽样范围</h2></div>
              <p>{{ siteAudit.aggregation_method }}</p>
            </div>
            <div class="site-coverage-meta">
              <span>页面发现：{{ siteAudit.discovery_source === 'sitemap' ? 'Sitemap' : '首页站内链接' }}</span>
              <span>成功诊断：{{ siteAudit.successful_pages }}/{{ siteAudit.requested_pages }} 页</span>
              <span>加权基数：{{ siteAudit.total_weight }}</span>
            </div>
            <div class="site-page-grid">
              <article v-for="(page, index) in sitePages" :key="page.url" :class="pageScoreTone(page.score)">
                <span>{{ String(index + 1).padStart(2, '0') }}</span>
                <div><small>{{ page.page_type }} · 权重 {{ page.weight }}</small><h3>{{ page.title || page.url }}</h3><a :href="page.url" target="_blank" rel="noopener">{{ page.url }}</a></div>
                <strong>{{ page.score }}</strong>
              </article>
            </div>
          </section>

          <section class="summary-grid">
            <article class="overall-card" :class="scoreTone">
              <div class="score-ring" :style="{ '--score': `${audit.score * 3.6}deg` }">
                <span><strong>{{ audit.score }}</strong><small>/100</small></span>
              </div>
              <div><span>综合健康度</span><h2>{{ scoreLabel }}</h2><p>基于 {{ findings.length }} 项可解释规则</p></div>
            </article>
            <article class="metric-card">
              <span>{{ isSiteAudit ? '规则全站通过' : '检查通过' }}</span><strong>{{ passedCount }}<small>/{{ findings.length }}</small></strong>
              <div class="mini-bar"><i :style="{ width: `${passedCount / Math.max(findings.length, 1) * 100}%` }" /></div>
            </article>
            <article class="metric-card risk-card">
              <span>高优先问题</span><strong>{{ problemCounts.critical + problemCounts.high }}</strong>
              <p>{{ problemCounts.critical }} 阻断 · {{ problemCounts.high }} 高优先</p>
            </article>
            <article class="metric-card">
              <span>{{ isSiteAudit ? '抽样页面' : '页面信息量' }}</span><strong>{{ isSiteAudit ? sitePages.length : (audit.snapshot?.content_units || 0) }}</strong>
              <p>{{ isSiteAudit ? `最多 ${siteAudit.page_limit} 页` : '中英文可读单元' }}</p>
            </article>
          </section>

          <section class="insight-panel">
            <div class="insight-mark">AI</div>
            <div class="insight-main">
              <span class="section-index">DIAGNOSTIC SUMMARY</span>
              <h2>诊断综述</h2>
              <p>{{ diagnosisSummary }}</p>
            </div>
            <div class="priority-note">
              <span>建议先做</span>
              <p>{{ priorityAction }}</p>
            </div>
          </section>

          <section class="capability-panel">
            <div class="panel-heading capability-heading">
              <div>
                <span class="section-index">SCORE DECOMPOSITION / 6 AXES</span>
                <h2>综合评分 · 六维拆解</h2>
                <p>同一套规则，按六个能力域重新归类，直接定位得分来源。</p>
              </div>
              <div class="decomposition-score" :class="scoreTone">
                <span>OVERALL SCORE</span>
                <strong>{{ audit.score }}</strong><small>/100</small>
              </div>
            </div>
            <div class="capability-body">
              <div class="radar-wrap">
                <span class="radar-scan-label">SYSTEM READINESS</span>
                <svg viewBox="0 0 220 220" role="img" aria-label="六维诊断雷达图">
                  <g class="radar-grid">
                    <polygon points="110,28 181,69 181,151 110,192 39,151 39,69" />
                    <polygon points="110,55 158,82 158,138 110,165 62,138 62,82" />
                    <polygon points="110,82 134,96 134,124 110,138 86,124 86,96" />
                    <line x1="110" y1="110" x2="110" y2="28" />
                    <line x1="110" y1="110" x2="181" y2="69" />
                    <line x1="110" y1="110" x2="181" y2="151" />
                    <line x1="110" y1="110" x2="110" y2="192" />
                    <line x1="110" y1="110" x2="39" y2="151" />
                    <line x1="110" y1="110" x2="39" y2="69" />
                  </g>
                  <polygon class="radar-value" :points="radarPoints" />
                  <circle
                    v-for="(item, index) in dimensions"
                    :key="item.key"
                    :cx="radarPoints.split(' ')[index]?.split(',')[0]"
                    :cy="radarPoints.split(' ')[index]?.split(',')[1]"
                    r="3.5"
                  />
                </svg>
                <span class="radar-label label-1">技术</span>
                <span class="radar-label label-2">语义</span>
                <span class="radar-label label-3">结构</span>
                <span class="radar-label label-4">Schema</span>
                <span class="radar-label label-5">就绪</span>
                <span class="radar-label label-6">可信</span>
                <div class="radar-signals">
                  <span><i />最强项 <b>{{ strongestDimension?.label }} {{ strongestDimension?.score }}</b></span>
                  <span><i />优先修复 <b>{{ weakestDimension?.label }} {{ weakestDimension?.score }}</b></span>
                </div>
              </div>
              <div class="dimension-list">
                <article v-for="item in dimensions" :key="item.key" :class="dimensionTone(item.score)">
                  <div class="dimension-title">
                    <span>{{ item.label }}</span>
                    <em>{{ dimensionStatus(item.score) }}</em>
                    <strong>{{ item.score }}<small>/100</small></strong>
                  </div>
                  <div class="dimension-bar"><i :style="{ width: `${item.score}%` }" /></div>
                  <small>规则通过 {{ item.passed }} / {{ item.total }}</small>
                </article>
                <p class="dimension-method"><b>计算逻辑</b><span>总分 = 全部已通过规则权重之和；六维分 = 各维度已通过权重 ÷ 该维度总权重。六维用于解释总分来源，不做相加或平均。</span></p>
              </div>
            </div>
          </section>
          </section>

          <section class="flow-screen diagnosis-screen">
          <div id="flow-diagnosis" class="flow-stage-heading">
            <span>02</span><div><b>SEO + GEO DIAGNOSIS</b><h2>逐项核对规则、证据与扣分原因</h2></div>
          </div>

          <div class="diagnosis-highlights">
            <article v-for="item in featuredFindings" :key="`featured-${item.code}`" :class="{ passed: item.passed }">
              <header><span>{{ categoryLabel(item) }}</span><b>{{ item.passed ? '已通过' : (severityLabel(item.severity) || '待优化') }}</b></header>
              <h3>{{ ruleNarrative(item).userTitle }}</h3>
              <div class="highlight-impact"><i :style="{ width: `${item.passed ? 100 : Math.min(100, Number(item.deduction || 0) / 15 * 100)}%` }" /><strong>{{ item.passed ? 'PASS' : `-${item.deduction}` }}</strong></div>
              <p>{{ ruleNarrative(item).why }}</p>
              <a :href="`#${findingSection(item)}`">进入完整诊断 →</a>
            </article>
          </div>

          <section id="section-seo" class="diagnostic-section seo-report-prototype">
            <div class="panel-heading seo-report-heading">
              <div>
                <span class="section-index">02 / SEO DIAGNOSIS</span>
                <h2>SEO 诊断</h2>
                <p>分析网站搜索基础能力、关键词覆盖、索引质量以及网站访问体验。</p>
              </div>
              <span class="prototype-badge"><i /> {{ chinazSourceState }}</span>
            </div>

            <section class="seo-health-overview" aria-label="SEO 健康度">
              <div class="seo-score-column">
                <span>SEO HEALTH SCORE</span>
                <small>SEO 健康度</small>
                <div class="seo-parent-score"><strong>68</strong><b>/100</b></div>
                <em>基础良好</em>
                <p>衡量搜索引擎发现、索引和呈现网站内容的基础能力。</p>
              </div>

              <div class="seo-overview-copy">
                <span class="seo-overview-kicker">SEO 健康总览</span>
                <h3>网站已经具备基础搜索能力，<br><b>但关键词覆盖、索引质量和访问体验仍有提升空间。</b></h3>
                <p>当前官网能够被搜索引擎发现，但搜索曝光仍偏向品牌词。下一阶段应提升产品与行业需求覆盖，并核查索引质量和真实访问体验。</p>
                <div class="seo-overview-status">
                  <span><i /> 基础可访问</span>
                  <span><i /> 百度索引规模充足</span>
                  <span class="attention"><i /> 产品词覆盖待提升</span>
                </div>
              </div>

              <div class="seo-fact-grid" aria-label="SEO 总览数据">
                <article><span>百度索引</span><strong>{{ formatCompactMetric(baiduIndexMetric.site_count) }}</strong><b>{{ baiduIndexMetric.status === 'available' ? '搜索引擎发现页面规模' : baiduIndexMetric.reason }}</b></article>
                <article><span>PC 关键词</span><strong>{{ formatCompactMetric(seoPcKeywordCount) }}</strong><b>{{ baiduPcKeywordsMetric.status === 'available' ? '桌面搜索覆盖' : baiduPcKeywordsMetric.reason }}</b></article>
                <article><span>移动关键词</span><strong>{{ formatCompactMetric(seoMobileKeywordCount) }}</strong><b>{{ baiduMobileKeywordsMetric.status === 'available' ? '移动搜索覆盖' : baiduMobileKeywordsMetric.reason }}</b></article>
                <article class="weight"><span>百度综合权重</span><strong>{{ seoPcWeight ?? '—' }} / {{ seoMobileWeight ?? '—' }}<small>PC / 移动</small></strong><b>预估流量 {{ seoTrafficLabel }}</b></article>
                <article :class="{ pending: whoisMetric.status !== 'available' }"><span>网站年龄</span><strong class="word-value">{{ seoDomainAgeLabel }}</strong><b>{{ seoDomainAssetSummary }}</b></article>
              </div>
            </section>

            <section class="seo-core-section">
              <header class="seo-subheading"><div><span>CORE SIGNALS</span><h3>搜索可见性核心指标</h3></div><p>判断官网是否能被搜索引擎发现、理解，并覆盖真实业务需求。</p></header>
              <div class="seo-core-grid">
                <article class="index">
                  <div class="seo-metric-icon">⌕</div>
                  <span>搜索引擎索引规模</span>
                  <strong>{{ formatCompactMetric(baiduIndexMetric.site_count) }}<small>页面</small></strong>
                  <p>索引数量代表搜索引擎发现页面规模，不代表有效商业页面数量。</p>
                  <small class="seo-source-note">{{ metricSourceLabel(baiduIndexMetric, 'BD 收录量接口') }}</small>
                  <i><b style="width:88%" /></i>
                </article>
                <article class="keyword">
                  <div class="seo-metric-icon">K</div>
                  <span>关键词覆盖</span>
                  <strong>{{ formatCompactMetric(seoKeywordTotal) }}<small>PC/移动合计</small></strong>
                  <div class="seo-mini-breakdown"><span>PC 关键词 <b>{{ formatCompactMetric(seoPcKeywordCount) }}</b></span><span>移动关键词 <b>{{ formatCompactMetric(seoMobileKeywordCount) }}</b></span><span>样本词 <b>{{ (baiduPcKeywordsMetric.sample_count || 0) + (baiduMobileKeywordsMetric.sample_count || 0) }}</b></span></div>
                  <p>关键词总量来自两个终端接口；样本词用于后续分析品牌词、产品词与行业词结构。</p>
                  <small class="seo-source-note">{{ metricSourceLabel(baiduPcKeywordsMetric, 'PC 关键词接口') }} · {{ metricSourceLabel(baiduMobileKeywordsMetric, '移动关键词接口') }}</small>
                  <i><b style="width:46%" /></i>
                </article>
                <article class="weight">
                  <div class="seo-metric-icon">W</div>
                  <span>百度综合权重</span>
                  <div class="seo-dual-metric">
                    <b>PC 权重<strong>{{ seoPcWeight ?? '—' }}</strong></b>
                    <b>移动权重<strong>{{ seoMobileWeight ?? '—' }}</strong></b>
                  </div>
                  <div class="seo-weight-traffic"><span>百度预估流量</span><b>{{ seoTrafficLabel }}</b></div>
                  <p>综合观察网站在百度 PC 与移动搜索中的关键词覆盖和预估流量表现。</p>
                  <small class="seo-source-note">{{ metricSourceLabel(comprehensiveWeightMetric, '综合权重接口') }}</small>
                  <i><b style="width:30%" /></i>
                </article>
                <article class="technical website-experience">
                  <div class="seo-metric-icon">✓</div>
                  <span>网站体验健康</span>
                  <strong>{{ pageSpeedLoading ? '…' : (pageSpeed?.performance_score ?? '—') }}<small>Performance</small></strong>
                  <div class="seo-tech-tags"><span>HTTPS</span><span>页面速度</span><span>核心网页指标 CWV</span></div>
                  <div class="seo-cwv-grid" aria-label="核心网页指标 CWV">
                    <div :class="`is-${pageSpeed?.metrics?.lcp?.status || 'missing'}`"><span>LCP<small>最大内容绘制 · ≤2.5s</small></span><strong>{{ formatCwvMetric(pageSpeed?.metrics?.lcp, 'lcp') }} <b>{{ cwvStatusLabel(pageSpeed?.metrics?.lcp) }}</b></strong></div>
                    <div :class="`is-${pageSpeed?.metrics?.cls?.status || 'missing'}`"><span>CLS<small>累计布局偏移 · ≤0.1</small></span><strong>{{ formatCwvMetric(pageSpeed?.metrics?.cls, 'cls') }} <b>{{ cwvStatusLabel(pageSpeed?.metrics?.cls) }}</b></strong></div>
                    <div :class="`is-${pageSpeed?.metrics?.inp?.status || 'missing'}`"><span>INP<small>交互响应速度 · ≤200ms</small></span><strong>{{ formatCwvMetric(pageSpeed?.metrics?.inp, 'inp') }} <b>{{ cwvStatusLabel(pageSpeed?.metrics?.inp) }}</b></strong></div>
                  </div>
                  <small class="seo-source-note">{{ pageSpeedSourceLabel }}</small>
                  <i><b :style="{ width: `${pageSpeed?.performance_score || 0}%` }" /></i>
                </article>
              </div>
            </section>

            <section class="seo-analysis-grid">
              <article class="seo-insight-card index-quality">
                <header><div><span>INDEX QUALITY</span><h3>索引质量分析</h3></div><b>需要关注</b></header>
                <div class="seo-index-compare" aria-label="索引规模与实际页面对比">
                  <div><span>百度索引</span><strong>{{ formatCompactMetric(baiduIndexMetric.site_count) }}</strong><i><b style="width:100%" /></i></div>
                  <div><span>网站实际页面</span><strong>3,588</strong><i><b style="width:18%" /></i></div>
                </div>
                <dl>
                  <div><dt>分析</dt><dd>检测到索引规模明显高于实际内容规模。</dd></div>
                  <div class="risk"><dt>可能存在风险</dt><dd><span class="seo-risk-list">参数页面 · 重复 URL · 历史页面 · 低价值索引</span></dd></div>
                  <div class="advice"><dt>优化建议</dt><dd>集中搜索权重到核心产品页面和解决方案页面。</dd></div>
                </dl>
              </article>

              <article class="seo-insight-card keyword-opportunity">
                <header><div><span>KEYWORD OPPORTUNITY</span><h3>关键词机会分析</h3></div><b>增长机会</b></header>
                <div class="keyword-balance" aria-label="关键词结构分析">
                  <span>品牌词覆盖 <b>72%</b></span><i><b style="width:72%" /></i>
                  <span>产品词覆盖 <b>28%</b></span><i><b style="width:28%" /></i>
                  <span>行业词覆盖 <b>待提升</b></span><i><b style="width:2%" /></i>
                </div>
                <dl>
                  <div><dt>诊断</dt><dd>当前网站搜索流量主要依赖品牌认知。</dd></div>
                  <div class="risk"><dt>分析</dt><dd>当前搜索曝光主要依赖品牌词，产品和行业关键词覆盖不足。</dd></div>
                  <div class="advice"><dt>优化建议</dt><dd><span class="seo-opportunity-list">产品页面 · 行业解决方案 · 应用案例 · 专业知识内容</span></dd></div>
                </dl>
              </article>
            </section>

            <section class="seo-priority-section">
              <header class="seo-subheading"><div><span>PRIORITY ROADMAP</span><h3>SEO 优化优先级</h3></div><p>优先处理最能影响搜索发现、页面理解和长期搜索价值的三项工作。</p></header>
              <div class="seo-priority-grid">
                <article><span>01</span><div><small>第一优先级</small><h3>提升产品搜索覆盖</h3><p>让客户搜索产品需求时，更容易发现企业及对应产品能力。</p></div><b>增长</b></article>
                <article><span>02</span><div><small>第二优先级</small><h3>优化页面理解结构</h3><p>提升搜索引擎对页面主题和内容关系的理解。</p></div><b>理解</b></article>
                <article><span>03</span><div><small>第三优先级</small><h3>增强专业内容资产</h3><p>增加 FAQ、案例和解决方案，提高长期搜索价值。</p></div><b>内容</b></article>
              </div>
            </section>

            <details class="seo-technical-details">
              <summary><span>查看现有 SEO 技术检测明细</span><small>保留全部规则、证据和业务影响解释</small><b>展开 ↓</b></summary>
              <div class="check-grid">
                <article v-for="item in seoFindings" :key="item.code" :class="{ failed: !item.passed }">
                  <span class="check-status">{{ item.passed ? '✓' : '!' }}</span>
                  <div class="check-copy">
                    <small>{{ categoryLabel(item) }}</small>
                    <h3>{{ ruleNarrative(item).userTitle }}</h3>
                    <div class="plain-rule-explanation">
                      <p><b>检测结果</b>{{ item.passed ? '当前页面已达到这项基础要求。' : failureSummary(item) }}</p>
                      <p><b>为什么重要</b>{{ ruleNarrative(item).why }}</p>
                      <p><b>业务影响</b>{{ item.passed ? '当前未发现这项风险对客户发现和 AI 推荐造成明显影响。' : businessImpact(item) }}</p>
                      <p><b>优化方向</b>{{ item.passed ? '保持当前设置，并在网站改版后重新检查。' : ruleNarrative(item).direction }}</p>
                    </div>
                    <details class="technical-evidence">
                      <summary>查看技术规则与当前证据</summary>
                      <p><b>技术规则</b>{{ item.title }} · {{ item.criterion || item.recommendation }}</p>
                      <p><b>当前证据</b>{{ item.evidence }}</p>
                    </details>
                    <button v-if="evidenceDetails(item).length" class="evidence-toggle" type="button" @click="toggleEvidence(item)">
                      {{ expandedEvidence === item.code ? '收起明细 ↑' : `查看 ${evidenceDetails(item).length} 条明细 ↓` }}
                    </button>
                  </div>
                  <span class="impact-badge" :class="item.passed ? 'passed' : item.severity">{{ impactLevel(item) }}</span>
                  <div v-if="expandedEvidence === item.code" class="evidence-detail">
                    <header><span>抓取证据明细</span><button type="button" @click="copyEvidence(item)">复制全部</button></header>
                    <ol>
                      <li v-for="(detail, index) in evidenceRows(item)" :key="`${item.code}-${index}`" :class="{ failed: detail.passed === false }">
                        <a v-if="/^https?:\/\//i.test(detail.text)" :href="detail.text" target="_blank" rel="noopener">{{ detail.text }}</a>
                        <span v-else>{{ detail.text }}</span>
                      </li>
                    </ol>
                  </div>
                </article>
              </div>
            </details>
          </section>

          <section id="section-geo" class="diagnostic-section geo-section">
            <div class="panel-heading">
              <div>
                <span class="section-index">03 / GEO DIAGNOSIS</span><h2>GEO / AI 搜索诊断</h2>
                <p class="geo-explainer"><b>GEO（生成式搜索优化）</b>帮助 ChatGPT、DeepSeek 等 AI 搜索工具理解并推荐你的品牌。</p>
              </div>
              <a v-if="!isCompetitorAudit" href="/deal-sniper/geo/dashboard">去 GEO 执行 →</a>
            </div>
            <div class="check-grid">
              <article v-for="item in geoFindings" :key="item.code" :class="{ failed: !item.passed }">
                <span class="check-status">{{ item.passed ? '✓' : '!' }}</span>
                <div class="check-copy">
                  <small>{{ categoryLabel(item) }}</small>
                  <h3>{{ ruleNarrative(item).userTitle }}</h3>
                  <div class="plain-rule-explanation">
                    <p><b>检测结果</b>{{ item.passed ? '当前页面已达到这项基础要求。' : failureSummary(item) }}</p>
                    <p><b>为什么重要</b>{{ ruleNarrative(item).why }}</p>
                    <p><b>业务影响</b>{{ item.passed ? '当前未发现这项风险对客户发现和 AI 推荐造成明显影响。' : businessImpact(item) }}</p>
                    <p><b>优化方向</b>{{ item.passed ? '保持当前设置，并在网站改版后重新检查。' : ruleNarrative(item).direction }}</p>
                  </div>
                  <details class="technical-evidence">
                    <summary>查看技术规则与当前证据</summary>
                    <p><b>技术规则</b>{{ item.title }} · {{ item.criterion || item.recommendation }}</p>
                    <p><b>当前证据</b>{{ item.evidence }}</p>
                  </details>
                  <button
                    v-if="evidenceDetails(item).length"
                    class="evidence-toggle"
                    type="button"
                    @click="toggleEvidence(item)"
                  >
                    {{ expandedEvidence === item.code ? '收起明细 ↑' : `查看 ${evidenceDetails(item).length} 条明细 ↓` }}
                  </button>
                </div>
                <span class="impact-badge" :class="item.passed ? 'passed' : item.severity">{{ impactLevel(item) }}</span>
                <div v-if="expandedEvidence === item.code" class="evidence-detail">
                  <header><span>抓取证据明细</span><button type="button" @click="copyEvidence(item)">复制全部</button></header>
                  <ol>
                    <li v-for="(detail, index) in evidenceRows(item)" :key="`${item.code}-${index}`" :class="{ failed: detail.passed === false }">
                      <a v-if="/^https?:\/\//i.test(detail.text)" :href="detail.text" target="_blank" rel="noopener">{{ detail.text }}</a>
                      <span v-else>{{ detail.text }}</span>
                    </li>
                  </ol>
                </div>
              </article>
            </div>
          </section>
          </section>

          <section v-if="!isCompetitorAudit" class="flow-screen brand-screen">
          <div id="flow-brand" class="flow-stage-heading brand-stage-heading">
            <span>03</span><div><b>BRAND INTELLIGENCE</b><h2>确认品牌与竞品上下文，再验证 AI 搜索提及</h2></div>
          </div>

          <section class="brand-intelligence-panel">
            <div class="brand-console-copy">
              <span class="console-kicker">AI BRAND EXTRACTION / LIVE CONTEXT</span>
              <h2>{{ brandProfile.name || '当前诊断品牌' }}</h2>
              <p>{{ brandProfile.business_desc || '品牌档案为诊断规则、竞品参照和 AI 提及抽样提供统一上下文。' }}</p>
              <div class="brand-console-meta">
                <span><b>行业</b>{{ brandProfile.industry || '待确认' }}</span>
                <span><b>官网</b>{{ brandProfile.website || audit.final_url }}</span>
                <span><b>竞品</b>{{ confirmedCompetitors.length }} 个已确认</span>
              </div>
            </div>
            <div class="brand-console-signal">
              <span class="signal-orbit"><i /></span>
              <strong>{{ brandReady ? '品牌档案已接入' : '品牌档案待完善' }}</strong>
              <small>诊断资料独立存储，不写回 SEM 租户资料</small>
              <div v-if="confirmedCompetitors.length" class="competitor-chips">
                <span v-for="item in confirmedCompetitors.slice(0, 4)" :key="item.name">{{ item.name }}</span>
              </div>
              <button type="button" @click="openAsset('brand')">查看品牌与竞品档案 →</button>
            </div>
          </section>

          <section class="ai-sample-panel">
            <div class="sample-heading">
              <div>
                <span class="section-index">03B / LIVE MODEL SAMPLE</span>
                <h2>AI 是否认识你的品牌？</h2>
                <p>模拟真实用户问题，查看 AI 是否会在回答中推荐或提到你的品牌。</p>
              </div>
              <div class="sample-chips">
                <span class="sample-chip">待测品牌：{{ aiSample?.brand_name || '当前客户品牌' }}</span>
                <span class="sample-chip">真实 API · 最多 3 个问题</span>
              </div>
            </div>

            <div class="model-access-bar">
              <div class="model-access-copy">
                <span>MULTI-MODEL VISIBILITY</span>
                <strong>免费版检测 DeepSeek，会员版将解锁更多 AI 检索入口</strong>
                <p>不同 AI 的训练数据和推荐结果并不相同，多模型交叉检索更接近客户真实看到的品牌表现。</p>
              </div>
              <div class="model-access-grid">
                <article class="active">
                  <i>DS</i>
                  <div><strong>DeepSeek</strong><small>当前真实检索</small></div>
                  <b>免费可用</b>
                </article>
                <article class="locked">
                  <i>豆</i>
                  <div><strong>豆包</strong><small>字节 AI 搜索场景</small></div>
                  <b>会员解锁</b>
                  <span aria-hidden="true" />
                </article>
                <article class="locked">
                  <i>千</i>
                  <div><strong>通义千问</strong><small>阿里 AI 搜索场景</small></div>
                  <b>会员解锁</b>
                  <span aria-hidden="true" />
                </article>
              </div>
            </div>

            <section class="member-model-preview" aria-label="会员版多模型检索能力预览">
              <header>
                <div><span>MEMBER RESULT PREVIEW</span><h3>会员版多模型检索结果</h3><p>开通并完成真实检测后，可查看各模型的品牌提及、回答证据与横向差异。</p></div>
                <b>能力预览 · 非真实检测结果</b>
              </header>
              <div class="member-preview-grid">
                <article>
                  <header><i>豆</i><div><strong>豆包品牌检索</strong><small>字节 AI 场景</small></div><em>会员</em></header>
                  <div class="locked-metric"><span>AI 品牌提及率</span><strong aria-hidden="true">68%</strong></div>
                  <div class="locked-answer" aria-hidden="true"><span /><span /><span /></div>
                  <footer><span class="mini-lock" />购买会员后查看回答与命中证据</footer>
                </article>
                <article>
                  <header><i>千</i><div><strong>通义千问品牌检索</strong><small>阿里 AI 场景</small></div><em>会员</em></header>
                  <div class="locked-metric"><span>AI 品牌提及率</span><strong aria-hidden="true">42%</strong></div>
                  <div class="locked-answer" aria-hidden="true"><span /><span /><span /></div>
                  <footer><span class="mini-lock" />购买会员后查看回答与命中证据</footer>
                </article>
                <article class="comparison-preview">
                  <header><i>↗</i><div><strong>多模型对比结论</strong><small>DeepSeek · 豆包 · 千问</small></div><em>会员</em></header>
                  <div class="comparison-rows" aria-hidden="true"><span><b>01</b><i /></span><span><b>02</b><i /></span><span><b>03</b><i /></span></div>
                  <footer><span class="mini-lock" />购买会员后查看模型差异与优化机会</footer>
                </article>
              </div>
            </section>

            <div class="sample-composer">
              <div class="sample-question-list">
                <label v-for="(_, index) in sampleQuestions" :key="index">
                  <span>Q{{ index + 1 }}</span>
                  <input
                    v-model="sampleQuestions[index]"
                    type="text"
                    maxlength="300"
                    :placeholder="index === 0 ? '留空则根据品牌行业自动生成三个中立问题' : '可选：输入客户真实会问的问题（不能包含待测品牌名）'"
                    :disabled="samplingLoading"
                  >
                </label>
              </div>
              <button
                type="button"
                :disabled="samplingLoading || !audit.ai_enabled"
                @click="createDeepSeekSample"
              >
                {{ samplingLoading ? '正在进行真实抽样…' : aiSample ? '重新抽样 →' : '开始 DeepSeek 实测 →' }}
              </button>
              <small v-if="!audit.ai_enabled">DeepSeek 服务当前未启用</small>
            </div>

            <template v-if="aiSample">
              <div class="sample-metrics">
                <article>
                  <span>AI 品牌提及率</span>
                  <strong>{{ Math.round(aiSample.mention_rate * 100) }}<small>%</small></strong>
                </article>
                <article>
                  <span>品牌被提及</span>
                  <strong>{{ aiSample.mention_count }}<small>/{{ aiSample.question_count }} 次</small></strong>
                </article>
                <article>
                  <span>抽样平台</span>
                  <strong class="model-name">{{ aiSample.platform }}</strong>
                  <small>{{ aiSample.model }} · {{ formatDate(aiSample.executed_at) }}</small>
                </article>
              </div>

              <div class="sample-results">
                <article v-for="(item, index) in aiSample.results" :key="`${item.question}-${index}`" :class="{ mentioned: item.mentioned }">
                  <span class="sample-index">{{ String(index + 1).padStart(2, '0') }}</span>
                  <div class="sample-result-copy">
                    <header>
                      <span :class="item.mentioned ? 'hit' : 'miss'">{{ item.mentioned ? 'AI 回答中发现你的品牌' : 'AI 回答中未发现你的品牌' }}</span>
                      <small v-if="item.matched_terms?.length">命中：{{ item.matched_terms.join('、') }}</small>
                    </header>
                    <h3><small>用户问题</small>{{ item.question }}</h3>
                    <p><b>AI 回答</b>{{ item.response }}</p>
                    <details>
                      <summary>查看完整原始回答与证据</summary>
                      <pre>{{ item.response }}</pre>
                      <div v-if="item.source_urls?.length" class="sample-sources">
                        <b>回答中的链接</b>
                        <a v-for="source in item.source_urls" :key="source" :href="source" target="_blank" rel="noopener">{{ source }}</a>
                      </div>
                      <button type="button" @click="copySampleResponse(item)">复制原始回答</button>
                    </details>
                  </div>
                </article>
              </div>
              <footer class="sample-method">
                <p><b>计算口径</b>{{ aiSample.methodology }}</p>
                <p><b>抽样局限</b>{{ aiSample.limitations }}</p>
              </footer>
            </template>
            <div v-else class="sample-empty">
              <span>DS</span>
              <p><strong>你的官网能被读取，不代表 AI 会主动推荐品牌。</strong>运行抽样后，这里会展示真实用户问题、AI 回答和品牌提及率。</p>
            </div>
          </section>
          </section>

          <section class="flow-screen action-screen">
          <div id="flow-action" class="flow-stage-heading action-stage-heading">
            <span>{{ isCompetitorAudit ? '03' : '04' }}</span><div><b>ISSUE MATRIX + ACTION ROUTE</b><h2>{{ isCompetitorAudit ? '查看竞品公开页面的问题与诊断依据' : '按影响排序问题，形成可派发的行动路线' }}</h2></div>
          </div>

          <section id="section-issues" class="issues-panel">
            <div class="panel-heading issue-heading">
              <div>
                <span class="section-index">04 / ISSUE MATRIX</span>
                <h2>问题清单 <em>{{ problems.length }}</em></h2>
              </div>
              <div class="issue-filters">
                <button :class="{ active: issueFilter === 'all' }" @click="issueFilter = 'all'">全部</button>
                <button :class="{ active: issueFilter === 'critical' }" @click="issueFilter = 'critical'">高优先</button>
                <button :class="{ active: issueFilter === 'seo' }" @click="issueFilter = 'seo'">SEO</button>
                <button :class="{ active: issueFilter === 'geo' }" @click="issueFilter = 'geo'">GEO</button>
                <button :class="{ active: issueFilter === 'content' }" @click="issueFilter = 'content'">内容</button>
              </div>
            </div>
            <div class="issue-card-list">
              <article v-for="item in filteredProblems" :key="item.code" :class="item.severity">
                <header>
                  <div><span class="domain-tag" :class="issueDomain(item)">{{ issueDomainLabel(item) }}</span><span class="severity-tag" :class="item.severity">{{ impactLevel(item) }}</span></div>
                  <small>评分影响 -{{ item.deduction }}</small>
                </header>
                <h3>{{ ruleNarrative(item).userTitle }}</h3>
                <dl>
                  <div><dt>业务影响</dt><dd>{{ businessImpact(item) }}</dd></div>
                  <div><dt>为什么重要</dt><dd>{{ ruleNarrative(item).why }}</dd></div>
                  <div><dt>优化方向</dt><dd>{{ ruleNarrative(item).direction }}</dd></div>
                </dl>
                <details>
                  <summary>查看技术问题与检测证据</summary>
                  <p><b>{{ item.title }}</b>{{ item.evidence }}</p>
                </details>
              </article>
              <p v-if="!filteredProblems.length" class="empty-row">当前筛选下没有待处理问题</p>
            </div>
          </section>

          <section class="action-panel">
            <div class="panel-heading">
              <div><span class="section-index">PRIORITY DIRECTIONS</span><h2>优先优化方向</h2><p>免费诊断先告诉你最值得投入的三件事，避免被技术清单淹没。</p></div>
              <span class="boundary-chip">按业务影响排序</span>
            </div>
            <div v-if="priorityDirections.length" class="priority-direction-list">
              <article v-for="(item, index) in priorityDirections" :key="item.title" :class="item.impact">
                <span>{{ String(index + 1).padStart(2, '0') }}</span>
                <h3>{{ item.title }}</h3>
                <p>{{ item.description }}</p>
                <small>关联 {{ item.count }} 项当前问题</small>
                <button class="bridge-btn" :disabled="bridgeLoading" @click="bridgeToContent(item.codes[0])">
                  创建 GEO 优化文章 →
                </button>
              </article>
            </div>
            <div v-else class="priority-clean-state">
              <strong>当前基础规则表现良好</strong><p>下一步可继续验证行业内容竞争力和真实 AI 品牌提及。</p>
            </div>
            <footer v-if="!isCompetitorAudit" class="full-plan-cta">
              <div><strong>需要负责人、执行步骤和验收标准？</strong><p>进入优化工作区，获取基于本次诊断的完整优化方案。</p></div>
              <a href="/deal-sniper/geo/dashboard">获取完整优化方案 →</a>
            </footer>
          </section>
          </section>
        </template>
      </div>

      <DiagnosisAssetsView
        v-else
        :id="`asset-${activeAsset}`"
        :key="`${activeAsset}-${url}`"
        :tenant-id="tenantId"
        :asset="currentAsset"
        :initial-website="url"
        @brand-saved="handleBrandSaved"
      />
    </section>
  </main>
</template>

<style scoped>
.diagnosis-center {
  --ink: #18272b;
  --muted: #718086;
  --line: #dfe7e6;
  --canvas: #f4f7f6;
  --paper: #ffffff;
  --teal: #0b9388;
  --teal-dark: #076a64;
  --teal-soft: #e8f7f4;
  --amber: #d97706;
  --red: #d14343;
  min-height: 100vh;
  display: grid;
  grid-template-columns: 236px minmax(0, 1fr);
  color: var(--ink);
  background: var(--canvas);
  font-family: "Avenir Next", "Noto Sans SC", "PingFang SC", sans-serif;
}

button, input { font: inherit; }
button { color: inherit; }

.diagnosis-sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  display: flex;
  flex-direction: column;
  padding: 22px 14px 16px;
  border-right: 1px solid var(--line);
  background:
    linear-gradient(180deg, rgba(11,147,136,.035), transparent 160px),
    #fbfdfc;
  z-index: 10;
}
.diagnosis-brand { display:flex; align-items:center; gap:11px; padding:4px 8px 26px; }
.brand-mark { width:38px; height:38px; display:block; object-fit:contain; filter:drop-shadow(0 8px 12px rgba(105,49,190,.18)); }
.diagnosis-brand strong,.diagnosis-brand small { display:block; }
.diagnosis-brand strong { font-size:17px; letter-spacing:.02em; }
.diagnosis-brand small { margin-top:3px; color:var(--muted); font-size:10px; letter-spacing:.12em; }
.nav-label { padding:12px 12px 8px; color:#9aa6a9; font-size:10px; font-weight:800; letter-spacing:.16em; text-transform:uppercase; }
.asset-label { margin-top:10px; padding-top:19px; border-top:1px solid #edf1f0; }
.sidebar-item {
  width:100%; min-height:41px; display:flex; align-items:center; gap:10px; padding:0 12px; border:0; border-radius:9px;
  color:#53646a; background:transparent; font-size:13px; font-weight:650; text-align:left; text-decoration:none; cursor:pointer;
  transition:background .2s,color .2s,transform .2s;
}
.sidebar-item:hover { color:var(--teal-dark); background:#f0f8f6; transform:translateX(2px); }
.sidebar-item.active { color:var(--teal-dark); background:var(--teal-soft); box-shadow:inset 3px 0 0 var(--teal); }
.sidebar-icon { width:20px; color:#7c8c90; text-align:center; font-weight:900; }
.sidebar-item.active .sidebar-icon { color:var(--teal); }
.sidebar-spacer { flex:1; min-height:20px; }
.module-link { min-height:36px; color:#69797d; }
.module-link span { width:20px; text-align:center; color:#96a3a6; }
.sidebar-bottom { display:grid; gap:8px; margin-top:10px; padding:14px 12px 0; border-top:1px solid var(--line); }
.sidebar-bottom a { color:#77868a; font-size:12px; text-decoration:none; }
.sidebar-bottom a:hover { color:var(--teal); }

.diagnosis-main { min-width:0; }
.diagnosis-topbar {
  min-height:112px; display:flex; align-items:center; justify-content:space-between; gap:24px; padding:20px 32px 18px;
  border-bottom:1px solid var(--line); background:rgba(255,255,255,.9); backdrop-filter:blur(14px);
}
.topbar-kicker,.section-index { color:var(--teal); font-size:9px; font-weight:850; letter-spacing:.18em; }
.diagnosis-topbar h1 { margin:5px 0 2px; font-family:"Songti SC","Noto Serif SC",serif; font-size:24px; font-weight:700; letter-spacing:-.03em; }
.diagnosis-topbar p { margin:0; color:var(--muted); font-size:12px; }
.topbar-actions { display:flex; align-items:center; gap:9px; }
.topbar-actions button { height:36px; padding:0 13px; border:1px solid var(--line); border-radius:8px; background:#fff; color:#5d6d72; font-size:11px; cursor:pointer; }
.topbar-actions button:hover:not(:disabled) { color:var(--teal); border-color:#9ed4cf; }
.topbar-actions button:disabled { opacity:.45; cursor:not-allowed; }
.avatar { width:37px; height:37px; display:grid; place-items:center; margin-left:4px; border-radius:50%; color:#fff; background:var(--teal); font-size:12px; font-weight:800; }
.history-modal-backdrop { position:fixed; z-index:1200; inset:0; display:grid; place-items:center; padding:24px; background:rgba(25,23,34,.44); backdrop-filter:blur(8px); animation:history-fade-in .18s ease-out; }
.history-modal { width:min(780px,calc(100vw - 32px)); max-height:min(760px,calc(100vh - 48px)); display:grid; grid-template-rows:auto minmax(0,1fr) auto; overflow:hidden; border:1px solid rgba(139,99,205,.22); border-radius:22px; background:linear-gradient(145deg,#fff 0%,#fbf9fe 68%,#f2fbf8 100%); box-shadow:0 28px 80px rgba(35,27,52,.24); animation:history-rise-in .22s ease-out; }
.history-modal>header { display:flex; align-items:flex-start; justify-content:space-between; gap:24px; padding:27px 29px 20px; border-bottom:1px solid #e9e4ef; }
.history-modal>header span { color:#7a42ca; font-size:9px; font-weight:900; letter-spacing:.18em; }
.history-modal>header h2 { margin:6px 0 4px; font-family:"Songti SC","Noto Serif SC",serif; font-size:25px; }
.history-modal>header p { margin:0; color:#85808d; font-size:11px; }
.history-modal>header>button { width:34px; height:34px; flex:none; border:1px solid #e4ddec; border-radius:50%; color:#736d7b; background:#fff; font-size:22px; line-height:1; cursor:pointer; }
.history-modal>header>button:hover { color:#7137c2; border-color:#cdb9e8; transform:rotate(4deg); }
.history-list { display:grid; gap:9px; overflow:auto; padding:18px 20px; }
.history-list>button { min-width:0; display:grid; grid-template-columns:68px minmax(0,1fr) auto; align-items:center; gap:16px; padding:13px 15px; border:1px solid #e9e5ee; border-radius:14px; color:inherit; background:rgba(255,255,255,.84); text-align:left; cursor:pointer; transition:border-color .18s,box-shadow .18s,transform .18s; }
.history-list>button:hover,.history-list>button.current { border-color:#cdb7e9; box-shadow:0 8px 22px rgba(90,58,135,.08); transform:translateY(-1px); }
.history-list>button.current { background:linear-gradient(105deg,#fbf8ff,#f4fbf9); }
.history-list>button:disabled { cursor:wait; opacity:.72; }
.history-score { width:58px; height:58px; display:flex; align-items:baseline; justify-content:center; border-radius:18px; background:#f4f1f7; }
.history-score b { font:700 24px Georgia,serif; }.history-score small { font-size:8px; }.history-score.good { color:#0c9b79; background:#e9f8f3; }.history-score.fair { color:#b5790d; background:#fff5df; }.history-score.risk { color:#d9514b; background:#fff0ee; }
.history-copy { min-width:0; display:grid; gap:3px; }.history-copy strong,.history-copy em { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.history-copy strong { color:#30303a; font-size:13px; }.history-copy em { color:#6d42ae; font-size:10px; font-style:normal; }.history-copy small { color:#99949f; font-size:9px; }
.history-action { align-self:center; padding:7px 10px; border-radius:14px; color:#7550aa; background:#f3eef9; font-size:9px; font-weight:800; white-space:nowrap; }
.history-modal>footer { padding:12px 26px 15px; border-top:1px solid #e9e4ef; color:#918b97; font-size:9px; }.history-modal>footer i { width:6px; height:6px; display:inline-block; margin-right:7px; border-radius:50%; background:#10aa86; }
.history-loading,.history-empty { min-height:260px; display:grid; place-content:center; justify-items:center; gap:10px; padding:35px; text-align:center; }.history-loading i { width:34px; height:34px; border:3px solid #e9e0f4; border-top-color:#793bd7; border-radius:50%; animation:history-spin .75s linear infinite; }.history-loading span,.history-empty p { color:#918c98; font-size:11px; }.history-empty b { font:700 21px "Songti SC","Noto Serif SC",serif; }.history-empty p { margin:0; }.history-empty button { height:36px; padding:0 18px; border:0; border-radius:18px; color:#fff; background:linear-gradient(110deg,#793bd7,#10aa86); font-size:10px; font-weight:800; cursor:pointer; }
.print-report-header { display:none; }
@keyframes history-fade-in { from { opacity:0; } }
@keyframes history-rise-in { from { opacity:0; transform:translateY(12px) scale(.985); } }
@keyframes history-spin { to { transform:rotate(360deg); } }
.diagnosis-content { max-width:1460px; margin:0 auto; padding:28px 32px 80px; }
#section-overview,#section-seo,#section-geo,#section-issues { scroll-margin-top:18px; }
.report-overview-anchor { height:0; scroll-margin-top:18px; }
.diagnosis-error-banner { margin:0 0 12px; padding:11px 14px; border:1px solid #f0c7c3; border-radius:10px; color:#a4423d; background:#fff3f1; font-size:10px; }
.quick-audit-bar { position:relative; display:grid; gap:12px; padding:17px 18px 15px; overflow:hidden; border:1px solid #ddd8e7; border-radius:16px; background:linear-gradient(112deg,rgba(255,255,255,.98),rgba(249,247,253,.96) 70%,rgba(239,250,246,.9)); box-shadow:0 10px 28px rgba(48,37,67,.055); transition:border-color .2s,box-shadow .2s; }
.quick-audit-bar:before { content:""; position:absolute; right:-58px; top:-93px; width:180px; height:180px; border:1px solid rgba(16,170,134,.13); border-radius:50%; box-shadow:0 0 0 24px rgba(121,59,215,.025); pointer-events:none; }.quick-audit-bar.competitor { border-color:#d7c9ec; box-shadow:inset 3px 0 0 #793bd7,0 10px 28px rgba(48,37,67,.055); }
.quick-audit-bar>header,.quick-audit-bar>footer { position:relative; z-index:1; display:flex; align-items:center; justify-content:space-between; gap:16px; }.quick-audit-bar>header>div:first-child { display:grid; gap:2px; }.quick-audit-bar>header span { color:#7d62aa; font-size:8px; font-weight:850; letter-spacing:.13em; }.quick-audit-bar>header strong { color:#292a32; font-size:14px; }
.quick-mode-switch { display:flex; padding:3px; border:1px solid #e4e0ea; border-radius:20px; background:#f5f3f8; }.quick-mode-switch button { height:28px; padding:0 13px; border:0; border-radius:16px; color:#777580; background:transparent; font-size:9px; font-weight:750; cursor:pointer; }.quick-mode-switch button.active { color:#fff; background:linear-gradient(105deg,#793bd7,#9d55df); box-shadow:0 5px 12px rgba(121,59,215,.2); }
.quick-audit-form { position:relative; z-index:1; min-height:52px; display:grid; grid-template-columns:30px minmax(0,1fr) auto; align-items:center; padding:4px 5px 4px 10px; border:1px solid #dcd6e6; border-radius:12px; background:#fff; box-shadow:0 7px 19px rgba(57,43,78,.045); }.quick-audit-form:focus-within { border-color:#9f7bd1; box-shadow:0 0 0 4px rgba(121,59,215,.07),0 7px 19px rgba(57,43,78,.045); }.quick-audit-form>span { color:#8a6cb8; font-size:17px; }.quick-audit-form input { width:100%; min-width:0; height:42px; box-sizing:border-box; border:0; outline:0; color:#30333c; background:transparent; font-size:12px; }.quick-audit-form input::placeholder { color:#aaa8b1; }.quick-audit-form>button { height:42px; padding:0 18px; border:0; border-radius:9px; color:#fff; background:linear-gradient(105deg,#793bd7,#6f5ad5 48%,#10aa86); font-size:10px; font-weight:850; cursor:pointer; box-shadow:0 7px 16px rgba(90,65,178,.18); }.quick-audit-form>button:disabled { opacity:.45; cursor:not-allowed; }
.quick-audit-bar>footer { min-height:24px; }.quick-scope-switch { display:flex; align-items:center; gap:6px; }.quick-scope-switch label { display:inline-flex; align-items:center; gap:4px; padding:4px 7px; border-radius:11px; color:#85838c; font-size:8px; cursor:pointer; }.quick-scope-switch label.active { color:#6f48ad; background:#f1ecf8; font-weight:800; }.quick-scope-switch input { width:11px; height:11px; margin:0; accent-color:#793bd7; }.quick-scope-switch small { color:#0b9171; font-size:7px; }.quick-audit-bar>footer p { display:flex; align-items:center; gap:6px; margin:0 0 0 auto; color:#85838c; font-size:8px; }.quick-audit-bar>footer p i { width:6px; height:6px; flex:none; border-radius:50%; background:#10aa86; box-shadow:0 0 0 3px rgba(16,170,134,.1); }.return-own-report { flex:none; padding:5px 9px; border:1px solid #d7c9e9; border-radius:12px; color:#7048aa; background:#fff; font-size:8px; font-weight:800; cursor:pointer; }
.quick-profile-context { position:relative; z-index:1; display:grid; grid-template-columns:minmax(220px,1.1fr) minmax(340px,1.5fr) auto; align-items:center; gap:18px; padding:13px 14px; border:1px solid #e2ddeb; border-radius:12px; background:linear-gradient(100deg,rgba(247,243,252,.94),rgba(255,255,255,.98) 52%,rgba(237,249,246,.88)); }.quick-profile-context.empty { grid-template-columns:minmax(260px,1fr) auto; }.quick-profile-identity { min-width:0; display:grid; grid-template-columns:auto minmax(0,1fr); align-items:center; gap:2px 9px; }.quick-profile-identity>span { grid-row:1/3; align-self:stretch; display:flex; align-items:center; padding-right:10px; border-right:2px solid #8e55d5; color:#7954aa; font-size:8px; font-weight:850; letter-spacing:.08em; }.quick-profile-identity strong,.quick-profile-identity small { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.quick-profile-identity strong { color:#30313a; font-size:11px; }.quick-profile-identity small { color:#8b8992; font-size:8px; }
.quick-profile-metrics { display:grid; grid-template-columns:repeat(4,minmax(68px,1fr)); gap:1px; overflow:hidden; border:1px solid #ebe7ee; border-radius:9px; background:#ebe7ee; }.quick-profile-metrics span { min-height:42px; display:flex; align-items:center; justify-content:center; gap:5px; padding:0 8px; color:#85838c; background:rgba(255,255,255,.94); font-size:8px; white-space:nowrap; }.quick-profile-metrics b { color:#6d3fad; font:650 16px Georgia,serif; }.quick-profile-actions { justify-self:end; }.quick-profile-actions button { min-width:116px; height:34px; padding:0 12px; border:1px solid #cfc1e4; border-radius:17px; color:#7043ad; background:#fff; font-size:8px; font-weight:850; cursor:pointer; transition:.2s; }.quick-profile-actions button:hover { border-color:#9667cf; box-shadow:0 5px 13px rgba(121,59,215,.1); transform:translateY(-1px); }.quick-profile-actions button:disabled { opacity:.45; cursor:not-allowed; transform:none; }
.quick-profile-detail { position:relative; z-index:1; display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:1px; overflow:hidden; border:1px solid #ded6e9; border-radius:12px; background:#e4deeb; animation:quick-profile-reveal .24s ease-out; }.quick-profile-detail>section { min-width:0; min-height:76px; display:grid; align-content:start; gap:5px; padding:13px 15px; background:rgba(255,255,255,.97); }.quick-profile-detail>section.wide { grid-column:1/-1; min-height:auto; }.quick-profile-detail span { color:#7951ae; font-size:8px; font-weight:850; letter-spacing:.05em; }.quick-profile-detail strong { color:#30323a; font-size:11px; line-height:1.45; }.quick-profile-detail p { margin:0; color:#555964; font-size:10px; line-height:1.6; }.quick-profile-detail small { color:#aaa5b0; font-size:7px; }.quick-profile-tags { display:flex; flex-wrap:wrap; gap:5px; }.quick-profile-tags i { padding:4px 7px; border:1px solid #d8eee8; border-radius:10px; color:#157a68; background:#f1faf7; font-size:8px; font-style:normal; }.quick-profile-tags em { color:#a09da6; font-size:9px; font-style:normal; }.quick-profile-detail>footer { grid-column:1/-1; display:flex; align-items:center; gap:7px; padding:8px 14px; color:#817d89; background:#faf8fc; font-size:8px; }.quick-profile-detail>footer i { width:6px; height:6px; border-radius:50%; background:#10aa86; box-shadow:0 0 0 3px rgba(16,170,134,.1); }
@keyframes quick-profile-reveal { from { opacity:0; transform:translateY(-5px); } to { opacity:1; transform:translateY(0); } }

.scan-panel {
  position:relative; overflow:hidden; min-height:252px; display:grid; grid-template-columns:.9fr 1.1fr; gap:54px; align-items:center;
  padding:36px 42px; border-radius:16px; color:#e9f7f5;
  background:
    radial-gradient(circle at 15% 20%,rgba(82,218,197,.19),transparent 32%),
    linear-gradient(118deg,#14383b 0%,#0d2f33 55%,#0a292d 100%);
  box-shadow:0 18px 44px rgba(31,57,59,.11);
}
.scan-panel:after { content:""; position:absolute; width:300px; height:300px; right:-110px; top:-170px; border:1px solid rgba(101,221,204,.2); border-radius:50%; box-shadow:0 0 0 36px rgba(101,221,204,.03),0 0 0 74px rgba(101,221,204,.025); }
.scan-copy,.scan-form { position:relative; z-index:1; }
.scan-copy h2 { margin:10px 0 13px; font-family:"Songti SC","Noto Serif SC",serif; font-size:29px; line-height:1.25; font-weight:650; letter-spacing:-.035em; }
.scan-copy h2 em { color:#70ddc9; font-style:normal; }
.scan-copy>p { max-width:500px; margin:0; color:#aac0c0; font-size:12px; line-height:1.75; }
.scan-notes { display:flex; flex-wrap:wrap; gap:13px; margin-top:22px; color:#a8c6c4; font-size:10px; }
.scan-form { padding:22px; border:1px solid rgba(199,237,231,.14); border-radius:13px; background:rgba(255,255,255,.06); box-shadow:inset 0 1px 0 rgba(255,255,255,.04); }
.scan-form>label { display:block; margin-bottom:9px; color:#d7e6e4; font-size:11px; font-weight:750; }
.url-input-wrap { height:58px; display:grid; grid-template-columns:minmax(0,1fr) auto; align-items:center; padding:5px 5px 5px 12px; border:1px solid transparent; border-radius:9px; background:#fff; box-shadow:0 12px 28px rgba(0,0,0,.16); }
.url-input-wrap.invalid { border-color:#ff897c; }
.url-input-wrap input { min-width:0; height:100%; padding:0 9px 0 2px; border:0; outline:0; color:#203236; background:transparent; font-size:13px; }
.url-input-wrap button { height:46px; padding:0 18px; border:0; border-radius:7px; color:#fff; background:var(--teal); font-size:12px; font-weight:800; cursor:pointer; transition:background .2s,transform .2s; }
.url-input-wrap button:hover:not(:disabled) { background:#087f76; transform:translateY(-1px); }
.url-input-wrap button:disabled { opacity:.6; cursor:wait; }
.url-input-wrap button b { margin-left:6px; }
.scope-row { display:flex; gap:16px; margin-top:13px; font-size:10px; }
.scope { padding:0; border:0; color:#789491; background:transparent; font-size:10px; cursor:pointer; }
.scope.active { color:#71ddca; }
.scope:disabled { cursor:wait; }
.scope small { margin-left:4px; padding:2px 5px; border-radius:4px; background:rgba(255,255,255,.08); font-size:8px; }
.form-error,.form-hint { margin:8px 0 0; font-size:10px; }
.form-error { color:#ffad9f; }
.form-hint { color:#799796; }

.loading-report { min-height:236px; display:grid; grid-template-columns:110px 1fr auto; gap:28px; align-items:center; margin-top:18px; padding:30px 44px; border:1px solid var(--line); border-radius:14px; background:#fff; }
.loading-orbit { position:relative; width:86px; height:86px; border:1px solid #c8dcda; border-radius:50%; background:repeating-radial-gradient(circle,transparent 0 14px,rgba(11,147,136,.08) 15px 16px); }
.loading-orbit:before,.loading-orbit:after { content:""; position:absolute; background:#d1dfdd; }.loading-orbit:before{left:50%;top:0;width:1px;height:100%}.loading-orbit:after{top:50%;left:0;width:100%;height:1px}
.loading-orbit span { position:absolute; left:50%; top:50%; width:38px; height:1px; background:linear-gradient(90deg,var(--teal),transparent); transform-origin:0 0; animation:sweep 2s linear infinite; }
.loading-orbit i { position:absolute; left:58px; top:22px; width:6px; height:6px; border-radius:50%; background:var(--teal); box-shadow:0 0 0 5px rgba(11,147,136,.12); }
@keyframes sweep { to { transform:rotate(360deg); } }
.loading-report h2 { margin:7px 0; font-family:"Songti SC",serif; font-size:24px; }
.loading-report p { margin:0; color:var(--muted); font-size:11px; }
.stage-track { display:flex; gap:7px; }
.stage-track span { width:27px; height:27px; display:grid; place-items:center; border:1px solid var(--line); border-radius:50%; color:#9ba7aa; font-size:9px; }
.stage-track span.done { color:#fff; border-color:var(--teal); background:var(--teal); }

.preflight-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:14px; margin-top:18px; }
.preflight-grid article { position:relative; min-height:162px; padding:24px; overflow:hidden; border:1px solid var(--line); border-radius:12px; background:#fff; }
.preflight-grid article:after { content:""; position:absolute; right:-27px; bottom:-38px; width:90px; height:90px; border:18px solid var(--teal-soft); border-radius:50%; }
.preflight-grid span { color:var(--teal); font:800 9px "SFMono-Regular",monospace; letter-spacing:.18em; }
.preflight-grid h3 { margin:13px 0 8px; font-size:16px; }
.preflight-grid p { max-width:280px; margin:0; color:var(--muted); font-size:11px; line-height:1.65; }
.preflight-grid b { display:block; margin-top:16px; color:#8b999d; font-size:10px; }

.report-anchor,.diagnostic-section,.issues-panel { scroll-margin-top:18px; }
.report-meta { display:flex; justify-content:space-between; gap:20px; margin-top:20px; padding:13px 17px; border:1px solid var(--line); border-radius:10px; color:#7b898d; background:rgba(255,255,255,.72); font-size:10px; }
.report-meta>div { display:flex; align-items:center; gap:10px; min-width:0; }
.report-meta strong { max-width:350px; overflow:hidden; color:#34464a; text-overflow:ellipsis; white-space:nowrap; }
.report-meta a { max-width:360px; overflow:hidden; color:var(--teal); text-overflow:ellipsis; text-decoration:none; white-space:nowrap; }
.live-dot { width:7px; height:7px; flex:none; border-radius:50%; background:#1dac79; box-shadow:0 0 0 4px rgba(29,172,121,.12); }

.site-coverage-panel { margin-top:12px; overflow:hidden; border:1px solid #cfe3df; border-radius:12px; background:#fff; }
.site-coverage-heading { min-height:70px; display:flex; align-items:center; justify-content:space-between; gap:25px; padding:15px 20px; border-bottom:1px solid #dfe9e7; background:linear-gradient(110deg,#f0f9f6,#fff); }
.site-coverage-heading h2 { margin:4px 0 0; font-family:"Songti SC","Noto Serif SC",serif; font-size:18px; }
.site-coverage-heading p { max-width:540px; margin:0; color:#66807e; font-size:9px; text-align:right; }
.site-coverage-meta { display:flex; gap:22px; padding:10px 20px; border-bottom:1px solid #edf2f1; color:#758885; background:#fbfdfc; font-size:9px; }
.site-page-grid { display:grid; grid-template-columns:1fr 1fr; gap:1px; background:#e6eceb; }
.site-page-grid article { min-width:0; display:grid; grid-template-columns:28px minmax(0,1fr) auto; gap:11px; align-items:center; padding:15px 18px; background:#fff; }
.site-page-grid article>span { color:#c5d1cf; font:500 19px "Iowan Old Style",Georgia,serif; }
.site-page-grid article>div { min-width:0; }
.site-page-grid small { color:#78908c; font-size:8px; font-weight:750; }
.site-page-grid h3 { margin:4px 0 3px; overflow:hidden; font-size:10px; text-overflow:ellipsis; white-space:nowrap; }
.site-page-grid a { display:block; overflow:hidden; color:#8b9997; font-size:8px; text-overflow:ellipsis; text-decoration:none; white-space:nowrap; }
.site-page-grid strong { min-width:35px; color:#1c806f; font:600 22px "Iowan Old Style",Georgia,serif; text-align:right; }
.site-page-grid article.fair strong { color:#c17b16; }
.site-page-grid article.risk strong { color:#c94c4c; }

.summary-grid { display:grid; grid-template-columns:1.5fr repeat(3,1fr); gap:12px; margin-top:12px; }
.summary-grid article { min-height:147px; padding:22px; border:1px solid var(--line); border-radius:12px; background:#fff; box-shadow:0 7px 20px rgba(46,68,69,.035); }
.overall-card { display:flex; align-items:center; gap:20px; }
.score-ring { --score:0deg; width:94px; height:94px; display:grid; place-items:center; flex:none; border-radius:50%; background:conic-gradient(var(--teal) var(--score),#e8eeed 0); }
.score-ring:before { content:""; position:absolute; width:76px; height:76px; border-radius:50%; background:#fff; }
.score-ring span { position:relative; z-index:1; }
.score-ring strong { font-family:"Iowan Old Style",Georgia,serif; font-size:34px; font-weight:500; }
.score-ring small { color:var(--muted); font-size:9px; }
.overall-card.fair .score-ring { background:conic-gradient(#d5922b var(--score),#e8eeed 0); }
.overall-card.risk .score-ring { background:conic-gradient(#d45b50 var(--score),#e8eeed 0); }
.overall-card>div:last-child>span,.metric-card>span { color:var(--muted); font-size:10px; }
.overall-card h2 { margin:6px 0 4px; font-family:"Songti SC",serif; font-size:18px; }
.overall-card p,.metric-card p { margin:0; color:#8a979a; font-size:9px; }
.metric-card { display:flex; flex-direction:column; justify-content:center; }
.metric-card>strong { margin:9px 0 8px; font-family:"Iowan Old Style",Georgia,serif; font-size:35px; font-weight:500; }
.metric-card>strong small { margin-left:3px; color:#9aa5a7; font:500 12px "Avenir Next",sans-serif; }
.risk-card>strong { color:var(--red); }
.mini-bar { height:4px; overflow:hidden; border-radius:2px; background:#edf1f0; }
.mini-bar i { display:block; height:100%; border-radius:inherit; background:var(--teal); }

.insight-panel { display:grid; grid-template-columns:52px 1.35fr .8fr; gap:24px; align-items:center; margin-top:12px; padding:24px 26px; border:1px solid #cae6e2; border-radius:12px; background:linear-gradient(112deg,#f0fbf8,#fff 60%); }
.insight-mark { width:45px; height:45px; display:grid; place-items:center; border-radius:12px; color:#fff; background:var(--teal); font-family:Georgia,serif; font-size:15px; box-shadow:0 9px 20px rgba(11,147,136,.2); }
.insight-main h2 { margin:5px 0 6px; font-family:"Songti SC",serif; font-size:18px; }
.insight-main p { margin:0; color:#566b6f; font-size:11px; line-height:1.7; }
.priority-note { padding-left:22px; border-left:1px solid #d8e9e6; }
.priority-note span { color:var(--amber); font-size:9px; font-weight:800; letter-spacing:.1em; }
.priority-note p { margin:6px 0 0; color:#455a5e; font-size:10px; line-height:1.6; }

.capability-panel,.diagnostic-section,.issues-panel,.action-panel,.ai-sample-panel { margin-top:16px; border:1px solid var(--line); border-radius:13px; background:#fff; }
.panel-heading { min-height:68px; display:flex; align-items:center; justify-content:space-between; gap:20px; padding:15px 21px; border-bottom:1px solid var(--line); }
.panel-heading h2 { margin:4px 0 0; font-family:"Songti SC","Noto Serif SC",serif; font-size:18px; }
.panel-heading>p { max-width:430px; margin:0; color:var(--muted); font-size:10px; text-align:right; }
.panel-heading>a { color:var(--teal); font-size:10px; font-weight:700; text-decoration:none; }
.capability-heading { min-height:86px; background:linear-gradient(105deg,#f7fcfb 0,#fff 58%); }
.capability-heading>div:first-child>p { margin:7px 0 0; color:#708184; font-size:10px; }
.decomposition-score { min-width:142px; display:grid; grid-template-columns:1fr auto; grid-template-rows:auto auto; column-gap:4px; align-items:end; padding:10px 14px 9px; border:1px solid #cfe4e0; border-radius:9px; background:#fff; box-shadow:inset 3px 0 0 var(--teal),0 8px 22px rgba(34,80,77,.06); }
.decomposition-score>span { grid-column:1/-1; color:#77908d; font:750 8px "SFMono-Regular",monospace; letter-spacing:.15em; }
.decomposition-score strong { margin-top:2px; color:var(--teal-dark); font:600 29px "Iowan Old Style",Georgia,serif; line-height:1; }
.decomposition-score small { padding-bottom:2px; color:#8a999b; font-size:9px; }
.decomposition-score.fair { box-shadow:inset 3px 0 0 #d5922b,0 8px 22px rgba(34,80,77,.06); }
.decomposition-score.fair strong { color:#b77515; }
.decomposition-score.risk { box-shadow:inset 3px 0 0 #d45b50,0 8px 22px rgba(34,80,77,.06); }
.decomposition-score.risk strong { color:#c34940; }
.capability-body { display:grid; grid-template-columns:310px 1fr; min-height:316px; }
.radar-wrap { position:relative; display:grid; place-items:center; overflow:hidden; border-right:1px solid var(--line); background-color:#fbfdfd; background-image:linear-gradient(rgba(26,122,113,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(26,122,113,.035) 1px,transparent 1px); background-size:18px 18px; }
.radar-wrap:after { content:""; position:absolute; width:215px; height:215px; border:1px solid rgba(11,147,136,.08); border-radius:50%; box-shadow:0 0 0 22px rgba(11,147,136,.025),0 0 0 44px rgba(11,147,136,.018); pointer-events:none; }
.radar-scan-label { position:absolute; top:16px; left:18px; color:#75918e; font:700 7px "SFMono-Regular",monospace; letter-spacing:.18em; }
.radar-scan-label:before { content:""; display:inline-block; width:5px; height:5px; margin-right:6px; border-radius:50%; background:#19a58e; box-shadow:0 0 0 4px rgba(25,165,142,.1); }
.radar-wrap svg { width:230px; height:230px; overflow:visible; }
.radar-grid polygon,.radar-grid line { fill:none; stroke:#cfdfdc; stroke-width:1; }
.radar-value { fill:rgba(11,147,136,.17); stroke:var(--teal); stroke-width:2.3; filter:drop-shadow(0 4px 7px rgba(11,147,136,.14)); }
.radar-wrap circle { fill:var(--teal); stroke:#fff; stroke-width:2; }
.radar-label { z-index:1; position:absolute; color:#617a78; font:750 8px "SFMono-Regular",monospace; letter-spacing:.04em; }
.label-1{top:41px;left:145px}.label-2{top:91px;right:24px}.label-3{bottom:91px;right:24px}.label-4{bottom:38px;left:137px}.label-5{bottom:91px;left:24px}.label-6{top:91px;left:26px}
.radar-signals { position:absolute; z-index:2; left:18px; right:18px; bottom:11px; display:flex; justify-content:space-between; gap:8px; padding-top:8px; border-top:1px solid rgba(111,146,141,.18); }
.radar-signals span { color:#82918f; font-size:7px; white-space:nowrap; }
.radar-signals i { display:inline-block; width:5px; height:5px; margin-right:4px; border-radius:1px; background:var(--teal); }
.radar-signals span:last-child i { background:#d45b50; }
.radar-signals b { margin-left:3px; color:#385552; font-weight:800; }
.dimension-list { display:grid; grid-template-columns:1fr 1fr; gap:0 32px; align-content:center; padding:22px 34px; }
.dimension-list article { padding:11px 0; }
.dimension-title { display:grid; grid-template-columns:auto 1fr auto; gap:8px; align-items:center; font-size:11px; }
.dimension-title>span { color:#263f42; font-weight:750; }
.dimension-title em { width:max-content; padding:2px 6px; border-radius:3px; color:#287d71; background:#e8f7f3; font-size:7px; font-style:normal; font-weight:800; letter-spacing:.04em; }
.dimension-list article.watch .dimension-title em { color:#9a6818; background:#fff4df; }
.dimension-list article.risk .dimension-title em { color:#b54842; background:#fff0ee; }
.dimension-list strong { color:var(--teal-dark); font:600 18px "Iowan Old Style",Georgia,serif; }
.dimension-list strong small { margin-left:2px; color:#9aa7a8; font:500 7px "SFMono-Regular",monospace; }
.dimension-list article.watch strong { color:#b77515; }
.dimension-list article.risk strong { color:#c34940; }
.dimension-bar { height:5px; margin:8px 0 6px; overflow:hidden; border-radius:1px; background:repeating-linear-gradient(90deg,#edf2f1 0,#edf2f1 calc(20% - 2px),transparent calc(20% - 2px),transparent 20%); }
.dimension-bar i { display:block; height:100%; border-radius:1px; background:linear-gradient(90deg,#63cdbc,var(--teal)); box-shadow:0 0 9px rgba(11,147,136,.2); }
.dimension-list article.watch .dimension-bar i { background:linear-gradient(90deg,#efc36d,#d5922b); }
.dimension-list article.risk .dimension-bar i { background:linear-gradient(90deg,#ee9b93,#d45b50); }
.dimension-list>article>small { color:#8e9b9d; font:500 8px "SFMono-Regular",monospace; }
.dimension-method { grid-column:1/-1; display:grid; grid-template-columns:auto 1fr; gap:10px; align-items:center; margin:8px 0 0; padding:10px 12px; border:1px solid #dceae7; border-radius:7px; color:#60777a; background:#f5fbf9; font-size:8px; line-height:1.6; }
.dimension-method b { color:#1e766d; font:800 7px "SFMono-Regular",monospace; letter-spacing:.12em; white-space:nowrap; }

.check-grid { display:grid; grid-template-columns:1fr 1fr; gap:1px; background:var(--line); }
.check-grid article { min-height:108px; display:grid; grid-template-columns:29px 1fr auto; gap:12px; align-items:start; padding:19px 20px; background:#fff; }
.check-status { width:25px; height:25px; display:grid; place-items:center; border-radius:50%; color:#fff; background:#25a77f; font-size:11px; font-weight:900; }
.check-grid article.failed .check-status { background:#fff3e3; color:var(--amber); }
.check-copy { min-width:0; }
.check-grid small { color:#92a0a3; font-size:8px; font-weight:750; letter-spacing:.08em; }
.check-grid h3 { margin:4px 0 5px; font-size:12px; }
.check-grid p { margin:0; color:var(--muted); font-size:10px; line-height:1.55; }
.check-grid b { color:var(--red); font:600 13px Georgia,serif; }
.failure-summary { display:grid; grid-template-columns:auto minmax(0,1fr); gap:8px; align-items:start; margin-top:9px; padding:8px 10px; border-left:2px solid #dc746b; border-radius:0 6px 6px 0; background:#fff6f4; }
.failure-summary>span { padding:2px 5px; border-radius:8px; color:#b84a43; background:#ffe6e2; font-size:7px; font-weight:850; white-space:nowrap; }
.failure-summary>p { color:#8d4d48; font-size:9px; line-height:1.55; }
.evidence-toggle { margin-top:9px; padding:0; border:0; color:var(--teal); background:transparent; font-size:9px; font-weight:750; cursor:pointer; }
.evidence-detail { grid-column:2/-1; padding:11px 13px; border:1px solid #d9e9e6; border-radius:8px; background:#f6fbfa; }
.evidence-detail header { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:7px; }
.evidence-detail header span { color:#466568; font-size:9px; font-weight:800; letter-spacing:.04em; }
.evidence-detail header button { padding:0; border:0; color:var(--teal); background:transparent; font-size:9px; font-weight:750; cursor:pointer; }
.evidence-detail ol { max-height:180px; margin:0; padding-left:18px; overflow:auto; }
.evidence-detail li { padding:3px 0; color:#62777a; font-size:9px; line-height:1.5; word-break:break-all; }
.evidence-detail li.failed { margin:3px 0; padding:6px 8px; border-radius:5px; color:#9d443e; background:#fff0ed; font-weight:700; }
.evidence-detail a { color:var(--teal-dark); text-decoration:none; }
.geo-section .section-index { color:#7657be; }
.geo-section .check-status { background:#7657be; }
.geo-section article.failed .check-status { color:#7657be; background:#f1edfb; }
.geo-section .evidence-toggle,.geo-section .evidence-detail header button { color:#7657be; }
.geo-section .evidence-detail { border-color:#e3dcf5; background:#faf8ff; }

.ai-sample-panel { overflow:hidden; border-color:#dcd6ea; }
.sample-heading { min-height:90px; display:flex; align-items:center; justify-content:space-between; gap:24px; padding:20px 24px; color:#f7f4ff; background:#252938; }
.sample-heading .section-index { color:#a895e5; }
.sample-heading h2 { margin:5px 0 4px; font-family:"Songti SC","Noto Serif SC",serif; font-size:20px; }
.sample-heading p { margin:0; color:#aeb4c5; font-size:10px; }
.sample-chips { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:7px; }
.sample-chip { flex:none; padding:7px 10px; border:1px solid rgba(199,185,245,.28); border-radius:14px; color:#d9cff7; background:rgba(137,111,214,.13); font-size:9px; font-weight:750; }
.model-access-bar { display:grid; grid-template-columns:minmax(230px,.8fr) minmax(0,1.65fr); gap:22px; align-items:center; padding:18px 21px; border-bottom:1px solid #e8e4f0; background:radial-gradient(circle at 85% 0,rgba(121,59,215,.08),transparent 35%),linear-gradient(110deg,#fbfafd,#f7faf9); }
.model-access-copy>span,.model-access-copy>strong,.model-access-copy>p { display:block; }.model-access-copy>span { color:#8061c1; font:800 8px "SFMono-Regular",monospace; letter-spacing:.15em; }.model-access-copy>strong { margin-top:6px; color:#30313a; font-size:12px; line-height:1.45; }.model-access-copy>p { margin:5px 0 0; color:#848590; font-size:9px; line-height:1.55; }
.model-access-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; }.model-access-grid article { position:relative; min-width:0; display:grid; grid-template-columns:34px minmax(0,1fr); gap:9px; align-items:center; min-height:62px; padding:10px 11px; box-sizing:border-box; border:1px solid #e2ddea; border-radius:12px; background:rgba(255,255,255,.9); box-shadow:0 7px 18px rgba(61,48,79,.035); }.model-access-grid article>i { width:32px; height:32px; display:grid; place-items:center; border-radius:10px; color:#fff; background:linear-gradient(145deg,#7455ba,#9780d0); font-size:9px; font-style:normal; font-weight:850; }.model-access-grid article.active { border-color:#bfe4d8; background:linear-gradient(145deg,#f5fcf9,#fff); }.model-access-grid article.active>i { background:linear-gradient(145deg,#0e9d79,#21bd91); }
.model-access-grid article div { min-width:0; }.model-access-grid article div strong,.model-access-grid article div small { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.model-access-grid article div strong { color:#3b3c45; font-size:10px; }.model-access-grid article div small { margin-top:3px; color:#96949d; font-size:7px; }.model-access-grid article>b { grid-column:1/-1; width:max-content; padding:3px 6px; border-radius:8px; color:#6e4cab; background:#f0ebfa; font-size:7px; }.model-access-grid article.active>b { color:#087961; background:#e4f7f0; }
.model-access-grid article.locked { padding-right:29px; }.model-access-grid article.locked>span { position:absolute; right:10px; top:13px; width:10px; height:9px; border:1.5px solid #947fba; border-radius:2px; opacity:.8; }.model-access-grid article.locked>span:before { content:""; position:absolute; left:1px; top:-7px; width:6px; height:7px; box-sizing:border-box; border:1.5px solid #947fba; border-bottom:0; border-radius:5px 5px 0 0; }
.member-model-preview { padding:20px 21px 22px; border-bottom:1px solid #e8e4f0; background:#fff; }.member-model-preview>header { display:flex; align-items:flex-start; justify-content:space-between; gap:20px; margin-bottom:13px; }.member-model-preview>header span { color:#8061c1; font:800 8px "SFMono-Regular",monospace; letter-spacing:.15em; }.member-model-preview>header h3 { margin:5px 0 3px; color:#32333b; font-size:15px; }.member-model-preview>header p { margin:0; color:#85858e; font-size:10px; line-height:1.55; }.member-model-preview>header>b { flex:none; padding:5px 8px; border-radius:10px; color:#7b699a; background:#f2eef8; font-size:8px; }
.member-preview-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }.member-preview-grid>article { position:relative; min-width:0; overflow:hidden; padding:15px; border:1px solid #e4dfeb; border-radius:14px; background:linear-gradient(145deg,#fff,#faf8fd); box-shadow:0 8px 20px rgba(59,44,78,.045); }.member-preview-grid>article:after { content:""; position:absolute; inset:47px 0 34px; pointer-events:none; background:linear-gradient(90deg,rgba(255,255,255,.1),rgba(255,255,255,.55),rgba(255,255,255,.12)); backdrop-filter:blur(1.5px); }.member-preview-grid article>header { display:grid; grid-template-columns:34px minmax(0,1fr) auto; gap:9px; align-items:center; }.member-preview-grid article>header>i { width:32px; height:32px; display:grid; place-items:center; border-radius:9px; color:#fff; background:linear-gradient(145deg,#7252b6,#9a83cf); font-size:10px; font-style:normal; font-weight:850; }.member-preview-grid article>header div { min-width:0; }.member-preview-grid article>header strong,.member-preview-grid article>header small { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.member-preview-grid article>header strong { color:#3a3b44; font-size:11px; }.member-preview-grid article>header small { margin-top:3px; color:#97949f; font-size:8px; }.member-preview-grid article>header em { padding:4px 6px; border-radius:8px; color:#7654b5; background:#f0eafa; font-size:7px; font-style:normal; font-weight:850; }
.locked-metric { display:flex; align-items:flex-end; justify-content:space-between; gap:12px; margin-top:14px; padding:12px; border-radius:10px; background:#f7f5f9; }.locked-metric span { color:#83808a; font-size:9px; }.locked-metric strong { color:#4d3f62; font:750 25px/1 "Iowan Old Style",Georgia,serif; filter:blur(5px); opacity:.62; user-select:none; }.locked-answer { display:grid; gap:6px; margin-top:12px; filter:blur(3.5px); opacity:.58; user-select:none; }.locked-answer span { height:7px; border-radius:4px; background:#bdb5ca; }.locked-answer span:nth-child(2) { width:86%; }.locked-answer span:nth-child(3) { width:63%; }
.member-preview-grid article>footer { position:relative; z-index:2; display:flex; align-items:center; gap:7px; margin:14px -15px -15px; padding:10px 15px; color:#6f5c90; background:rgba(244,240,250,.92); font-size:8px; font-weight:750; }.mini-lock { position:relative; width:10px; height:9px; box-sizing:border-box; border:1.5px solid #8064ae; border-radius:2px; }.mini-lock:before { content:""; position:absolute; left:1px; top:-7px; width:6px; height:7px; box-sizing:border-box; border:1.5px solid #8064ae; border-bottom:0; border-radius:5px 5px 0 0; }
.comparison-preview>header>i { background:linear-gradient(145deg,#0e9d79,#6a51b3) !important; }.comparison-rows { display:grid; gap:8px; margin-top:16px; filter:blur(3.5px); opacity:.62; user-select:none; }.comparison-rows span { display:grid; grid-template-columns:20px minmax(0,1fr); gap:8px; align-items:center; }.comparison-rows b { color:#857a98; font:800 7px "SFMono-Regular",monospace; }.comparison-rows i { height:8px; border-radius:5px; background:linear-gradient(90deg,#16b184 0 62%,#ded8e8 62%); }.comparison-rows span:nth-child(2) i { background:linear-gradient(90deg,#8c55cb 0 45%,#ded8e8 45%); }.comparison-rows span:nth-child(3) i { background:linear-gradient(90deg,#45a6a0 0 75%,#ded8e8 75%); }
.sample-composer { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:14px; align-items:end; padding:18px 21px; border-bottom:1px solid #e8e4f0; background:#fbfafd; }
.sample-question-list { display:grid; gap:7px; }
.sample-question-list label { display:grid; grid-template-columns:29px minmax(0,1fr); align-items:center; gap:8px; }
.sample-question-list label>span { color:#7c699e; font:800 9px "SFMono-Regular",monospace; }
.sample-question-list input { min-width:0; height:34px; padding:0 11px; border:1px solid #ddd8e9; border-radius:7px; outline:0; color:#303440; background:#fff; font-size:10px; }
.sample-question-list input:focus { border-color:#8870c4; box-shadow:0 0 0 3px rgba(118,87,190,.09); }
.sample-composer>button { height:39px; padding:0 16px; border:0; border-radius:8px; color:#fff; background:#7657be; font-size:10px; font-weight:800; cursor:pointer; }
.sample-composer>button:disabled { opacity:.5; cursor:wait; }
.sample-composer>small { grid-column:2; color:var(--red); font-size:8px; }
.sample-metrics { display:grid; grid-template-columns:1fr 1fr 1.25fr; border-bottom:1px solid #e8e4f0; }
.sample-metrics article { min-height:112px; padding:20px 23px; border-right:1px solid #e8e4f0; }
.sample-metrics article:last-child { border-right:0; }
.sample-metrics span { display:block; color:#838797; font-size:9px; }
.sample-metrics strong { display:block; margin-top:9px; color:#2b3040; font:500 31px "Iowan Old Style",Georgia,serif; }
.sample-metrics strong small { display:inline; margin-left:3px; color:#969aaa; font:500 11px "Avenir Next",sans-serif; }
.sample-metrics .model-name { font-size:23px; }
.sample-metrics article>small { display:block; margin-top:4px; color:#989cab; font-size:8px; }
.sample-results { display:grid; grid-template-columns:1fr 1fr 1fr; gap:1px; background:#e8e4f0; }
.sample-results>article { min-width:0; display:grid; grid-template-columns:29px minmax(0,1fr); gap:10px; padding:20px; background:#fff; }
.sample-results>article.mentioned { box-shadow:inset 0 3px 0 #2aa579; }
.sample-index { color:#d4cede; font:500 22px "Iowan Old Style",Georgia,serif; }
.sample-result-copy { min-width:0; }
.sample-result-copy header { display:flex; align-items:center; justify-content:space-between; gap:7px; }
.sample-result-copy header>span { padding:3px 7px; border-radius:9px; font-size:8px; font-weight:800; }
.sample-result-copy .hit { color:#167452; background:#e6f7f0; }
.sample-result-copy .miss { color:#9b6721; background:#fff4df; }
.sample-result-copy header small { max-width:120px; overflow:hidden; color:#8a8e9c; font-size:8px; text-overflow:ellipsis; white-space:nowrap; }
.sample-result-copy h3 { min-height:38px; margin:10px 0 7px; font-size:11px; line-height:1.55; }
.sample-result-copy>p { max-height:68px; margin:0; overflow:hidden; color:#68707b; font-size:9px; line-height:1.7; }
.sample-result-copy details { margin-top:10px; }
.sample-result-copy summary { color:#7657be; font-size:9px; font-weight:750; cursor:pointer; }
.sample-result-copy pre { max-height:260px; margin:9px 0; padding:11px; overflow:auto; border:1px solid #e7e2ef; border-radius:7px; color:#4d5360; background:#f8f7fa; font:9px/1.7 "SFMono-Regular",Consolas,monospace; white-space:pre-wrap; word-break:break-word; }
.sample-result-copy details>button { padding:0; border:0; color:#7657be; background:transparent; font-size:8px; font-weight:750; cursor:pointer; }
.sample-sources { display:grid; gap:4px; margin:8px 0; }
.sample-sources b { color:#777c89; font-size:8px; }
.sample-sources a { overflow:hidden; color:#7657be; font-size:8px; text-overflow:ellipsis; text-decoration:none; white-space:nowrap; }
.sample-method { display:grid; grid-template-columns:1fr 1fr; gap:20px; padding:15px 21px; color:#777c89; background:#f8f7fa; }
.sample-method p { margin:0; font-size:9px; line-height:1.6; }
.sample-method b { margin-right:7px; color:#4c5260; }
.sample-empty { min-height:108px; display:flex; align-items:center; justify-content:center; gap:13px; padding:24px; }
.sample-empty>span { width:38px; height:38px; display:grid; place-items:center; border-radius:50%; color:#fff; background:#7657be; font-size:10px; font-weight:850; }
.sample-empty p { max-width:610px; margin:0; color:#777c89; font-size:10px; line-height:1.7; }
.sample-empty strong { color:#343946; }

.issue-heading h2 em { display:inline-grid; place-items:center; min-width:22px; height:20px; margin-left:5px; border-radius:10px; color:#fff; background:var(--red); font:700 9px "Avenir Next",sans-serif; font-style:normal; vertical-align:3px; }
.issue-filters { display:flex; gap:6px; }
.issue-filters button { height:28px; padding:0 10px; border:1px solid var(--line); border-radius:7px; background:#fff; color:#758388; font-size:9px; cursor:pointer; }
.issue-filters button.active { color:#fff; border-color:var(--teal); background:var(--teal); }
.issue-table-wrap { overflow-x:auto; }
.issues-panel table { width:100%; border-collapse:collapse; font-size:10px; }
.issues-panel th { padding:12px 15px; color:#879498; background:#f8faf9; font-size:9px; text-align:left; white-space:nowrap; }
.issues-panel td { padding:14px 15px; border-top:1px solid #e9eeed; color:#5f6e72; vertical-align:top; }
.issues-panel td:first-child { min-width:220px; }
.issues-panel td:last-child { min-width:270px; line-height:1.55; }
.issues-panel td strong,.issues-panel td small { display:block; }
.issues-panel td strong { margin-bottom:4px; color:#273b3f; font-size:11px; }
.issues-panel td small { max-width:370px; color:#8c999c; line-height:1.45; }
.domain-tag,.severity-tag { display:inline-flex; align-items:center; height:21px; padding:0 7px; border-radius:11px; font-size:8px; font-weight:800; }
.domain-tag.seo { color:#1769a5; background:#ebf5fb; }.domain-tag.geo{color:#7452b6;background:#f1edfb}.domain-tag.content{color:#8a641a;background:#fff5dd}
.severity-tag.critical,.severity-tag.high { color:#b73c3c; background:#fff0ef; }.severity-tag.medium{color:#ae6c11;background:#fff5e7}.severity-tag.low{color:#47757b;background:#edf6f5}
.deduction { color:var(--red) !important; font-weight:800; }
.empty-row { padding:35px !important; color:#96a2a5 !important; text-align:center; }

.boundary-chip { height:24px; display:inline-flex; align-items:center; padding:0 9px; border-radius:12px; color:#34736d; background:var(--teal-soft); font-size:8px; font-weight:750; }
.action-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; padding:18px; }
.action-grid article { position:relative; min-height:205px; padding:21px; border:1px solid var(--line); border-radius:10px; background:#fbfcfc; }
.action-grid article>span { position:absolute; right:16px; top:13px; color:#d7e1df; font:500 30px Georgia,serif; }
.action-grid small { color:var(--amber); font-size:8px; font-weight:800; letter-spacing:.1em; }
.action-grid h3 { margin:12px 0 8px; padding-right:30px; font-size:13px; }
.action-grid p { margin:0; color:#657579; font-size:10px; line-height:1.65; }
.action-grid footer { margin-top:18px; padding-top:12px; border-top:1px solid var(--line); color:#7c898c; font-size:9px; line-height:1.5; }
.action-grid footer b { margin-right:6px; color:#40565a; }
.bridge-btn {
  margin-top:12px; height:32px; padding:0 12px; border:1px solid var(--teal);
  border-radius:8px; background:#fff; color:var(--teal-dark); font-size:10px; font-weight:700; cursor:pointer;
}
.bridge-btn:disabled { opacity:.55; cursor:not-allowed; }
.action-empty { display:flex; align-items:center; justify-content:space-between; gap:20px; padding:25px; }
.action-empty strong { font-size:13px; }
.action-empty p { margin:6px 0 0; color:var(--muted); font-size:10px; }
.action-empty button { height:39px; padding:0 17px; border:0; border-radius:8px; color:#fff; background:var(--teal); font-size:10px; font-weight:800; cursor:pointer; }

/* Acquisition command center visual system */
.diagnosis-center {
  --ink:#171820; --muted:#727581; --line:#e6e5ea; --canvas:#f5f6f8;
  --teal:#10aa86; --teal-dark:#087961; --teal-soft:#eaf9f4;
  --violet:#793bd7; --violet-dark:#54229d; --violet-soft:#f2edfb;
  grid-template-columns:252px minmax(0,1fr);
  background:radial-gradient(circle at 72% 5%,rgba(121,59,215,.055),transparent 25%),radial-gradient(circle at 96% 38%,rgba(16,170,134,.05),transparent 22%),var(--canvas);
}
.diagnosis-sidebar { padding:25px 17px 18px; border-right-color:#ecebf0; background:rgba(255,255,255,.93); box-shadow:12px 0 34px rgba(43,35,61,.025); backdrop-filter:blur(18px); }
.diagnosis-brand { gap:13px; padding:3px 10px 29px; }
.brand-mark { width:64px; height:64px; flex:none; margin:-8px -4px -8px -6px; object-fit:contain; filter:drop-shadow(0 10px 16px rgba(105,49,190,.22)); }
.diagnosis-brand strong { font-size:16px; font-weight:800; letter-spacing:-.02em; }.diagnosis-brand small { color:#898794; font-size:8px; font-weight:750; letter-spacing:.12em; }
.nav-label { color:#aaa7b1; font-size:9px; letter-spacing:.18em; }.sidebar-item { min-height:43px; border-radius:12px; color:#5e606b; }
.sidebar-item:hover { color:var(--violet-dark); background:#f7f4fc; }.sidebar-item.active { color:var(--violet-dark); background:linear-gradient(100deg,#f0eafd,#f7f5fb 72%); box-shadow:inset 3px 0 0 var(--violet); }
.sidebar-item.active .sidebar-icon { color:var(--violet); }.asset-label { border-top-color:#efedf2; }.module-link:hover { color:var(--teal-dark); background:var(--teal-soft); }
.diagnosis-topbar { min-height:106px; padding:19px 36px 17px; border-bottom-color:#ebe9ef; background:rgba(255,255,255,.86); }
.topbar-kicker,.section-index { color:var(--violet); }.diagnosis-topbar h1 { color:#191a21; font-size:26px; }
.topbar-actions button { border-radius:18px; }.topbar-actions button:hover:not(:disabled) { color:var(--violet); border-color:#cbb7eb; }.avatar { background:linear-gradient(145deg,var(--violet),#9d52df); box-shadow:0 6px 17px rgba(121,59,215,.2); }
.diagnosis-content { padding-top:30px; }
.scan-panel { min-height:272px; grid-template-columns:.95fr 1.05fr; padding:40px 44px; color:var(--ink); border:1px solid rgba(121,59,215,.13); border-radius:22px; background:linear-gradient(90deg,rgba(255,255,255,.97),rgba(255,255,255,.9)),repeating-linear-gradient(90deg,transparent 0 39px,rgba(121,59,215,.08) 40px),repeating-linear-gradient(0deg,transparent 0 39px,rgba(16,170,134,.08) 40px); box-shadow:0 18px 48px rgba(45,36,61,.075); }
.scan-panel:before { content:""; position:absolute; width:420px; height:420px; left:-250px; bottom:-320px; border-radius:50%; background:rgba(121,59,215,.08); filter:blur(2px); }
.scan-panel:after { width:285px; height:285px; right:-82px; top:-176px; border-color:rgba(16,170,134,.22); box-shadow:0 0 0 34px rgba(16,170,134,.025),0 0 0 69px rgba(121,59,215,.02); }
.scan-copy h2 { margin-top:12px; color:#171820; font-size:32px; line-height:1.22; }.scan-copy h2 em { color:transparent; background:linear-gradient(90deg,var(--violet) 0 42%,var(--teal) 88%); background-clip:text; -webkit-background-clip:text; }
.scan-copy>p { color:#666a75; }.scan-notes { color:#70747e; }
.scan-form { padding:24px; border:1px solid #e4e0eb; border-radius:17px; background:rgba(250,249,252,.88); box-shadow:0 13px 34px rgba(57,43,78,.06); }.scan-form>label { color:#363641; }
.url-input-wrap { height:61px; border-color:#dfd7ea; border-radius:13px; box-shadow:0 10px 24px rgba(55,39,78,.07); }.url-input-wrap:focus-within { border-color:#a98bd6; box-shadow:0 0 0 4px rgba(121,59,215,.08),0 10px 24px rgba(55,39,78,.07); }
.url-input-wrap button { border-radius:9px; background:linear-gradient(110deg,var(--violet) 0 16%,#6754d8 45%,var(--teal) 100%); box-shadow:0 8px 20px rgba(92,67,197,.2); }.url-input-wrap button:hover:not(:disabled) { background:linear-gradient(110deg,#6e2fc8,#159d82); }
.scope { color:#8a8993; }.scope.active { color:var(--violet); font-weight:800; }.scope small { color:#118b72; background:#e8f7f2; }.form-hint { color:#8a8993; }
.preflight-grid article,.summary-grid article,.capability-panel,.diagnostic-section,.issues-panel,.action-panel,.site-coverage-panel { border-color:#e7e4eb; border-radius:17px; box-shadow:0 10px 28px rgba(52,43,68,.04); }
.preflight-grid article:first-child { box-shadow:inset 0 3px 0 var(--teal),0 10px 28px rgba(52,43,68,.04); }.preflight-grid article:nth-child(2) { box-shadow:inset 0 3px 0 var(--violet),0 10px 28px rgba(52,43,68,.04); }.preflight-grid article:nth-child(3) { box-shadow:inset 0 3px 0 #32b8b0,0 10px 28px rgba(52,43,68,.04); }.preflight-grid article:nth-child(2) span { color:var(--violet); }
.summary-grid { gap:14px; }.summary-grid article { border-radius:18px; }.score-ring { background:conic-gradient(var(--teal) 0 var(--score),#ececf0 0); box-shadow:0 0 0 7px #f8f8fa; }
.metric-card:nth-child(2)>strong { color:var(--teal-dark); }.metric-card:nth-child(4)>strong { color:var(--violet); }
.insight-panel { border-color:#ded4ee; border-radius:18px; background:linear-gradient(115deg,#f5f0fd 0,#fff 53%,#effbf7 100%); box-shadow:0 10px 28px rgba(52,43,68,.04); }.insight-mark { background:linear-gradient(145deg,var(--violet),#8f52d7); box-shadow:0 9px 20px rgba(121,59,215,.19); }
.capability-heading { background:linear-gradient(105deg,#f7f3fd 0,#fff 55%,#f2fbf8); }.decomposition-score { border-color:#dcd3e9; box-shadow:inset 3px 0 0 var(--violet),0 8px 22px rgba(69,51,91,.06); }.decomposition-score strong { color:var(--violet-dark); }
.radar-wrap { background-color:#fbfafd; background-image:linear-gradient(rgba(121,59,215,.04) 1px,transparent 1px),linear-gradient(90deg,rgba(16,170,134,.04) 1px,transparent 1px); }.radar-wrap:after { border-color:rgba(121,59,215,.1); box-shadow:0 0 0 22px rgba(121,59,215,.025),0 0 0 44px rgba(16,170,134,.018); }
.radar-value { fill:rgba(121,59,215,.13); stroke:var(--violet); filter:drop-shadow(0 4px 7px rgba(121,59,215,.16)); }.radar-wrap circle { fill:var(--teal); }.radar-scan-label:before,.radar-signals i { background:var(--violet); }
.dimension-list { gap:0 36px; }.dimension-title em { color:#165f91; background:#eaf4fb; }.dimension-bar i { background:linear-gradient(90deg,var(--violet),#5b83db 46%,var(--teal)); }.dimension-method { border-color:#e3dced; background:linear-gradient(90deg,#f8f5fc,#f5fbf9); }.dimension-method b { color:var(--violet-dark); }
.diagnostic-section { overflow:hidden; }.check-grid { grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; padding:14px; background:#faf9fb; }.check-grid article { min-height:150px; border:1px solid #e8e5ec; border-radius:13px; box-shadow:0 7px 18px rgba(54,43,68,.035); }
.check-grid article:not(.failed):nth-child(3n) { box-shadow:inset 0 3px 0 rgba(121,59,215,.72),0 7px 18px rgba(54,43,68,.035); }.check-grid article:not(.failed):nth-child(3n) .check-status { background:var(--violet); }
.geo-section .section-index { color:var(--violet); }.issue-heading { background:linear-gradient(90deg,#fff,#faf8fd); }.issue-filters button { border-radius:14px; }.issue-filters button.active { border-color:var(--violet); background:var(--violet); }
.issues-panel th { color:#777681; background:#f8f7fa; }.issues-panel tr:hover td { background:#fdfcfe; }
.issue-impact { min-width:126px; display:grid; grid-template-columns:minmax(82px,1fr) 28px; gap:9px; align-items:center; }.issue-impact:before { content:""; grid-column:1; grid-row:1; height:9px; border-radius:3px; background:repeating-linear-gradient(90deg,#f0edef 0,#f0edef calc(20% - 1px),transparent calc(20% - 1px),transparent 20%); }.issue-impact i { z-index:1; grid-column:1; grid-row:1; height:9px; max-width:100%; border-radius:3px; background:linear-gradient(90deg,#ff9b47,#f15d52,#e8404d); box-shadow:0 4px 10px rgba(235,75,75,.18); }.issue-impact b { grid-column:2; grid-row:1; color:#d43d48; font:800 11px "SFMono-Regular",monospace; }
.action-panel .boundary-chip { color:var(--violet-dark); background:var(--violet-soft); }.action-grid article { border-color:#e6e2eb; border-radius:14px; background:linear-gradient(145deg,#fff,#fbfafc); }.action-grid article>span { color:#ded6ec; }.action-empty button { background:linear-gradient(110deg,var(--violet),var(--teal)); box-shadow:0 8px 20px rgba(92,67,197,.16); }

.flow-map { position:relative; display:grid; grid-template-columns:repeat(4,1fr); gap:1px; margin:14px 0 0; overflow:hidden; border:1px solid #e4e1e8; border-radius:16px; background:#e4e1e8; box-shadow:0 9px 26px rgba(50,41,63,.035); }
.flow-map.compact { grid-template-columns:repeat(3,1fr); }
.flow-map:before { content:""; position:absolute; z-index:2; left:11%; right:11%; top:25px; height:1px; background:linear-gradient(90deg,var(--teal),#9a90c7 52%,var(--violet)); pointer-events:none; }
.flow-map a { position:relative; z-index:3; min-height:66px; display:flex; align-items:center; gap:11px; padding:13px 16px; color:#363742; background:rgba(255,255,255,.97); text-decoration:none; transition:background .2s,transform .2s; }
.flow-map a:hover { background:#faf8fd; transform:translateY(-1px); }
.flow-map b { width:27px; height:27px; display:grid; place-items:center; flex:none; border:3px solid #fff; border-radius:50%; color:#fff; background:var(--teal); box-shadow:0 0 0 1px #a8dace; font:800 8px "SFMono-Regular",monospace; }
.flow-map a:nth-child(2) b { background:#3aa49d; }.flow-map a:nth-child(3) b { background:#6b64bd; box-shadow:0 0 0 1px #c9c1e6; }.flow-map a:nth-child(4) b { background:var(--violet); box-shadow:0 0 0 1px #c4afe7; }
.flow-map span,.flow-map small { display:block; }.flow-map span { font-size:10px; font-weight:800; }.flow-map small { margin-top:3px; color:#93919b; font-size:8px; font-weight:500; }
.flow-screen { position:relative; margin-top:18px; padding:18px; border:1px solid #e5e2e8; border-radius:22px; background:rgba(255,255,255,.82); box-shadow:0 18px 48px rgba(51,41,64,.06); scroll-margin-top:16px; }
.flow-screen>.flow-stage-heading { margin-top:0; padding:0 6px 8px; }.flow-screen>.site-coverage-panel,.flow-screen>.summary-grid,.flow-screen>.insight-panel,.flow-screen>.capability-panel,.flow-screen>.diagnostic-section,.flow-screen>.issues-panel,.flow-screen>.action-panel,.flow-screen>.ai-sample-panel { margin-top:14px; }
.overview-screen { background:radial-gradient(circle at 91% 0,rgba(16,170,134,.06),transparent 28%),linear-gradient(145deg,rgba(255,255,255,.94),rgba(249,248,251,.94)); }
.overview-screen>.site-coverage-panel,.overview-screen>.summary-grid,.overview-screen>.insight-panel,.overview-screen>.capability-panel { display:none; }
.flow-stage-heading p { margin:4px 0 0; color:#8e8d96; font-size:9px; }
.overview-dashboard { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:16px; margin-top:8px; }
.dashboard-card { min-width:0; padding:23px 25px; border:1px solid #e2e2e5; border-radius:22px; background:#fff; box-shadow:0 10px 30px rgba(45,40,52,.045); }
.dashboard-card>header { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; }.dashboard-card>header h3,.dashboard-card>header small { display:block; margin:0; }.dashboard-card>header h3 { color:#26272e; font-size:15px; font-weight:650; }.dashboard-card>header small { margin-top:4px; color:#a5a4aa; font-size:9px; letter-spacing:.02em; }.dashboard-card>header>span { color:#b4b3b8; font-size:13px; letter-spacing:.08em; }
.score-rules-help { position:relative; z-index:35; }.score-rules-help summary { width:22px; height:22px; display:grid; place-items:center; box-sizing:border-box; border:1px solid #dfe6e3; border-radius:50%; color:#169a77; background:#f4faf8; font:800 10px Georgia,serif; list-style:none; cursor:help; transition:border-color .18s,background .18s,transform .18s; }.score-rules-help summary::-webkit-details-marker { display:none; }.score-rules-help summary:hover,.score-rules-help[open] summary { border-color:#8fd6c2; background:#e8f8f2; transform:translateY(-1px); }.score-rules-popover { position:absolute; z-index:40; top:30px; left:-126px; width:min(690px,calc(100vw - 390px)); padding:20px; box-sizing:border-box; border:1px solid #dce8e4; border-radius:16px; color:#30363a; background:rgba(255,255,255,.98); box-shadow:0 24px 65px rgba(31,51,48,.18),0 2px 8px rgba(31,51,48,.06); opacity:0; visibility:hidden; transform:translateY(-6px); transition:opacity .16s,visibility .16s,transform .16s; backdrop-filter:blur(18px); }.score-rules-help:hover .score-rules-popover,.score-rules-help:focus-within .score-rules-popover,.score-rules-help[open] .score-rules-popover { opacity:1; visibility:visible; transform:translateY(0); }.score-rules-popover>header { display:flex; align-items:flex-start; justify-content:space-between; gap:18px; padding-bottom:13px; border-bottom:1px solid #e8eeec; }.score-rules-popover>header small { color:#0c9b76; font:800 7px "SFMono-Regular",monospace; letter-spacing:.18em; }.score-rules-popover>header h4 { margin:5px 0 0; color:#20262a; font-size:16px; }.score-rules-popover>header>span { padding:5px 8px; border-radius:12px; color:#6f7c79; background:#f2f6f5; font-size:8px; white-space:nowrap; }.score-rules-summary { margin:12px 0; color:#6f7978; font-size:9px; line-height:1.65; }.score-rule-list { max-height:370px; display:grid; grid-template-columns:1fr 1fr; gap:7px; overflow:auto; padding:1px 4px 1px 1px; scrollbar-color:#b8d9d0 transparent; }.score-rule-list article { min-width:0; display:grid; grid-template-columns:25px minmax(0,1fr) auto; gap:9px; align-items:start; padding:10px; border:1px solid #eceff0; border-radius:10px; background:#fbfbfc; }.score-rule-list article>span { width:23px; height:23px; display:grid; place-items:center; border-radius:50%; color:#a56a66; background:#fff0ed; font:800 7px "SFMono-Regular",monospace; }.score-rule-list article.passed>span { color:#08785f; background:#e4f6ef; }.score-rule-list article header { display:flex; align-items:center; flex-wrap:wrap; gap:5px; }.score-rule-list strong { color:#343a3d; font-size:9px; }.score-rule-list em { padding:2px 5px; border-radius:8px; color:#73807e; background:#eef3f1; font-size:6px; font-style:normal; }.score-rule-list p,.score-rule-list small { display:block; margin:0; line-height:1.5; }.score-rule-list p { margin-top:4px; color:#697472; font-size:7px; }.score-rule-list small { margin-top:3px; overflow:hidden; color:#9a9fa0; font-size:6px; text-overflow:ellipsis; white-space:nowrap; }.score-rule-list article>b { color:#4f5b58; font:800 8px "SFMono-Regular",monospace; white-space:nowrap; }.score-rules-popover>footer { display:flex; align-items:center; gap:7px; margin-top:12px; padding-top:12px; border-top:1px solid #e8eeec; color:#178d70; font-size:8px; }.score-rules-popover>footer i { width:6px; height:6px; border-radius:50%; background:#18b687; box-shadow:0 0 0 4px rgba(24,182,135,.1); }.score-rules-popover>footer span { margin-left:auto; color:#8b9391; }
.health-dashboard-card { min-height:370px; display:flex; flex-direction:column; align-items:stretch; }.health-gauge { position:relative; width:270px; height:220px; margin:10px auto -19px; }.health-gauge svg { width:100%; height:100%; overflow:visible; filter:drop-shadow(0 9px 15px rgba(19,190,129,.1)); }.health-gauge circle { fill:none; stroke-width:14; stroke-linecap:round; transform:rotate(135deg); transform-origin:120px 111px; }.health-gauge .gauge-track { stroke:#e4ebe8; stroke-dasharray:367 490; }.health-gauge .gauge-progress { stroke:url(#health-score-gradient); }.health-gauge>div { position:absolute; z-index:2; left:0; right:0; top:94px; display:flex; align-items:baseline; justify-content:center; }.health-gauge strong { color:#171820; font:700 45px "Iowan Old Style",Georgia,serif; }.health-gauge small { margin-left:3px; color:#34353c; font-size:14px; }.health-dashboard-card>p { margin:0 auto; color:#85858d; font-size:10px; line-height:1.7; text-align:center; }.health-dashboard-card>p b { color:#4c4d55; }.health-dashboard-card>footer { display:flex; justify-content:center; gap:12px; margin:auto auto 0; padding:9px 18px; border-radius:20px; color:#96959c; background:#f7f8f8; font-size:9px; }.health-dashboard-card>footer b { color:#0ca77d; font-size:12px; }
.radar-dashboard-card { min-height:370px; }.dashboard-radar { position:relative; width:285px; height:275px; margin:3px auto -3px; }.dashboard-radar svg { width:250px; height:250px; margin:12px 18px; overflow:visible; }.dashboard-radar .radar-grid polygon,.dashboard-radar .radar-grid line { stroke:#cee6de; }.dashboard-radar .radar-value { fill:rgba(16,181,123,.35); stroke:#0da878; stroke-width:2; filter:drop-shadow(0 6px 9px rgba(16,170,134,.16)); }.dashboard-radar circle { fill:#0da878; stroke:#fff; stroke-width:2; }.dashboard-radar-label { position:absolute; color:#59615f; font-size:9px; white-space:nowrap; }.radar-position-1{top:2px;left:112px}.radar-position-2{top:67px;right:-8px}.radar-position-3{bottom:66px;right:-13px}.radar-position-4{bottom:2px;left:108px}.radar-position-5{bottom:66px;left:-10px}.radar-position-6{top:67px;left:-9px}.radar-dashboard-card>footer { display:flex; justify-content:center; gap:22px; color:#8c9293; font-size:9px; }.radar-dashboard-card>footer i { display:inline-block; width:16px; height:4px; margin-right:6px; border-radius:2px; background:#10aa86; }.radar-dashboard-card>footer span:last-child i { opacity:.28; }
.metrics-dashboard-card { min-height:370px; }.dashboard-metrics { display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-top:22px; }.dashboard-metrics section { position:relative; min-height:118px; padding:18px; overflow:hidden; border-radius:17px; background:linear-gradient(145deg,#fafafa,#f2f3f3); }.dashboard-metrics section:nth-child(2),.dashboard-metrics section:nth-child(4) { background:linear-gradient(145deg,#faf8fd,#f3eff9); }.dashboard-metrics span,.dashboard-metrics strong,.dashboard-metrics b { display:block; }.dashboard-metrics span { color:#85868d; font-size:10px; }.dashboard-metrics strong { margin-top:8px; color:#1f2027; font:700 31px "Iowan Old Style",Georgia,serif; }.dashboard-metrics strong small { margin-left:3px; color:#92939a; font:500 9px "Avenir Next",sans-serif; }.dashboard-metrics section>i { position:absolute; right:16px; top:48px; color:#8e4ed5; font-size:24px; font-style:normal; font-weight:800; opacity:.9; }.dashboard-metrics section:nth-child(1)>i,.dashboard-metrics section:nth-child(3)>i { color:#0da27c; }.dashboard-metrics section>b { margin-top:5px; color:#10a67f; font-size:9px; }.dashboard-metrics section:nth-child(2)>b { color:#d45b50; }.dashboard-metrics .baidu-index-metric { grid-column:1/-1; min-height:104px; border:1px solid #e5e1ef; background:linear-gradient(120deg,#f7f2ff,#effaf6); }.dashboard-metrics .baidu-index-metric>i { color:#793bd7; font:800 18px/1 "Avenir Next",sans-serif; }.dashboard-metrics .baidu-index-metric>b { color:#6f6481; }.dashboard-metrics .baidu-index-metric>a { position:absolute; right:18px; bottom:16px; color:#7650ae; font-size:8px; font-weight:750; text-decoration:none; }.dashboard-metrics .baidu-index-metric.unavailable strong,.dashboard-metrics .baidu-index-metric.unavailable>i { color:#aaa4b2; }.dashboard-metrics .baidu-index-metric.unavailable>b { max-width:70%; color:#9b8794; }
.health-gauge { width:258px; height:255px; margin:0 auto -17px; }.health-gauge:before { content:""; position:absolute; z-index:0; inset:25px 20px 17px; border-radius:50%; background:radial-gradient(circle,rgba(56,222,145,.15),rgba(93,224,157,.055) 42%,transparent 70%); filter:blur(7px); }.health-gauge svg { position:relative; z-index:1; height:238px; }.health-gauge circle { stroke-width:12; }.health-gauge>div { top:78px; }.health-gauge strong { font-size:52px; font-weight:700; letter-spacing:-.045em; }.health-gauge small { font-size:13px; }.health-gauge>p { position:absolute; z-index:3; left:0; right:0; top:140px; margin:0; color:#6f7077; font-size:9px; line-height:1.55; text-align:center; }.health-gauge>p b { color:#3f4047; }.health-gauge>p small { display:block; margin-top:4px; color:#a09fa6; font-size:8px; }.health-dashboard-card>footer { margin:0 auto; min-width:146px; box-sizing:border-box; align-items:center; }.health-dashboard-card>footer span { flex:1; }.health-dashboard-card>footer b { font-size:13px; }
.signals-dashboard-card { grid-column:span 2; min-height:205px; }.signal-chart { display:grid; grid-template-columns:1fr 1fr; gap:14px 28px; margin-top:21px; }.signal-chart>div { display:grid; grid-template-columns:72px minmax(0,1fr) 24px; gap:9px; align-items:center; }.signal-chart span { color:#74777f; font-size:8px; }.signal-chart>div>i { height:5px; overflow:hidden; border-radius:3px; background:#edf0ef; }.signal-chart>div>i b { display:block; height:100%; border-radius:inherit; background:linear-gradient(90deg,#10b982,#13a8a0 60%,#793bd7); }.signal-chart strong { color:#3f4149; font:700 9px "SFMono-Regular",monospace; text-align:right; }
.recent-dashboard-card { min-height:205px; }.recent-diagnostics { display:grid; gap:5px; margin-top:14px; }.recent-diagnostics>div { display:grid; grid-template-columns:20px minmax(0,1fr) auto; gap:9px; align-items:center; padding:8px 0; border-bottom:1px solid #f0eef2; }.recent-diagnostics>div>i { width:17px; height:17px; display:grid; place-items:center; border-radius:50%; color:#fff; background:#25b98a; font-size:7px; font-style:normal; }.recent-diagnostics p,.recent-diagnostics strong,.recent-diagnostics small { display:block; min-width:0; margin:0; }.recent-diagnostics p strong { overflow:hidden; color:#43454d; font-size:8px; text-overflow:ellipsis; white-space:nowrap; }.recent-diagnostics p small { margin-top:2px; color:#98979e; font-size:7px; }.recent-diagnostics>div>b { color:#65666e; font-size:8px; white-space:nowrap; }
.dashboard-cta { width:100%; min-height:58px; display:grid; grid-template-columns:34px minmax(0,1fr) auto; gap:12px; align-items:center; padding:11px 17px; border:1px solid #e5e2e9; border-radius:15px; color:#34353d; background:#fff; font:inherit; text-align:left; text-decoration:none; box-shadow:0 8px 18px rgba(48,39,61,.03); cursor:pointer; }.dashboard-cta:disabled { opacity:.55; cursor:wait; }.dashboard-cta.primary { grid-column:span 2; }.dashboard-cta>span { width:30px; height:30px; display:grid; place-items:center; border-radius:50%; color:#793bd7; background:#f1eafb; }.dashboard-cta:not(.primary)>span { color:#0a9c79; background:#e8f8f2; }.dashboard-cta p,.dashboard-cta strong,.dashboard-cta small { display:block; min-width:0; margin:0; }.dashboard-cta p strong { font-size:10px; }.dashboard-cta p small { margin-top:2px; color:#96959c; font-size:7px; }.dashboard-cta>b { padding:8px 14px; border-radius:17px; color:#fff; background:linear-gradient(100deg,#793bd7,#12ab83); font-size:8px; }.dashboard-cta:not(.primary)>b { background:#10aa86; }
.suggestions-dashboard-card { grid-column:1/-1; padding-bottom:13px; }.dashboard-suggestions { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:1px; margin-top:13px; background:#eeecf0; }.dashboard-suggestions>a { min-width:0; display:grid; grid-template-columns:22px minmax(0,1fr) auto; gap:8px; align-items:center; padding:10px; color:#37383f; background:#fff; text-decoration:none; }.dashboard-suggestions>a>i { width:18px; height:18px; display:grid; place-items:center; border-radius:50%; color:#fff; background:#20b887; font-size:7px; font-style:normal; }.dashboard-suggestions>a>i.critical,.dashboard-suggestions>a>i.high { background:#ef6259; }.dashboard-suggestions p,.dashboard-suggestions strong,.dashboard-suggestions small { display:block; min-width:0; margin:0; }.dashboard-suggestions p strong { overflow:hidden; font-size:8px; text-overflow:ellipsis; white-space:nowrap; }.dashboard-suggestions p small { display:-webkit-box; margin-top:3px; overflow:hidden; color:#9a989f; font-size:7px; -webkit-box-orient:vertical; -webkit-line-clamp:1; }.dashboard-suggestions>a>b { padding:4px 7px; border-radius:9px; color:#159574; background:#edf8f4; font-size:7px; white-space:nowrap; }.dashboard-clean { grid-column:1/-1; margin:0; padding:22px; color:#7f8385; background:#fff; font-size:9px; text-align:center; }
.diagnosis-screen { background:radial-gradient(circle at 8% 0,rgba(121,59,215,.055),transparent 27%),rgba(255,255,255,.9); }
.diagnosis-screen:before { content:"SEO / GEO"; position:absolute; right:24px; top:19px; color:rgba(121,59,215,.065); font:800 38px "Avenir Next",sans-serif; letter-spacing:.08em; pointer-events:none; }
.diagnosis-highlights { position:relative; z-index:1; display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; margin-top:10px; }
.diagnosis-highlights article { min-height:185px; display:flex; flex-direction:column; padding:20px; border:1px solid #e5e2e9; border-radius:15px; background:#fff; box-shadow:0 9px 22px rgba(52,42,67,.045); }
.diagnosis-highlights header { display:flex; align-items:center; justify-content:space-between; gap:10px; }.diagnosis-highlights header span { color:#898791; font-size:8px; font-weight:800; letter-spacing:.08em; }.diagnosis-highlights header b { padding:4px 7px; border-radius:10px; color:#bd4d43; background:#fff0ed; font-size:8px; }.diagnosis-highlights article.passed header b { color:#087961; background:#e7f8f2; }
.diagnosis-highlights h3 { margin:18px 0 12px; font-size:14px; }.diagnosis-highlights p { display:-webkit-box; margin:12px 0 0; overflow:hidden; color:#777a84; font-size:9px; line-height:1.65; -webkit-box-orient:vertical; -webkit-line-clamp:2; }.diagnosis-highlights>a,.diagnosis-highlights article>a { width:max-content; margin-top:auto; padding:11px 0 0; color:var(--violet); font-size:9px; font-weight:800; text-decoration:none; }
.highlight-impact { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:10px; align-items:center; }.highlight-impact:before { content:""; grid-column:1; grid-row:1; height:7px; border-radius:4px; background:#f0edef; }.highlight-impact i { z-index:1; grid-column:1; grid-row:1; height:7px; border-radius:4px; background:linear-gradient(90deg,#ff9b47,#e94d50); }.diagnosis-highlights article.passed .highlight-impact i { background:linear-gradient(90deg,#17c28f,#0da97f); }.highlight-impact strong { color:#d84d48; font:800 11px "SFMono-Regular",monospace; }.diagnosis-highlights article.passed .highlight-impact strong { color:#0b8b6d; }
.brand-screen { overflow:hidden; border-color:rgba(84,206,174,.38); background:radial-gradient(circle at 92% -12%,rgba(121,59,215,.34),transparent 35%),radial-gradient(circle at 0 110%,rgba(19,189,143,.22),transparent 34%),linear-gradient(120deg,#102d32,#091f26 62%,#151b34); box-shadow:0 22px 55px rgba(8,31,37,.2); }
.brand-screen>.flow-stage-heading>span { color:rgba(184,240,225,.22); }.brand-screen>.flow-stage-heading>div { border-left-color:rgba(148,220,202,.24); }.brand-screen>.flow-stage-heading b { color:#76e7c8; }.brand-screen>.flow-stage-heading h2 { color:#effbf8; }
.brand-screen>.brand-intelligence-panel { min-height:206px; padding:28px 20px; border:0; border-top:1px solid rgba(115,226,197,.18); border-radius:0; background:transparent; box-shadow:none; }
.brand-screen>.ai-sample-panel { border-color:rgba(214,207,229,.22); box-shadow:0 18px 38px rgba(0,0,0,.12); }
.action-screen { background:linear-gradient(145deg,#fff,#fbfafc); }.action-screen:after { content:""; position:absolute; right:25px; top:28px; width:54px; height:10px; opacity:.35; background:repeating-linear-gradient(90deg,#f0804d 0 7px,transparent 7px 11px); pointer-events:none; }
.flow-stage-heading { min-height:73px; display:flex; align-items:center; gap:15px; margin-top:22px; padding:0 7px; scroll-margin-top:18px; }
.flow-stage-heading>span { color:#d6d1dc; font:500 38px/1 "Iowan Old Style",Georgia,serif; }.flow-stage-heading>div { padding-left:15px; border-left:1px solid #ddd8e3; }.flow-stage-heading b { color:var(--teal-dark); font:850 8px "SFMono-Regular",monospace; letter-spacing:.17em; }.flow-stage-heading h2 { margin:5px 0 0; font:700 18px "Songti SC","Noto Serif SC",serif; letter-spacing:-.02em; }
.brand-stage-heading b { color:#6d45b2; }.action-stage-heading b { color:#9c5527; }
.brand-intelligence-panel { position:relative; min-height:230px; display:grid; grid-template-columns:minmax(0,1.35fr) minmax(260px,.65fr); gap:36px; align-items:center; overflow:hidden; padding:34px 38px; border:1px solid rgba(82,218,180,.45); border-radius:18px; color:#ecfbf7; background:radial-gradient(circle at 92% -10%,rgba(121,59,215,.42),transparent 38%),radial-gradient(circle at 5% 125%,rgba(18,205,151,.27),transparent 42%),linear-gradient(120deg,#102e33,#0a242b 58%,#151d38); box-shadow:0 19px 45px rgba(10,36,42,.17),inset 0 1px 0 rgba(255,255,255,.07); }
.brand-intelligence-panel:before { content:""; position:absolute; right:-75px; top:-120px; width:280px; height:280px; border:1px solid rgba(126,239,208,.14); border-radius:50%; box-shadow:0 0 0 34px rgba(126,239,208,.025),0 0 0 70px rgba(125,72,206,.025); }
.brand-console-copy,.brand-console-signal { position:relative; z-index:1; }.console-kicker { color:#72e6c6; font:800 8px "SFMono-Regular",monospace; letter-spacing:.18em; }.brand-console-copy h2 { margin:10px 0 8px; font:700 29px "Songti SC","Noto Serif SC",serif; }.brand-console-copy>p { max-width:670px; margin:0; color:#a9c7c3; font-size:11px; line-height:1.75; }
.brand-console-meta { display:flex; flex-wrap:wrap; gap:8px; margin-top:24px; }.brand-console-meta span { max-width:360px; overflow:hidden; padding:8px 10px; border:1px solid rgba(124,231,202,.16); border-radius:6px; color:#c5dcd8; background:rgba(255,255,255,.045); font-size:9px; text-overflow:ellipsis; white-space:nowrap; }.brand-console-meta b { margin-right:7px; color:#69dfbf; font-size:8px; }
.brand-console-signal { display:grid; justify-items:start; padding:20px 0 20px 26px; border-left:1px solid rgba(141,225,204,.18); }.signal-orbit { position:relative; width:48px; height:48px; display:grid; place-items:center; margin-bottom:12px; border:1px solid rgba(109,235,200,.48); border-radius:50%; box-shadow:0 0 0 8px rgba(58,207,166,.05),0 0 24px rgba(58,207,166,.17); }.signal-orbit:before,.signal-orbit:after { content:""; position:absolute; left:50%; top:50%; background:rgba(133,240,211,.25); transform:translate(-50%,-50%); }.signal-orbit:before { width:1px; height:65px; }.signal-orbit:after { width:65px; height:1px; }.signal-orbit i { width:10px; height:10px; border-radius:50%; background:#6ff0cd; box-shadow:0 0 0 5px rgba(111,240,205,.12); }.brand-console-signal strong { font-size:13px; }.brand-console-signal>small { margin-top:5px; color:#85a7a3; font-size:8px; line-height:1.5; }
.competitor-chips { display:flex; flex-wrap:wrap; gap:5px; margin-top:12px; }.competitor-chips span { padding:4px 7px; border-radius:10px; color:#cbbaf0; background:rgba(121,59,215,.18); font-size:7px; }.brand-console-signal button { height:34px; margin-top:15px; padding:0 12px; border:1px solid rgba(109,235,200,.4); border-radius:7px; color:#d9faf1; background:rgba(18,175,137,.18); font-size:9px; font-weight:800; cursor:pointer; }.brand-console-signal button:hover { color:#fff; background:rgba(18,175,137,.3); }

/* Plain-language diagnosis hierarchy */
.ai-conclusion-card { display:grid; grid-template-columns:250px minmax(0,1fr); gap:30px; margin:8px 0 20px; overflow:hidden; border:1px solid #ded9e8; border-radius:20px; background:radial-gradient(circle at 0 100%,rgba(121,59,215,.09),transparent 33%),linear-gradient(120deg,#fff,#fbf9ff 58%,#f5fbf9); box-shadow:0 16px 38px rgba(54,42,76,.07); }
.conclusion-score { display:flex; flex-direction:column; align-items:center; justify-content:center; padding:24px 26px; border-right:1px solid #e8e3ee; background:rgba(255,255,255,.64); }
.conclusion-score>span { color:#7b6c93; font-size:10px; font-weight:800; letter-spacing:.08em; }.conclusion-score>strong { margin-top:9px; color:#171820; font:750 46px/1 "Iowan Old Style",Georgia,serif; letter-spacing:-.04em; }.conclusion-score>strong small { margin-left:6px; color:#8f8b98; font:600 14px "Avenir Next",sans-serif; letter-spacing:0; }
.conclusion-score>em { width:max-content; margin-top:12px; padding:5px 10px; border-radius:12px; color:#81510d; background:#fff2d9; font-size:9px; font-style:normal; font-weight:850; }.ai-conclusion-card.good .conclusion-score>em { color:#087961; background:#e7f8f2; }.ai-conclusion-card.risk .conclusion-score>em { color:#b53f3b; background:#fff0ee; }
.conclusion-score>p { margin:10px 0 0; color:#85818d; font-size:9px; line-height:1.6; text-align:center; }.conclusion-score>p b { color:#793bd7; }.conclusion-copy { padding:28px 32px 26px 0; }.conclusion-copy h2 { margin:6px 0 8px; color:#202129; font:750 22px "Songti SC","Noto Serif SC",serif; }.conclusion-copy>p { margin:0; color:#646673; font-size:11px; line-height:1.75; }.findings-label { margin:16px 0 -9px; color:#56545e; font-size:9px; font-weight:850; }
.readiness-score-gauge { position:relative; width:205px; height:172px; margin:3px 0 -8px; }.readiness-score-gauge:before { content:""; position:absolute; inset:26px 26px 5px; border-radius:50%; background:radial-gradient(circle,rgba(56,222,145,.14),rgba(93,224,157,.045) 47%,transparent 72%); filter:blur(5px); }.readiness-score-gauge svg { position:relative; z-index:1; width:100%; height:100%; overflow:visible; filter:drop-shadow(0 8px 13px rgba(19,190,129,.1)); }.readiness-score-gauge circle { fill:none; stroke-width:12; stroke-linecap:round; transform:rotate(135deg); transform-origin:120px 111px; }.readiness-track { stroke:#e4ebe8; stroke-dasharray:367 490; }.readiness-progress { stroke:url(#readiness-score-gradient); }.readiness-score-gauge>div { position:absolute; z-index:2; left:0; right:0; top:70px; display:flex; align-items:baseline; justify-content:center; }.readiness-score-gauge strong { color:#171820; font:750 43px/1 "Iowan Old Style",Georgia,serif; letter-spacing:-.045em; }.readiness-score-gauge small { margin-left:3px; color:#55565e; font-size:11px; font-weight:650; }
.ai-risk-note { display:grid; grid-template-columns:auto minmax(0,1fr); gap:10px; align-items:start; margin-top:13px; padding:10px 12px; border:1px solid #f0d8d5; border-radius:10px; background:linear-gradient(105deg,#fff4f2,#fffafa); }.ai-risk-note>span { margin-top:1px; padding:3px 6px; border-radius:8px; color:#fff; background:#d9564d; font-size:7px; font-weight:850; white-space:nowrap; }.ai-risk-note>p { margin:0; color:#784f4c; font-size:9px; line-height:1.65; }
.conclusion-findings { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:9px; margin-top:18px; }.conclusion-findings article { min-width:0; padding:12px 13px; border:1px solid #f0dfdc; border-radius:11px; background:#fff8f7; }.conclusion-findings article.medium,.conclusion-findings article.low { border-color:#f0e4c9; background:#fffaf0; }.conclusion-findings article.passed { grid-column:1/-1; border-color:#d7ebe5; background:#f3fbf8; }
.conclusion-findings span,.conclusion-findings strong,.conclusion-findings small { display:block; }.conclusion-findings span { color:#c54b43; font-size:7px; font-weight:850; letter-spacing:.06em; }.conclusion-findings article.medium span,.conclusion-findings article.low span { color:#a66a13; }.conclusion-findings article.passed span { color:#087961; }.conclusion-findings strong { margin-top:6px; color:#393a42; font-size:10px; line-height:1.45; }.conclusion-findings small { display:-webkit-box; margin-top:4px; overflow:hidden; color:#85838b; font-size:8px; line-height:1.55; -webkit-box-orient:vertical; -webkit-line-clamp:2; }
.authority-proof { display:grid; grid-template-columns:auto minmax(300px,1fr); gap:13px 24px; align-items:center; margin-top:17px; padding:17px 20px; border:1px solid rgba(121,59,215,.16); border-radius:13px; background:linear-gradient(105deg,rgba(247,243,253,.92),rgba(255,255,255,.94) 48%,rgba(237,249,245,.84)); box-shadow:inset 3px 0 0 rgba(121,59,215,.72); }
.authority-proof-brand { display:flex; align-items:center; gap:12px; min-width:236px; }.authority-proof-brand div { display:grid; gap:3px; }.authority-proof-brand small { color:#8064aa; font-size:9px; font-weight:850; letter-spacing:.12em; }.authority-proof-brand strong { color:#292631; font-size:14px; line-height:1.35; white-space:nowrap; }
.authority-seal { width:58px; height:58px; flex:none; display:block; margin:-5px 0 -5px -5px; object-fit:contain; filter:drop-shadow(0 8px 13px rgba(105,49,190,.2)); }
.authority-proof>p { margin:0; color:#5f5b67; font-size:11px; line-height:1.72; }.authority-credentials { grid-column:1/-1; display:flex; flex-wrap:wrap; gap:10px 18px; padding-top:11px; border-top:1px solid rgba(121,59,215,.09); }.authority-credentials span { display:inline-flex; align-items:center; gap:7px; color:#66606f; font-size:10px; font-weight:750; }.authority-credentials i { width:17px; height:17px; display:grid; place-items:center; border-radius:50%; color:#fff; background:#10aa86; font-size:9px; font-style:normal; }
.foundation-stats { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:20px; }.foundation-stats article { min-height:90px; padding:14px; border:1px solid #e4ece9; border-radius:14px; background:linear-gradient(145deg,#f7fcfa,#fff); }.foundation-stats article.risk { grid-column:1/-1; min-height:82px; border-color:#f1ddda; background:linear-gradient(145deg,#fff8f7,#fff); }.foundation-stats span,.foundation-stats strong,.foundation-stats small { display:block; }.foundation-stats span { color:#777b81; font-size:8px; font-weight:800; }.foundation-stats strong { margin-top:6px; color:#0a9875; font:750 28px/1 "Iowan Old Style",Georgia,serif; }.foundation-stats small { margin-top:6px; color:#9a9ca1; font-size:7px; }.foundation-stats article.pending strong { color:#bd7b18; }.foundation-stats article.risk strong { color:#d34f48; }.foundation-summary { margin-top:13px; }.foundation-summary>div { height:6px; overflow:hidden; border-radius:4px; background:#edf1ef; }.foundation-summary>div i { display:block; height:100%; border-radius:inherit; background:linear-gradient(90deg,#14bc87,#12aa93); }.foundation-summary p { margin:9px 0 0; color:#7b7e84; font-size:8px; line-height:1.6; }.foundation-summary p b { color:#0b9976; }
.rule-technical-note { color:#999fa0 !important; }.geo-explainer { max-width:560px; margin:7px 0 0; color:#74727e; font-size:9px; line-height:1.55; }.geo-explainer b { color:#6e48b0; }
.check-grid { gap:10px; padding:10px; }.check-grid article { min-height:305px; grid-template-columns:27px minmax(0,1fr) auto; gap:9px; padding:15px 14px; }.check-grid small { font-size:9px; }.check-grid h3 { margin:5px 0 7px; font-size:14px; line-height:1.4; }.evidence-toggle { font-size:10px; }.plain-rule-explanation { display:grid; gap:8px; margin-top:10px; }.plain-rule-explanation p { display:grid; grid-template-columns:70px minmax(0,1fr); gap:8px; color:#62646e; font-size:11px; line-height:1.62; }.plain-rule-explanation p>b { color:#4d4e57; font:800 9px "Avenir Next",sans-serif; }.plain-rule-explanation p:nth-child(2) { padding:9px 10px; border-radius:7px; background:#f8f6fb; }.plain-rule-explanation p:nth-child(2)>b { color:#793bd7; }.plain-rule-explanation p:nth-child(3) { padding:9px 10px; border-radius:7px; background:#fff4f2; }.plain-rule-explanation p:nth-child(3)>b { color:#c34840; }.plain-rule-explanation p:nth-child(4)>b { color:#0b8f70; }
.technical-evidence { margin-top:11px; padding-top:10px; border-top:1px solid #efedf1; }.technical-evidence summary { width:max-content; color:#7f7c88; font-size:9px; cursor:pointer; }.technical-evidence p { display:grid; grid-template-columns:62px 1fr; gap:8px; margin-top:8px; color:#7e7c85; font-size:10px; line-height:1.55; }.technical-evidence p>b { color:#5f5d67; font:800 8px "Avenir Next",sans-serif; }
.impact-badge { height:24px; display:inline-flex; align-items:center; padding:0 9px; border-radius:12px; color:#b33f3a; background:#fff0ee; font-size:9px; font-weight:850; white-space:nowrap; }.impact-badge.medium { color:#a7670b; background:#fff3df; }.impact-badge.low { color:#627378; background:#edf4f3; }.impact-badge.passed { color:#087961; background:#e7f8f2; }
.sample-result-copy h3>small { display:block; margin-bottom:4px; color:#8c7baa; font-size:7px; letter-spacing:.08em; }.sample-result-copy>p>b { display:block; margin-bottom:4px; color:#4e5260; font-size:7px; }
.issue-card-list { display:grid; grid-template-columns:1fr 1fr; gap:12px; padding:18px; }.issue-card-list>article { position:relative; min-width:0; padding:18px; overflow:hidden; border:1px solid #ece3e1; border-radius:14px; background:linear-gradient(145deg,#fff,#fffafa); }.issue-card-list>article:before { content:""; position:absolute; left:0; top:0; bottom:0; width:3px; background:#e35c53; }.issue-card-list>article.medium:before { background:#e7a23d; }.issue-card-list>article.low:before { background:#8ba5a2; }
.issue-card-list header { display:flex; align-items:center; justify-content:space-between; gap:12px; }.issue-card-list header>div { display:flex; gap:5px; }.issue-card-list header>small { color:#bf5149; font-size:8px; font-weight:800; }.issue-card-list h3 { margin:13px 0; color:#2b2c34; font-size:14px; }.issue-card-list dl,.issue-card-list dd { margin:0; }.issue-card-list dl { display:grid; gap:8px; }.issue-card-list dl>div { display:grid; grid-template-columns:72px minmax(0,1fr); gap:8px; }.issue-card-list dt { color:#72707a; font-size:8px; font-weight:850; }.issue-card-list dd { color:#65666f; font-size:9px; line-height:1.6; }
.issue-card-list details { margin-top:13px; padding-top:10px; border-top:1px solid #eee9eb; }.issue-card-list summary { color:#7a50ba; font-size:8px; font-weight:750; cursor:pointer; }.issue-card-list details p { margin:8px 0 0; color:#8a8990; font-size:8px; line-height:1.6; }.issue-card-list details p b { display:block; margin-bottom:3px; color:#5f5e66; }.issue-card-list>.empty-row { grid-column:1/-1; margin:0; }
.priority-direction-list { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; padding:18px; }.priority-direction-list article { position:relative; min-height:130px; padding:18px 18px 16px 54px; border:1px solid #e5e0eb; border-radius:14px; background:linear-gradient(145deg,#fff,#fbf9ff); }.priority-direction-list article>span { position:absolute; left:17px; top:18px; width:27px; height:27px; display:grid; place-items:center; border-radius:50%; color:#fff; background:linear-gradient(135deg,#793bd7,#a060e6); font:800 8px "SFMono-Regular",monospace; }.priority-direction-list h3 { margin:1px 0 8px; color:#303139; font-size:12px; }.priority-direction-list p { margin:0; color:#71717a; font-size:9px; line-height:1.65; }.priority-direction-list small { display:block; margin-top:10px; color:#9a7ac5; font-size:8px; font-weight:750; }
.priority-clean-state { padding:25px; text-align:center; }.priority-clean-state strong { color:#087961; font-size:13px; }.priority-clean-state p { margin:6px 0 0; color:#81828a; font-size:9px; }.full-plan-cta { display:flex; align-items:center; justify-content:space-between; gap:24px; margin:0 18px 18px; padding:16px 18px; border-radius:13px; color:#fff; background:linear-gradient(105deg,#312348,#553088 58%,#137d72); box-shadow:0 12px 26px rgba(64,39,101,.15); }.full-plan-cta strong,.full-plan-cta p { display:block; margin:0; }.full-plan-cta strong { font-size:11px; }.full-plan-cta p { margin-top:4px; color:#cfc6dd; font-size:8px; }.full-plan-cta a { flex:none; padding:10px 15px; border-radius:18px; color:#fff; background:linear-gradient(100deg,#8d48df,#16b189); font-size:9px; font-weight:850; text-decoration:none; box-shadow:0 7px 18px rgba(32,16,54,.2); }

@media (max-width: 1050px) {
  .diagnosis-center { grid-template-columns:190px minmax(0,1fr); }
  .scan-panel { grid-template-columns:1fr; gap:26px; }
  .summary-grid { grid-template-columns:1fr 1fr; }
  .capability-body { grid-template-columns:270px 1fr; }
  .dimension-list { grid-template-columns:1fr; }
  .action-grid { grid-template-columns:1fr 1fr; }
  .sample-results { grid-template-columns:1fr; }
  .site-page-grid { grid-template-columns:1fr; }
  .check-grid { grid-template-columns:1fr 1fr; }
  .diagnosis-highlights { grid-template-columns:1fr; }
  .flow-map { grid-template-columns:1fr 1fr; }
  .flow-map.compact { grid-template-columns:1fr 1fr; }
  .flow-map:before { display:none; }
  .quick-audit-bar>footer { flex-wrap:wrap; }
  .quick-profile-context { grid-template-columns:minmax(220px,1fr) auto; }
  .quick-profile-metrics { grid-column:1/-1; grid-row:2; }
  .brand-intelligence-panel { grid-template-columns:1fr; }
  .brand-console-signal { padding:19px 0 0; border-top:1px solid rgba(141,225,204,.18); border-left:0; }
  .ai-conclusion-card { grid-template-columns:210px minmax(0,1fr); gap:22px; }.conclusion-score { padding:24px; }.conclusion-copy { padding:24px 24px 24px 0; }.conclusion-findings { grid-template-columns:1fr; }.conclusion-findings article.passed { grid-column:auto; }
  .priority-direction-list { grid-template-columns:1fr; }
  .overview-dashboard { grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }
  .dashboard-card { padding:18px; border-radius:18px; }
  .dashboard-card>header h3 { font-size:12px; }
  .dashboard-card>header small { font-size:7px; }
  .health-dashboard-card,.radar-dashboard-card,.metrics-dashboard-card { min-height:300px; }
  .health-gauge { width:205px; height:205px; margin:2px auto -10px; }
  .health-gauge svg { height:195px; }
  .health-gauge circle { stroke-width:10; }
  .health-gauge>div { top:60px; }
  .health-gauge strong { font-size:41px; }
  .health-gauge>p { top:110px; font-size:8px; }
  .health-gauge>p small { font-size:7px; }
  .health-dashboard-card>footer { min-width:132px; padding:7px 12px; font-size:8px; }
  .health-dashboard-card>footer b { font-size:11px; }
  .dashboard-radar { width:215px; height:215px; }
  .dashboard-radar svg { width:190px; height:190px; margin:12px; }
  .dashboard-radar-label { font-size:7px; }
  .radar-position-1{top:2px;left:86px}.radar-position-2{top:54px;right:-5px}.radar-position-3{bottom:53px;right:-8px}.radar-position-4{bottom:2px;left:82px}.radar-position-5{bottom:53px;left:-7px}.radar-position-6{top:54px;left:-6px}
  .radar-dashboard-card>footer { gap:12px; font-size:7px; }
  .dashboard-metrics { gap:8px; margin-top:14px; }
  .dashboard-metrics section { min-height:88px; padding:12px; border-radius:13px; }
  .dashboard-metrics span { font-size:8px; }
  .dashboard-metrics strong { font-size:23px; }
  .dashboard-metrics section>i { right:10px; top:38px; font-size:17px; }
  .dashboard-metrics section>b { font-size:7px; }
  .metrics-dashboard-card,.recent-dashboard-card { grid-column:auto; }
  .signals-dashboard-card,.dashboard-cta.primary,.suggestions-dashboard-card { grid-column:1/-1; }
  .dashboard-suggestions { grid-template-columns:1fr 1fr; }
}
@media (max-width: 760px) {
  .diagnosis-center { display:block; }
  .diagnosis-sidebar { position:relative; width:100%; height:auto; display:block; padding:13px; }
  .diagnosis-brand { padding-bottom:12px; }
  .nav-label,.asset-label,.sidebar-spacer,.module-link,.sidebar-bottom { display:none; }
  .sidebar-item { width:auto; display:inline-flex; margin-right:4px; padding:0 9px; }
  .diagnosis-topbar { padding:17px 18px; }
  .diagnosis-topbar p,.topbar-kicker,.topbar-actions button { display:none; }
  .diagnosis-content { padding:18px 14px 55px; }
  .quick-audit-bar { padding:15px; }
  .quick-audit-bar>header,.quick-audit-bar>footer { align-items:flex-start; flex-direction:column; }
  .quick-mode-switch { width:100%; box-sizing:border-box; }
  .quick-mode-switch button { flex:1; }
  .quick-audit-form { grid-template-columns:24px minmax(0,1fr); }
  .quick-audit-form>button { grid-column:1/-1; width:100%; }
  .quick-scope-switch { flex-wrap:wrap; }
  .quick-audit-bar>footer p { margin:0; }
  .quick-profile-context,.quick-profile-context.empty { grid-template-columns:1fr; gap:11px; }
  .quick-profile-metrics { grid-column:auto; grid-row:auto; grid-template-columns:1fr 1fr; }
  .quick-profile-actions { width:100%; justify-self:stretch; }
  .quick-profile-actions button { width:100%; }
  .quick-profile-detail { grid-template-columns:1fr; }
  .quick-profile-detail>section.wide,.quick-profile-detail>footer { grid-column:auto; }
  .asset-hero { min-height:160px; align-items:flex-start; flex-direction:column; padding:25px 22px; }
  .asset-field-grid { grid-template-columns:1fr; }
  .asset-empty-panel { grid-template-columns:48px 1fr; padding:24px 20px; }
  .asset-empty-mark { width:48px; height:48px; }
  .asset-empty-panel button { grid-column:1/-1; width:100%; }
  .scan-panel { padding:28px 20px; border-radius:12px; }
  .url-input-wrap { grid-template-columns:minmax(0,1fr); height:auto; padding:5px; }
  .url-input-wrap input { height:45px; padding:0 9px; }
  .url-input-wrap button { width:100%; }
  .preflight-grid,.summary-grid,.check-grid,.action-grid { grid-template-columns:1fr; }
  .loading-report { grid-template-columns:80px 1fr; padding:24px 18px; }
  .stage-track { grid-column:1/-1; }
  .report-meta { display:block; }
  .report-meta>div { flex-wrap:wrap; }
  .report-meta>span { display:block; margin-top:7px; }
  .insight-panel { grid-template-columns:45px 1fr; }
  .priority-note { grid-column:1/-1; padding:15px 0 0; border-top:1px solid #d8e9e6; border-left:0; }
  .capability-heading { align-items:stretch; flex-direction:column; }
  .decomposition-score { width:100%; box-sizing:border-box; }
  .capability-body { grid-template-columns:1fr; }
  .radar-wrap { min-height:280px; border-right:0; border-bottom:1px solid var(--line); }
  .dimension-list { grid-template-columns:1fr; padding:18px; }
  .panel-heading { align-items:flex-start; }
  .panel-heading>p { display:none; }
  .action-empty { align-items:flex-start; flex-direction:column; }
  .sample-heading,.sample-composer { grid-template-columns:1fr; align-items:flex-start; }
  .sample-heading { flex-direction:column; }
  .model-access-bar { grid-template-columns:1fr; }.model-access-grid { grid-template-columns:1fr; }
  .member-model-preview>header { flex-direction:column; }.member-preview-grid { grid-template-columns:1fr; }
  .sample-composer>button { width:100%; }
  .sample-metrics { grid-template-columns:1fr; }
  .sample-metrics article { border-right:0; border-bottom:1px solid #e8e4f0; }
  .sample-method { grid-template-columns:1fr; }
  .site-coverage-heading { align-items:flex-start; flex-direction:column; }
  .site-coverage-heading p { text-align:left; }
  .site-coverage-meta { flex-wrap:wrap; gap:8px 16px; }
  .flow-map { grid-template-columns:1fr; }
  .flow-map.compact { grid-template-columns:1fr; }
  .flow-map a { min-height:58px; }
  .flow-stage-heading { align-items:flex-start; padding-top:15px; }
  .brand-intelligence-panel { padding:28px 22px; }
  .brand-console-meta { display:grid; width:100%; }
  .ai-conclusion-card { grid-template-columns:1fr; gap:0; }.conclusion-score { border-right:0; border-bottom:1px solid #e8e3ee; }.conclusion-copy { padding:24px; }.conclusion-findings { grid-template-columns:1fr; }
  .authority-proof { grid-template-columns:1fr; }.authority-proof>p { font-size:9px; }.authority-credentials { grid-column:auto; }
  .issue-card-list { grid-template-columns:1fr; padding:12px; }.full-plan-cta { align-items:flex-start; flex-direction:column; }.full-plan-cta a { width:100%; box-sizing:border-box; text-align:center; }
  .overview-dashboard { grid-template-columns:1fr; }
  .score-rules-help { position:static; }
  .score-rules-popover { position:fixed; top:72px; right:14px; bottom:18px; left:14px; width:auto; max-height:none; overflow:hidden; padding:17px; }
  .score-rule-list { max-height:calc(100vh - 245px); grid-template-columns:1fr; }
  .score-rules-popover>footer { align-items:flex-start; flex-wrap:wrap; }
  .score-rules-popover>footer span { width:100%; margin:3px 0 0 13px; }
  .signals-dashboard-card,.dashboard-cta.primary,.suggestions-dashboard-card { grid-column:auto; }
  .signal-chart,.dashboard-suggestions { grid-template-columns:1fr; }
  .dashboard-cta { grid-template-columns:34px minmax(0,1fr); }
  .dashboard-cta>b { grid-column:1/-1; text-align:center; }
}

/* Readability pass: keep the editorial layout while raising the type scale. */
.diagnosis-brand strong { font-size:19px; }
.diagnosis-brand small { font-size:11px; }
.nav-label { font-size:11px; }
.sidebar-item { font-size:14px; }
.diagnosis-topbar h1 { font-size:29px; }
.topbar-kicker,.section-index,.flow-stage-heading b { font-size:10px; }
.flow-map span { font-size:12px; }
.flow-map small,.flow-stage-heading p { font-size:10px; }
.dashboard-card>header h3 { font-size:17px; }
.dashboard-card>header small,.health-dashboard-card>p,.radar-dashboard-card>footer { font-size:11px; }
.dashboard-metrics span,.signal-chart span { font-size:11px; }
.dashboard-metrics section>b,.recent-diagnostics p strong,.dashboard-cta p strong { font-size:10px; }
.recent-diagnostics p small,.dashboard-cta p small,.dashboard-suggestions p small { font-size:9px; }
.diagnosis-highlights header span,.diagnosis-highlights header b { font-size:10px; }
.diagnosis-highlights h3 { font-size:16px; }
.diagnosis-highlights p,.diagnosis-highlights>a,.diagnosis-highlights article>a { font-size:11px; }
.brand-console-copy>p { font-size:13px; }
.brand-console-meta span,.brand-console-signal button { font-size:11px; }
.brand-console-meta b,.brand-console-signal>small,.competitor-chips span { font-size:10px; }
.conclusion-copy h2 { font-size:25px; }
.conclusion-copy>p { font-size:13px; }
.conclusion-findings strong { font-size:12px; }
.conclusion-findings small,.foundation-summary p,.geo-explainer { font-size:10px; }
.foundation-stats span,.foundation-stats small { font-size:10px; }
.issue-card-list header>small,.issue-card-list dt,.issue-card-list summary,.issue-card-list details p { font-size:10px; }
.issue-card-list h3 { font-size:16px; }
.suggestions-dashboard-card { padding-bottom:18px; }
.dashboard-suggestions>a { min-height:72px; grid-template-columns:28px minmax(0,1fr) auto; gap:11px; padding:13px 14px; box-sizing:border-box; }
.dashboard-suggestions>a>i { width:24px; height:24px; font-size:10px; }
.dashboard-suggestions p strong { font-size:12px; line-height:1.35; }
.dashboard-suggestions p small { margin-top:5px; font-size:10px; line-height:1.45; -webkit-line-clamp:2; }
.dashboard-suggestions>a>b { padding:6px 9px; border-radius:12px; font-size:9px; }
.issue-card-list dd,.priority-direction-list p { font-size:11px; }
.priority-direction-list h3 { font-size:14px; }
.priority-direction-list small,.full-plan-cta p,.full-plan-cta a { font-size:10px; }
.full-plan-cta strong { font-size:13px; }

/* SEO free-diagnosis prototype: an executive health report, not a webmaster console. */
.seo-report-prototype { position:relative; background:linear-gradient(180deg,#fff 0,#fdfcfe 100%); }
.seo-report-heading { min-height:92px; padding:20px 25px; background:radial-gradient(circle at 88% 0,rgba(24,178,135,.08),transparent 28%),linear-gradient(105deg,#fff,#fbf9fe); }
.seo-report-heading>div p { margin:7px 0 0; color:#747580; font-size:12px; }.seo-report-heading h2 { font-size:24px; }
.prototype-badge { display:inline-flex; align-items:center; gap:7px; padding:7px 11px; border:1px solid #ded4eb; border-radius:16px; color:#7651a9; background:rgba(255,255,255,.86); font-size:9px; font-weight:800; letter-spacing:.03em; }.prototype-badge i { width:6px; height:6px; border-radius:50%; background:#8a4add; box-shadow:0 0 0 4px rgba(138,74,221,.09); }
.seo-health-overview { position:relative; min-height:350px; display:grid; grid-template-columns:220px minmax(300px,1fr) minmax(420px,1.18fr); align-items:stretch; margin:22px; overflow:hidden; border:1px solid #e2dbea; border-radius:22px; background:radial-gradient(circle at 84% 8%,rgba(16,173,133,.09),transparent 27%),linear-gradient(122deg,#faf7fe 0,#fff 46%,#f7fcfa 100%); box-shadow:0 20px 48px rgba(66,46,91,.075); }.seo-health-overview:before { content:""; position:absolute; right:-74px; top:-114px; width:290px; height:290px; border:1px solid rgba(121,59,215,.08); border-radius:50%; box-shadow:0 0 0 42px rgba(16,170,134,.018),0 0 0 92px rgba(121,59,215,.014); pointer-events:none; }
.seo-score-column { position:relative; z-index:1; display:flex; flex-direction:column; align-items:center; justify-content:center; padding:25px 14px; border-right:1px solid rgba(121,59,215,.1); }.seo-score-column>span { color:#8063a9; font-size:9px; font-weight:850; letter-spacing:.16em; }.seo-score-column>em { margin-top:-12px; padding:6px 13px; border-radius:14px; color:#8e650e; background:#fff3d7; font-size:10px; font-style:normal; font-weight:850; }
.seo-score-gauge { position:relative; width:200px; height:190px; margin-top:1px; }.seo-score-gauge svg { width:100%; height:100%; overflow:visible; filter:drop-shadow(0 10px 17px rgba(23,186,127,.12)); }.seo-score-gauge circle { fill:none; stroke-width:13; stroke-linecap:round; transform:rotate(135deg); transform-origin:110px 98px; }.seo-score-track { stroke:#e4ebe9; stroke-dasharray:275.25 367; }.seo-score-progress { stroke:url(#seo-score-gradient); }.seo-score-gauge>div { position:absolute; inset:0; display:flex; align-items:baseline; justify-content:center; padding-top:72px; box-sizing:border-box; }.seo-score-gauge strong { color:#181923; font:750 48px/1 "Iowan Old Style",Georgia,serif; letter-spacing:-.04em; }.seo-score-gauge small { margin-left:3px; color:#575763; font-size:13px; font-weight:700; }
.seo-overview-copy { position:relative; z-index:1; display:flex; flex-direction:column; justify-content:center; padding:36px 34px; }.seo-overview-kicker { color:#0b9775; font-size:9px; font-weight:900; letter-spacing:.16em; }.seo-overview-copy h3 { margin:13px 0 15px; color:#272832; font-family:"Songti SC","Noto Serif SC",serif; font-size:22px; line-height:1.5; }.seo-overview-copy h3 b { color:#7041b3; font-weight:700; }.seo-overview-copy>p { max-width:570px; margin:0; color:#676873; font-size:12px; line-height:1.82; }.seo-overview-status { display:flex; flex-wrap:wrap; gap:7px; margin-top:21px; }.seo-overview-status span { display:inline-flex; align-items:center; gap:6px; padding:6px 9px; border-radius:13px; color:#137a64; background:#eaf8f3; font-size:9px; font-weight:750; }.seo-overview-status span.attention { color:#96670e; background:#fff4dc; }.seo-overview-status i { width:5px; height:5px; border-radius:50%; background:#17b889; }.seo-overview-status .attention i { background:#dc9b21; }
.seo-fact-grid { position:relative; z-index:1; display:grid; grid-template-columns:1fr 1fr; gap:1px; align-self:center; margin:26px 25px 26px 0; overflow:hidden; border:1px solid #e5e2e8; border-radius:17px; background:#e8e5eb; box-shadow:0 11px 27px rgba(43,35,54,.045); }.seo-fact-grid article { min-height:91px; display:flex; flex-direction:column; justify-content:center; padding:14px 17px; background:rgba(255,255,255,.93); }.seo-fact-grid article.risk { background:linear-gradient(145deg,#fff,#fff7f4); }.seo-fact-grid span { color:#85848d; font-size:9px; }.seo-fact-grid strong { margin-top:5px; color:#282931; font:720 25px/1 "Iowan Old Style",Georgia,serif; }.seo-fact-grid strong small { margin-left:2px; color:#62636d; font:650 10px "Avenir Next",sans-serif; }.seo-fact-grid b { margin-top:6px; color:#aaa8af; font-size:8px; font-weight:650; }.seo-fact-grid .risk strong,.seo-fact-grid .risk b { color:#d2584f; }
.seo-core-section,.seo-priority-section { margin:0 22px 22px; }.seo-subheading { display:flex; align-items:flex-end; justify-content:space-between; gap:22px; padding:4px 2px 13px; }.seo-subheading span { color:#7350a5; font-size:8px; font-weight:900; letter-spacing:.18em; }.seo-subheading h3 { margin:5px 0 0; color:#292a32; font-family:"Songti SC","Noto Serif SC",serif; font-size:19px; }.seo-subheading>p { max-width:420px; margin:0; color:#888791; font-size:10px; text-align:right; }
.seo-core-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; }.seo-core-grid article { position:relative; min-height:176px; padding:20px; overflow:hidden; border:1px solid #e5e2e9; border-radius:17px; background:#fff; box-shadow:0 11px 28px rgba(49,39,61,.045); transition:transform .2s,border-color .2s,box-shadow .2s; }.seo-core-grid article:hover { z-index:2; transform:translateY(-3px); border-color:#d4c6e7; box-shadow:0 18px 34px rgba(57,40,78,.09); }.seo-core-grid article:before { content:""; position:absolute; inset:0; background:radial-gradient(circle at 100% 0,rgba(121,59,215,.08),transparent 36%); pointer-events:none; }.seo-core-grid article.index:before,.seo-core-grid article.technical:before { background:radial-gradient(circle at 100% 0,rgba(16,170,134,.11),transparent 36%); }.seo-core-grid article.risk:before { background:radial-gradient(circle at 100% 0,rgba(223,89,78,.09),transparent 38%); }.seo-metric-icon { position:absolute; right:18px; top:17px; width:31px; height:31px; display:grid; place-items:center; border-radius:10px; color:#7747b8; background:#f0e8fa; font-size:14px; font-weight:850; }.seo-core-grid .index .seo-metric-icon,.seo-core-grid .technical .seo-metric-icon { color:#078d6e; background:#e5f7f1; }.seo-core-grid .risk .seo-metric-icon { color:#c55149; background:#fff0ed; }.seo-core-grid article>span { color:#73747d; font-size:10px; font-weight:750; }.seo-core-grid article>strong { display:block; margin-top:15px; color:#25262e; font:730 31px/1 "Iowan Old Style",Georgia,serif; }.seo-core-grid article>strong small { margin-left:4px; color:#85858d; font:650 10px "Avenir Next",sans-serif; }.seo-core-grid article>p { min-height:32px; margin:11px 0 16px; color:#8b8a92; font-size:9px; line-height:1.55; }.seo-core-grid article>i { display:block; height:5px; overflow:hidden; border-radius:4px; background:#eeeef0; }.seo-core-grid article>i b { display:block; height:100%; border-radius:inherit; background:linear-gradient(90deg,#783ed4,#11aa83); }.seo-core-grid article.risk>i b { background:linear-gradient(90deg,#f5a14d,#e65b50); }
.seo-analysis-grid { display:grid; grid-template-columns:1fr 1fr; gap:14px; margin:0 22px 25px; }.seo-insight-card { position:relative; min-height:318px; padding:23px; overflow:hidden; border:1px solid #e4e0e9; border-radius:19px; background:#fff; box-shadow:0 13px 30px rgba(51,40,64,.045); }.seo-insight-card:after { content:""; position:absolute; right:-70px; bottom:-90px; width:210px; height:210px; border:1px solid rgba(121,59,215,.07); border-radius:50%; box-shadow:0 0 0 35px rgba(16,170,134,.018); pointer-events:none; }.seo-insight-card>header { position:relative; z-index:1; display:flex; align-items:flex-start; justify-content:space-between; gap:18px; }.seo-insight-card header span { color:#7c5aac; font-size:8px; font-weight:900; letter-spacing:.16em; }.seo-insight-card header h3 { margin:6px 0 0; color:#292a32; font-family:"Songti SC","Noto Serif SC",serif; font-size:18px; }.seo-insight-card header>b { padding:6px 9px; border-radius:13px; color:#b06f0a; background:#fff1d8; font-size:8px; }.keyword-opportunity header>b { color:#147b66; background:#e8f8f2; }
.seo-insight-visual { position:relative; z-index:1; height:46px; display:flex; align-items:flex-end; gap:5px; margin:24px 0 18px; padding:0 72px 0 2px; border-bottom:1px solid #ece8f0; }.seo-insight-visual i { flex:1; border-radius:4px 4px 0 0; background:linear-gradient(180deg,#a259df,#7740bd); }.seo-insight-visual i:nth-child(1){height:21%}.seo-insight-visual i:nth-child(2){height:34%}.seo-insight-visual i:nth-child(3){height:48%}.seo-insight-visual i:nth-child(4){height:66%}.seo-insight-visual i:nth-child(5){height:84%}.seo-insight-visual i:nth-child(6){height:100%;background:linear-gradient(180deg,#17bd8c,#0a9273)}.seo-insight-visual span { position:absolute; right:0; bottom:8px; color:#272832; font:720 23px/1 "Iowan Old Style",Georgia,serif; }
.keyword-balance { position:relative; z-index:1; display:grid; grid-template-columns:1fr; gap:7px; margin:23px 0 19px; }.keyword-balance>span { display:flex; justify-content:space-between; color:#70717a; font-size:9px; }.keyword-balance>span b { color:#4e4f58; }.keyword-balance>i { height:7px; overflow:hidden; margin-bottom:6px; border-radius:4px; background:#edf0ef; }.keyword-balance>i>b { display:block; height:100%; border-radius:inherit; background:linear-gradient(90deg,#7940d1,#a35edf); }.keyword-balance>i:nth-of-type(2)>b { background:linear-gradient(90deg,#0ba981,#55d897); }
.seo-insight-card dl,.seo-insight-card dd { margin:0; }.seo-insight-card dl { position:relative; z-index:1; display:grid; gap:8px; }.seo-insight-card dl>div { display:grid; grid-template-columns:70px minmax(0,1fr); gap:11px; padding:9px 10px; border-radius:9px; background:#faf9fb; }.seo-insight-card dl>div.risk { background:#fff5f2; }.seo-insight-card dl>div.advice { background:#eef9f5; }.seo-insight-card dt { color:#777780; font-size:8px; font-weight:850; }.seo-insight-card dd { color:#555761; font-size:10px; line-height:1.58; }.seo-insight-card .risk dt { color:#c6554c; }.seo-insight-card .advice dt { color:#078d6e; }
.seo-priority-section { padding:21px; border:1px solid #dfd7ea; border-radius:19px; background:radial-gradient(circle at 92% 0,rgba(20,177,135,.12),transparent 29%),linear-gradient(112deg,#f8f4fd,#fff 52%,#f2faf7); }.seo-priority-section .seo-subheading { padding:0 1px 16px; }.seo-priority-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }.seo-priority-grid article { position:relative; min-height:118px; display:grid; grid-template-columns:39px minmax(0,1fr); gap:13px; padding:17px 50px 17px 16px; border:1px solid rgba(121,59,215,.12); border-radius:14px; background:rgba(255,255,255,.86); box-shadow:0 9px 21px rgba(54,39,73,.035); }.seo-priority-grid article>span { width:36px; height:36px; display:grid; place-items:center; border-radius:11px; color:#fff; background:linear-gradient(145deg,#793bd7,#9b56dc); font:850 9px "SFMono-Regular",monospace; box-shadow:0 7px 14px rgba(121,59,215,.18); }.seo-priority-grid article:nth-child(2)>span { background:linear-gradient(145deg,#0a9e7c,#25c398); box-shadow:0 7px 14px rgba(10,158,124,.17); }.seo-priority-grid article:nth-child(3)>span { background:linear-gradient(145deg,#4e5f74,#71899b); box-shadow:0 7px 14px rgba(78,95,116,.14); }.seo-priority-grid small { color:#8e76af; font-size:7px; font-weight:850; letter-spacing:.08em; }.seo-priority-grid h3 { margin:5px 0 7px; color:#303139; font-size:12px; }.seo-priority-grid p { margin:0; color:#797984; font-size:9px; line-height:1.6; }.seo-priority-grid article>b { position:absolute; right:13px; top:16px; padding:4px 7px; border-radius:9px; color:#7650aa; background:#f0e9f8; font-size:7px; }
.seo-technical-details { margin:0 22px 22px; border:1px solid #e5e1e9; border-radius:15px; background:#fff; }.seo-technical-details>summary { min-height:64px; display:grid; grid-template-columns:minmax(0,1fr) auto; align-items:center; gap:4px 20px; padding:0 18px; list-style:none; cursor:pointer; }.seo-technical-details>summary::-webkit-details-marker { display:none; }.seo-technical-details>summary span { color:#3d3e46; font-size:11px; font-weight:800; }.seo-technical-details>summary small { grid-column:1; color:#94929a; font-size:8px; }.seo-technical-details>summary b { grid-column:2; grid-row:1/3; color:#744cad; font-size:9px; }.seo-technical-details[open]>summary { border-bottom:1px solid #e8e5eb; }.seo-technical-details[open]>summary b { font-size:0; }.seo-technical-details[open]>summary b:after { content:"收起 ↑"; font-size:9px; }

/* Search visibility report: SEO is one layer of the wider AI-search capability. */
.seo-health-overview { min-height:392px; grid-template-columns:220px minmax(350px,1.05fr) minmax(390px,1fr); }
.seo-score-column>small { margin-top:17px; color:#6e6877; font-size:11px; font-weight:800; }
.seo-parent-score { display:flex; align-items:baseline; margin:17px 0 8px; }
.seo-parent-score strong { color:#1d1e27; font:750 62px/.9 "Iowan Old Style",Georgia,serif; letter-spacing:-.055em; }
.seo-parent-score b { margin-left:5px; color:#696974; font-size:14px; }
.seo-score-column>p { max-width:164px; margin:18px 0 0; color:#8a8790; font-size:9px; line-height:1.65; text-align:center; }
.seo-score-column>em { margin-top:2px; }
.seo-capability-stack { display:grid; gap:12px; margin-top:23px; }
.seo-capability-stack>div { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:7px 14px; }
.seo-capability-stack>div>span { color:#4f5059; font-size:10px; font-weight:850; }
.seo-capability-stack>div>span small { display:block; margin-top:3px; color:#98969e; font-size:8px; font-weight:600; }
.seo-capability-stack>div>strong { color:#383943; font:750 19px/1 "Iowan Old Style",Georgia,serif; }
.seo-capability-stack>div>strong small { margin-left:2px; color:#9997a0; font:650 8px "Avenir Next",sans-serif; }
.seo-capability-stack>div>i { grid-column:1/-1; height:6px; overflow:hidden; border-radius:6px; background:#ecebed; }
.seo-capability-stack>div>i>b { display:block; height:100%; border-radius:inherit; background:linear-gradient(90deg,#0aa27d,#55d397); }
.seo-capability-stack>div:nth-child(2)>i>b { background:linear-gradient(90deg,#7441ca,#a160df); }
.seo-capability-stack>div:nth-child(3)>i>b { background:linear-gradient(90deg,#6f7891,#9ba4ba); }
.seo-fact-grid .word-value { font-size:21px; letter-spacing:.04em; }
.seo-core-grid article { min-height:230px; }
.seo-dual-metric { display:grid; grid-template-columns:1fr 1fr; gap:6px; margin:18px 0 2px; }
.seo-dual-metric>b { padding:9px; border:1px solid #e8e7ea; border-radius:9px; color:#85848d; background:rgba(250,251,251,.8); font-size:8px; }
.seo-dual-metric strong { display:block; margin-top:4px; color:#282932; font:750 18px/1 "Iowan Old Style",Georgia,serif; }
.seo-weight-traffic { display:flex; align-items:center; justify-content:space-between; margin-top:7px; padding:7px 9px; border-radius:8px; color:#777780; background:#f5f1fa; font-size:8px; }
.seo-weight-traffic b { color:#7041b3; font-size:10px; }
.seo-core-grid .weight .seo-metric-icon { color:#7442b7; background:#efe7f8; }
.seo-fact-grid article.pending { background:linear-gradient(145deg,#fff,#faf9fc); }
.seo-fact-grid article.pending .word-value { color:#8f8c97; font-family:"Avenir Next",sans-serif; font-size:17px; letter-spacing:.04em; }
.seo-mini-breakdown { display:flex; gap:5px; margin:11px 0 0; }
.seo-mini-breakdown span { flex:1; padding:5px 3px; border-radius:7px; color:#777780; background:#f6f3fa; font-size:7px; text-align:center; }
.seo-mini-breakdown b { display:block; margin-top:2px; color:#7242b5; font-size:9px; }
.seo-reference-state { display:flex; align-items:center; justify-content:space-between; margin-top:11px; padding:7px 9px; border-radius:8px; color:#85848c; background:#fff3ef; font-size:8px; }
.seo-reference-state b { color:#c7564d; font-size:10px; }
.seo-tech-tags { display:flex; flex-wrap:wrap; gap:4px; margin-top:10px; }
.seo-tech-tags span { padding:4px 6px; border-radius:7px; color:#087d63; background:#e9f8f3; font-size:7px; font-weight:750; }
.seo-core-grid article>p { min-height:42px; }
.seo-index-compare { position:relative; z-index:1; display:grid; gap:13px; margin:24px 0 18px; }
.seo-index-compare>div { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:6px 14px; }
.seo-index-compare span { color:#767680; font-size:9px; font-weight:700; }
.seo-index-compare strong { color:#2f3038; font:750 16px/1 "Iowan Old Style",Georgia,serif; }
.seo-index-compare i { grid-column:1/-1; height:7px; overflow:hidden; border-radius:6px; background:#eeedf0; }
.seo-index-compare i b { display:block; height:100%; min-width:8px; border-radius:inherit; background:linear-gradient(90deg,#7541c8,#ad67df); }
.seo-index-compare>div:nth-child(2) i b { background:linear-gradient(90deg,#0b9e7a,#4fd097); }
.seo-risk-list,.seo-opportunity-list { color:inherit; font-size:9px; font-weight:700; line-height:1.7; }

/* SEO report readability: this section is explanatory, not a dense admin console. */
.seo-insight-card { min-height:350px; padding:27px; }
.seo-insight-card header span { font-size:10px; }
.seo-insight-card header h3 { margin-top:8px; font-size:22px; }
.seo-insight-card header>b { padding:7px 11px; font-size:10px; }
.seo-index-compare { gap:15px; margin:27px 0 21px; }
.seo-index-compare>div { gap:8px 16px; }
.seo-index-compare span,.keyword-balance>span { font-size:11px; }
.seo-index-compare strong { font-size:21px; }
.seo-index-compare i,.keyword-balance>i { height:8px; }
.keyword-balance { gap:9px; margin:27px 0 22px; }
.keyword-balance>span b { font-size:12px; }
.seo-insight-card dl { gap:10px; }
.seo-insight-card dl>div { grid-template-columns:92px minmax(0,1fr); gap:14px; padding:12px 13px; }
.seo-insight-card dt { font-size:10px; }
.seo-insight-card dd { font-size:12px; line-height:1.65; }
.seo-risk-list,.seo-opportunity-list { font-size:11px; line-height:1.75; }
.seo-priority-section { padding:27px; }
.seo-priority-section .seo-subheading { padding-bottom:20px; }
.seo-priority-section .seo-subheading span { font-size:10px; }
.seo-priority-section .seo-subheading h3 { font-size:22px; }
.seo-priority-section .seo-subheading>p { max-width:520px; font-size:12px; line-height:1.6; }
.seo-priority-grid { gap:14px; }
.seo-priority-grid article { min-height:142px; grid-template-columns:47px minmax(0,1fr); gap:16px; padding:21px 57px 20px 20px; }
.seo-priority-grid article>span { width:43px; height:43px; font-size:11px; }
.seo-priority-grid small { font-size:9px; }
.seo-priority-grid h3 { margin:7px 0 9px; font-size:15px; }
.seo-priority-grid p { font-size:11px; line-height:1.65; }
.seo-priority-grid article>b { right:15px; top:18px; padding:5px 8px; font-size:9px; }
.seo-ai-impact-card { grid-column:1/-1; position:relative; display:grid; grid-template-columns:72px minmax(250px,1.2fr) minmax(220px,.8fr); gap:20px; align-items:center; padding:24px; overflow:hidden; border:1px solid #ded5eb; border-radius:19px; background:radial-gradient(circle at 96% 0,rgba(11,169,129,.13),transparent 31%),linear-gradient(118deg,#f7f2fd,#fff 49%,#f2fbf7); box-shadow:0 14px 31px rgba(53,40,67,.05); }
.seo-ai-impact-card:before { content:""; position:absolute; right:-42px; top:-74px; width:190px; height:190px; border:1px solid rgba(119,61,203,.1); border-radius:50%; box-shadow:0 0 0 30px rgba(12,167,129,.025); }
.seo-ai-impact-card>div { position:relative; z-index:1; }
.seo-ai-impact-mark { width:62px; height:62px; display:grid; place-items:center; border-radius:19px; color:#fff; background:linear-gradient(145deg,#7540ce,#0ca57e); box-shadow:0 12px 24px rgba(89,62,149,.2); }
.seo-ai-impact-mark span { font:850 17px "Avenir Next",sans-serif; }
.seo-ai-impact-mark i { position:absolute; width:6px; height:6px; border:2px solid #fff; border-radius:50%; background:#11b68a; }
.seo-ai-impact-mark i:nth-of-type(1) { right:-3px; top:8px; }.seo-ai-impact-mark i:nth-of-type(2) { right:7px; bottom:-3px; }.seo-ai-impact-mark i:nth-of-type(3) { left:-3px; bottom:10px; }
.seo-ai-impact-card>div:nth-child(2)>span { color:#7447ad; font-size:8px; font-weight:900; letter-spacing:.16em; }
.seo-ai-impact-card h3 { margin:6px 0 8px; color:#292a32; font-family:"Songti SC","Noto Serif SC",serif; font-size:19px; }
.seo-ai-impact-card>div:nth-child(2)>p { max-width:620px; margin:0; color:#686973; font-size:10px; line-height:1.75; }
.seo-ai-questions { display:grid; gap:7px; }
.seo-ai-questions span { display:flex; align-items:center; gap:9px; padding:8px 10px; border:1px solid rgba(121,59,215,.1); border-radius:9px; color:#565760; background:rgba(255,255,255,.74); font-size:9px; font-weight:750; }
.seo-ai-questions i { color:#8550c6; font:800 7px "SFMono-Regular",monospace; }
.seo-ai-advice { grid-column:2/-1; display:flex; align-items:center; gap:11px; padding:10px 13px; border-radius:10px; background:rgba(232,248,242,.82); }
.seo-ai-advice b { color:#087e64; font-size:9px; }.seo-ai-advice p { margin:0; color:#5f6866; font-size:9px; line-height:1.55; }

/* Unified capability structure lives in Overview; SEO remains search-foundation only. */
.overview-capability-composition { width:100%; max-width:205px; display:grid; gap:9px; margin-top:18px; padding-top:15px; border-top:1px solid #ebe7ef; }
.overview-capability-composition>div { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:5px 9px; text-align:left; }
.overview-capability-composition>div>span { color:#62616b; font-size:8px; font-weight:800; }
.overview-capability-composition>div>strong { color:#393a43; font:750 13px/1 "Iowan Old Style",Georgia,serif; }
.overview-capability-composition>div>strong small { margin-left:2px; color:#9a97a0; font:650 7px "Avenir Next",sans-serif; }
.overview-capability-composition>div>i { grid-column:1/-1; height:4px; overflow:hidden; border-radius:4px; background:#ecebed; }
.overview-capability-composition>div>i>b { display:block; height:100%; border-radius:inherit; background:linear-gradient(90deg,#0b9f7b,#4ed092); }
.overview-capability-composition>div:nth-child(2)>i>b { background:linear-gradient(90deg,#7340ca,#a15fdd); }
.overview-capability-composition>div:nth-child(3)>i>b { background:linear-gradient(90deg,#70798f,#a0a8b7); }
.overview-capability-composition>p { margin:2px 0 0; color:#92909a; font-size:7px; line-height:1.55; text-align:left; }
.seo-health-overview { min-height:350px; }
.seo-fact-grid article:last-child { grid-column:1/-1; min-height:64px; }
.seo-source-note { display:block; min-height:13px; margin:-8px 0 10px; color:#aaa7b0; font-size:7px; font-weight:600; }
.seo-cwv-grid { display:grid; gap:5px; margin:11px 0 13px; }
.seo-cwv-grid>div { display:flex; align-items:center; justify-content:space-between; gap:8px; padding:6px 8px; border:1px solid #e2f0eb; border-radius:8px; background:rgba(239,249,245,.76); }
.seo-cwv-grid span { color:#087c63; font-size:8px; font-weight:850; }
.seo-cwv-grid span small { display:block; margin-top:2px; color:#94999a; font-size:6px; font-weight:600; }
.seo-cwv-grid strong { color:#3d4b47; font-size:9px; }.seo-cwv-grid strong b { color:#0aa47d; }
.seo-cwv-grid .is-needs_improvement { border-color:#f3d9a9; background:#fff9ed; }
.seo-cwv-grid .is-needs_improvement strong b { color:#c47b09; }
.seo-cwv-grid .is-poor { border-color:#f1c7c4; background:#fff5f4; }
.seo-cwv-grid .is-poor strong b { color:#d94d45; }
.seo-cwv-grid .is-missing { border-color:#e8e8eb; background:#f8f8fa; }
.seo-cwv-grid .is-missing span,.seo-cwv-grid .is-missing strong { color:#9899a1; }
.website-experience .seo-source-note { margin-top:0; }

/* Core signal cards carry explanations, so keep them readable at report scale. */
.seo-core-grid article { min-height:285px; padding:24px; }
.seo-core-grid article>span { font-size:12px; }
.seo-core-grid article>strong { margin-top:17px; font-size:34px; }
.seo-core-grid article>strong small { font-size:12px; }
.seo-core-grid article>p { min-height:58px; margin:14px 0 16px; font-size:12px; line-height:1.7; }
.seo-source-note { min-height:16px; margin:-4px 0 13px; font-size:10px; line-height:1.45; }
.seo-mini-breakdown { gap:7px; margin-top:14px; }
.seo-mini-breakdown span { padding:7px 4px; font-size:9px; }
.seo-mini-breakdown b { margin-top:3px; font-size:12px; }
.seo-dual-metric { gap:8px; margin-top:17px; }
.seo-dual-metric>b { padding:11px; font-size:10px; }
.seo-dual-metric strong { margin-top:5px; font-size:22px; }
.seo-weight-traffic { margin-top:9px; padding:9px 11px; font-size:10px; }
.seo-weight-traffic b { font-size:12px; }
.seo-tech-tags { gap:6px; margin-top:12px; }
.seo-tech-tags span { padding:5px 7px; font-size:9px; }
.seo-cwv-grid { gap:7px; margin:13px 0 15px; }
.seo-cwv-grid>div { padding:9px 10px; }
.seo-cwv-grid span { font-size:10px; }
.seo-cwv-grid span small { margin-top:3px; font-size:8px; line-height:1.4; }
.seo-cwv-grid strong { font-size:11px; white-space:nowrap; }

@media (max-width: 1180px) {
  .seo-health-overview { grid-template-columns:200px minmax(0,1fr); }.seo-fact-grid { grid-column:1/-1; grid-template-columns:repeat(3,1fr); margin:0 24px 24px; }.seo-fact-grid article { min-height:76px; }
  .seo-overview-copy { padding:30px; }.seo-core-grid { grid-template-columns:1fr 1fr; }
  .seo-ai-impact-card { grid-template-columns:62px minmax(0,1fr) minmax(210px,.7fr); }
}
@media (max-width: 760px) {
  .seo-report-heading { align-items:flex-start; flex-direction:column; }.prototype-badge { align-self:flex-start; }
  .seo-health-overview { grid-template-columns:1fr; margin:14px; }.seo-score-column { border-right:0; border-bottom:1px solid rgba(121,59,215,.1); }.seo-overview-copy { padding:25px 21px; }.seo-overview-copy h3 { font-size:19px; }.seo-fact-grid { grid-template-columns:1fr 1fr; margin:0 14px 14px; }
  .seo-core-section,.seo-priority-section,.seo-analysis-grid,.seo-technical-details { margin-right:14px; margin-left:14px; }.seo-subheading { align-items:flex-start; flex-direction:column; }.seo-subheading>p { text-align:left; }.seo-core-grid,.seo-analysis-grid,.seo-priority-grid { grid-template-columns:1fr; }
  .seo-ai-impact-card { grid-template-columns:58px minmax(0,1fr); padding:19px; }.seo-ai-impact-card .seo-ai-questions,.seo-ai-advice { grid-column:1/-1; }.seo-ai-advice { align-items:flex-start; }
  .history-modal-backdrop { padding:10px; }.history-modal { width:100%; max-height:calc(100vh - 20px); border-radius:17px; }.history-modal>header { padding:20px; }.history-list { padding:12px; }.history-list>button { grid-template-columns:54px minmax(0,1fr); gap:11px; }.history-score { width:50px; height:50px; border-radius:15px; }.history-action { grid-column:2; justify-self:start; }.history-copy strong { font-size:12px; }
}

@media print {
  @page { size:A4 portrait; margin:12mm; }
  * { -webkit-print-color-adjust:exact !important; print-color-adjust:exact !important; }
  .diagnosis-center { display:block; background:#fff; }
  .diagnosis-sidebar,.diagnosis-topbar,.quick-audit-bar,.scan-panel,.preflight-grid,.topbar-actions,.issue-filters,.action-empty button,.history-modal-backdrop { display:none !important; }
  .diagnosis-content { max-width:none; padding:0; }
  .print-report-header { display:flex; align-items:flex-end; justify-content:space-between; gap:20px; margin:0 0 14px; padding:0 0 12px; border-bottom:2px solid #793bd7; }
  .print-report-header>div { display:flex; align-items:center; gap:10px; }.print-report-header img { width:38px; height:38px; object-fit:contain; }.print-report-header span { display:grid; gap:2px; }.print-report-header b { font-size:15px; }.print-report-header small { color:#77727e; font-size:8px; }.print-report-header>p { max-width:55%; display:grid; gap:2px; margin:0; text-align:right; }.print-report-header>p strong,.print-report-header>p span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.print-report-header>p strong { font-size:10px; }.print-report-header>p span { color:#6d6672; font-size:7px; }
  .report-meta { margin-top:0; }
  .site-coverage-panel,.capability-panel,.diagnostic-section,.issues-panel,.action-panel,.ai-sample-panel,.summary-grid article { break-inside:avoid; box-shadow:none; }
}
</style>

<style>
@media print {
  body > .el-overlay,
  body > .el-message,
  body > .el-notification,
  body > .el-popper,
  .el-message-box__wrapper {
    display:none !important;
  }
}
</style>
