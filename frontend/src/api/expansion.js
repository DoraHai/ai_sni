import client from './client'

// 拓词候选（🚫 红线：百度只读，状态标记只落本地库）
export function fetchCandidates({
  tenantId, source, status, suggestedCategory, minScore, q, aiRelevance, sortBy, order, page, pageSize,
}) {
  return client.get('/api/v1/expansion/candidates', {
    params: {
      tenant_id: tenantId,
      source: source || undefined,
      status: status || undefined,
      suggested_category: suggestedCategory || undefined,
      min_score: minScore ?? undefined,
      q: q || undefined,
      ai_relevance: aiRelevance || undefined,
      sort_by: sortBy || undefined,
      order: order || undefined,
      page,
      page_size: pageSize,
    },
  })
}

// AI 语义相关性评估（治通用词噪音，按词去重批量调 DeepSeek，可能要数十秒~数分钟）
export function evaluateCandidates({ tenantId, force, limit = 20, afterId = 0, retryIds }) {
  return client.post('/api/v1/expansion/evaluate', retryIds ? { retry_ids: retryIds } : null, {
    params: { tenant_id: tenantId, force: force || undefined, limit, after_id: afterId },
    timeout: 600000,
  })
}

export function sampleCandidates({ tenantId, seed, limit = 20 }) {
  return client.post('/api/v1/expansion/sample', null, {
    params: { tenant_id: tenantId, seed, limit },
    timeout: 120000,
  })
}

export function updateCandidateStatus({ tenantId, candidateId, status }) {
  return client.patch(`/api/v1/expansion/candidates/${candidateId}/status`, null, {
    params: { tenant_id: tenantId, status },
  })
}

// 加入计划：把候选词加成正式关键词到指定单元（addWord 写回，dry-run 保护）。
// 候选词无所属单元，须传 adgroupId + price + matchMode。真写成功后候选自动标 adopted。
export function addCandidateToPlan({ tenantId, candidateId, adgroupId, price, matchMode = 'phrase' }) {
  return client.post(`/api/v1/expansion/candidates/${candidateId}/add-to-plan`, {
    tenant_id: tenantId, adgroup_id: adgroupId, price, match_mode: matchMode,
  })
}

export function batchSetPreset({ tenantId, candidateIds, presetPrice, presetMatchMode }) {
  return client.post('/api/v1/expansion/candidates/batch-set-preset', {
    tenant_id: tenantId,
    candidate_ids: candidateIds,
    preset_price: presetPrice,
    preset_match_mode: presetMatchMode,
  })
}

export function batchSetCategory({ tenantId, candidateIds, category }) {
  return client.post('/api/v1/expansion/candidates/batch-set-category', {
    tenant_id: tenantId,
    candidate_ids: candidateIds,
    category,
  })
}

export function batchSetStatus({ tenantId, candidateIds, status }) {
  return client.post('/api/v1/expansion/candidates/batch-status', {
    tenant_id: tenantId,
    candidate_ids: candidateIds,
    status,
  })
}

export function batchAddNegative({ tenantId, candidateIds, adgroupId, matchMode }) {
  return client.post('/api/v1/expansion/candidates/batch-negative', {
    tenant_id: tenantId,
    candidate_ids: candidateIds,
    adgroup_id: adgroupId,
    match_mode: matchMode,
  }, { timeout: 60000 })
}

// 手动触发同步（规划师逐种子词调用 + 搜索词报告，可能要 10-30 秒）
export function syncExpansion({ tenantId, seeds, queryDays }) {
  return client.post('/api/v1/admin/sync-expansion', null, {
    params: {
      tenant_id: tenantId,
      seeds: seeds || undefined,
      query_days: queryDays || undefined,
    },
    timeout: 120000,
  })
}

// URL 爬取拓词(自研提词 + 流量回查,可能要 20-60 秒)
export function syncUrlWords({ tenantId, urls }) {
  return client.post('/api/v1/admin/sync-url-words', { tenant_id: tenantId, urls }, {
    timeout: 180000,
  })
}

export function candidatesExportUrl({ tenantId, source, status, suggestedCategory, minScore, q, aiRelevance }) {
  const params = new URLSearchParams({ tenant_id: tenantId })
  if (source) params.set('source', source)
  if (status) params.set('status', status)
  if (suggestedCategory) params.set('suggested_category', suggestedCategory)
  if (minScore != null) params.set('min_score', minScore)
  if (q) params.set('q', q)
  if (aiRelevance) params.set('ai_relevance', aiRelevance)
  return `/api/v1/expansion/candidates/export?${params.toString()}`
}
