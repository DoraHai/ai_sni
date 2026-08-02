<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  fetchGeoAssetProfile,
  fetchLatestGeoAudit,
  generateGeoAdvice,
  runDeepSeekSample,
  runGeoAudit,
} from '../../api/geo'
import { fetchTenants } from '../../api/auth'
import { session } from '../../store/session'
import DiagnosisAssetsView from './DiagnosisAssetsView.vue'

const tenantId = computed(() => session.tenantId || (import.meta.env.DEV && import.meta.env.VITE_API_KEY ? 1 : null))

const url = ref('')
const auditScope = ref('single')
const audit = ref(null)
const loading = ref(false)
const tenantLoading = ref(false)
const adviceLoading = ref(false)
const samplingLoading = ref(false)
const error = ref('')
const issueFilter = ref('all')
const loadingStage = ref(0)
const activeReport = ref('overview')
const activeAsset = ref('')
const expandedEvidence = ref('')
const sampleQuestions = ref(['', '', ''])
const brandReady = ref(false)
let stageTimer = null

const reportNav = [
  { key: 'overview', label: '网站体检', icon: '◉' },
  { key: 'seo', label: 'SEO 表现诊断', icon: '⌕' },
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

const scoreTone = computed(() => {
  const score = audit.value?.score ?? 0
  if (score >= 80) return 'good'
  if (score >= 60) return 'fair'
  return 'risk'
})

const scoreLabel = computed(() => {
  const score = audit.value?.score ?? 0
  if (score >= 80) return '基础良好'
  if (score >= 60) return '存在提升空间'
  return '需要优先整改'
})

const findings = computed(() => audit.value?.findings || [])
const problems = computed(() => audit.value?.problems || [])
const aiSample = computed(() => audit.value?.snapshot?.ai_sampling || null)
const siteAudit = computed(() => audit.value?.snapshot?.site_audit || null)
const isSiteAudit = computed(() => audit.value?.snapshot?.audit_scope === 'site')
const sitePages = computed(() => siteAudit.value?.pages || [])
const passedCount = computed(() => findings.value.filter((item) => item.passed).length)

const problemCounts = computed(() => ({
  critical: problems.value.filter((item) => item.severity === 'critical').length,
  high: problems.value.filter((item) => item.severity === 'high').length,
  medium: problems.value.filter((item) => item.severity === 'medium').length,
  low: problems.value.filter((item) => item.severity === 'low').length,
}))

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

const seoFindings = computed(() => findings.value.filter((item) =>
  ['技术基础', '页面语义', '内容结构', '内容质量'].includes(item.category),
))

const geoFindings = computed(() => findings.value.filter((item) =>
  ['结构化数据', 'AI 引用就绪度', 'AI 可引用性', 'AI 可访问性', '可信度'].includes(item.category),
))

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
  if (issueFilter.value === 'all') return problems.value
  if (issueFilter.value === 'critical') {
    return problems.value.filter((item) => ['critical', 'high'].includes(item.severity))
  }
  return problems.value.filter((item) => issueDomain(item) === issueFilter.value)
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
    return brandReady.value
  } catch {
    brandReady.value = false
    return false
  }
}

