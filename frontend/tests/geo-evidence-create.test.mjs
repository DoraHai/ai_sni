import test from 'node:test'
import assert from 'node:assert/strict'
import { evidenceRequest, createEvidenceSubmitter } from '../src/utils/geoEvidenceCreate.js'
const form = { title: '提升提及', role: 'geo_operator', metric: 'geo.visibility.ai_mention_rate_7d', delta: 1 }
test('request uses absolute percentage points and real article link, without completion evidence', () => {
  const req = evidenceRequest(12, form)
  assert.deepEqual(req.params, { content_task_id: 12, metric_key: form.metric, direction: 'increase', min_delta: 1 })
  assert.equal(req.completion_evidence, undefined)
  for (const delta of ['', 0, -1, Infinity, 'bad']) assert.throws(() => evidenceRequest(12, { ...form, delta }))
  assert.throws(() => evidenceRequest(0, form))
  assert.throws(() => evidenceRequest(12, { ...form, metric: 'seo.rank' }))
})
test('double click creates once and tenant switch ignores late response', async () => {
  let resolve, tenant = 7, calls = 0
  const state = { busy: false }
  const controller = createEvidenceSubmitter(state, { create: () => { calls++; return new Promise(r => { resolve = r }) } }, () => tenant, () => 12)
  const pending = controller.submit(evidenceRequest(12, form))
  await controller.submit(evidenceRequest(12, form))
  assert.equal(calls, 1)
  tenant = 8; controller.invalidate(); state.busy = false
  resolve({ id: 21 }); await pending
  assert.equal(state.result, null)
})
test('failed create keeps error and allows safe retry', async () => {
  let fail = true
  const state = { busy: false }
  const controller = createEvidenceSubmitter(state, { create: async () => { if (fail) throw new Error('已有任务 #10'); return { id: 10 } } }, () => 7, () => 12)
  await controller.submit(evidenceRequest(12, form))
  assert.equal(state.error, '已有任务 #10'); assert.equal(state.busy, false)
  fail = false; await controller.submit(evidenceRequest(12, form))
  assert.equal(state.result.id, 10)
})

test('bounded metrics reject impossible deltas while counts remain unbounded', () => {
  for (const metric of [form.metric, 'geo.visibility.ai_visibility_score']) {
    assert.throws(() => evidenceRequest(12, { ...form, metric, delta: 100.01 }))
    assert.equal(evidenceRequest(12, { ...form, metric, delta: 100 }).params.min_delta, 100)
  }
  assert.equal(evidenceRequest(12, { ...form, metric: 'geo.visibility.ai_mention_count_7d', delta: 101 }).params.min_delta, 101)
})
