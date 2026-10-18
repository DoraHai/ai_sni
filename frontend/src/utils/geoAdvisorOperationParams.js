// Exact operational endpoints that require a project when no content ID is supplied.
const PROJECT_PATHS = new Set([
  '/prompts/expand-candidates', '/answer-snapshots/extract-urls', '/answer-snapshots/suggest-fields',
  '/answer-snapshots/check-citations', '/visibility-patrol/runs/cleanup', '/competitor-insights/web-search',
  '/competitor-insights/report', '/competitor-aliases', '/publishing-channels',
  '/publishing-channels/enable-multi-media-auto', '/oauth/social/refresh', '/channel-polish-prompts',
  '/audits', '/structure-scan', '/action-tickets', '/onboarding/preview', '/onboarding/apply',
  '/onboarding/sitemap-audit', '/onboarding/sitemap-audit/create-tasks', '/daily-metrics/rebuild',
  '/attribution/backfill', '/monitoring-stance', '/deliverables/archives', '/content-imports/preview-url',
  '/integration/tasks',
])
const OBJECT_PATHS = [
  /^\/publishing-channels\/[1-9]\d*$/, /^\/channel-accounts\/[1-9]\d*\/verify-social$/,
  /^\/action-tickets\/[1-9]\d*(?:\/(?:verify|prepare-content|execution))?$/,
]

export function advisorOperationParams(config, { advisor, tenantId, projectId }) {
  if (!advisor || !Number.isSafeInteger(tenantId) || tenantId <= 0) return config
  const prefix = '/api/v1/geo'
  const path = String(config.url || '').split('?')[0]
  const method = String(config.method || 'get').toLowerCase()
  if (!path.startsWith(prefix + '/') || !['post', 'put', 'patch', 'delete'].includes(method)) return config
  const params = { ...(config.params || {}) }
  if (params.tenant_id == null) params.tenant_id = tenantId
  const suffix = path.slice(prefix.length)
  if ((PROJECT_PATHS.has(suffix) || OBJECT_PATHS.some((pattern) => pattern.test(suffix)))
      && params.project_id == null && Number.isSafeInteger(projectId) && projectId > 0) params.project_id = projectId
  return { ...config, params }
}
