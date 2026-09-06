import client from './client'
const base = '/api/v1/geo/integration/tasks'
const config = (tenant) => ({ params: { tenant_id: tenant } })
export const list = (tenant, after = 0, status = '') => client.get(base, { params: { tenant_id: tenant, limit: 200, after_id: after, ...(status ? { status } : {}) } })
export const get = (tenant, id) => client.get(`${base}/${id}`, config(tenant))
export const readiness = (tenant, id) => client.get(`${base}/${id}/execution-readiness`, config(tenant))
export const baseline = (tenant, id) => client.post(`${base}/${id}/baseline`, {}, config(tenant))
export const publication = (tenant, id, publicationId) => client.post(`${base}/${id}/publication-check`, { publication_id: publicationId }, config(tenant))
export const retest = (tenant, id) => client.post(`${base}/${id}/retest`, {}, config(tenant))
export const complete = (tenant, id) => client.patch(`${base}/${id}`, { status: 'done' }, config(tenant))

export const create = (tenant, body) => client.post(base, body, config(tenant))

export const start = (tenant, id) => client.patch(`${base}/${id}`, { status: 'in_progress' }, config(tenant))
export const cancel = (tenant, id) => client.patch(`${base}/${id}`, { status: 'cancelled' }, config(tenant))

export const baselineReadiness = (tenant, id) => client.get(`${base}/${id}/baseline-readiness`, config(tenant))

export const listForContent = (tenant, contentId) => client.get(base, { params: { tenant_id: tenant, content_task_id: contentId, limit: 200 } })
