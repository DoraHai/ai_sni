// Framework-independent request lifetime and two-step relabel state.
export function createInboxState(api, changed = () => {}) {
  const state = { items: [], devices: [], count: 0, pairing: null, busy: false, error: '', errorReceiptId: null, filter: 'pending', ownerUserId: null, offset: 0, total: 0, q: '', focusedReceipt: null, needsTargetRefresh: false, refreshErrors: {} }
  let generation = 0
  let controller = new AbortController()

  function clear() {
    generation += 1
    controller.abort()
    controller = new AbortController()
    Object.assign(state, { items: [], devices: [], count: 0, pairing: null, busy: false, error: '', errorReceiptId: null, filter: 'pending', ownerUserId: null, offset: 0, total: 0, q: '', focusedReceipt: null, needsTargetRefresh: false, refreshErrors: {} })
    changed(state)
  }
  async function operation(work, receiptId = null, clearsRefresh = false) {
    if (state.busy) return
    const version = generation
    state.busy = true; state.error = ''; state.errorReceiptId = null; changed(state)
    try {
      const result = await work(controller.signal)
      if (version !== generation) return
      if (clearsRefresh && result !== false) {
        delete state.refreshErrors[receiptId]
        state.needsTargetRefresh = Object.keys(state.refreshErrors).length > 0
      }
      return result
    } catch (error) {
      if (version === generation && error.name !== 'AbortError') {
        state.error = error.message
        state.errorReceiptId = receiptId
        if (receiptId && error.code === 'REVISION_CONFLICT') state.refreshErrors[receiptId] = error.message
        state.needsTargetRefresh = Object.keys(state.refreshErrors).length > 0
      }
    } finally {
      if (version === generation) { state.busy = false; changed(state) }
    }
  }
  async function reload(signal) {
    if (signal.aborted) return
    const version = generation
    const params = state.filter === 'pending' ? {} : { state: state.filter }
    if (state.offset) params.offset = state.offset
    if (state.q) params.q = state.q
    if (state.ownerUserId) params.ownerUserId = state.ownerUserId
    const { offset: unused, ...countParams } = params
    const [receipts, devices, counts] = await Promise.all([api.receipts(params, signal), state.ownerUserId ? api.devicesFor(state.ownerUserId, signal) : api.devices(signal), api.count(countParams, signal)])
    if (version !== generation) return
    state.items = receipts.items; state.devices = devices.items; state.count = counts.count; state.total = receipts.total ?? counts.count
    changed(state)
  }
  return {
    state, clear,
    focusReceipt: receiptId => operation(async signal => {
      const version = generation
      const row = await api.receipt(receiptId, signal)
      if (version !== generation) return
      if (row.id !== receiptId) throw new Error('回执身份不符，请刷新')
      state.focusedReceipt = row
      state.filter = 'active'; state.offset = 0
      await reload(signal)
    }, receiptId, true),
    show: filter => operation(async signal => { state.filter = filter; state.offset = 0; await reload(signal) }),
    page: offset => operation(async signal => { state.offset = Math.max(0, offset); await reload(signal) }),
    search: q => operation(async signal => { state.q = q; state.offset = 0; await reload(signal) }),
    owner: uid => operation(async signal => { state.items = []; state.devices = []; state.count = 0; state.offset = 0; state.ownerUserId = Number(uid) || null; changed(state); await reload(signal) }),
    archive: receipt => operation(async signal => { await api.archive(receipt.id, receipt.revision, signal); await reload(signal) }, receipt.id, true),
    remove: receipt => operation(async signal => {
      if (!globalThis.confirm('清理内容后仍保留回传确认记录。确认清理？')) return false
      await api.delete(receipt.id, receipt.revision, signal); await reload(signal)
    }, receipt.id, true),
    refresh: () => operation(reload),
    pair: () => operation(async signal => {
      const version = generation
      const pairing = await api.createPairing(signal)
      if (version === generation) { state.pairing = pairing; changed(state) }
    }),
    cancelPairing: () => operation(async signal => {
      if (!state.pairing) return
      await api.cancelPairing(state.pairing.pairingId, state.pairing.revision, signal)
      state.pairing = null; changed(state); await reload(signal)
    }),
    revoke: device => operation(async signal => { await api.revoke(device.id, device.revision, signal); await reload(signal) }),
    label: (receipt, target) => operation(async signal => {
      const version = generation
      await api.label(target.module, target.tenantId, receipt.id, { expectedRevision: receipt.revision,
        targetTenant: target.tenantId, scopeId: target.scopeId || null,
        ...(target.article ? { articleId: target.article.id, articleVersion: target.article.version, articleDigest: target.article.digest } : {}),
        ...(Object.hasOwn(target, 'publishedAccount') ? { publishedAccount: target.publishedAccount || null } : {}) }, signal)
      if (version !== generation) return
      let saved
      if (state.focusedReceipt?.id === receipt.id) saved = await api.receipt(receipt.id, signal)
      if (version !== generation) return
      if (saved) state.focusedReceipt = saved
      await reload(signal)
      return saved
    }, receipt.id, true),
    // Each call uses the *current* business context. Never issue a new target
    // write automatically if unlabel failed or the identity changed in flight.
    unlabel: receipt => operation(async signal => {
      await api.unlabel(receipt.assignment.module, receipt.assignment.tenantId, receipt.id,
        { expectedRevision: receipt.revision, reason: '人工撤销归属' }, signal)
      await reload(signal)
    }, receipt.id, true),
  }
}
