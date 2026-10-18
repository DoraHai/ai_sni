// Preserve the captured customer scope and reject stale workspace actions.
export function prepareAdvisorSeoRequest(config, actor, confirmAction = globalThis.confirm) {
  if (!actor.isAdvisorSession || !config.url?.startsWith('/api/v1/seo/')) return config
  const url = new URL(config.url, 'https://local.invalid')
  const params = config.params instanceof URLSearchParams
    ? Object.fromEntries(config.params) : { ...config.params }
  const body = config.data instanceof FormData ? config.data.get('tenant_id') : config.data?.tenant_id
  const scopes = [params.tenant_id, url.searchParams.get('tenant_id'), body].filter(v => v != null)
  const selected = Number(actor.tenantId)
  if (!Number.isSafeInteger(selected) || selected < 1 || scopes.some(v => Number(v) !== selected)) {
    throw new Error('客户选择已变化，请刷新当前页面后再操作')
  }
  config.params = { ...params, tenant_id: selected }
  const method = (config.method || 'get').toLowerCase()
  const deleting = method === 'delete'
  const sending = method === 'post' && (
    /^\/api\/v1\/seo\/content-distribution\/publish$/.test(url.pathname)
    || /^\/api\/v1\/seo\/content-distribution\/publications\/\d+\/(retry|complete)$/.test(url.pathname)
    || /^\/api\/v1\/seo\/content-distribution\/video\/publications\/\d+\/publish$/.test(url.pathname)
    || /^\/api\/v1\/seo\/content-assets\/offline-handoff\/(export|import-receipts)$/.test(url.pathname)
    || /^\/api\/v1\/seo\/qa\/placements\/\d+\/(receipt|assistant-receipt)$/.test(url.pathname)
  )
  if ((deleting || sending) && !confirmAction(deleting
    ? '确定删除当前客户的这条记录？删除后不能恢复。'
    : '确定为当前客户发布或提交这次外发操作？请先核对稿件版本、账号和发布结果。')) {
    throw new Error('已取消操作')
  }
  return config
}
