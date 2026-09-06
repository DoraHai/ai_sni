import test from 'node:test'
import assert from 'node:assert/strict'

import {
  isPersistedGeoRow,
  persistedGeoRows,
} from '../src/utils/geoVirtualDefaults.js'

test('virtual defaults and malformed ids never enter id-based write paths', () => {
  for (const row of [
    null,
    {},
    { id: null, virtual_default: true },
    { id: 7, virtual_default: true },
    { id: '7' },
    { id: 0 },
    { id: -1 },
  ]) {
    assert.equal(isPersistedGeoRow(row), false)
  }
  assert.equal(isPersistedGeoRow({ id: 7, virtual_default: false }), true)
})

test('account selectors contain only persisted customer channels', () => {
  const stored = { id: 9, name: 'Stored' }
  assert.deepEqual(
    persistedGeoRows([
      { id: null, virtual_default: true },
      stored,
      { id: 10, virtual_default: true },
    ]),
    [stored],
  )
  assert.deepEqual(persistedGeoRows(null), [])
})
