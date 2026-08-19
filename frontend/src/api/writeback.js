import client from './client'

// 调价回写台账（平台主动发起的 updateWord 留痕）。返回 {status_counts, writebacks}
export function fetchWritebacks({ tenantId, status = null, limit = 200 }) {
  return client.get('/api/v1/writeback', {
    params: { tenant_id: tenantId, status, limit },
  })
}
