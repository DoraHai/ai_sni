import test from 'node:test'
import assert from 'node:assert/strict'
import { createWorkbenchViewState } from './view-state.mjs'
const metric = (revision, value = 0) => ({ id: 'clicks', contextRevision: revision, state: 'available', display: String(value), series: [{ value: null }, { value }], rows: [{ clicks: value }] })

test('customer change removes cards and discussion references and rejects late response', () => {
  const view = createWorkbenchViewState()
  view.begin('sem', 'clicks').publish(metric(view.revision))
  const ref = view.reference('sem', 'clicks', view.revision)
  const late = view.begin('seo', 'clicks')
  view.invalidate()
  assert.equal(late.signal.aborted, true)
  assert.equal(late.publish(metric(late.revision, 99)), false)
  assert.equal(view.resolve(ref), null)
  assert.deepEqual(view.snapshot(), [])
})
test('refresh clears visible evidence immediately and a previous failure cannot erase new data', () => {
  const view = createWorkbenchViewState()
  view.begin('sem', 'clicks').publish(metric(view.revision, 3))
  const ref = view.reference('sem', 'clicks', view.revision)
  const old = view.begin('sem', 'clicks')
  assert.deepEqual(view.snapshot(), [])
  assert.equal(view.resolve(ref), null)
  const next = view.begin('sem', 'clicks')
  next.publish(metric(view.revision, 4))
  assert.equal(old.fail(), false)
  assert.equal(old.publish(metric(view.revision, 8)), false)
  assert.equal(view.snapshot()[0].metric.display, '4')
})
test('module keys do not collide and null remains distinct from measured zero', () => {
  const view = createWorkbenchViewState()
  for (const module of ['sem', 'seo']) view.begin(module, 'clicks').publish(metric(view.revision))
  assert.equal(view.snapshot().length, 2)
  const resolved = view.resolve(view.reference('sem', 'clicks', view.revision))
  assert.deepEqual(resolved.series.map(p => p.value), [null, 0])
  resolved.rows[0].clicks = 99
  assert.equal(view.snapshot()[0].metric.rows[0].clicks, 0)
})
test('unknown cards cannot become evidence and forged or stale references are rejected', () => {
  const view = createWorkbenchViewState()
  view.begin('geo', 'clicks').publish({ ...metric(view.revision), state: 'unavailable' })
  assert.equal(view.reference('geo', 'clicks', view.revision), null)
  assert.equal(view.resolve({ module: 'geo', metricId: 'clicks', contextRevision: view.revision }), null)
  const request = view.begin('sem', 'clicks')
  assert.throws(() => request.publish(metric(view.revision + 1)), /INVALID_CARD_CONTEXT/)
})
test('disposing on route exit aborts work and prevents new requests', () => {
  const view = createWorkbenchViewState()
  const request = view.begin('sem', 'clicks')
  view.dispose()
  assert.equal(request.signal.aborted, true)
  assert.equal(request.publish(metric(request.revision)), false)
  assert.throws(() => view.begin('sem', 'clicks'), /VIEW_DISPOSED/)
})
