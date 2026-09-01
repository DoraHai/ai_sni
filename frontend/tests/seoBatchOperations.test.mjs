import assert from 'node:assert/strict'
import test from 'node:test'

import { runSeoBatch } from '../src/views/seo/seoBatchOperations.js'

test('runSeoBatch aggregates completed, failed and skipped items', async () => {
  const active = { current: 0, maximum: 0 }
  const result = await runSeoBatch(
    [1, 2, 3, 4],
    async (item) => {
      active.current += 1
      active.maximum = Math.max(active.maximum, active.current)
      await new Promise((resolve) => setTimeout(resolve, 2))
      active.current -= 1
      if (item === 2) throw new Error('failed')
      return item * 10
    },
    { concurrency: 2, limit: 3 },
  )

  assert.deepEqual(result.completed.map(({ item }) => item).sort(), [1, 3])
  assert.deepEqual(result.failed.map(({ item }) => item), [2])
  assert.deepEqual(result.skipped, [4])
  assert.equal(active.maximum, 2)
})

test('runSeoBatch supports an empty selection', async () => {
  assert.deepEqual(await runSeoBatch([], async () => null), {
    completed: [],
    failed: [],
    skipped: [],
  })
})
