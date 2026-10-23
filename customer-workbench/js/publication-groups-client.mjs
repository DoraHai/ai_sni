// Client-only, read-only publication projection. No URL/title identity inference.
export const positiveId = value => (typeof value === 'number' && Number.isSafeInteger(value) && value > 0);
const count = value => Number.isSafeInteger(value) && value >= 0;
const fail = (code = 'PUBLICATION_RESPONSE_INVALID', status) => { throw Object.assign(Error(code), {code, status}); };
export const publicationContextKey = (module, c) => JSON.stringify([module, c?.connected, c?.userId, c?.tenantId, module === 'seo' ? c?.siteId : c?.projectId, c?.revision]);
export function publicationGroupQuery(params) {
  if (Object.keys(params).some(k => !['bucket', 'article_id', 'limit', 'cursor'].includes(k))) return false;
  if (params.bucket != null && !['linked', 'unlinked'].includes(params.bucket)) return false;
  if (params.article_id != null && (!positiveId(Number(params.article_id)) || !/^[1-9]\d*$/.test(String(params.article_id)) || (params.bucket ?? 'linked') !== 'linked')) return false;
  if (params.limit != null && (!/^[1-9]\d*$/.test(String(params.limit)) || !positiveId(Number(params.limit)) || Number(params.limit) > 100)) return false;
  if (params.cursor != null && (typeof params.cursor !== 'string' || !params.cursor.trim() || params.cursor.length > 4096)) return false;
  return true;
}
export function publicationGroupKey(module, context, articleId) {
  const scope = module === 'seo' ? context.siteId : context.projectId;
  if (!['seo', 'geo'].includes(module) || ![context.tenantId, scope, articleId].every(positiveId)) fail();
  return JSON.stringify([module, context.tenantId, scope, articleId]);
}
export function publicationDetailKey(module, item) {
  if (item.source === 'native' && positiveId(item.native_publication_id) && item.external_receipt_id == null) return `native:${module}:${item.native_publication_id}`;
  if (item.source === 'external' && item.native_publication_id == null && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(item.external_receipt_id)) return `external:${item.external_receipt_id}`;
  fail();
}
export function appendUnique(previous, items, key) {
  const map = new Map(previous.map(v => [key(v), v]));
  for (const item of items) map.set(key(item), item);
  return [...map.values()];
}
export function validatePublicationPage(value, module, context, params) {
  const c = value?.context, scope = module === 'seo' ? context.siteId : context.projectId;
  if (value?.schema !== 'publication-groups.v1' || value.read_only !== true || c?.module !== module || c.tenant_id !== context.tenantId || c.scope_id !== scope || c.bucket !== (params.bucket ?? 'linked') || (c.article_id ?? null) !== (params.article_id ?? null)) fail();
  if (!Array.isArray(value.items) || typeof value.has_more !== 'boolean' || (value.has_more ? typeof value.next_cursor !== 'string' || !value.next_cursor.trim() : value.next_cursor !== null) || value.completeness?.complete !== true) fail();
  if (!['native_records', 'external_records', 'article_groups', 'unlinked_records'].every(k => count(value.counts?.[k]))) fail();
  for (const item of value.items) {
    if (c.bucket === 'unlinked') {
      if (item.group_article_id !== null || item.source !== 'external') fail();
      publicationDetailKey(module, item);
    } else {
      publicationGroupKey(module, context, item.group_article_id);
      if (params.article_id != null) {
        if (item.group_article_id !== params.article_id || (module === 'geo' ? item.task_id !== params.article_id || item.content_id !== null : item.content_id !== params.article_id || item.task_id !== null)) fail();
        if (item.article_version_id != null && (!positiveId(item.article_version_id) || module !== 'geo' || item.source !== 'native')) fail();
        if (item.article_version_no != null && !positiveId(item.article_version_no)) fail();
        publicationDetailKey(module, item);
      } else if (!count(item.native_count) || !count(item.external_count) || typeof item.title !== 'string') fail();
    }
  }
  return value;
}
export function createPublicationGroupsClient({module, transport, getContext}) {
  if (!['seo', 'geo'].includes(module)) fail('PUBLICATION_ROUTE_DENIED');
  let generation = 0;
  const pending = new Set();
  return {
    invalidate() { generation++; for (const c of pending) c.abort(); pending.clear(); },
    async read(params = {}) {
      if (!publicationGroupQuery(params)) fail('PUBLICATION_QUERY_DENIED');
      const context = {...getContext()}, stamp = generation, key = publicationContextKey(module, context);
      if (!context.connected || ![context.tenantId, context.userId, module === 'seo' ? context.siteId : context.projectId].every(positiveId)) fail('PUBLICATION_CONTEXT_CHANGED');
      const current = () => { if (generation !== stamp || key !== publicationContextKey(module, getContext())) fail('PUBLICATION_CONTEXT_CHANGED'); };
      const query = new URLSearchParams({tenant_id: context.tenantId, ...(module === 'seo' ? {site_id: context.siteId} : {}), ...params});
      const path = module === 'seo' ? '/api/v1/seo/workbench/publication-groups' : `/api/v1/geo/projects/${context.projectId}/client/publication-groups`;
      const controller = new AbortController(); pending.add(controller);
      try {
        const response = await transport(path + '?' + query, {method: 'GET', signal: controller.signal});
        current();
        if (!response.ok) fail([409, 422].includes(response.status) ? 'PUBLICATION_REFRESH_REQUIRED' : 'PUBLICATION_READ_FAILED', response.status);
        const value = await response.json(); current();
        return validatePublicationPage(value, module, context, params);
      } catch (e) { current(); throw e; } finally { pending.delete(controller); }
    },
  };
}
