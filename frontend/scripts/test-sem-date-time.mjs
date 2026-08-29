import assert from 'node:assert/strict'

import { parseUtcTimestamp } from '../src/utils/dateTime.js'


assert.equal(
  parseUtcTimestamp('2026-08-29T12:34:56')?.toISOString(),
  '2026-08-29T12:34:56.000Z',
)
assert.equal(
  parseUtcTimestamp('2026-08-29T20:34:56+08:00')?.toISOString(),
  '2026-08-29T12:34:56.000Z',
)
assert.equal(
  parseUtcTimestamp('2026-08-29T12:34:56Z')?.toISOString(),
  '2026-08-29T12:34:56.000Z',
)
assert.equal(parseUtcTimestamp('not-a-date'), null)
assert.equal(parseUtcTimestamp(''), null)

console.log('SEM UTC timestamp contract passed')
