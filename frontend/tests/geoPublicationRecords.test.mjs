import test from 'node:test'
import assert from 'node:assert/strict'
import { createPublicationRecordsState, publicationPlatform } from '../src/utils/geoPublicationRecords.js'
import { publicationTime } from '../src/utils/articlePublicationGroups.js'

test('flat records page replaces twenty rows; filters reach server and reset pagination', async () => {
  const calls = []
  const model = createPublicationRecordsState({ publicationGroups: async (tid, pid, params) => {
    calls.push(params)
    return { schema: 1, read_only: true,
      context: { module: 'geo', audience: 'internal', tenant_id: tid, scope_id: pid, bucket: 'records',
        article_id: null, month: params.month || null, source: params.source },
      items: Array.from({ length: params.cursor ? 3 : 20 }, (_, i) => ({ source: 'external_report', source_key: `r${i}`, task_id: null })),
      counts: { filtered_records: 23 }, has_more: !params.cursor, next_cursor: params.cursor ? null : 'next', completeness: { complete: true } }
  } })
  await model.refresh({ tenantId: 101, projectId: 1 })
  assert.equal(calls[0].limit, 20)
  assert.equal(model.state.items.length, 20)
  await model.read(1)
  assert.equal(model.state.items.length, 3)
  assert.equal(model.state.page, 2)
  await model.read(-1)
  assert.equal(model.state.items.length, 20)
  await model.refresh({ tenantId: 101, projectId: 1, month: '2026-10', source: 'external_report' })
  assert.equal(model.state.page, 1)
  assert.equal(calls.at(-1).month, '2026-10')
  assert.equal(calls.at(-1).source, 'external_report')
  assert.equal(calls.at(-1).cursor, undefined)
})

test('platform mapping preserves unknown; UTC times show exact Shanghai format', () => {
  assert.equal(publicationPlatform('zhihu'), '知乎')
  assert.equal(publicationPlatform('toutiao'), '头条')
  assert.equal(publicationPlatform('baijiahao'), '百家号')
  assert.equal(publicationPlatform('custom-platform'), 'custom-platform')
  assert.equal(publicationTime('2026-10-23T02:45:00Z'), '2026-10-23 10:45')
})
