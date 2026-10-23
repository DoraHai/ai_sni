import { safeId } from './articlePublicationGroups.js'

export function publicationPlatform(value) {
  return ({ zhihu: '知乎', toutiao: '头条', bytedance: '头条', baijiahao: '百家号', baidu: '百家号',
    wechat: '微信公众号', weixin: '微信公众号', mp_weixin: '微信公众号', sohu: '搜狐',
    xiaohongshu: '小红书', xhs: '小红书', wangyi: '网易号', netease: '网易号',
    penguin: '企鹅号', douyin: '抖音', bilibili: '哔哩哔哩', website: '官网' })[value] || value || '未提供平台'
}

export function createPublicationRecordsState(api, changed = () => {}) {
  const state = { items: [], counts: null, loading: false, error: '', page: 1, next: null, starts: [null] }
  let context, epoch = 0, controller = new AbortController()
  function clear() {
    epoch++; controller.abort(); controller = new AbortController()
    Object.assign(state, { items: [], counts: null, loading: false, error: '', page: 1, next: null, starts: [null] })
    changed()
  }
  async function read(direction = 0) {
    if (!context || state.loading || (direction === 1 && !state.next) || (direction === -1 && state.page === 1)) return
    const current = epoch, selected = context, page = state.page + direction
    const cursor = direction === 1 ? state.next : state.starts[page - 1]
    const params = { bucket: 'records', limit: 20, source: selected.source || 'all',
      ...(selected.month ? { month: selected.month } : {}), ...(selected.taskId ? { article_id: selected.taskId } : {}),
      ...(cursor ? { cursor } : {}) }
    state.loading = true; state.error = ''; changed()
    try {
      const data = await api.publicationGroups(selected.tenantId, selected.projectId, params, controller.signal)
      if (epoch !== current) return
      const c = data?.context
      if (data?.read_only !== true || data.schema !== 1 || c?.module !== 'geo' || c.audience !== 'internal'
        || c.tenant_id !== selected.tenantId || c.scope_id !== selected.projectId || c.bucket !== 'records'
        || c.article_id !== (selected.taskId || null) || c.month !== (selected.month || null) || c.source !== params.source
        || data.completeness?.complete !== true || !Array.isArray(data.items)
        || !Number.isSafeInteger(data.counts?.filtered_records) || data.counts.filtered_records < 0
        || typeof data.has_more !== 'boolean' || (data.has_more && typeof data.next_cursor !== 'string')
        || data.items.some(r => !['native', 'external_report'].includes(r.source) || typeof r.source_key !== 'string'
          || (r.task_id !== null && !safeId(r.task_id)))) throw new Error('发布记录响应不完整，请刷新重试')
      state.items = data.items; state.counts = data.counts; state.page = page; state.next = data.next_cursor
      state.starts = [...state.starts.slice(0, page - 1), cursor || null]
    } catch (error) {
      if (current !== epoch || error.name === 'AbortError') return
      if ([400, 403, 404, 409].includes(error.status) || error.code === 'AUTH_CONTEXT_CHANGED') clear()
      state.error = error.message || '发布记录读取不完整，请刷新重试'
    } finally {
      if (current === epoch) state.loading = false
      changed()
    }
  }
  return { state, clear, read, refresh(next) {
    clear(); context = next
    if (next && [next.tenantId, next.projectId].every(safeId) && (next.taskId == null || safeId(next.taskId))) return read()
  } }
}
