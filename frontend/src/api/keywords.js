import client from './client'
import { createWritebackIdempotencyKey } from './idempotency'

export function fetchKeywordDetail({ keywordId, tenantId, startDate, endDate }) {
  return client.get(`/api/v1/keywords/${keywordId}`, {
    params: {
      tenant_id: tenantId,
      start_date: startDate || undefined,
      end_date: endDate || undefined,
    },
  })
}

// category: brand/focus/normal/longtail/new，传 auto 恢复自动分级
export function updateKeywordCategory({ keywordId, tenantId, category }) {
  return client.patch(`/api/v1/keywords/${keywordId}/category`, null, {
    params: { tenant_id: tenantId, category },
  })
}

// 关键词工作台列表：分页 + 筛选 + 7 天指标 + 峰值系数预警
export function fetchKeywordList({
  tenantId, category, campaignId, pause, serving, q, coefWarning, hasSuggestion, sortBy, order, page, pageSize,
}) {
  return client.get('/api/v1/keywords', {
    params: {
      tenant_id: tenantId,
      category: category || undefined,
      campaign_id: campaignId ?? undefined,
      pause: pause ?? undefined,
      serving: serving ?? undefined,
      q: q || undefined,
      coef_warning: coefWarning || undefined,
      has_suggestion: hasSuggestion ?? undefined,
      sort_by: sortBy || undefined,
      order: order || undefined,
      page,
      page_size: pageSize,
    },
  })
}

// 立即从百度刷新工作台数据；全量同步可能超过普通列表请求耗时。
export function refreshKeywordWorkbench({ tenantId }) {
  return client.post('/api/v1/admin/refresh-keyword-workbench', null, {
    params: { tenant_id: tenantId },
    timeout: 120000,
  })
}

// 批量改分级，category 同上（auto=恢复自动）
export function batchUpdateCategory({ tenantId, keywordIds, category }) {
  return client.post('/api/v1/keywords/batch-category', {
    tenant_id: tenantId,
    keyword_ids: keywordIds,
    category,
  })
}

// 回写单个关键词的最终执行价到百度（updateWord）。经 dry-run 安全网 + 20% 硬上限 + 台账留痕。
// 返回 { status, dry_run, writeback }
export function writebackKeyword({
  keywordId,
  tenantId,
  price,
  approvalId = null,
  confirmation = null,
  idempotencyKey = createWritebackIdempotencyKey(),
}) {
  return client.post(`/api/v1/keywords/${keywordId}/writeback`, {
    tenant_id: tenantId,
    price,
    approval_id: approvalId,
    confirmation,
    idempotency_key: idempotencyKey,
  })
}

// 批量回写：items = [{ keyword_id, price }]。返回 { total, applied, simulated, rejected, failed }
export function matchTypeWriteback({ keywordId, tenantId, matchType, phraseType }) {
  return client.post(`/api/v1/keywords/${keywordId}/match-type-writeback`, {
    tenant_id: tenantId,
    match_type: matchType,
    phrase_type: phraseType,
  })
}

export function writebackKeywordBatch({ tenantId, items }) {
  return client.post('/api/v1/keywords/writeback-batch', {
    tenant_id: tenantId,
    items,
  })
}

// 批量暂停/启用关键词（updateWord pause 写回，dry-run 保护）。pause: true=暂停 false=启用
export function pauseKeywordBatch({ tenantId, keywordIds, pause }) {
  return client.post('/api/v1/keywords/pause-batch', {
    tenant_id: tenantId,
    keyword_ids: keywordIds,
    pause,
  })
}

// 工作台视图 tabs：计划列表 / 单元列表
export function fetchCampaignList({ tenantId }) {
  return client.get('/api/v1/structure/campaigns', { params: { tenant_id: tenantId } })
}

export function fetchAdgroupList({ tenantId, campaignId }) {
  return client.get('/api/v1/structure/adgroups', {
    params: { tenant_id: tenantId, campaign_id: campaignId ?? undefined },
  })
}
