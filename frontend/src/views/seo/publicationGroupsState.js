import { mergeRows, groupKey, safeId, validateGroupsPage, validateRecordsPage } from '../../utils/articlePublicationGroups.js'

export function createPublicationGroupsState(api, changed = () => {}) {
  const empty = () => ({ items: [], cursor: null, more: false, busy: false, error: '', page: 1, cursors: [null] })
  const state = { buckets: { linked: empty(), unlinked: empty(), invalid: empty() }, details: {}, counts: null, revision: null, busy: false, error: '' }
  let context = null, generation = 0, controller = new AbortController()
  function clear(next = null) {
    generation++; controller.abort(); controller = new AbortController(); context = next
    Object.assign(state, { buckets: { linked: empty(), unlinked: empty(), invalid: empty() }, details: {}, counts: null, revision: null, busy: false, error: '' })
    changed()
  }
  function scope() {
    if (!context?.tenant || !context?.scope) return null
    return { tenant: safeId(context.tenant), scope: safeId(context.scope) }
  }
  async function get(bucket, article = null, cursor = null) {
    const target = scope()
    if (!target) return null
    const result = await api.publicationGroups('seo', target.tenant, target.scope,
      { bucket, limit: 20, ...(article == null ? {} : { article_id: article }), ...(cursor ? { cursor } : {}) }, controller.signal)
    return validateGroupsPage(result, { ...target, bucket, article })
  }
  const fresh = page => {
    if (state.revision && page.context.revision !== state.revision) throw Object.assign(new Error('记录或权限已变化，请刷新后重新加载'), { code: 'GROUPS_REFRESH_REQUIRED' })
  }
  function failure(error, target) {
    target.error = error.message
    if (['GROUPS_REFRESH_REQUIRED', 'AUTH_CONTEXT_CHANGED'].includes(error.code) || [401, 403, 404, 409].includes(error.status)) {
      clear(context); state.error = error.message
    }
  }
  async function refresh(next = context) {
    clear(next)
    if (!scope()) return
    const version = generation
    state.busy = true; changed()
    try {
      const buckets = ['linked', 'unlinked', 'invalid']
      const pages = await Promise.all(buckets.map(bucket => get(bucket)))
      if (version !== generation) return
      state.revision = pages[0].context.revision
      for (const page of pages) fresh(page)
      pages.forEach((page, i) => Object.assign(state.buckets[buckets[i]], { items: page.items, cursor: page.next_cursor, more: page.has_more }))
      state.counts = pages[0].counts
    } catch (error) {
      if (version === generation && error.name !== 'AbortError') { state.error = error.message; state.counts = null }
    } finally { if (version === generation) { state.busy = false; changed() } }
  }
  async function navigate(bucket, direction = 1) {
    const target = state.buckets[bucket]
    if (!target || target.busy || state.busy || (direction === 1 ? !target.more : target.page <= 1)) return
    const nextPage = target.page + direction
    const cursor = direction === 1 ? target.cursor : target.cursors[nextPage - 1]
    const version = generation
    target.busy = true; target.error = ''; changed()
    try {
      const page = await get(bucket, null, cursor)
      if (version !== generation) return
      fresh(page)
      target.cursors[nextPage - 1] = cursor
      Object.assign(target, { items: page.items, cursor: page.next_cursor, more: page.has_more, page: nextPage })
    } catch (error) { if (version === generation && error.name !== 'AbortError') failure(error, target) }
    finally { if (version === generation) { target.busy = false; changed() } }
  }
  async function details(row, nextPage = false) {
    const id = safeId(row.group_article_id), key = groupKey(row)
    const target = state.details[key] ||= empty()
    if (target.busy || state.busy || (nextPage ? !target.more : target.loaded)) return
    const version = generation
    target.busy = true; target.error = ''; changed()
    try {
      const page = await get('linked', id, nextPage ? target.cursor : null)
      if (version !== generation) return
      fresh(page)
      Object.assign(target, { items: mergeRows(nextPage ? target.items : [], page.items, r => r.key), cursor: page.next_cursor, more: page.has_more, loaded: true })
    } catch (error) { if (version === generation && error.name !== 'AbortError') failure(error, target) }
    finally { if (version === generation) { target.busy = false; changed() } }
  }
  return { state, clear, refresh, more: bucket => navigate(bucket), previous: bucket => navigate(bucket, -1), details }
}


export function createPublicationRecordsState(api, changed = () => {}) {
  const state = { items: [], total: null, page: 1, more: false, busy: false, error: '', month: null, source: 'all' }
  let context = null, generation = 0, controller = new AbortController(), cursors = [null], nextCursor = null, revision = null
  function clear(next = context) {
    generation++; controller.abort(); controller = new AbortController(); context = next
    cursors = [null]; nextCursor = null; revision = null
    Object.assign(state, { items: [], total: null, page: 1, more: false, busy: false, error: '', month: next?.month || null, source: next?.source || 'all' })
    changed()
  }
  async function load(page = 1) {
    if (!context?.tenant || !context?.scope || state.busy) return
    const target = { tenant: safeId(context.tenant), scope: safeId(context.scope), month: state.month, source: state.source }
    const version = generation
    const cursor = page > state.page ? nextCursor : cursors[page - 1]
    state.busy = true; state.error = ''; changed()
    try {
      const result = validateRecordsPage(await api.publicationGroups('seo', target.tenant, target.scope,
        { bucket: 'records', limit: 20, source: target.source, ...(target.month ? { month: target.month } : {}), ...(cursor ? { cursor } : {}) }, controller.signal), target)
      if (version !== generation) return
      if (revision && result.context.revision !== revision) throw Object.assign(new Error('记录或权限已变化，请刷新后重新加载'), { code: 'GROUPS_REFRESH_REQUIRED' })
      revision = result.context.revision; cursors[page - 1] = cursor; nextCursor = result.next_cursor
      Object.assign(state, { items: result.items, total: result.counts.total, more: result.has_more, page })
    } catch (error) {
      if (version !== generation || error.name === 'AbortError') return
      if (['GROUPS_REFRESH_REQUIRED', 'AUTH_CONTEXT_CHANGED'].includes(error.code) || [401,403,404,409].includes(error.status)) clear(context)
      state.error = error.message
    } finally { if (version === generation) { state.busy = false; changed() } }
  }
  async function refresh(next = context) { clear(next); await load() }
  return { state, clear, refresh, more: () => state.more && load(state.page + 1), previous: () => state.page > 1 && load(state.page - 1) }
}
