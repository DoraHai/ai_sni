import test from 'node:test'
import assert from 'node:assert/strict'

import {
  getGeoPrototypeEditorSurface,
  getGeoPrototypePageSurface,
} from '../src/utils/geoEditorSurface.js'
import * as editorSurfaceModule from '../src/utils/geoEditorSurface.js'

test('prototype editor exposes fact binding and prototype action sequence', () => {
  const surface = getGeoPrototypeEditorSurface()
  assert.equal(surface.showFactBinding, true)
  assert.equal(surface.showChannelVariants, true)
  assert.deepEqual(surface.actions, [
    'bind_facts',
    'generate_master',
    'save_master',
    'check',
    'suggest_brief',
    'save_brief',
    'generate_channels',
    'copy',
  ])
  assert.deepEqual(surface.briefFields, [
    'industry',
    'audience',
    'intent',
    'content_type',
    'cta',
    'banned_claims',
  ])
  assert.equal(surface.showProgressHint, false)
  assert.equal(surface.showBatchPush, false)
  assert.equal(surface.showImpact, false)
  assert.equal(surface.showAiReview, false)
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

test('channel drafts require a current GEO score at or above 60', () => {
  assert.equal(typeof editorSurfaceModule.getGeoChannelDraftGate, 'function')
  const gate = editorSurfaceModule.getGeoChannelDraftGate

  assert.deepEqual(gate({ hasMasterDraft: false, geoScore: null, scoreIsCurrent: false }), {
    allowed: false,
    reason: '请先生成母稿',
  })
  assert.deepEqual(gate({ hasMasterDraft: true, geoScore: null, scoreIsCurrent: false }), {
    allowed: false,
    reason: '请先完成 GEO 评分',
  })
  assert.deepEqual(gate({ hasMasterDraft: true, geoScore: 59, scoreIsCurrent: true }), {
    allowed: false,
    reason: 'GEO 评分需达到 60 分，当前 59 分',
  })
  assert.deepEqual(gate({ hasMasterDraft: true, geoScore: 60, scoreIsCurrent: true }), {
    allowed: true,
    reason: '',
  })
})
