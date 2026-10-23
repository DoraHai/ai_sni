// Exact, source-specific identity. Never deduplicate by title or URL.
export const safeId = value => Number.isSafeInteger(value) && value > 0
export function scopeId(value) {
  if (typeof value === 'number') return safeId(value) ? value : null
  if (typeof value !== 'string' || !/^[1-9][0-9]{0,15}$/.test(value)) return null
  const parsed = Number(value)
  return safeId(parsed) ? parsed : null
}
export function groupKey(context, id) {
  if (context.module !== 'geo' || ![context.tenantId, context.projectId, id].every(safeId)) throw new TypeError('INVALID_GROUP_ID')
  return `geo:${context.tenantId}:${context.projectId}:${id}`
}
export function safePublicationLink(value) {
  try {
    if (typeof value !== 'string' || /[\s\\]/.test(value)) return null
    const url = new URL(value)
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? value : null
  } catch { return null }
}
export function publicationTime(value) {
  if (!value || !/(?:Z|[+-]\d\d:\d\d)$/.test(value)) return '未提供'
  const time = new Date(value)
  if (Number.isNaN(time.valueOf())) return '未提供'
  const parts = Object.fromEntries(new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(time).map(p => [p.type, p.value]))
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`
}
export function reportedResult(value) {
  return '操作人报告' + ({ success: '成功', failed: '失败', risk_control: '平台风控', verification_required: '需验证', pending_review: '审核中', unknown: '结果未知' }[value] || '结果未知')
}
export function mergeRows(old, fresh, key) {
  const rows = new Map(old.map(r => [key(r), r]))
  for (const row of fresh) rows.set(key(row), row)
  return [...rows.values()]
}
export function validateGroupPage(data, context, params) {
  const c = data?.context
  const bad = () => { throw new Error('发布记录响应不完整，请刷新重试') }
  if (data?.schema !== 1 || data.read_only !== true || c?.module !== 'geo' || c.audience !== 'internal'
      || c.tenant_id !== context.tenantId || c.scope_id !== context.projectId
      || c.bucket !== (params.bucket || 'linked') || c.article_id !== (params.article_id || null)
      || !Array.isArray(data.items) || data.completeness?.complete !== true
      || typeof data.completeness.revision !== 'string' || typeof data.has_more !== 'boolean'
      || (data.has_more && (typeof data.next_cursor !== 'string' || !data.next_cursor))) bad()
  for (const key of ['native_records', 'external_records', 'article_groups', 'unlinked_records', 'invalid_records']) {
    if (!Number.isSafeInteger(data.counts?.[key]) || data.counts[key] < 0) bad()
  }
  const list = c.bucket === 'linked' && !params.article_id
  for (const row of data.items) {
    if (list) {
      if (!safeId(row.group_article_id) || row.task_id !== row.group_article_id || row.content_id !== null
          || ![row.native_count, row.external_count].every(n => Number.isSafeInteger(n) && n >= 0)) bad()
    } else {
      if (!['native', 'external_report'].includes(row.source)) bad()
      if (c.bucket === 'linked' && (row.group_article_id !== params.article_id || row.task_id !== params.article_id)) bad()
      if (row.source === 'native') {
        if (!safeId(row.native_publication_id) || !safeId(row.article_version_id)
            || row.external_receipt_id !== null || row.source_key !== `native:geo:${row.native_publication_id}`) bad()
      } else if (typeof row.external_receipt_id !== 'string'
          || !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(row.external_receipt_id)
          || row.native_publication_id !== null || row.article_version_id !== null
          || row.source_key !== `external:${row.external_receipt_id}`) bad()
    }
  }
  return data
}

export function createPublicationGroupsState(api, changed = () => {}) {
  const state = { groups: [], details: {}, unlinked: [], invalid: [], counts: null, cursors: {},
    pages: {}, pageStarts: {}, loading: {}, error: '', revision: null }
  let context = null, epoch = 0, controller = new AbortController()
  const notify = () => changed(state)
  function clear() {
    epoch++; controller.abort(); controller = new AbortController()
    Object.assign(state, { groups: [], details: {}, unlinked: [], invalid: [], counts: null,
      cursors: {}, pages: {}, pageStarts: {}, loading: {}, error: '', revision: null })
    notify()
  }
  async function read(key, params, apply) {
    if (!context || state.loading[key]) return
    const current = epoch, selected = context
    state.loading = { ...state.loading, [key]: true }; state.error = ''; notify()
    try {
      const data = validateGroupPage(await api.publicationGroups(selected.tenantId, selected.projectId, params, controller.signal), selected, params)
      if (epoch !== current) return
      if (state.revision && state.revision !== data.completeness.revision) throw Object.assign(new Error('发布记录已变化，请刷新后重新读取'), { status: 409 })
      state.revision = data.completeness.revision
      state.counts = data.counts
      state.cursors = { ...state.cursors, [key]: data.next_cursor }
      apply(data.items)
    } catch (error) {
      if (epoch !== current || error.name === 'AbortError') return
      if ([400, 403, 404, 409].includes(error.status) || error.code === 'AUTH_CONTEXT_CHANGED') clear()
      state.error = error.message || '发布记录读取不完整，请重试'; notify()
    } finally {
      if (epoch === current) { state.loading = { ...state.loading, [key]: false }; notify() }
    }
  }
  const detail = (articleId, more = false) => read(`detail:${articleId}`, { bucket: 'linked', article_id: articleId, limit: 20,
    ...(more ? { cursor: state.cursors[`detail:${articleId}`] } : {}) }, rows => {
    state.details = { ...state.details, [articleId]: mergeRows(more ? state.details[articleId] || [] : [], rows, r => r.source_key) }
  })
  function list(bucket = 'linked', direction = false) {
    const current = state.pages[bucket] || 1
    const next = direction === true ? current + 1 : direction === 'previous' ? current - 1 : 1
    if (next < 1 || (direction === true && !state.cursors[bucket])) return
    const starts = state.pageStarts[bucket] || [null]
    const cursor = direction === true ? state.cursors[bucket] : starts[next - 1]
    return read(bucket, { bucket, limit: 20, ...(cursor ? { cursor } : {}) }, rows => {
      state.pages = { ...state.pages, [bucket]: next }
      state.pageStarts = { ...state.pageStarts, [bucket]: [...starts.slice(0, next - 1), cursor || null] }
      if (bucket === 'linked') state.groups = mergeRows([], rows, r => groupKey(context, r.group_article_id))
      else state[bucket] = mergeRows([], rows, r => r.source_key)
    })
  }
  return { state, clear, list, detail,
    async refresh(next) {
      clear(); context = next
      if (!next || ![next.tenantId, next.projectId].every(safeId) || (next.taskId != null && !safeId(next.taskId))) return
      if (next.taskId) {
        state.groups = [{ group_article_id: next.taskId, task_id: next.taskId, title: `任务 #${next.taskId}` }]
        await detail(next.taskId)
      } else await Promise.all(['linked', 'unlinked', 'invalid'].map(bucket => list(bucket)))
    },
  }
}
