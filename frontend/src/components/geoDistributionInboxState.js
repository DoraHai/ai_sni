// Framework-independent request lifetime and two-step relabel state.
export function createInboxState(api, changed = () => {}) {
  const state = { items: [], devices: [], count: 0, pairing: null, focused: null, conflict: false, busy: false, error: '', filter: 'pending', ownerUserId: null, offset: 0 }
  let generation = 0
  let controller = new AbortController()

  function clear() {
    generation += 1
    controller.abort()
    controller = new AbortController()
    Object.assign(state, { items: [], devices: [], count: 0, pairing: null, focused: null, conflict: false, busy: false, error: '', filter: 'pending', ownerUserId: null, offset: 0 })
    changed(state)
  }
  async function operation(work) {
    if (state.busy) return
    const version = generation
    state.busy = true; state.error = ''; state.conflict = false; changed(state)
    try {
      const result = await work(controller.signal)
      if (version !== generation) return
      return result
    } catch (error) {
      if (version === generation && error.name !== 'AbortError') {
        state.error = error.message
        state.conflict = error.status === 409 || error.code === 'REVISION_CONFLICT'
      }
    } finally {
      if (version === generation) { state.busy = false; changed(state) }
    }
  }
  async function reload(signal) {
    if (signal.aborted) return
    const version = generation
    const params = { state: state.filter }
    if (state.ownerUserId) params.ownerUserId = state.ownerUserId
    const [receipts, devices, counts] = await Promise.all([api.receipts({ ...params, offset: state.offset }, signal), state.ownerUserId ? api.devicesFor(state.ownerUserId, signal) : api.devices(signal), api.count(params, signal)])
    if (version !== generation) return
    state.items = receipts.items; state.devices = devices.items; state.count = counts.count
    changed(state)
  }
  return {
    state, clear,
    focus: receiptId => operation(async signal => {
      state.focused = null; changed(state)
      const row = await api.receipt(receiptId, signal)
      if (!signal.aborted && row?.id === receiptId) { state.focused = row; changed(state) }
    }),
    show: filter => operation(async signal => { state.filter = filter; state.offset = 0; await reload(signal) }),
    page: offset => operation(async signal => { state.offset = offset; await reload(signal) }),
    owner: uid => operation(async signal => { state.items = []; state.devices = []; state.count = 0; state.offset = 0; state.ownerUserId = Number(uid) || null; changed(state); await reload(signal) }),
    archive: receipt => operation(async signal => { await api.archive(receipt.id, receipt.revision, signal); await reload(signal) }),
    remove: receipt => operation(async signal => {
      if (!globalThis.confirm('清理内容后仍保留回传确认记录。确认清理？')) return
      await api.delete(receipt.id, receipt.revision, signal); await reload(signal)
    }),
    refresh: () => operation(reload),
    pair: () => operation(async signal => {
      const version = generation
      const pairing = await api.createPairing(signal)
      if (version === generation) { state.pairing = pairing; changed(state) }
    }),
    revoke: device => operation(async signal => { await api.revoke(device.id, device.revision, signal); await reload(signal) }),
    label: (receipt, target) => operation(async signal => {
      const result = await api.label(target.module, target.tenantId, receipt.id, { expectedRevision: receipt.revision,
        targetTenant: target.tenantId, scopeId: target.scopeId || null,
        ...(target.article ? { articleId: target.article.id, articleVersion: target.article.version, articleDigest: target.article.digest } : {}),
        ...(Object.hasOwn(target, 'publishedAccount') ? { publishedAccount: target.publishedAccount || null } : {}) }, signal)
      await reload(signal)
      if (!signal.aborted && state.focused?.id === receipt.id && result?.id === receipt.id) state.focused = result
      return signal.aborted ? undefined : result
    }),
    // Each call uses the *current* business context. Never issue a new target
    // write automatically if unlabel failed or the identity changed in flight.
    unlabel: receipt => operation(async signal => {
      await api.unlabel(receipt.assignment.module, receipt.assignment.tenantId, receipt.id,
        { expectedRevision: receipt.revision, reason: '人工撤销归属' }, signal)
      await reload(signal)
    }),
  }
}
