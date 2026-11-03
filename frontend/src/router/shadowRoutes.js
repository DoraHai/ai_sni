const view = () => import('../views/onboarding/ShadowPlanningView.vue')
export const shadowRoutes = [
  { path: '/onboarding/sem-shadow', component: view, meta: { title: 'SEM 影子规划', workflow: '首次接入', shadowPage: 'entry' } },
  { path: '/onboarding/sem-shadow/submit', component: view, meta: { title: '提交落地页', workflow: '首次接入', shadowPage: 'submit' } },
  { path: '/onboarding/sem-shadow/plans', component: view, meta: { title: '影子规划', workflow: '首次接入', shadowPage: 'plans' } },
  { path: '/onboarding/sem-shadow/plans/:planId', component: view, meta: { title: '规划详情', workflow: '首次接入', shadowPage: 'plans' } },
  { path: '/onboarding/sem-shadow/plans/:planId/export', component: view, meta: { title: '导出 Excel', workflow: '首次接入', shadowPage: 'export' } },
  { path: '/settings/sem-account-grants', component: view, meta: { title: '账户授权管理', workflow: '系统设置', perm: 'settings.accounts', shadowPage: 'grants' } },
]