async function loadLatest({ notify = false } = {}) {
  if (!tenantId.value) return
  try {
    const result = await fetchLatestGeoAudit(tenantId.value)
    audit.value = result.audit
    if (result.audit?.url) url.value = result.audit.url
    await refreshBrandProfile(result.audit?.url || url.value)
    auditScope.value = result.audit?.snapshot?.audit_scope === 'site' ? 'site' : 'single'
    if (result.audit?.snapshot?.ai_sampling?.results) {
      sampleQuestions.value = result.audit.snapshot.ai_sampling.results.map((item) => item.question).slice(0, 3)
      while (sampleQuestions.value.length < 3) sampleQuestions.value.push('')
    }
    if (notify) ElMessage.success(result.audit ? '已载入最近一次诊断' : '暂无历史诊断')
  } catch {
    if (notify) ElMessage.error('历史诊断读取失败')
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

function openAsset(page) {
  activeAsset.value = page
  activeReport.value = ''
  window.history.replaceState(null, '', `${window.location.pathname}#asset-${page}`)
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

async function handleBrandSaved(profile) {
  brandReady.value = true
  url.value = profile?.website || url.value
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

function printReport() {
  window.print()
}

watch(tenantId, () => {
  audit.value = null
  url.value = ''
  brandReady.value = false
  loadLatest()
})

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
        <span class="brand-mark">诊</span>
        <span><strong>诊断中心</strong><small>评分 · 风险 · 建议</small></span>
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
          <span class="topbar-kicker">{{ activeAsset ? `DIAGNOSTIC CENTER / ${currentAsset.kicker}` : 'DIAGNOSTIC CENTER / WEBSITE AUDIT' }}</span>
          <h1>{{ activeAsset ? currentAsset.label : '网站体检' }}</h1>
          <p>{{ activeAsset ? currentAsset.description : '发现问题、评估风险并给出建议；具体优化动作派发到 SEO / GEO 工作区' }}</p>
        </div>
        <div class="topbar-actions">
          <template v-if="!activeAsset">
            <button type="button" @click="loadLatest({ notify: true })">↺ 查看最近诊断</button>
            <button type="button" :disabled="!audit" @click="printReport">⇩ 导出报告</button>
          </template>
          <button v-else type="button" @click="navigateReport('overview')">← 返回网站体检</button>
          <span class="avatar">DZ</span>
        </div>
      </header>

      <div v-if="!activeAsset" class="diagnosis-content">
        <section id="section-overview" class="scan-panel">
          <div class="scan-copy">
            <span class="section-index">01 / START AUDIT</span>
            <h2>输入网址，开始一次<br><em>可解释的全域诊断</em></h2>
            <p>同时检查技术可访问性、SEO 基础、Schema、内容结构、可信信号和 AI 引用就绪度。</p>
            <div class="scan-notes">
              <span>✓ 仅读取公开页面</span>
              <span>✓ 每项结果附带证据</span>
              <span>✓ 不会修改目标网站</span>
            </div>
          </div>

          <form class="scan-form" @submit.prevent="startAudit">
            <label for="diagnosis-url">需要诊断的网址</label>
            <div class="url-input-wrap" :class="{ invalid: error }">
              <input
                id="diagnosis-url"
                v-model="url"
                type="text"
                inputmode="url"
                autocomplete="url"
                placeholder="www.example.com 或具体页面地址"
                :disabled="loading"
              >
              <button type="submit" :disabled="loading || tenantLoading">
                {{ tenantLoading ? '准备诊断…' : loading ? '诊断进行中' : '开始诊断' }} <b>→</b>
              </button>
            </div>
            <div class="scope-row">
              <button type="button" class="scope" :class="{ active: auditScope === 'single' }" :disabled="loading" @click="auditScope = 'single'">{{ auditScope === 'single' ? '●' : '○' }} 单页快速诊断</button>
              <button type="button" class="scope" :class="{ active: auditScope === 'site' }" :disabled="loading" @click="auditScope = 'site'">{{ auditScope === 'site' ? '●' : '○' }} 全站抽样诊断 <small>最多10页</small></button>
            </div>
            <p v-if="error" class="form-error">{{ error }}</p>
            <p v-else class="form-hint">{{ auditScope === 'site' ? '优先读取 Sitemap，缺失时从首页发现站内链接；通常在 1–2 分钟内完成。' : '支持官网首页、产品页、文章页等公开 HTML 页面，通常在 20 秒内完成。' }}</p>
          </form>
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

          <section class="report-meta">
            <div>
              <span class="live-dot" /> 诊断完成
              <strong>{{ audit.page_title || '页面未设置标题' }}</strong>
              <a :href="audit.final_url" target="_blank" rel="noopener">{{ audit.final_url }}</a>
            </div>
            <span>{{ formatDate(audit.created_at) }} · {{ isSiteAudit ? `全站抽样 ${sitePages.length} 页` : '单页诊断' }} · 规则版本 v{{ audit.rule_version || '1.1.0' }}</span>
          </section>

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
            <div class="panel-heading">
              <div><span class="section-index">READINESS MAP</span><h2>六维能力图</h2></div>
              <p>不是黑盒分数，每个维度均由下方检查项和扣分证据组成。</p>
            </div>
            <div class="capability-body">
              <div class="radar-wrap">
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
              </div>
              <div class="dimension-list">
                <article v-for="item in dimensions" :key="item.key">
                  <div><span>{{ item.label }}</span><strong>{{ item.score }}</strong></div>
                  <div class="dimension-bar"><i :style="{ width: `${item.score}%` }" /></div>
                  <small>{{ item.passed }} / {{ item.total }} 项通过</small>
                </article>
                <p class="dimension-method">计分规则：维度得分 = 已通过规则权重 ÷ 该维度全部规则权重 × 100。规则权重固定，通过项不会从分母中消失。</p>
              </div>
            </div>
          </section>

          <section id="section-seo" class="diagnostic-section">
            <div class="panel-heading">
              <div><span class="section-index">02 / SEO DIAGNOSIS</span><h2>SEO 表现诊断</h2></div>
              <a href="/deal-sniper/seo/dashboard">去 SEO 执行 →</a>
            </div>
            <div class="check-grid">
              <article v-for="item in seoFindings" :key="item.code" :class="{ failed: !item.passed }">
                <span class="check-status">{{ item.passed ? '✓' : '!' }}</span>
                <div class="check-copy">
                  <small>{{ categoryLabel(item) }}</small>
                  <h3>{{ item.title }}</h3>
                  <p>{{ item.evidence }}</p>
                  <div v-if="!item.passed" class="failure-summary"><span>扣分原因</span><p>{{ failureSummary(item) }}</p></div>
                  <button
                    v-if="evidenceDetails(item).length"
                    class="evidence-toggle"
                    type="button"
                    @click="toggleEvidence(item)"
                  >
                    {{ expandedEvidence === item.code ? '收起明细 ↑' : `查看 ${evidenceDetails(item).length} 条明细 ↓` }}
                  </button>
                </div>
                <b v-if="!item.passed">-{{ item.deduction }}</b>
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

          <section id="section-geo" class="diagnostic-section geo-section">
            <div class="panel-heading">
              <div><span class="section-index">03 / GEO DIAGNOSIS</span><h2>GEO / AI 搜索诊断</h2></div>
              <a href="/deal-sniper/geo/dashboard">去 GEO 执行 →</a>
            </div>
            <div class="check-grid">
              <article v-for="item in geoFindings" :key="item.code" :class="{ failed: !item.passed }">
                <span class="check-status">{{ item.passed ? '✓' : '!' }}</span>
                <div class="check-copy">
                  <small>{{ categoryLabel(item) }}</small>
                  <h3>{{ item.title }}</h3>
                  <p>{{ item.evidence }}</p>
                  <div v-if="!item.passed" class="failure-summary"><span>扣分原因</span><p>{{ failureSummary(item) }}</p></div>
                  <button
                    v-if="evidenceDetails(item).length"
                    class="evidence-toggle"
                    type="button"
                    @click="toggleEvidence(item)"
                  >
                    {{ expandedEvidence === item.code ? '收起明细 ↑' : `查看 ${evidenceDetails(item).length} 条明细 ↓` }}
                  </button>
                </div>
                <b v-if="!item.passed">-{{ item.deduction }}</b>
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

          <section class="ai-sample-panel">
            <div class="sample-heading">
              <div>
                <span class="section-index">03B / LIVE MODEL SAMPLE</span>
                <h2>DeepSeek 品牌提及抽样</h2>
                <p>用中立问题真实调用模型；品牌提及由后端按已确认名称和别名匹配。</p>
              </div>
              <div class="sample-chips">
                <span class="sample-chip">待测品牌：{{ aiSample?.brand_name || '当前客户品牌' }}</span>
                <span class="sample-chip">真实 API · 最多 3 个问题</span>
              </div>
            </div>

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
                  <span>品牌被提及</span>
                  <strong>{{ aiSample.mention_count }}<small>/{{ aiSample.question_count }}</small></strong>
                </article>
                <article>
                  <span>本次提及率</span>
                  <strong>{{ Math.round(aiSample.mention_rate * 100) }}<small>%</small></strong>
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
                      <span :class="item.mentioned ? 'hit' : 'miss'">{{ item.mentioned ? '已提及品牌' : '未提及品牌' }}</span>
                      <small v-if="item.matched_terms?.length">命中：{{ item.matched_terms.join('、') }}</small>
                    </header>
                    <h3>{{ item.question }}</h3>
                    <p>{{ item.response }}</p>
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
              <p><strong>结构就绪度不等于真实提及。</strong>运行抽样后，这里会展示每个问题的完整模型回答与品牌命中证据。</p>
            </div>
          </section>

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
            <div class="issue-table-wrap">
              <table>
                <thead><tr><th>问题与证据</th><th>归属</th><th>严重程度</th><th>扣分</th><th>建议动作</th></tr></thead>
                <tbody>
                  <tr v-for="item in filteredProblems" :key="item.code">
                    <td><strong>{{ item.title }}</strong><small>{{ item.evidence }}</small></td>
                    <td><span class="domain-tag" :class="issueDomain(item)">{{ issueDomainLabel(item) }}</span></td>
                    <td><span class="severity-tag" :class="item.severity">{{ severityLabel(item.severity) }}</span></td>
                    <td class="deduction">-{{ item.deduction }}</td>
                    <td>{{ item.recommendation }}</td>
                  </tr>
                  <tr v-if="!filteredProblems.length"><td colspan="5" class="empty-row">当前筛选下没有待处理问题</td></tr>
                </tbody>
              </table>
            </div>
          </section>

          <section class="action-panel">
            <div class="panel-heading">
              <div><span class="section-index">ACTION ROUTE</span><h2>诊断问题转任务</h2></div>
              <span class="boundary-chip">只派发，不在诊断中心执行</span>
            </div>
            <div v-if="audit.advice?.length" class="action-grid">
              <article v-for="(item, index) in audit.advice" :key="`${item.code}-${index}`">
                <span>{{ String(index + 1).padStart(2, '0') }}</span>
                <small>{{ severityLabel(item.priority) }}</small>
                <h3>{{ item.title }}</h3>
                <p>{{ item.action }}</p>
                <footer><b>验收</b>{{ item.acceptance }}</footer>
              </article>
            </div>
            <div v-else class="action-empty">
              <div><strong>把 {{ problems.length }} 个问题整理成团队行动路线</strong><p>生成后按优先级、责任团队和验收标准拆分，可继续派发到 SEO / GEO 工作区。</p></div>
              <button :disabled="adviceLoading" @click="createAdvice">{{ adviceLoading ? '正在生成…' : '生成行动建议 →' }}</button>
            </div>
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
.brand-mark { width:38px; height:38px; display:grid; place-items:center; color:#fff; background:var(--teal); border-radius:11px; box-shadow:0 8px 18px rgba(11,147,136,.22); font-weight:800; }
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
.diagnosis-content { max-width:1460px; margin:0 auto; padding:28px 32px 80px; }
#section-overview,#section-seo,#section-geo,#section-issues { scroll-margin-top:18px; }

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
.capability-body { display:grid; grid-template-columns:310px 1fr; min-height:316px; }
.radar-wrap { position:relative; display:grid; place-items:center; border-right:1px solid var(--line); }
.radar-wrap svg { width:230px; height:230px; overflow:visible; }
.radar-grid polygon,.radar-grid line { fill:none; stroke:#d8e4e2; stroke-width:1; }
.radar-value { fill:rgba(11,147,136,.18); stroke:var(--teal); stroke-width:2; }
.radar-wrap circle { fill:var(--teal); stroke:#fff; stroke-width:2; }
.radar-label { position:absolute; color:#748488; font-size:9px; font-weight:700; }
.label-1{top:25px;left:145px}.label-2{top:78px;right:25px}.label-3{bottom:78px;right:25px}.label-4{bottom:24px;left:140px}.label-5{bottom:78px;left:26px}.label-6{top:78px;left:28px}
.dimension-list { display:grid; grid-template-columns:1fr 1fr; gap:0 30px; align-content:center; padding:24px 34px; }
.dimension-list article { padding:12px 0; }
.dimension-list article>div:first-child { display:flex; justify-content:space-between; font-size:11px; }
.dimension-list strong { color:var(--teal-dark); font:600 18px Georgia,serif; }
.dimension-bar { height:5px; margin:7px 0 5px; border-radius:3px; background:#edf2f1; }
.dimension-bar i { display:block; height:100%; border-radius:inherit; background:linear-gradient(90deg,#62c9b8,var(--teal)); }
.dimension-list small { color:#9aa6a9; font-size:9px; }
.dimension-method { grid-column:1/-1; margin:8px 0 0; padding:10px 12px; border:1px solid #dceae7; border-radius:8px; color:#60777a; background:#f5fbf9; font-size:9px; line-height:1.65; }

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
.action-empty { display:flex; align-items:center; justify-content:space-between; gap:20px; padding:25px; }
.action-empty strong { font-size:13px; }
.action-empty p { margin:6px 0 0; color:var(--muted); font-size:10px; }
.action-empty button { height:39px; padding:0 17px; border:0; border-radius:8px; color:#fff; background:var(--teal); font-size:10px; font-weight:800; cursor:pointer; }

@media (max-width: 1050px) {
  .diagnosis-center { grid-template-columns:190px minmax(0,1fr); }
  .scan-panel { grid-template-columns:1fr; gap:26px; }
  .summary-grid { grid-template-columns:1fr 1fr; }
  .capability-body { grid-template-columns:270px 1fr; }
  .dimension-list { grid-template-columns:1fr; }
  .action-grid { grid-template-columns:1fr 1fr; }
  .sample-results { grid-template-columns:1fr; }
  .site-page-grid { grid-template-columns:1fr; }
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
  .capability-body { grid-template-columns:1fr; }
  .radar-wrap { min-height:280px; border-right:0; border-bottom:1px solid var(--line); }
  .dimension-list { grid-template-columns:1fr 1fr; padding:18px; }
  .panel-heading { align-items:flex-start; }
  .panel-heading>p { display:none; }
  .action-empty { align-items:flex-start; flex-direction:column; }
  .sample-heading,.sample-composer { grid-template-columns:1fr; align-items:flex-start; }
  .sample-heading { flex-direction:column; }
  .sample-composer>button { width:100%; }
  .sample-metrics { grid-template-columns:1fr; }
  .sample-metrics article { border-right:0; border-bottom:1px solid #e8e4f0; }
  .sample-method { grid-template-columns:1fr; }
  .site-coverage-heading { align-items:flex-start; flex-direction:column; }
  .site-coverage-heading p { text-align:left; }
  .site-coverage-meta { flex-wrap:wrap; gap:8px 16px; }
}

@media print {
  .diagnosis-center { display:block; background:#fff; }
  .diagnosis-sidebar,.diagnosis-topbar,.scan-panel,.preflight-grid,.topbar-actions,.issue-filters,.action-empty button { display:none !important; }
  .diagnosis-content { max-width:none; padding:0; }
  .report-meta { margin-top:0; }
  .site-coverage-panel,.capability-panel,.diagnostic-section,.issues-panel,.action-panel,.ai-sample-panel,.summary-grid article { break-inside:avoid; box-shadow:none; }
}
</style>
