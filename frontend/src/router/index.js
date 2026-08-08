import { createRouter, createWebHistory } from 'vue-router'
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
  document.title =
    to.meta.documentTitle || (to.meta.title ? to.meta.title + ' · ' : '') + 'SEM 智投平台'
})
export default router
