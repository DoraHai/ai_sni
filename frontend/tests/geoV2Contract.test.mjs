import test from 'node:test'
import assert from 'node:assert/strict'
import { GEO_PROTOTYPE_PAGES } from '../src/utils/geoPrototypeContract.js'

test('GEO v2 contract includes hidden import and distribution pages', () => {
  const byId = Object.fromEntries(GEO_PROTOTYPE_PAGES.map((page) => [page.id, page]))
  assert.equal(byId.import.path, '/geo/import')
  assert.equal(byId.import.hidden, true)
  assert.equal(byId.distribution.path, '/geo/articles/:taskId/distribution')
  assert.equal(byId.distribution.hidden, true)
  assert.equal(byId.evaluation.hidden, true)
  assert.equal(byId.channels.path, '/geo/channels')
  assert.equal(byId['ai-settings'].path, '/geo/ai-settings')
  assert.equal(byId['ai-settings'].hidden, undefined)
})
