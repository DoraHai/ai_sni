import { createRouter, createWebHistory } from 'vue-router'
import { session } from '../store/session'
import { GEO_WORKBENCH_START } from '../utils/geoPrototypeContract'

// 路由按原型 v3.0 的 6 个工作流划分，未实现的页面挂占位组件。
// meta.perm = 该页所需菜单权限 key（自定义角色 RBAC）；可为数组=任一可见即可（下钻页）。
const DealSniperShell = () => import('../views/deal/DealSniperShell.vue')
const GrowthSniperLanding = () => import('../views/landing/GrowthSniperLanding.vue')
const DiagnosisLanding = () => import('../views/landing/DiagnosisLanding.vue')

const routes = [
  {
    path: '/',
    redirect: '/monitor/dashboard',
  },
  {
    path: '/growth-sniper',
    component: GrowthSniperLanding,
    meta: {
      title: '平台门户',
      documentTitle: 'Growth Sniper｜SEM·SEO·GEO 全域智能获客平台',
      public: true,
      bare: true,
    },
  },
  {
    path: '/deal-sniper',
    redirect: '/growth-sniper',
  },
  {
    path: '/diagnosis',
    component: DiagnosisLanding,
    meta: {
      title: '免费诊断',
      documentTitle: '免费获客诊断｜Growth Sniper',
      public: true,
      bare: true,
    },
  },
  {
    path: '/deal-sniper/portal',
    component: DealSniperShell,
    meta: { title: '产品门户', public: true, bare: true },
  },
  {
    path: '/deal-sniper/:section(hub|seo|geo|content)/:page',
    component: DealSniperShell,
    meta: { title: 'Growth Sniper', public: true, bare: true },
  },
  {
    path: '/assistant',
    component: () => import('../views/assistant/AssistantView.vue'),
    meta: { title: 'AI 助手', workflow: '智能助手', perm: 'assistant' },
  },
  {
    path: '/geo/overview',
    component: () => import('../views/geo/GeoOverviewView.vue'),
    meta: {
      title: 'GEO 概览',
      documentTitle: 'GEO 工作台｜GEO 概览',
      workflow: 'GEO 工作台',
      perm: 'geo.content',
    },
  },
  {
    path: '/geo/visibility',
    component: () => import('../views/geo/GeoVisibilityDashView.vue'),
    meta: {
      title: 'AI 可见度',
      documentTitle: 'GEO 工作台｜AI 可见度',
      workflow: 'GEO 工作台',
      perm: 'geo.content',
    },
  },
  {
    path: '/geo/visibility/snapshots',
    redirect: (to) => ({ path: '/geo/visibility', query: to.query }),
  },
  {
    path: '/geo/units',
    redirect: (to) => ({
      path: '/geo/prompts',
      query: { ...to.query, layer: to.query.layer || 'keyword' },
    }),
  },
  {
    path: '/geo/keywords',
    redirect: (to) => ({
      path: '/geo/prompts',
      query: { ...to.query, layer: to.query.layer || 'keyword' },
    }),
  },
  {
    path: '/geo/prompts',
    component: () => import('../views/geo/GeoAskManageView.vue'),
    meta: {
      title: '提问监控',
      documentTitle: 'GEO 工作台｜提问监控',
      workflow: 'GEO 工作台',
      perm: 'geo.content',
    },
  },
  {
    path: '/geo/recommend',
    redirect: (to) => ({ path: '/geo/prompts', query: to.query }),
  },
  {
    path: '/geo/answers',
    redirect: (to) => ({ path: '/geo/visibility', query: to.query }),
  },
  {
    path: '/geo/sources',
    component: () => import('../views/geo/GeoCitationsView.vue'),
    meta: {
      title: '信源分析',
      documentTitle: 'GEO 工作台｜信源分析',
      workflow: 'GEO 工作台',
      perm: 'geo.content',
    },
  },
  {
    path: '/geo/brand',
    component: () => import('../views/geo/GeoBrandSettingsView.vue'),
    meta: {
      title: '品牌信息',
      documentTitle: 'GEO 工作台｜品牌信息',
      workflow: 'GEO 工作台',
      perm: 'geo.content',
    },
  },
  {
    path: '/geo/permissions',
    redirect: (to) => ({ path: '/geo/overview', query: to.query }),
  },
  {
    path: '/geo/engines',
    component: () => import('../views/geo/GeoEnginesView.vue'),
    meta: {
      title: 'AI 引擎管理',
      documentTitle: 'GEO 工作台｜AI 引擎管理',
      workflow: 'GEO 工作台',
      perm: 'geo.content',
    },
  },
  {
    path: '/geo/geo-diagnosis',
    redirect: (to) => ({ path: GEO_WORKBENCH_START, query: to.query }),
  },
  {
    path: '/geo/visibility/evaluation',
    redirect: (to) => ({ path: '/geo/evaluation', query: to.query }),
  },
  {
    path: '/geo/visibility/patrol',
    redirect: (to) => ({ path: '/geo/visibility/snapshots', query: to.query }),
  },
  {
    path: '/geo/period-diff',
    redirect: (to) => ({ path: '/geo/visibility', query: to.query }),
  },
  {
    path: '/geo/gaps',
    redirect: (to) => ({ path: '/geo/prompts', query: to.query }),
  },
  {
    path: '/geo/gap-workbench',
    redirect: (to) => ({ path: '/geo/prompts', query: to.query }),
  },
  {
    path: '/geo/periods',
    redirect: (to) => ({ path: GEO_WORKBENCH_START, query: to.query }),
  },
  {
    path: '/geo/citations',
    redirect: (to) => ({ path: '/geo/sources', query: to.query }),
  },
  {
    path: '/geo/competitors',
    component: () => import('../views/geo/GeoCompetitorsView.vue'),
    meta: {
      title: '竞品分析',
      documentTitle: 'GEO 工作台｜竞品分析',
      workflow: 'GEO 工作台',
      perm: 'geo.content',
    },
  },
  {
    path: '/geo/topic-heat',
    redirect: (to) => ({ path: '/geo/prompts', query: to.query }),
  },
  {
    path: '/geo/ai-trends',
    redirect: (to) => ({ path: GEO_WORKBENCH_START, query: to.query }),
  },
  {
    path: '/geo/evaluation',
    component: () => import('../views/geo/GeoEvaluationView.vue'),
    meta: {
      title: '评价分析',
      documentTitle: 'GEO 工作台｜评价分析',
      workflow: 'GEO 工作台',
      perm: 'geo.content',
    },
  },
  {
    path: '/geo/deliverables',
    redirect: (to) => ({ path: GEO_WORKBENCH_START, query: to.query }),
  },
  {
    path: '/geo/deliverables/share/:shareToken',
    component: () => import('../views/geo/GeoDeliverableShareView.vue'),
    meta: {
      title: '交付摘要分享',
      documentTitle: 'GEO 交付摘要 · 只读分享',
      public: true,
      bare: true,
    },
  },
  // 兼容旧 hash 风格外链误写（部分环境会把 # 去掉后落到此路径）
  {
    path: '/geo/deliverables/share',
    redirect: (to) => {
      const t = to.query.token || to.query.share_token
      return t
        ? { path: `/geo/deliverables/share/${t}`, query: to.query }
        : { path: GEO_WORKBENCH_START, query: to.query }
    },
  },
  {
    path: '/geo/workbench',
    redirect: (to) => ({ path: GEO_WORKBENCH_START, query: to.query }),
  },
  {
    path: '/geo/articles',
    component: () => import('../views/geo/GeoTasksView.vue'),
    meta: {
      title: 'GEO 文章',
      documentTitle: 'GEO 工作台｜GEO 文章',
      workflow: 'GEO 工作台',
      perm: 'geo.content',
    },
  },
  {
    path: '/geo/import',
    component: () => import('../views/geo/GeoArticleImportView.vue'),
    meta: {
      title: '导入已有文章',
      documentTitle: 'GEO 工作台｜导入已有文章',
      workflow: 'GEO 工作台',
      perm: 'geo.content',
    },
  },
  {
    path: '/geo/articles/:taskId/distribution',
    component: () => import('../views/geo/GeoDistributionView.vue'),
    meta: {
      title: '分发记录',
      documentTitle: 'GEO 工作台｜分发记录',
      workflow: 'GEO 工作台',
      perm: 'geo.content',
    },
  },
  {
    path: '/geo/articles/:taskId',
    component: () => import('../views/geo/GeoTaskEditorView.vue'),
    meta: {
      title: '在线编辑器',
      documentTitle: 'GEO 工作台｜在线编辑器',
      workflow: 'GEO 工作台',
      perm: 'geo.content',
    },
  },
  {
    path: '/geo/structure',
    component: () => import('../views/geo/GeoStructureView.vue'),
    meta: {
      title: '官网结构优化',
      documentTitle: 'GEO 工作台｜官网结构优化',
      workflow: 'GEO 工作台',
      perm: 'geo.content',
    },
  },
  {
    path: '/geo/tickets',
    component: () => import('../views/geo/GeoTicketsView.vue'),
    meta: {
      title: '验收工单',
      documentTitle: 'GEO 工作台｜验收工单',
      workflow: 'GEO 工作台',
      perm: 'geo.content',
    },
  },
  {
    path: '/geo/tasks/:taskId',
    redirect: (to) => ({
      path: `/geo/articles/${to.params.taskId}`,
      query: to.query,
    }),
  },
  {
    path: '/geo/tasks',
    redirect: (to) => ({ path: '/geo/articles', query: to.query }),
  },
  {
    path: '/geo/questions',
    redirect: (to) => ({ path: '/geo/prompts', query: to.query }),
  },
  {
    path: '/geo/knowledge',
    component: () => import('../views/geo/GeoFactsView.vue'),
    meta: {
      title: '知识库',
      documentTitle: 'GEO 工作台｜知识库',
      workflow: 'GEO 工作台',
      perm: 'geo.content',
    },
  },
  {
    path: '/geo/models',
    redirect: (to) => ({ path: '/geo/engines', query: to.query }),
  },
  {
    path: '/geo/placements',
    redirect: (to) => ({ path: '/geo/media', query: to.query }),
  },
  {
    path: '/geo/publishing',
    redirect: (to) => ({ path: '/geo/channels', query: to.query }),
  },
  {
    path: '/geo/channel-polish-prompts',
    component: () => import('../views/geo/GeoChannelPolishPromptsView.vue'),
    meta: {
      title: '渠道成稿提示词',
      documentTitle: 'GEO 工作台｜渠道成稿提示词',
      workflow: 'GEO 工作台',
      perm: 'geo.content',
    },
  },
  {
    path: '/geo/businesses',
    redirect: (to) => ({
      path: '/geo/prompts',
      query: { ...to.query, layer: to.query.layer || 'business' },
    }),
  },
  {
    path: '/geo/businesses/:businessId',
    redirect: (to) => ({
      path: '/geo/prompts',
      query: { ...to.query, layer: 'keyword', business_id: to.params.businessId },
    }),
  },
  {
    path: '/geo/onboarding',
    redirect: (to) => ({ path: GEO_WORKBENCH_START, query: to.query }),
  },
  {
    path: '/geo/facts',
    redirect: (to) => ({ path: '/geo/knowledge', query: to.query }),
  },
  {
    path: '/geo/ai-settings',
    component: () => import('../views/geo/GeoAiSettingsView.vue'),
    meta: {
      title: 'AI 能力配置',
      documentTitle: 'GEO 工作台｜AI 能力配置',
      workflow: 'GEO 工作台',
      perm: 'geo.content',
    },
  },
  {
    path: '/geo/publishing-channels',
    redirect: (to) => ({ path: '/geo/channels', query: to.query }),
  },
  {
    path: '/geo/channels',
    component: () => import('../views/geo/GeoChannelsView.vue'),
    meta: {
      title: '分发平台',
      documentTitle: 'GEO 工作台｜分发平台',
      workflow: 'GEO 工作台',
      perm: 'geo.content',
    },
  },
  {
    path: '/geo/media',
    component: () => import('../views/geo/GeoPlacementsView.vue'),
    meta: {
      title: '媒体 / 信源策略',
      documentTitle: 'GEO 工作台｜媒体 / 信源策略',
      workflow: 'GEO 工作台',
      perm: 'geo.content',
    },
  },
  {
    path: '/geo/diagnosis',
    component: () => import('../views/diagnosis/DiagnosisRedirectView.vue'),
    meta: {
      title: '网站体检',
      documentTitle: '诊断中心｜网站体检',
      workflow: '诊断中心',
      perm: 'geo.diagnosis',
      bare: true,
    },
  },
  {
    path: '/diagnostic-center',
    component: () => import('../views/diagnosis/DiagnosisRedirectView.vue'),
    meta: { title: '诊断中心', perm: 'geo.diagnosis', bare: true },
  },
  {
    path: '/login',
    component: () => import('../views/LoginView.vue'),
    meta: { title: '登录', public: true, bare: true },
  },
  {
    path: '/monitor/dashboard',
    component: () => import('../views/monitor/DashboardView.vue'),
    meta: { title: '数据看板', workflow: '每日盯盘', perm: 'monitor.dashboard' },
  },
  {
    path: '/monitor/alerts',
    component: () => import('../views/monitor/AlertsView.vue'),
    meta: { title: '异常提醒', workflow: '每日盯盘', perm: 'monitor.alerts' },
  },
  {
    path: '/monitor/profile',
    component: () => import('../views/monitor/CustomerProfileView.vue'),
    meta: { title: '客户画像', workflow: '每日盯盘', perm: 'monitor.profile' },
  },
  {
    path: '/monitor/keywords/:keywordId',
    component: () => import('../views/monitor/KeywordDetailView.vue'),
    meta: { title: '关键词详情', workflow: '每日盯盘', perm: ['monitor.dashboard', 'monitor.alerts', 'optimize.keywords'] },
  },
  {
    path: '/onboarding',
    component: () => import('../views/onboarding/AuthorizationSyncView.vue'),
    meta: { title: '授权与同步', workflow: '首次接入', perm: 'onboarding' },
  },
  {
    path: '/onboarding/builder',
    component: () => import('../views/onboarding/SmartBuilderView.vue'),
    meta: { title: '智能搭建', workflow: '首次接入', perm: 'onboarding' },
  },
  { path: '/optimize', redirect: '/optimize/expand' },
  {
    path: '/optimize/expand',
    component: () => import('../views/optimize/KeywordExpandView.vue'),
    meta: { title: '拓词', workflow: '优化执行', perm: 'optimize.expand' },
  },
  {
    path: '/optimize/keywords',
    component: () => import('../views/optimize/KeywordWorkbenchView.vue'),
    meta: { title: '关键词工作台', workflow: '优化执行', perm: 'optimize.keywords' },
  },
  {
    path: '/optimize/search-terms',
    component: () => import('../views/optimize/SearchTermsView.vue'),
    meta: { title: '搜索词报告', workflow: '优化执行', perm: 'optimize.searchterms' },
  },
  {
    path: '/optimize/negatives',
    component: () => import('../views/optimize/NegativeWordsView.vue'),
    meta: { title: '否词管理', workflow: '优化执行', perm: 'optimize.negatives' },
  },
  { path: '/verify', redirect: '/verify/adjustments' },
  {
    path: '/verify/adjustments',
    component: () => import('../views/verify/AdjustmentLogView.vue'),
    meta: { title: '调价台账', workflow: '效果验证', perm: 'verify.adjustments' },
  },
  {
    path: '/verify/pending',
    component: () => import('../views/verify/PendingAdjustmentsView.vue'),
    meta: { title: '待验证调价', workflow: '效果验证', perm: 'verify.pending' },
  },
  {
    path: '/verify/leads',
    component: () => import('../views/verify/LeadsView.vue'),
    meta: { title: '线索管理', workflow: '效果验证', perm: 'verify.leads' },
  },
  { path: '/manage', redirect: '/manage/account' },
  {
    path: '/manage/account',
    component: () => import('../views/manage/AccountBudgetView.vue'),
    meta: { title: '账户与预算', workflow: '投放管理', perm: 'manage.account' },
  },
  {
    path: '/manage/campaigns',
    component: () => import('../views/manage/CampaignManageView.vue'),
    meta: { title: '计划管理', workflow: '投放管理', perm: 'manage.campaigns' },
  },
  {
    path: '/manage/adgroups',
    component: () => import('../views/manage/AdgroupManageView.vue'),
    meta: { title: '单元管理', workflow: '投放管理', perm: 'manage.adgroups' },
  },
  {
    path: '/manage/ocpc',
    component: () => import('../views/manage/OcpcView.vue'),
    meta: { title: 'oCPC 投放', workflow: '投放管理', perm: 'manage.ocpc' },
  },
  { path: '/delivery', redirect: '/delivery/report' },
  {
    path: '/delivery/report',
    component: () => import('../views/delivery/MonthlyReportView.vue'),
    meta: { title: '分析报告', workflow: '客户交付', perm: 'delivery.report' },
  },
  {
    path: '/settings/accounts',
    component: () => import('../views/settings/AccountsRolesView.vue'),
    meta: { title: '账号与权限', workflow: '系统设置', perm: 'settings.accounts' },
  },
  { path: '/settings', redirect: '/settings/accounts' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) return savedPosition
    if (to.hash) return { el: to.hash, behavior: 'smooth' }
    return { top: 0 }
  },
})

