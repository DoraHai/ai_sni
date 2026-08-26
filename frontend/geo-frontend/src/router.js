import { createRouter, createWebHashHistory } from 'vue-router'
import { session } from '../../src/store/session'
import { GEO_WORKBENCH_START } from '../../src/utils/geoPrototypeNavigation'

const geoMeta = (title, extra = {}) => ({
  title,
  workflow: 'GEO 工作台',
  perm: 'geo.content',
  ...extra,
})

const routes = [
  { path: '/', redirect: GEO_WORKBENCH_START },
  {
    path: '/geo',
    component: () => import('../../src/views/geo/GeoWorkspaceShell.vue'),
    redirect: GEO_WORKBENCH_START,
    meta: geoMeta('GEO 工作台', { bare: true }),
    children: [
      { path: 'overview', component: () => import('../../src/views/geo/GeoOverviewView.vue'), meta: geoMeta('GEO 概览') },
      { path: 'visibility', component: () => import('../../src/views/geo/GeoVisibilityDashView.vue'), meta: geoMeta('AI 可见度') },
      { path: 'visibility/snapshots', component: () => import('../../src/views/geo/GeoVisibilityView.vue'), meta: geoMeta('采集与判断') },
      { path: 'questions', component: () => import('../../src/views/geo/GeoPromptsView.vue'), meta: geoMeta('优化意图词') },
      { path: 'knowledge', component: () => import('../../src/views/geo/GeoFactsView.vue'), meta: geoMeta('知识库') },
      { path: 'brand', component: () => import('../../src/views/geo/GeoBrandSettingsView.vue'), meta: geoMeta('品牌资料') },
      { path: 'models', component: () => import('../../src/views/geo/GeoEnginesView.vue'), meta: geoMeta('引擎') },
      { path: 'citations', component: () => import('../../src/views/geo/GeoCitationsView.vue'), meta: geoMeta('AI 引用次数') },
      { path: 'competitors', component: () => import('../../src/views/geo/GeoCompetitorsView.vue'), meta: geoMeta('竞品分析') },
      { path: 'tasks', component: () => import('../../src/views/geo/GeoTasksView.vue'), meta: geoMeta('优化文章') },
      { path: 'tasks/:taskId', component: () => import('../../src/views/geo/GeoTaskEditorView.vue'), meta: geoMeta('内容编辑器', { fluidMain: true }) },
      { path: 'ai-settings', component: () => import('../../src/views/geo/GeoAiSettingsView.vue'), meta: geoMeta('AI 能力配置') },
      { path: 'channel-polish-prompts', component: () => import('../../src/views/geo/GeoChannelPolishPromptsView.vue'), meta: geoMeta('渠道成稿提示词') },
      { path: 'publishing', component: () => import('../../src/views/geo/GeoPublishingView.vue'), meta: geoMeta('分发平台') },
      { path: 'placements', component: () => import('../../src/views/geo/GeoPlacementsView.vue'), meta: geoMeta('信源策略') },
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
    component: () => import('../../src/views/geo/GeoDeliverableShareView.vue'),
    meta: geoMeta('交付摘要分享', { public: true, bare: true }),
  },
  {
    path: '/geo/deliverables/share',
    redirect: (to) => {
      const token = to.query.token || to.query.share_token
      return token ? { path: `/geo/deliverables/share/${token}` } : { path: GEO_WORKBENCH_START }
    },
  },
  { path: '/:pathMatch(.*)*', redirect: GEO_WORKBENCH_START },
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
