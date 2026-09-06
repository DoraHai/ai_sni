import test from 'node:test'
import assert from 'node:assert/strict'

import { staleProgressHint } from '../src/utils/geoProgressStatus.js'

test('active stale progress is described as awaiting background confirmation', () => {
  assert.equal(
    staleProgressHint({ status: 'running', stored_status: 'running', stale: true }),
    '后台任务疑似超时，等待后台恢复确认',
  )
  assert.equal(
    staleProgressHint({ status: 'pending', stale: true }, '巡检'),
    '巡检疑似超时，等待后台恢复确认',
  )
})

test('terminal or fresh progress keeps its normal status display', () => {
  assert.equal(staleProgressHint({ status: 'failed', stale: true }), '')
  assert.equal(staleProgressHint({ status: 'running', stale: false }), '')
  assert.equal(staleProgressHint(null), '')
})