const MENU_ORDER = [
  ['assistant', '/assistant'],
  ['geo.content', GEO_WORKBENCH_START],
  ['geo.diagnosis', '/geo/diagnosis'],
  ['monitor.dashboard', '/monitor/dashboard'],
  ['monitor.alerts', '/monitor/alerts'],
  ['monitor.profile', '/monitor/profile'],
  ['optimize.expand', '/optimize/expand'],
  ['optimize.keywords', '/optimize/keywords'],
  ['optimize.searchterms', '/optimize/search-terms'],
  ['optimize.negatives', '/optimize/negatives'],
  ['verify.adjustments', '/verify/adjustments'],
  ['verify.pending', '/verify/pending'],
  ['verify.leads', '/verify/leads'],
  ['manage.account', '/manage/account'],
  ['manage.campaigns', '/manage/campaigns'],
  ['manage.ocpc', '/manage/ocpc'],
  ['delivery.report', '/delivery/report'],
  ['onboarding', '/onboarding'],
  ['settings.accounts', '/settings/accounts'],
]

function firstAllowedPath() {
  const hit = MENU_ORDER.find(([k]) => session.canView(k))
  return hit ? hit[1] : null
}
function permOk(perm) {
  if (!perm) return true
  const keys = Array.isArray(perm) ? perm : [perm]
  return keys.some((k) => session.canView(k))
}
function hasDevApiKey() {
  if (!import.meta.env.DEV) return false
  const k = import.meta.env.VITE_API_KEY
  return Boolean(k && String(k).trim() && String(k).trim() !== 'CHANGE_ME')
}

