import { createRouter, createWebHashHistory } from 'vue-router'
import { session } from '../../src/store/session'

const geoMeta = (title, extra = {}) => ({
  title,
  workflow: 'GEO 增长',
  perm: 'geo.content',
  ...extra,
})

const routes = [
  { path: '/', redirect: '/geo/businesses' },
  { path: '/geo', redirect: '/geo/businesses' },
  { path: '/geo/businesses', component: () => import('../../src/views/geo/GeoBusinessesView.vue'), meta: geoMeta('优化业务') },
  { path: '/geo/businesses/:businessId', component: () => import('../../src/views/geo/GeoBusinessDetailView.vue'), meta: geoMeta('业务详情') },
  { path: '/geo/onboarding', component: () => import('../../src/views/geo/GeoOnboardingView.vue'), meta: geoMeta('GEO 开户向导') },
  { path: '/geo/prompts', component: () => import('../../src/views/geo/GeoPromptsView.vue'), meta: geoMeta('优化意图词') },
  { path: '/geo/gaps', component: () => import('../../src/views/geo/GeoGapWorkbenchView.vue'), meta: geoMeta('缺口工作台') },
  { path: '/geo/facts', component: () => import('../../src/views/geo/GeoFactsView.vue'), meta: geoMeta('事实库') },
  { path: '/geo/tasks', component: () => import('../../src/views/geo/GeoTasksView.vue'), meta: geoMeta('优化文章') },
  { path: '/geo/tasks/:taskId', component: () => import('../../src/views/geo/GeoTaskEditorView.vue'), meta: geoMeta('内容编辑器', { fluidMain: true }) },
  { path: '/geo/publishing', component: () => import('../../src/views/geo/GeoPublishingView.vue'), meta: geoMeta('发布渠道') },
  { path: '/geo/placements', component: () => import('../../src/views/geo/GeoPlacementsView.vue'), meta: geoMeta('媒体阵地') },

  { path: '/geo/overview', component: () => import('../../src/views/geo/GeoOverviewView.vue'), meta: geoMeta('GEO 概览') },
  { path: '/geo/visibility', component: () => import('../../src/views/geo/GeoVisibilityView.vue'), meta: geoMeta('AI 可见度') },
  { path: '/geo/visibility/patrol', component: () => import('../../src/views/geo/GeoVisibilityPatrolView.vue'), meta: geoMeta('全自动巡检') },
  { path: '/geo/periods', component: () => import('../../src/views/geo/GeoPeriodsView.vue'), meta: geoMeta('优化期次') },
  { path: '/geo/period-diff', component: () => import('../../src/views/geo/GeoPeriodDiffView.vue'), meta: geoMeta('期次对比') },
  { path: '/geo/citations', component: () => import('../../src/views/geo/GeoCitationsView.vue'), meta: geoMeta('AI 引用分析') },
  { path: '/geo/competitors', component: () => import('../../src/views/geo/GeoCompetitorsView.vue'), meta: geoMeta('竞品监测') },
  { path: '/geo/evaluation', component: () => import('../../src/views/geo/GeoEvaluationView.vue'), meta: geoMeta('评价与位置') },
  { path: '/geo/topic-heat', component: () => import('../../src/views/geo/GeoTopicHeatView.vue'), meta: geoMeta('话题覆盖热度') },
  { path: '/geo/deliverables', component: () => import('../../src/views/geo/GeoDeliverablesView.vue'), meta: geoMeta('交付摘要') },
  {
    path: '/geo/deliverables/share/:shareToken',
    component: () => import('../../src/views/geo/GeoDeliverableShareView.vue'),
    meta: geoMeta('交付摘要分享', { public: true, bare: true }),
  },

  { path: '/geo/engines', component: () => import('../../src/views/geo/GeoEnginesView.vue'), meta: geoMeta('引擎配置') },
  { path: '/geo/ai-settings', component: () => import('../../src/views/geo/GeoAiSettingsView.vue'), meta: geoMeta('AI 配置') },
  { path: '/geo/channel-polish-prompts', component: () => import('../../src/views/geo/GeoChannelPolishPromptsView.vue'), meta: geoMeta('渠道成稿提示词') },
  { path: '/geo/ai-trends', component: () => import('../../src/views/geo/GeoAiTrendsView.vue'), meta: geoMeta('AI 动态与策略') },
  { path: '/:pathMatch(.*)*', redirect: '/geo/businesses' },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach((to) => {
  const devBypass = !session.isLoggedIn && import.meta.env.VITE_API_KEY && import.meta.env.DEV
  if (!to.meta.public && !session.isLoggedIn && !devBypass) {
    const redirect = encodeURIComponent(window.location.href)
    window.location.assign(`/login?redirect=${redirect}`)
    return false
  }
})

router.afterEach((to) => {
  document.title = `${to.meta.title || '工作台'} · GEO 增长`
})

export default router
