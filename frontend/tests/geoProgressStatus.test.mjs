import assert from 'node:assert/strict'
import test from 'node:test'

import { staleProgressHint } from '../src/utils/geoProgressStatus.js'

test('fresh progress keeps the existing label path', () => {
  assert.equal(staleProgressHint({ status: 'pending', stale: false }), '')
  assert.equal(staleProgressHint({ status: 'completed', stale: true }), '')
})

test('stale stored progress is observation-only', () => {
  assert.equal(
    staleProgressHint({ status: 'pending', stored_status: 'pending', stale: true }),
    '后台任务疑似超时，等待后台恢复确认',
  )
  assert.equal(
    staleProgressHint({ status: 'running', stored_status: 'running', stale: true }, '巡检'),
    '巡检疑似超时，等待后台恢复确认',
  )
})
