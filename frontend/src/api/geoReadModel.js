import client from './client'

const root = '/api/v1/geo/integration'
// Explicit tenant wins over filters; no legacy GETs that reconcile or seed rows.
function query(path, tenantId, params = {}, signal) {
  return client.get(`${root}${path}`, { params: { ...params, tenant_id: tenantId }, signal })
}
export const getGeoReadAnswers = (tenant, params, signal) => query('/read/answers', tenant, params, signal)
export const getGeoReadAnswer = (tenant, id, params, signal) => query(`/read/answers/${id}`, tenant, params, signal)
export const getGeoReadPeriod = (tenant, params, signal) => query('/read/period-context', tenant, params, signal)
export const getGeoReadCapabilities = (tenant, signal) => query('/read/capabilities', tenant, {}, signal)
export const getGeoReadContentTask = (tenant, id, signal) => query(`/read/content-tasks/${id}`, tenant, {}, signal)
export const getGeoReadPatrol = (tenant, id, signal) => query(`/read/patrol-runs/${id}`, tenant, {}, signal)
export const getGeoReadJob = (tenant, id, signal) => query(`/read/async-jobs/${id}`, tenant, {}, signal)
export const getGeoReadPatrols = (tenant, params, signal) => query('/read/patrol-runs', tenant, params, signal)
export const getGeoReadJobs = (tenant, params, signal) => query('/read/async-jobs', tenant, params, signal)
export const getGeoOfficialMetrics = (tenant, weekEnd, signal) => query('/metrics/snapshot', tenant, { week_end: weekEnd }, signal)
export const getGeoMetricDictionary = (tenant, weekEnd, signal) => query('/metrics/dictionary', tenant, { week_end: weekEnd }, signal)