function geoClickStart() {
  return GEO_WORKBENCH_START
}

router.beforeEach((to) => {
  // 配了 VITE_API_KEY：未登录可进业务页（API 走 X-API-Key），不要停在登录页
  const devBypass = hasDevApiKey() && !session.isLoggedIn
  if (devBypass && (to.path === '/login' || to.path === '/')) {
    const redir = typeof to.query.redirect === 'string' ? to.query.redirect : ''
    if (redir.startsWith('/') && !redir.startsWith('//') && !redir.startsWith('/login')) {
      return redir
    }
    return geoClickStart()
  }
  if (!to.meta.public && !session.isLoggedIn && !devBypass) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.path === '/login' && session.isLoggedIn) {
    return { path: firstAllowedPath() || geoClickStart() }
  }
  if (devBypass || !session.isLoggedIn) return
  if (!to.meta.public && !permOk(to.meta.perm)) {
    // 本地 Key 模式下 token 残缺无菜单权限：仍放行，避免踢回登录
    if (hasDevApiKey()) return
    const dest = firstAllowedPath()
    if (dest && dest !== to.path) return { path: dest }
    if (!dest) return
  }
})
router.afterEach((to) => {
  const suffix = to.path.startsWith('/geo') ? 'GEO 工作台' : 'SEM 智投平台'
  document.title =
    to.meta.documentTitle || (to.meta.title ? `${to.meta.title} · ${suffix}` : suffix)
})
export default router
