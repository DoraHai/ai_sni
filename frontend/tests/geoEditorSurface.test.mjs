import test from 'node:test'
import assert from 'node:assert/strict'

import {
  getGeoPrototypeEditorSurface,
  getGeoPrototypePageSurface,
} from '../src/utils/geoEditorSurface.js'

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
