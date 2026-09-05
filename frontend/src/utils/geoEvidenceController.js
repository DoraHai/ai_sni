/** Keep execution requests bound to their original customer and task. */
export function createEvidenceController(state, api, getTenant) {
  let epoch = 0
  const current = (token, tenant) => token === epoch && tenant === getTenant()
  const invalidate = () => { epoch++ }
  async function load(more = false, targetId = null) {
    const tenant = getTenant(), token = ++epoch
    Object.assign(state, { loading: true, busy: false, error: '', message: '' })
    if (!more) Object.assign(state, { items: [], more: false, detail: null, selected: null })
    if (!tenant) { state.loading = false; state.more = false; return }
    if (targetId !== null && (!Number.isSafeInteger(targetId) || targetId < 1)) {
      state.error = '验收任务编号无效'; state.loading = false; state.more = false; return
    }
    try {
      const rows = await api.list(tenant, more ? state.items.at(-1)?.id || 0 : 0)
      if (!current(token, tenant)) return
      state.items = more ? [...state.items, ...rows] : rows
      state.more = rows.length === 200
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
    if (state.loading || state.busy || !state.selected || !['baseline', 'publication', 'retest', 'complete'].includes(kind)) return
    if (kind === 'publication' && (!Number.isSafeInteger(publicationId) || publicationId < 1)) {
      state.error = '请选择有效的发布记录'; return
    }
    const tenant = getTenant(), id = state.selected.id, token = ++epoch
    Object.assign(state, { busy: true, error: '', message: '' })
    try {
      const result = await api[kind](tenant, id, publicationId)
      if (!current(token, tenant)) return
      state.message = kind === 'retest' ? `复测任务 #${result.run_id} 已受理，请刷新查看执行结果` : '服务端核验成功'
      const [row, detail] = await Promise.all([api.get(tenant, id), api.readiness(tenant, id)])
      if (!current(token, tenant)) return
      state.selected = row; state.detail = detail
      state.items = state.items.map((item) => item.id === id ? row : item)
    } catch (e) { if (current(token, tenant)) state.error = e.message || '执行未通过，请检查条件后重试' }
    finally { if (current(token, tenant)) state.busy = false }
  }
  return { load, select, act, invalidate }
}
