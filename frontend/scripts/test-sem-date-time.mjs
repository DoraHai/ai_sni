import assert from 'node:assert/strict'

import { formatLocalDate, formatUtcTimestamp, parseUtcTimestamp } from '../src/utils/dateTime.js'


process.env.TZ = 'Asia/Shanghai'

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
assert.match(
  formatUtcTimestamp('2026-08-29T12:34:56', { timeZone: 'Asia/Shanghai' }),
  /2026.*08.*29.*20:34/,
)
assert.equal(formatUtcTimestamp('', { fallback: '从未同步' }), '从未同步')
assert.equal(formatLocalDate(new Date('2026-08-30T16:30:00Z')), '2026-08-31')
assert.equal(formatLocalDate(new Date('invalid')), '')

console.log('SEM UTC timestamp contract passed')
