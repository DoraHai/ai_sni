import { createRouter, createWebHistory } from 'vue-router'
import { ElMessage } from 'element-plus'
import { clearChunkRecoveryMarker, isChunkLoadError, recoverFromChunkLoadError } from './chunkRecovery'
import { session } from '../store/session'
import { loginUrl } from '../auth/loginRedirect'

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
    component: () => import('../views/diagnosis/DiagnosisCenterView.vue'),
    meta: {
      title: '网站体检',
      documentTitle: '诊断中心｜网站体检',
      workflow: '诊断中心',
      perm: 'geo.diagnosis',
    },
  },
  {
    path: '/diagnostic-center',
    redirect: '/geo/diagnosis',
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
    meta: { title: '授权与同步', workflow: '首次接入', perm: ['onboarding', 'settings.customers'] },
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
    meta: { title: '待验证调价', workflow: '效果验证', perm: ['verify.pending', 'verify.adjustments'] },
  },
  {
    path: '/verify/leads',
    component: () => import('../views/verify/LeadsView.vue'),
    meta: { title: '线索管理', workflow: '效果验证', perm: 'verify.leads' },
  },
  { path: '/manage', redirect: '/manage/account' },
  {
    path: '/sem/accounts',
    component: () => import('../views/manage/SemAccountsView.vue'),
    meta: { title: '推广账号', workflow: '投放管理', perm: 'sem.assets' },
  },
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
  { path: '/settings/users', redirect: '/settings/accounts' },
  {
    path: '/settings/customers',
    component: () => import('../views/settings/CustomerModulesView.vue'),
    meta: { title: '客户与模块', workflow: '系统设置', perm: 'settings.customers' },
  },
  { path: '/settings', redirect: '/settings/accounts' },
  {
    path: '/workspace',
    component: () => import('../views/workspace/ModuleWorkspaceView.vue'),
    meta: { title: '我的工作台' },
  },
  { path: '/sem/plans', redirect: '/manage/campaigns' },
  { path: '/admin/internal', redirect: '/settings/accounts' },
  {
    path: '/:pathMatch(.*)*',
    component: () => import('../views/NotFoundView.vue'),
    meta: { title: '页面不存在' },
  },
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
  ['sem.assets', '/sem/accounts'],
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
  ['settings.customers', '/settings/customers'],
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
    const permission = Array.isArray(to.meta.perm) ? to.meta.perm.join(' / ') : to.meta.perm
    ElMessage.warning(`当前账号没有“${to.meta.title || '该页面'}”权限（需要 ${permission}）。请让管理员在「账号与权限」中为你的角色开通。`)
    if (dest && dest !== to.path) return { path: dest }
    return { path: '/workspace' }
  }
})
router.afterEach((to) => {
  clearChunkRecoveryMarker()
  const productName = to.path.startsWith('/seo') ? 'SEO 工作台' : 'SEM 智投平台'
  document.title = to.meta.documentTitle || (to.meta.title ? to.meta.title + ' · ' : '') + productName
})
router.onError((error) => {
  if (recoverFromChunkLoadError(error)) return
  if (isChunkLoadError(error)) {
    ElMessage.error('系统版本已更新，请手动刷新页面后重试')
    return
  }
  ElMessage.error(`页面加载失败：${error.message || '请刷新后重试'}`)
})
window.addEventListener('vite:preloadError', (event) => {
  if (recoverFromChunkLoadError(event.payload)) event.preventDefault()
})
export default router
