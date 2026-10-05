import test from 'node:test'
import assert from 'node:assert/strict'
import { defaultTdkReviewSections, validTdkReviewTemplate, moveTdkReviewSection, reviewPageIds, reviewFilename } from '../src/api/seoTdkReview.js'

test('template sections and column toggles validate', () => {
  const sections = structuredClone(defaultTdkReviewSections)
  assert.equal(validTdkReviewTemplate(sections, { char_counts: true, rationale: false }), true)
  assert.equal(validTdkReviewTemplate([...sections, sections[0]], { char_counts: true, rationale: false }), false)
  assert.equal(validTdkReviewTemplate(sections, { char_counts: 'yes', rationale: false }), false)
  assert.equal(moveTdkReviewSection(sections, 1, -1)[0].key, 'screenshot')
})

test('selection deduplicates and attachment filename decodes', () => {
  assert.deepEqual(reviewPageIds([{ id: 3 }, { id: 3 }, { id: 4 }]), [3, 4])
  assert.equal(reviewFilename("attachment; filename*=UTF-8''TDK%E5%AE%A1%E6%A0%B8%E7%A8%BF.docx", 'fallback'), 'TDK审核稿.docx')
})
