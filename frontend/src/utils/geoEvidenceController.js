/** Keep execution requests bound to their original customer and task. */
export function createEvidenceController(state, api, getTenant, getStatus = () => '') {
  let epoch = 0
  const current = (token, tenant) => token === epoch && tenant === getTenant()
  const invalidate = () => { epoch++ }
  async function load(more = false, targetId = null) {
    const tenant = getTenant(), token = ++epoch
    Object.assign(state, { loading: true, busy: false, error: '', message: '' })
    if (!more) Object.assign(state, { items: [], afterId: 0, more: false, detail: null, selected: null })
    if (!tenant) { state.loading = false; state.more = false; return }
    if (targetId !== null && (!Number.isSafeInteger(targetId) || targetId < 1)) {
      state.error = '验收任务编号无效'; state.loading = false; state.more = false; return
    }
    try {
      const rows = await api.list(tenant, more ? state.afterId || state.items.at(-1)?.id || 0 : 0, getStatus())
      if (!current(token, tenant)) return
      state.items = more ? [...state.items, ...rows] : rows
      state.more = rows.length === 200
      if (rows.length) state.afterId = rows.at(-1).id
      if (targetId !== null) {
        // Fetch by tenant-scoped ID; do not change the pagination cursor/list.
        const row = await api.get(tenant, targetId)
        if (!current(token, tenant)) return
        state.selected = row
        const detail = await api.readiness(tenant, targetId)
        if (current(token, tenant)) state.detail = detail
      }
    } catch (e) { if (current(token, tenant)) state.error = e.message || '读取任务失败' }
    finally { if (current(token, tenant)) state.loading = false }
  }
  async function select(row) {
    if (state.loading) return
    const tenant = getTenant(), token = ++epoch
    Object.assign(state, { selected: row, detail: null, busy: true, error: '', message: '' })
    try {
      const detail = await api.readiness(tenant, row.id)
      if (current(token, tenant)) state.detail = detail
    } catch (e) { if (current(token, tenant)) state.error = e.message || '读取执行条件失败' }
    finally { if (current(token, tenant)) state.busy = false }
  }
  async function act(kind, publicationId) {
    if (state.loading || state.busy || !state.selected || !['baseline', 'publication', 'retest', 'complete', 'start', 'cancel'].includes(kind)) return
    if (['done', 'cancelled'].includes(state.selected.status)) return
    if (kind === 'start' && state.selected.status !== 'open') return
    if (kind === 'publication' && (!Number.isSafeInteger(publicationId) || publicationId < 1)) {
      state.error = '请选择有效的发布记录'; return
    }
    const tenant = getTenant(), id = state.selected.id, token = ++epoch
    Object.assign(state, { busy: true, error: '', message: '' })
    let accepted = false
    try {
      const result = await api[kind](tenant, id, publicationId)
      accepted = true
      if (!current(token, tenant)) return
      if (['start', 'cancel', 'complete'].includes(kind) && result?.id === id) {
        state.selected = result
        state.detail = null
        state.items = state.items.map(item => item.id === id ? result : item).filter(item => !getStatus() || item.status === getStatus())
      }
      state.message = kind === 'start' ? '任务已开始处理' : kind === 'cancel' ? '任务已取消；已启动的采样不会因此停止' : kind === 'retest' ? `复测任务 #${result.run_id} 已受理，请刷新查看执行结果` : '服务端核验成功'
      const [row, detail] = await Promise.all([api.get(tenant, id), api.readiness(tenant, id)])
      if (!current(token, tenant)) return
      state.selected = row; state.detail = detail
      state.items = state.items.map((item) => item.id === id ? row : item).filter(item => !getStatus() || item.status === getStatus())
    } catch (e) { if (current(token, tenant)) state.error = accepted ? `操作已受理，但刷新失败：${e.message || '请刷新执行条件'}` : (e.message || '执行未通过，请检查条件后重试') }
    finally { if (current(token, tenant)) state.busy = false }
  }
  return { load, select, act, invalidate }
}
