import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import {
  getGeoPrototypeEditorSurface,
  getGeoPrototypePageSurface,
} from '../src/utils/geoEditorSurface.js'

const editorSource = readFileSync(
  fileURLToPath(new URL('../src/views/geo/GeoTaskEditorView.vue', import.meta.url)),
  'utf8',
)

test('prototype editor exposes only drafting, quality and publication entry points', () => {
  assert.deepEqual(getGeoPrototypeEditorSurface(), {
    briefFields: [
      'industry',
      'audience',
      'intent',
      'content_type',
      'cta',
      'banned_claims',
    ],
    showProgressHint: false,
    showFactBinding: false,
    showChannelVariants: true,
    showBatchPush: false,
    showImpact: false,
    showAiReview: false,
    actions: [
      'suggest_brief',
      'save_brief',
      'generate_master',
      'save_master',
      'generate_channels',
      'copy',
      'check',
    ],
  })
})

test('prototype competitor and channel pages keep only their primary surfaces', () => {
  assert.deepEqual(getGeoPrototypePageSurface(), {
    showCompetitorAdvancedAnalysis: false,
    showChannelAutomationConsole: false,
    showChannelAccountConsole: true,
    showEvaluationRawMetrics: false,
    showCitationRawMetrics: false,
    showKnowledgeHealth: false,
    showLightweightOperations: false,
  })
})

test('task editor keeps the complete editor-first interaction surface', () => {
  for (const marker of [
    'class="ed-shell"',
    "const leftTab = ref('brief')",
    'const showCheckDrawer = ref(false)',
    'const focusMode = ref(false)',
    "window.dispatchEvent(new CustomEvent('geo-editor-focus'",
    'saveArticleBody({ silent: true })',
    '可信材料',
    '标记已处理',
  ]) {
    assert.ok(editorSource.includes(marker), `missing editor interaction marker: ${marker}`)
  }
})
