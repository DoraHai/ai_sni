// CONTRACT v1: exact project GET routes, with no tenant-only fallback.
const weekly = ['week_end'],
  page = ['limit', 'cursor'];
const routes = [
  [/^overview$/, weekly],
  [/^visibility$/, weekly],
  [/^questions$/, [...weekly, ...page, 'status', 'is_brand_probe', 'attention', 'q']],
  [/^questions\/([1-9]\d*)$/, weekly],
  [/^answers$/, [...weekly, ...page, 'question_id', 'engine_key', 'source_kind', 'eligibility']],
  [/^answers\/([1-9]\d*)$/, weekly],
  [/^content$/, [...page, 'question_id', 'review_status', 'include_archived', 'q']],
  [/^content\/([1-9]\d*)$/, []],
  [/^content\/([1-9]\d*)\/variants$/, page],
  [/^content\/([1-9]\d*)\/variants\/([1-9]\d*)$/, []],
  [/^content\/([1-9]\d*)\/articles\/([1-9]\d*)$/, []],
  [/^deliveries$/, [...page, 'task_id', 'record_type']],
];
export const geoPositive = (value) =>
  /^[1-9]\d*$/.test(String(value)) && Number.isSafeInteger(Number(value));
export function geoClientRoute(pathname) {
  const match = pathname.match(/^\/api\/v1\/geo\/projects\/([1-9]\d*)\/(client\/(.+)|executions)$/);
  if (!match || !geoPositive(match[1])) return null;
  if (match[2] === 'executions')
    return {projectId: Number(match[1]), keys: ['tenant_id'], executions: true};
  for (const [pattern, keys] of routes) {
    const m = match[3].match(pattern);
    if (m && m.slice(1).every(geoPositive))
      return {projectId: Number(match[1]), keys: ['tenant_id', ...keys]};
  }
  return null;
}
export function geoClientQuery(url, route, context) {
  if (
    route.projectId !== context.projectId ||
    url.searchParams.get('tenant_id') !== String(context.tenantId)
  )
    return false;
  const enums = {
    status: ['all', 'active', 'inactive', 'archived'],
    is_brand_probe: ['true', 'false'],
    attention: ['all', 'needs_attention'],
    source_kind: ['real', 'manual', 'simulated', 'unknown'],
    eligibility: ['all', 'qualified', 'excluded'],
    review_status: ['none', 'pending', 'approved', 'rejected', 'unknown'],
    include_archived: ['true', 'false'],
    record_type: ['all', 'publication', 'receipt'],
  };
  for (const [key, value] of url.searchParams) {
    if (!route.keys.includes(key) || url.searchParams.getAll(key).length !== 1) return false;
    if (['tenant_id', 'question_id', 'task_id'].includes(key) && !geoPositive(value)) return false;
    if (key === 'limit' && (!geoPositive(value) || Number(value) > 100)) return false;
    if (key === 'cursor' && (!value.trim() || value.length > 4096)) return false;
    if (key === 'q' && (!value.trim() || Array.from(value.trim()).length > 100)) return false;
    if (key === 'engine_key' && !/^[A-Za-z0-9_.-]{1,64}$/.test(value)) return false;
    if (key === 'week_end' && !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    if (enums[key] && !enums[key].includes(value)) return false;
  }
  return true;
}
