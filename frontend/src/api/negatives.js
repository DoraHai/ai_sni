import client from './client'

export function fetchNegativeWords({ tenantId, scope, match, flag, q }) {
  return client.get('/api/v1/negative-words', {
    params: {
      tenant_id: tenantId,
      scope: scope || undefined,
      match: match || undefined,
      flag: flag || undefined,
      q: q || undefined,
    },
  })
}

// 添加单元否词（updateAdgroup 追加写回，dry-run 保护）。matchMode: exact / phrase
export function addNegativeWord({ tenantId, word, adgroupId, matchMode = 'exact' }) {
  return client.post('/api/v1/negative-words/add', {
    tenant_id: tenantId, word, adgroup_id: adgroupId, match_mode: matchMode,
  })
}

// 删除单元否词（updateAdgroup 移除写回，dry-run 保护）
export function removeNegativeWord({ tenantId, word, adgroupId, matchMode }) {
  return client.post('/api/v1/negative-words/remove', {
    tenant_id: tenantId, word, adgroup_id: adgroupId, match_mode: matchMode,
  })
}
