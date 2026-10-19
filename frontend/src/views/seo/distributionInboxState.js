// Framework-independent request lifetime and two-step relabel state.
export function createInboxState(api, changed = () => {}) {
  const state = { items: [], devices: [], count: 0, pairing: null, busy: false, error: '' }
  let generation = 0
  let controller = new AbortController()

  function clear() {
    generation += 1
    controller.abort()
    controller = new AbortController()
    Object.assign(state, { items: [], devices: [], count: 0, pairing: null, busy: false, error: '' })
    changed(state)
  }
  async function operation(work) {
    if (state.busy) return
    const version = generation
    state.busy = true; state.error = ''; changed(state)
    try {
      const result = await work(controller.signal)
      if (version !== generation) return
      return result
    } catch (error) {
      if (version === generation && error.name !== 'AbortError') state.error = error.message
    } finally {
      if (version === generation) { state.busy = false; changed(state) }
    }
  }
  async function reload(signal) {
    if (signal.aborted) return
    const version = generation
    const [receipts, devices, counts] = await Promise.all([api.receipts({}, signal), api.devices(signal), api.count({}, signal)])
    if (version !== generation) return
    state.items = receipts.items; state.devices = devices.items; state.count = counts.count
    changed(state)
  }
  return {
    state, clear,
    refresh: () => operation(reload),
    pair: () => operation(async signal => {
      const version = generation
      const pairing = await api.createPairing(signal)
      if (version === generation) { state.pairing = pairing; changed(state) }
    }),
    revoke: device => operation(async signal => { await api.revoke(device.id, device.revision, signal); await reload(signal) }),
    label: (receipt, target) => operation(async signal => {
      await api.label(target.module, target.tenantId, receipt.id, { expectedRevision: receipt.revision,
        targetTenant: target.tenantId, scopeId: target.scopeId || null }, signal)
      await reload(signal)
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
