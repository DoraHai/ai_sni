import { test } from 'node:test'
import assert from 'node:assert/strict'
import { advisorVisibilityBody } from '../src/utils/geoAdvisorRequests.js'

test('both advisor visibility entry points send only the selected customer', () => {
  const body = { tenant_id: 10, auto_persist: true, run_async: true, prompt_limit: 99, engine_keys: ['x'] }
  assert.deepEqual(advisorVisibilityBody(body, true), { tenant_id: 10 })
  assert.equal(advisorVisibilityBody(body, false), body)
})
