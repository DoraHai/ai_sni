import client from './client'

const base = '/api/v1/seo/distribution/v1'
export const fetchReportSettings = params => client.get(`${base}/settings`, { params })
export const saveReportSettings = (params, body) => client.put(`${base}/settings`, body, { params })
export const createReportPairing = (params, body) => client.post(`${base}/device-pairings`, body, { params })
export const revokeReportDevice = (params, deviceId, body) => client.post(`${base}/devices/${encodeURIComponent(deviceId)}/revoke`, body, { params })
export const createReportTask = (params, body) => client.post(`${base}/tasks`, body, { params })
export const saveReportPublishAccount = (params, taskId, body) => client.post(`${base}/tasks/${encodeURIComponent(taskId)}/publish-account`, body, { params })
