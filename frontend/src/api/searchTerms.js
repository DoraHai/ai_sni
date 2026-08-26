import client from './client'

// 搜索词报告列表（分页 + 筛选）。返回 {total, summary, window, search_terms}
export function fetchSearchTerms({ tenantId, campaignId, adgroupId, status, hasClick, q, page, pageSize }) {
  return client.get('/api/v1/search-terms', {
    params: {
      tenant_id: tenantId,
      campaign_id: campaignId ?? undefined,
      adgroup_id: adgroupId ?? undefined,
      status: status || undefined,
      has_click: hasClick ?? undefined,
      q: q || undefined,
      page,
      page_size: pageSize,
    },
  })
}

// 手动从百度拉搜索词报告全量落库（窗口快照覆盖）
export function syncSearchTerms({ tenantId, days = 30 }) {
  return client.post('/api/v1/search-terms/sync', null, {
    params: { tenant_id: tenantId, days },
  })
}

// 加否词（写回百度，dry-run 保护）。matchMode: exact=精确否 / phrase=短语否
export function addNegative({ tenantId, word, scope = 'adgroup', adgroupId, campaignId, matchMode = 'exact' }) {
  return client.post('/api/v1/search-terms/negative', {
    tenant_id: tenantId,
    word,
    scope,
    adgroup_id: adgroupId,
    campaign_id: campaignId,
    match_mode: matchMode,
  })
}

// 转拓词：搜索词加成正式关键词（addWord 写回，dry-run 保护）
export function expandKeyword({ tenantId, word, adgroupId, price, matchMode = 'phrase' }) {
  return client.post('/api/v1/search-terms/expand', {
    tenant_id: tenantId, word, adgroup_id: adgroupId, price, match_mode: matchMode,
  })
}

// 动作回写台账（加否词/转拓词/删否词/启停）。actionType 可选筛选。返回 {actions}
export function fetchActions({ tenantId, actionType, limit = 200 }) {
  return client.get('/api/v1/search-terms/actions', {
    params: {
      tenant_id: tenantId,
      action_type: actionType || undefined,
      limit,
    },
  })
}
