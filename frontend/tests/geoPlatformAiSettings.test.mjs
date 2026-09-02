import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

function source(relativePath) {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8')
}

test('customer navigation does not expose tenant AI credential settings', () => {
  const navigation = source('../src/utils/geoPrototypeNavigation.js')
  const channelPrompts = source('../src/views/geo/GeoChannelPolishPromptsView.vue')
  const taskEditor = source('../src/views/geo/GeoTaskEditorView.vue')
  const engines = source('../src/views/geo/GeoEnginesView.vue')

  assert.ok(!navigation.includes("path: '/geo/ai-settings'"))
  assert.ok(!channelPrompts.includes('to="/geo/ai-settings"'))
  assert.ok(!taskEditor.includes('/geo/ai-settings'))
  assert.ok(!engines.includes('/geo/ai-settings'))
  assert.ok(channelPrompts.includes('AI 能力由平台统一提供'))
  assert.ok(engines.includes('AI 能力由平台统一提供'))
})

test('legacy AI settings URL redirects instead of loading the credential form', () => {
  const router = source('../geo-frontend/src/router.js')
  const sharedRouter = source('../src/router/index.js')

  assert.ok(router.includes("{ path: 'ai-settings', redirect: GEO_WORKBENCH_START }"))
  assert.ok(!router.includes("import('../../src/views/geo/GeoAiSettingsView.vue')"))
  assert.ok(sharedRouter.includes("{ path: 'ai-settings', redirect: GEO_WORKBENCH_START }"))
  assert.ok(!sharedRouter.includes("import('../views/geo/GeoAiSettingsView.vue')"))
})
