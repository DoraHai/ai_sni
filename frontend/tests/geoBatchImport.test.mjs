import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'

const frontendDir = resolve(import.meta.dirname, '..')
const source = (path) => readFileSync(resolve(frontendDir, path), 'utf8')

function functionBody(fileSource, functionName) {
  const start = fileSource.indexOf(`async function ${functionName}`)
  assert.notEqual(start, -1, `missing ${functionName}`)
  const bodyStart = fileSource.indexOf('{', start)
  let depth = 0
  for (let index = bodyStart; index < fileSource.length; index += 1) {
    if (fileSource[index] === '{') depth += 1
    if (fileSource[index] === '}') depth -= 1
    if (depth === 0) return fileSource.slice(start, index + 1)
  }
  assert.fail(`unable to isolate ${functionName}`)
}

test('GEO batch-import wrappers send CSV files to existing import endpoints', () => {
  const api = source('src/api/geoContent.js')
  for (const [name, path] of [
    ['importGeoPromptsCsv', 'prompts/import-csv'],
    ['importGeoFactsCsv', 'facts/import'],
  ]) {
    assert.match(api, new RegExp(`export function ${name}\\(tenantId, file\\)`))
    assert.match(api, new RegExp(path))
  }
  assert.match(api, /form\.append\('file', file\)/)
  assert.match(api, /params: \{ tenant_id: tenantId \}/)
})

test('GEO visibility wrappers cover patrol runs, batch probe, and period comparison', () => {
  const api = source('src/api/geoContent.js')
  for (const name of [
    'listVisibilityPatrolRuns',
    'getVisibilityPatrolRun',
    'startVisibilityPatrolRun',
    'probeGeoAnswerSnapshotBatch',
    'fetchVisibilityPeriodDiff',
  ]) {
    assert.match(api, new RegExp(`export function ${name}\\(`))
  }
})

test('GEO prompt and fact CSV uploaders delegate parsing and validation to batch APIs', () => {
  const promptUpload = functionBody(source('src/views/geo/GeoPromptsView.vue'), 'importPromptCsv')
  const factUpload = functionBody(source('src/views/geo/GeoFactsView.vue'), 'importFactCsv')

  assert.match(promptUpload, /importGeoPromptsCsv\(tenantId\.value, file\)/)
  assert.doesNotMatch(promptUpload, /file\.text\(\)|parseCsvLine|createGeoPrompt\(/)
  assert.match(factUpload, /importGeoFactsCsv\(tenantId\.value, file\)/)
  assert.doesNotMatch(factUpload, /file\.text\(\)|parseCsvLine|createGeoFact\(/)
})
