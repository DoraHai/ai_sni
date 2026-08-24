import test from 'node:test'
import assert from 'node:assert/strict'

import { getGeoPrototypeEditorSurface } from '../src/utils/geoEditorSurface.js'

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
    showChannelVariants: false,
    showBatchPush: false,
    showImpact: false,
    showAiReview: false,
    actions: ['suggest_brief', 'save_brief', 'generate_master', 'save_master', 'copy', 'check'],
  })
})
