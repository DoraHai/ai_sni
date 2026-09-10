import assert from 'node:assert/strict'
import test from 'node:test'

import {
  isSemDemoIdentity,
  SEM_DEMO_ACCOUNTS,
  SEM_DEMO_REVISION,
} from './semDemo.js'

test('demo identity requires the exact bound ordinary user context', () => {
  assert.equal(isSemDemoIdentity({ username: 'workbench_test_readonly', tenant_id: 16 }, 16), true)
  assert.equal(isSemDemoIdentity({ username: 'workbench_test_readonly', tenant_id: 15 }, 16), false)
  assert.equal(isSemDemoIdentity({ username: 'other', tenant_id: 16 }, 16), false)
  assert.equal(SEM_DEMO_REVISION, 'sem-demo-tenant16-v1')
})

test('demo account selector cannot mutate shared account fixtures', () => {
  assert.deepEqual(SEM_DEMO_ACCOUNTS.map((row) => row.id), [160001, 160002])
  assert.equal(SEM_DEMO_ACCOUNTS.every((row) => row.status === 'active' && row.demo), true)
  assert.throws(() => SEM_DEMO_ACCOUNTS.push({ id: 1 }), TypeError)
})
