import assert from 'node:assert/strict'
import test from 'node:test'
import { evidenceBoundaryCount, normalizeModuleSelection, readCompletionProgress } from './experience-state.mjs'

test('describes module reads as progress without claiming data completeness', () => {
  assert.equal(readCompletionProgress({ availableCount: 3, completedCount: 3 }), 100)
  assert.equal(readCompletionProgress({ availableCount: 0, completedCount: 0 }), 0)
  assert.equal(evidenceBoundaryCount({
    unresolvedModules: 1,
    cards: [{ state: 'available' }, { state: 'partial' }, { state: 'no_data' }, { state: 'unavailable' }],
  }), 4)
})

test('resets a module filter when the selected customer does not have that module', () => {
  assert.equal(normalizeModuleSelection('seo', ['sem', 'geo']), 'all')
  assert.equal(normalizeModuleSelection('geo', ['sem', 'geo']), 'geo')
  assert.equal(normalizeModuleSelection('all', []), 'all')
})
