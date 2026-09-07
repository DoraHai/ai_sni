// Page-local presentation state. Module authorization and response validation
// happen before values are published here. No credentials or persistence.
export function createWorkbenchViewState() {
  let revision = 0
  let disposed = false
  const cards = new Map()
  const pending = new Map()
  const references = new Map()
  const keyOf = (module, id) => JSON.stringify([module, id])
  function invalidate() {
    revision++
    for (const ticket of pending.values()) ticket.controller.abort()
    pending.clear(); cards.clear(); references.clear()
  }
  function invalidateModule(module) {
    if (!['sem', 'seo', 'geo'].includes(module)) throw new Error('INVALID_MODULE')
    for (const [key, ticket] of pending) {
      if (ticket.module === module) { ticket.controller.abort(); pending.delete(key) }
    }
    for (const key of [...cards.keys()]) {
      if (JSON.parse(key)[0] === module) cards.delete(key)
    }
    for (const key of [...references.keys()]) {
      if (JSON.parse(key)[0] === module) references.delete(key)
    }
  }
  function begin(module, id) {
    if (disposed) throw new Error('VIEW_DISPOSED')
    if (!['sem', 'seo', 'geo'].includes(module) || typeof id !== 'string' || !id) throw new Error('INVALID_CARD')
    const key = keyOf(module, id)
    pending.get(key)?.controller.abort()
    cards.delete(key); references.delete(key)
    const ticket = { revision, key, module, id, controller: new AbortController() }
    pending.set(key, ticket)
    const current = () => !disposed && revision === ticket.revision && pending.get(key) === ticket && !ticket.controller.signal.aborted
    return {
      revision: ticket.revision,
      signal: ticket.controller.signal,
      publish(metric) {
        if (!current()) return false
        if (!metric || metric.id !== id || metric.contextRevision !== revision) throw new Error('INVALID_CARD_CONTEXT')
        const copy = structuredClone(metric)
        if (!current()) return false
        cards.set(key, copy); pending.delete(key)
        return true
      },
      fail() {
        if (!current()) return false
        pending.delete(key); cards.delete(key); references.delete(key)
        return true
      },
    }
  }
  function reference(module, id, expectedRevision) {
    if (disposed || expectedRevision !== revision) return null
    const key = keyOf(module, id)
    const metric = cards.get(key)
    if (!metric || !['available', 'partial'].includes(metric.state)) return null
    // Discussion stores a reference, not a second cached copy of the evidence.
    const ref = Object.freeze({ module, metricId: id, contextRevision: revision })
    if (!references.has(key)) references.set(key, new Set())
    references.get(key).add(ref)
    return ref
  }
  function resolve(ref) {
    if (!ref || disposed || ref.contextRevision !== revision) return null
    const key = keyOf(ref.module, ref.metricId)
    if (!references.get(key)?.has(ref)) return null
    const metric = cards.get(key)
    return metric ? structuredClone(metric) : null
  }
  return {
    begin, invalidate, invalidateModule, reference, resolve,
    get revision() { return revision },
    snapshot() { return [...cards.entries()].map(([key, metric]) => ({ key, metric: structuredClone(metric) })) },
    dispose() { if (!disposed) { invalidate(); disposed = true } },
  }
}
