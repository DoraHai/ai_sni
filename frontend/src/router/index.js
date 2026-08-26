import { createRouter, createWebHistory } from 'vue-router'
import { session } from '../store/session'
import { loginUrl } from '../auth/loginRedirect'
import { GEO_WORKBENCH_START } from '../utils/geoPrototypeNavigation'

// 路由按原型 v3.0 的 6 个工作流划分，未实现的页面挂占位组件。
// meta.perm = 该页所需菜单权限 key（自定义角色 RBAC）；可为数组=任一可见即可（下钻页）。
const PlaceholderView = () => import('../views/PlaceholderView.vue')
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
  { path: '/deal-sniper/seo/manage', redirect: '/seo/keywords' },
  { path: '/deal-sniper/seo/keywords', redirect: '/seo/keywords' },
  { path: '/deal-sniper/seo/tdk', redirect: '/seo/site' },
  { path: '/deal-sniper/seo/dashboard', redirect: '/seo/dashboard' },
  { path: '/deal-sniper/seo/trends', redirect: '/seo/dashboard' },
  { path: '/deal-sniper/seo/competitors', redirect: '/seo/competitors' },
  { path: '/deal-sniper/seo/articles', redirect: '/seo/content/articles' },
  { path: '/deal-sniper/seo/rewrites', redirect: '/seo/content/rewrites' },
  { path: '/deal-sniper/seo/questions', redirect: '/seo/content/qa' },
  { path: '/deal-sniper/seo/channels', redirect: '/seo/distribution' },
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
    path: '/geo',
    component: () => import('../views/geo/GeoWorkspaceShell.vue'),
    redirect: GEO_WORKBENCH_START,
    meta: { bare: true, workflow: 'GEO 工作台', perm: 'geo.content' },
    children: [
      { path: 'overview', component: () => import('../views/geo/GeoOverviewView.vue'), meta: { title: 'GEO 概览', documentTitle: 'GEO 工作台｜GEO 概览' } },
      { path: 'visibility', component: () => import('../views/geo/GeoVisibilityDashView.vue'), meta: { title: 'AI 可见度', documentTitle: 'GEO 工作台｜AI 可见度' } },
      { path: 'visibility/snapshots', component: () => import('../views/geo/GeoVisibilityView.vue'), meta: { title: '采集与判断', documentTitle: 'GEO 工作台｜采集与判断' } },
      { path: 'questions', component: () => import('../views/geo/GeoPromptsView.vue'), meta: { title: '优化意图词', documentTitle: 'GEO 工作台｜优化意图词' } },
      { path: 'knowledge', component: () => import('../views/geo/GeoFactsView.vue'), meta: { title: '知识库', documentTitle: 'GEO 工作台｜知识库' } },
      { path: 'brand', component: () => import('../views/geo/GeoBrandSettingsView.vue'), meta: { title: '品牌资料', documentTitle: 'GEO 工作台｜品牌资料' } },
      { path: 'models', component: () => import('../views/geo/GeoEnginesView.vue'), meta: { title: '引擎', documentTitle: 'GEO 工作台｜引擎' } },
      { path: 'citations', component: () => import('../views/geo/GeoCitationsView.vue'), meta: { title: 'AI 引用次数', documentTitle: 'GEO 工作台｜AI 引用次数' } },
      { path: 'competitors', component: () => import('../views/geo/GeoCompetitorsView.vue'), meta: { title: '竞品分析', documentTitle: 'GEO 工作台｜竞品分析' } },
      { path: 'tasks', component: () => import('../views/geo/GeoTasksView.vue'), meta: { title: '优化文章', documentTitle: 'GEO 工作台｜优化文章' } },
      { path: 'tasks/:taskId', component: () => import('../views/geo/GeoTaskEditorView.vue'), meta: { title: '内容编辑器', documentTitle: 'GEO 工作台｜内容编辑器' } },
      { path: 'ai-settings', component: () => import('../views/geo/GeoAiSettingsView.vue'), meta: { title: 'AI 能力配置', documentTitle: 'GEO 工作台｜AI 能力配置' } },
      { path: 'channel-polish-prompts', component: () => import('../views/geo/GeoChannelPolishPromptsView.vue'), meta: { title: '渠道成稿提示词', documentTitle: 'GEO 工作台｜渠道成稿提示词' } },
      { path: 'publishing', component: () => import('../views/geo/GeoPublishingView.vue'), meta: { title: '分发平台', documentTitle: 'GEO 工作台｜分发平台' } },
      { path: 'placements', component: () => import('../views/geo/GeoPlacementsView.vue'), meta: { title: '信源策略', documentTitle: 'GEO 工作台｜信源策略' } },
      { path: 'keywords', redirect: '/geo/questions' },
      { path: 'recommend', redirect: '/geo/questions' },
      { path: 'answers', redirect: '/geo/visibility' },
      { path: 'permissions', redirect: '/geo/overview' },
      { path: 'geo-diagnosis', redirect: GEO_WORKBENCH_START },
      { path: 'visibility/evaluation', redirect: '/geo/visibility/snapshots' },
      { path: 'visibility/patrol', redirect: '/geo/visibility/snapshots' },
      { path: 'period-diff', redirect: '/geo/visibility' },
      { path: 'gaps', redirect: '/geo/questions' },
      { path: 'gap-workbench', redirect: '/geo/questions' },
      { path: 'periods', redirect: GEO_WORKBENCH_START },
      { path: 'topic-heat', redirect: '/geo/questions' },
      { path: 'ai-trends', redirect: GEO_WORKBENCH_START },
      { path: 'evaluation', redirect: '/geo/visibility' },
      { path: 'deliverables', redirect: GEO_WORKBENCH_START },
      { path: 'workbench', redirect: GEO_WORKBENCH_START },
      { path: 'businesses', redirect: '/geo/brand' },
      { path: 'businesses/:businessId', redirect: '/geo/brand' },
      { path: 'onboarding', redirect: GEO_WORKBENCH_START },
      { path: 'prompts', redirect: (to) => ({ path: '/geo/questions', query: to.query }) },
      { path: 'facts', redirect: '/geo/knowledge' },
      { path: 'engines', redirect: '/geo/models' },
    ],
  },
  {
    path: '/geo/deliverables/share/:shareToken',
    component: () => import('../views/geo/GeoDeliverableShareView.vue'),
    meta: { title: '交付摘要分享', documentTitle: 'GEO 交付摘要 · 只读分享', public: true, bare: true },
  },
  {
    path: '/geo/deliverables/share',
    redirect: (to) => {
      const token = to.query.token || to.query.share_token
      return token ? { path: `/geo/deliverables/share/${token}` } : { path: GEO_WORKBENCH_START }
    },
  },
  {
    path: '/seo',
    component: () => import('../views/seo/SeoWorkspaceShell.vue'),
    meta: { bare: true },
    children: [
      { path: '', redirect: '/seo/dashboard' },
      {
        path: 'dashboard',
        component: () => import('../views/seo/SeoDashboardView.vue'),
        meta: { title: 'SEO 工作台', workflow: '今日概览', perm: 'seo.dashboard', bare: true, immersive: true },
      },
      {
        path: 'alerts',
        component: () => import('../views/seo/SeoAlertsView.vue'),
        meta: { title: '异常提醒', workflow: '数据看板', perm: 'seo.alerts', bare: true },
      },
      {
        path: 'brand-assets',
        component: () => import('../views/seo/SeoBrandAssetsView.vue'),
        meta: { title: '品牌资产中心', workflow: '基础资产', perm: 'seo.keywords', bare: true },
      },
      {
        path: 'keywords',
        component: () => import('../views/seo/SeoKeywordAssetsView.vue'),
        meta: { title: '关键词管理', workflow: '关键词资产', perm: 'seo.keywords', bare: true, immersive: true },
      },
      {
        path: 'keywords/:keywordId',
        component: () => import('../views/seo/SeoKeywordDetailView.vue'),
        meta: { title: '关键词详情', workflow: '关键词资产', perm: 'seo.keywords', bare: true },
      },
      {
        path: 'rankings',
        component: () => import('../views/seo/SeoRankingMonitorView.vue'),
        meta: { title: '排名监控', workflow: '关键词资产', perm: 'seo.keywords', bare: true },
      },
      {
        path: 'trends',
        component: () => import('../views/seo/SeoTrendsView.vue'),
        meta: { title: '趋势总览', workflow: '关键词资产', perm: 'seo.keywords', bare: true },
      },
      {
        path: 'site',
        component: () => import('../views/seo/SeoSiteOptimizationView.vue'),
        meta: { title: '站内优化', workflow: '站内增长', perm: 'seo.site', bare: true },
      },
      {
        path: 'content',
        redirect: '/seo/content/articles',
      },
      {
        path: 'content/articles',
        component: () => import('../views/seo/SeoContentView.vue'),
        meta: { title: '原创文章', workflow: '内容增长', contentMode: 'article', perm: 'seo.content', bare: true, immersive: true },
      },
      {
        path: 'content/rewrites',
        component: () => import('../views/seo/SeoRewriteView.vue'),
        meta: { title: '文章改写', workflow: '内容增长', contentMode: 'rewrite', perm: 'seo.content', bare: true, immersive: true },
      },
      {
        path: 'content/qa',
        component: () => import('../views/seo/SeoContentView.vue'),
        meta: { title: '问答运营', workflow: '内容增长', contentMode: 'qa', perm: 'seo.content', bare: true, immersive: true },
      },
      {
        path: 'content/editor',
        component: () => import('../views/seo/SeoContentEditorView.vue'),
        meta: { title: '在线编辑器', workflow: '内容增长', perm: 'seo.content', bare: true, immersive: true },
      },
      {
        path: 'content/answer-editor',
        component: () => import('../views/seo/SeoContentEditorView.vue'),
        meta: { title: '问答编辑器', workflow: '内容增长', perm: 'seo.content', bare: true, immersive: true },
      },
      {
        path: 'distribution',
        component: () => import('../views/seo/SeoDistributionView.vue'),
        meta: { title: '分发平台', workflow: '内容增长', perm: 'seo.content', bare: true },
      },
      {
        path: 'links',
        component: () => import('../views/seo/SeoLinksView.vue'),
        meta: { title: '内外链管理', workflow: '站内增长', perm: 'seo.links', bare: true },
      },
      {
        path: 'competitors',
        component: () => import('../views/seo/SeoCompetitorsView.vue'),
        meta: { title: '竞品监控', workflow: '竞品市场', perm: 'seo.competitors', bare: true },
      },
    ],
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
  ['geo.diagnosis', '/geo/diagnosis'],
  ['seo.dashboard', '/seo/dashboard'],
  ['seo.alerts', '/seo/alerts'],
  ['seo.keywords', '/seo/keywords'],
  ['seo.content', '/seo/content'],
  ['seo.site', '/seo/site'],
  ['seo.links', '/seo/links'],
  ['seo.competitors', '/seo/competitors'],
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
router.beforeEach((to) => {
  const devBypass = !session.isLoggedIn && import.meta.env.VITE_API_KEY && import.meta.env.DEV
  if (!to.meta.public && !session.isLoggedIn && !devBypass) {
    window.location.assign(loginUrl(to.fullPath))
    return false
  }
  if (devBypass || !session.isLoggedIn) return
  if (!to.meta.public && !permOk(to.meta.perm)) {
    const dest = firstAllowedPath()
    if (dest && dest !== to.path) return { path: dest }
    if (!dest) return
  }
})
router.afterEach((to) => {
  const productName = to.path.startsWith('/geo') ? 'GEO 工作台' : (to.path.startsWith('/seo') ? 'SEO 工作台' : 'SEM 智投平台')
  document.title = to.meta.documentTitle || (to.meta.title ? to.meta.title + ' · ' : '') + productName
})
export default router
