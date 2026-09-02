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

  assert.ok(!navigation.includes("path: '/geo/ai-settings'"))
  assert.ok(!channelPrompts.includes('to="/geo/ai-settings"'))
  assert.ok(channelPrompts.includes('AI 能力由平台统一提供'))
})

test('legacy AI settings URL redirects instead of loading the credential form', () => {
  const router = source('../geo-frontend/src/router.js')

  assert.ok(router.includes("{ path: 'ai-settings', redirect: GEO_WORKBENCH_START }"))
  assert.ok(!router.includes("import('../../src/views/geo/GeoAiSettingsView.vue')"))
})
