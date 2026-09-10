import { createRouter, createWebHashHistory } from 'vue-router'
import { session } from '../../src/store/session'
import { GEO_WORKBENCH_START } from '../../src/utils/geoPrototypeNavigation'
import { loginUrl } from '../../src/auth/loginRedirect'
import { geoLoginRedirectPath } from './authRedirect'
import { geoSessionRouteDecision } from './authRouteDecision'
import { GEO_DEMO_HOME, isGeoDemoIdentity } from '../../src/utils/geoDemoIdentity'

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
      { path: 'demo', redirect: GEO_DEMO_HOME },
      { path: 'demo/overview', component: () => import('../../src/views/geo/GeoDemoView.vue'), meta: geoMeta('GEO 演示总览') },
      { path: 'demo/questions', component: () => import('../../src/views/geo/GeoDemoView.vue'), meta: geoMeta('演示问题监测') },
      { path: 'demo/answers', component: () => import('../../src/views/geo/GeoDemoView.vue'), meta: geoMeta('演示回答与引用') },
      { path: 'demo/answers/:answerId', component: () => import('../../src/views/geo/GeoDemoView.vue'), meta: geoMeta('演示回答详情') },
      { path: 'demo/tasks', component: () => import('../../src/views/geo/GeoDemoView.vue'), meta: geoMeta('演示内容任务') },
      { path: 'demo/tasks/:taskId', component: () => import('../../src/views/geo/GeoDemoView.vue'), meta: geoMeta('演示任务详情') },
      { path: 'overview', component: () => import('../../src/views/geo/GeoOverviewView.vue'), meta: geoMeta('GEO 概览') },
      { path: 'visibility', component: () => import('../../src/views/geo/GeoVisibilityDashView.vue'), meta: geoMeta('AI 可见度') },
      { path: 'visibility/snapshots', component: () => import('../../src/views/geo/GeoVisibilityView.vue'), meta: geoMeta('采集与判断') },
      { path: 'questions', component: () => import('../../src/views/geo/GeoAskManageView.vue'), meta: geoMeta('提问监控') },
      { path: 'knowledge', component: () => import('../../src/views/geo/GeoFactsView.vue'), meta: geoMeta('知识库') },
      { path: 'brand', component: () => import('../../src/views/geo/GeoBrandSettingsView.vue'), meta: geoMeta('品牌信息') },
      { path: 'models', component: () => import('../../src/views/geo/GeoEnginesView.vue'), meta: geoMeta('AI 引擎管理') },
      { path: 'citations', component: () => import('../../src/views/geo/GeoCitationsView.vue'), meta: geoMeta('信源分析') },
      { path: 'competitors', component: () => import('../../src/views/geo/GeoCompetitorsView.vue'), meta: geoMeta('竞品分析') },
      { path: 'tasks', component: () => import('../../src/views/geo/GeoTasksView.vue'), meta: geoMeta('GEO 文章') },
      { path: 'tasks/:taskId/distribution', component: () => import('../../src/views/geo/GeoDistributionView.vue'), meta: geoMeta('分发记录') },
      { path: 'tasks/:taskId', component: () => import('../../src/views/geo/GeoTaskEditorView.vue'), meta: geoMeta('内容编辑器', { fluidMain: true }) },
      { path: 'ai-settings', redirect: GEO_WORKBENCH_START },
      { path: 'channel-polish-prompts', component: () => import('../../src/views/geo/GeoChannelPolishPromptsView.vue'), meta: geoMeta('渠道成稿提示词') },
      { path: 'publishing', component: () => import('../../src/views/geo/GeoChannelsView.vue'), meta: geoMeta('分发平台') },
      { path: 'placements', component: () => import('../../src/views/geo/GeoPlacementsView.vue'), meta: geoMeta('媒体 / 信源策略') },
      { path: 'structure', component: () => import('../../src/views/geo/GeoStructureView.vue'), meta: geoMeta('官网结构优化') },
      { path: 'import', component: () => import('../../src/views/geo/GeoArticleImportView.vue'), meta: geoMeta('导入已有文章') },
      { path: 'tickets', component: () => import('../../src/views/geo/GeoTicketsView.vue'), meta: geoMeta('验收工单') },
      { path: 'evaluation', component: () => import('../../src/views/geo/GeoEvaluationView.vue'), meta: geoMeta('评价分析') },
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
      { path: 'deliverables', redirect: GEO_WORKBENCH_START },
      { path: 'workbench', redirect: GEO_WORKBENCH_START },
      { path: 'businesses', redirect: '/geo/brand' },
      { path: 'businesses/:businessId', redirect: '/geo/brand' },
      { path: 'onboarding', redirect: GEO_WORKBENCH_START },
      { path: 'prompts', redirect: (to) => ({ path: '/geo/questions', query: to.query }) },
      { path: 'facts', redirect: '/geo/knowledge' },
      { path: 'engines', redirect: '/geo/models' },
      { path: 'articles', redirect: '/geo/tasks' },
      { path: 'articles/:taskId/distribution', redirect: (to) => ({ path: `/geo/tasks/${to.params.taskId}/distribution`, query: to.query }) },
      { path: 'articles/:taskId', redirect: (to) => ({ path: `/geo/tasks/${to.params.taskId}`, query: to.query }) },
      { path: 'sources', redirect: '/geo/citations' },
      { path: 'media', redirect: '/geo/placements' },
      { path: 'channels', redirect: '/geo/publishing' },
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

function sessionRouteDecision(to) {
  const devBypass = !session.isLoggedIn && import.meta.env.VITE_API_KEY && import.meta.env.DEV
  return geoSessionRouteDecision({
    route: to,
    session,
    devBypass,
    redirectToLogin: () => window.location.assign(loginUrl(geoLoginRedirectPath())),
    leaveWorkspace: () => {
      window.location.assign('/deal-sniper/portal')
      return false
    },
  })
}

router.beforeEach((to) => {
  const decision = sessionRouteDecision(to)
  if (decision !== true) return decision
  if (
    isGeoDemoIdentity(session.user, session.tenantId)
    && to.path.startsWith('/geo')
    && !to.meta.public
    && !to.path.startsWith('/geo/demo')
  ) return GEO_DEMO_HOME
  return true
})

export function revalidateSessionRoute() {
  return sessionRouteDecision(router.currentRoute.value)
}

router.afterEach((to) => {
  document.title = `${to.meta.title || '工作台'} · GEO 增长`
})

export default router
