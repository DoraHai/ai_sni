import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const api = readFileSync(new URL('../src/api/geoContent.js', import.meta.url), 'utf8')
const visibility = readFileSync(new URL('../src/views/geo/GeoVisibilityDashView.vue', import.meta.url), 'utf8')
const prompts = readFileSync(new URL('../src/views/geo/GeoAskManageView.vue', import.meta.url), 'utf8')
const facts = readFileSync(new URL('../src/views/geo/GeoFactsView.vue', import.meta.url), 'utf8')

test('monitoring API wrappers cover patrol, probe, extract, citations, and CSV import', () => {
  for (const token of [
    'export function importGeoPromptsCsv(tenantId, file)',
    'prompts/import-csv',
    'export function importGeoFactsCsv(tenantId, file)',
    'facts/import',
    'export function startVisibilityPatrolRun(body)',
    'export function probeGeoAnswerSnapshot(body)',
    'export function probeGeoAnswerSnapshotBatch(body)',
    'export function extractGeoAnswerSnapshotUrls(body)',
    'export function checkGeoAnswerSnapshotCitations(body)',
  ]) {
    assert.ok(api.includes(token), `geoContent.js missing ${token}`)
  }
})

test('visibility refresh detection starts a patrol run and waits for completion', () => {
  assert.match(visibility, /async function refreshDetect\(\)/)
  assert.match(visibility, /await startVisibilityPatrolRun\(/)
  assert.match(visibility, /await getVisibilityPatrolRun\(tenantId\.value, id\)/)
  assert.match(visibility, /刷新检测/)
})

test('visibility snapshot ops probe, extract URLs, and check citations', () => {
  assert.match(visibility, /probeGeoAnswerSnapshot\(/)
  assert.match(visibility, /extractGeoAnswerSnapshotUrls\(/)
  assert.match(visibility, /checkGeoAnswerSnapshotCitations\(/)
  assert.match(visibility, /探测回答/)
  assert.match(visibility, /提取 URL/)
  assert.match(visibility, /检查引用/)
})

test('canonical prompt and knowledge pages upload CSV in one server batch', () => {
  assert.match(prompts, /importGeoPromptsCsv\(tenantId\.value, file\)/)
  assert.match(prompts, /CSV 导入/)
  assert.doesNotMatch(prompts, /file\.text\(\)/)
  assert.match(facts, /importGeoFactsCsv\(tenantId\.value, file\)/)
  assert.match(facts, /CSV 导入/)
})
