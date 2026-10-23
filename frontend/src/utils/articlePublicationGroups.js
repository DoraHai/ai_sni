// Display identities only. Titles, URLs and versions never decide grouping.
export function safeId(value) {
  if (!Number.isSafeInteger(value) || value < 1) throw new TypeError('发布记录 ID 无效')
  return value
}
export function safePublicationUrl(value) {
  if (typeof value !== 'string' || /[\s\\]/.test(value)) return null
  try {
    const url = new URL(value)
    return ['http:', 'https:'].includes(url.protocol) && url.hostname && !url.username && !url.password ? value : null
  } catch { return null }
}
export function groupKey(row) {
  if (row.module !== 'seo') throw new TypeError('发布记录模块不符')
  return `${row.module}:${safeId(row.tenant_id)}:${safeId(row.scope_id)}:${safeId(row.group_article_id)}`
}
export function mergeRows(previous, incoming, key) {
  const rows = new Map(previous.map(row => [key(row), row]))
  for (const row of incoming) rows.set(key(row), row)
  return [...rows.values()]
}
const uuid = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/
export function validateGroupsPage(page, { tenant, scope, bucket = 'linked', article = null }) {
  const c = page?.context
  if (page?.schema !== 1 || page.read_only !== true || page.completeness !== 'complete_snapshot' ||
      c?.module !== 'seo' || c.tenant_id !== tenant || c.scope_id !== scope ||
      c.bucket !== bucket || c.article_id !== article || typeof c.revision !== 'string' || !c.revision ||
      !Array.isArray(page.items) || typeof page.has_more !== 'boolean' ||
      (page.has_more ? typeof page.next_cursor !== 'string' || !page.next_cursor : page.next_cursor !== null)) {
    throw new Error('发布记录读取不完整，请刷新')
  }
  for (const key of ['native', 'external', 'articles', 'unlinked', 'invalid', 'loaded']) {
    if (!Number.isSafeInteger(page.counts?.[key]) || page.counts[key] < 0) throw new Error('发布记录计数无效，请刷新')
  }
  if (page.counts.loaded !== page.items.length) throw new Error('发布记录读取不完整，请刷新')
  for (const row of page.items) {
    if (row.module !== 'seo' || row.tenant_id !== tenant || row.scope_id !== scope || row.task_id !== null) throw new Error('发布记录范围不符，请刷新')
    if (bucket === 'linked') {
      groupKey(row)
      if (row.content_id !== row.group_article_id || (article !== null && row.group_article_id !== article)) throw new Error('发布记录稿件不符')
    } else if (row.group_article_id !== null || row.content_id !== null) throw new Error('发布记录归属异常')
    if (bucket === 'linked' && article === null) {
      for (const key of ['native_count', 'external_count']) {
        if (!Number.isSafeInteger(row[key]) || row[key] < 0) throw new Error('发布记录来源计数无效')
      }
      continue
    }
    if (row.source === 'native') {
      safeId(row.native_publication_id)
      if (row.external_receipt_id !== null || row.key !== `native:seo:${row.native_publication_id}`) throw new Error('原生记录身份无效')
    } else if (row.source === 'external_report') {
      if (!uuid.test(row.external_receipt_id) || row.native_publication_id !== null || row.key !== `external:${row.external_receipt_id}`) throw new Error('外部记录身份无效')
    } else throw new Error('发布记录来源无效')
  }
  return page
}
export function reportedResult(status) {
  return `操作人报告${({ success: '成功', failed: '失败', risk_control: '平台风控', verification_required: '需验证', pending_review: '审核中', unknown: '结果未知' })[status] || '结果未知'}`
}
export function beijingTime(value) {
  if (!value) return '未记录'
  const time = new Date(value)
  if (Number.isNaN(time.getTime())) return '未记录'
  const parts = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(time)
  const fields = Object.fromEntries(parts.map(part => [part.type, part.value]))
  return `${fields.year}-${fields.month}-${fields.day} ${fields.hour}:${fields.minute}`
}
