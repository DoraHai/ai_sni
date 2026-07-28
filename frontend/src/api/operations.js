import client from './client'

// 调价台账（百度 getOperationRecord 同步数据，只读）
export function fetchOperationRecords({
  tenantId, optLevel, optContent, q, startDate, endDate, overLimit, page, pageSize,
}) {
  return client.get('/api/v1/operation-records', {
    params: {
      tenant_id: tenantId,
      opt_level: optLevel ?? undefined,
      opt_content: optContent || undefined,
      q: q || undefined,
      start_date: startDate || undefined,
      end_date: endDate || undefined,
      over_limit: overLimit || undefined,
      page,
      page_size: pageSize,
    },
  })
}
