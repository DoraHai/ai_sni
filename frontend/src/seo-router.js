import { createRouter, createWebHistory } from 'vue-router'
import { loginUrl } from './auth/loginRedirect'
import { session } from './store/session'

const seoChildren = [
  { path: '', redirect: '/seo/dashboard' },
  {
    path: 'sites',
    component: () => import('./views/seo/SeoSitesView.vue'),
    meta: { title: '网站管理', workflow: '基础资产', perm: 'seo.assets' },
  },
  {
    path: 'dashboard',
    component: () => import('./views/seo/SeoDashboardView.vue'),
    meta: { title: 'SEO 工作台', workflow: '今日概览', perm: 'seo.dashboard', immersive: true },
  },
  {
    path: 'alerts',
    component: () => import('./views/seo/SeoAlertsView.vue'),
    meta: { title: '异常提醒', workflow: '数据看板', perm: 'seo.alerts' },
  },
  {
    path: 'brand-assets',
    component: () => import('./views/seo/SeoBrandAssetsView.vue'),
    meta: { title: '品牌资产中心', workflow: '基础资产', perm: 'seo.keywords' },
  },
  {
    path: 'keywords',
    component: () => import('./views/seo/SeoKeywordAssetsView.vue'),
    meta: { title: '关键词管理', workflow: '关键词资产', perm: 'seo.keywords', immersive: true },
  },
  {
    path: 'keywords/:keywordId',
    component: () => import('./views/seo/SeoKeywordDetailView.vue'),
    meta: { title: '关键词详情', workflow: '关键词资产', perm: 'seo.keywords' },
  },
  {
    path: 'rankings',
    component: () => import('./views/seo/SeoRankingMonitorView.vue'),
    meta: { title: '排名监控', workflow: '关键词资产', perm: 'seo.keywords' },
  },
  {
    path: 'trends',
    component: () => import('./views/seo/SeoTrendsView.vue'),
    meta: { title: '趋势总览', workflow: '关键词资产', perm: 'seo.keywords' },
  },
  {
    path: 'site',
    component: () => import('./views/seo/SeoSiteOptimizationView.vue'),
    meta: { title: '站内优化', workflow: '站内增长', perm: 'seo.site' },
  },
  { path: 'content', redirect: '/seo/content/articles' },
  {
    path: 'content/articles',
    component: () => import('./views/seo/SeoContentView.vue'),
    meta: { title: '原创文章', workflow: '内容增长', contentMode: 'article', perm: 'seo.content', immersive: true },
  },
  {
    path: 'content/rewrites',
    component: () => import('./views/seo/SeoRewriteView.vue'),
    meta: { title: '文章改写', workflow: '内容增长', contentMode: 'rewrite', perm: 'seo.content', immersive: true },
  },
  {
    path: 'content/qa',
    component: () => import('./views/seo/SeoContentView.vue'),
    meta: { title: '问答运营', workflow: '内容增长', contentMode: 'qa', perm: 'seo.content', immersive: true },
  },
  {
    path: 'content/editor',
    component: () => import('./views/seo/SeoContentEditorView.vue'),
    meta: { title: '在线编辑器', workflow: '内容增长', perm: 'seo.content', immersive: true },
  },
  {
    path: 'content/answer-editor',
    component: () => import('./views/seo/SeoContentEditorView.vue'),
    meta: { title: '问答编辑器', workflow: '内容增长', perm: 'seo.content', immersive: true },
  },
  {
    path: 'distribution',
    component: () => import('./views/seo/SeoDistributionView.vue'),
    meta: { title: '分发平台', workflow: '内容增长', perm: 'seo.content' },
  },
  {
    path: 'links',
    component: () => import('./views/seo/SeoLinksView.vue'),
    meta: { title: '内外链管理', workflow: '站内增长', perm: 'seo.links' },
  },
  {
    path: 'competitors',
    component: () => import('./views/seo/SeoCompetitorsView.vue'),
    meta: { title: '竞品监控', workflow: '竞品市场', perm: 'seo.competitors' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/seo/dashboard' },
    {
      path: '/seo',
      component: () => import('./views/seo/SeoWorkspaceShell.vue'),
      children: seoChildren,
    },
    { path: '/:pathMatch(.*)*', redirect: '/seo/dashboard' },
  ],
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) return savedPosition
    if (to.hash) return { el: to.hash, behavior: 'smooth' }
    return { top: 0 }
  },
})

const SEO_MENU_ORDER = [
  ['seo.assets', '/seo/sites'],
  ['seo.dashboard', '/seo/dashboard'],
  ['seo.alerts', '/seo/alerts'],
  ['seo.keywords', '/seo/keywords'],
  ['seo.content', '/seo/content/articles'],
  ['seo.site', '/seo/site'],
  ['seo.links', '/seo/links'],
  ['seo.competitors', '/seo/competitors'],
]

function firstAllowedSeoPath() {
  return SEO_MENU_ORDER.find(([permission]) => session.canView(permission))?.[1] || null
}

router.beforeEach((to) => {
  const devBypass = !session.isLoggedIn && import.meta.env.VITE_API_KEY && import.meta.env.DEV
  if (!session.isLoggedIn && !devBypass) {
    window.location.assign(loginUrl(to.fullPath))
    return false
  }
  if (devBypass || !to.meta.perm || session.canView(to.meta.perm)) return true
  const destination = firstAllowedSeoPath()
  if (destination && destination !== to.path) return { path: destination }
  return false
})

router.afterEach((to) => {
  const productName = 'SEO 工作台'
  document.title = !to.meta.title || to.meta.title === productName
    ? productName
    : `${to.meta.title} · ${productName}`
})

export default router
