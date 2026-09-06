import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  pageCheckDisplay,
  publicationDisplay,
  searchPerformanceDisplay,
  seoWorkbenchDisplay,
} from '../src/utils/seoWorkbenchDisplay.js'

const example = JSON.parse(readFileSync(
  new URL('../../docs/examples/seo_workbench_customer_example.json', import.meta.url),
  'utf8',
))

function scenario(id) {
  return example.items.find((item) => item.scenario_id === id).view
}

test('publication, page check and search performance remain separate', () => {
  const display = seoWorkbenchDisplay(scenario('multi_platform_mixed'))
  assert.equal(display.publication.recordCount, 2)
  assert.equal(display.publication.items[0].successful, true)
  assert.equal(display.publication.items[1].successful, false)
  assert.equal(display.pageCheck.state, 'unavailable')
  assert.equal(display.pageCheck.passed, null)
  assert.equal(display.searchPerformance.articleClicks, null)
  assert.equal(display.searchPerformance.valueText, '—')
})

test('a URL or successful attempt cannot turn a failed publication into success', () => {
  const result = publicationDisplay([{
    id: 7,
    state: 'failed',
    page_url: 'https://example.invalid/article',
    latest_attempt: { id: 8, status: 'success' },
  }], { record_count: 1, successful_count: 0, failed_count: 1 })
  assert.equal(result.items[0].state, 'failed')
  assert.equal(result.items[0].successful, false)
  assert.equal(result.items[0].latestAttempt.state, 'success')

  const unknown = publicationDisplay([{ id: 9, state: 'vendor_future_state' }], null)
  assert.equal(unknown.items[0].state, 'unknown')
  assert.equal(unknown.items[0].successful, null)
})

test('missing summary stays unknown while measured zero remains zero', () => {
  const missing = publicationDisplay([], null)
  assert.equal(missing.recordCount, null)
  assert.equal(missing.successfulCount, null)

  const measured = publicationDisplay([], {
    record_count: 0,
    successful_count: 0,
    failed_count: 0,
  })
  assert.equal(measured.recordCount, 0)
  assert.equal(measured.successfulCount, 0)
})

test('page check fields are hidden unless explicit mapping evidence matched', () => {
  const result = pageCheckDisplay({
    mapping_state: 'unmapped',
    page_id: 77,
    candidate_count: 1,
    check_state: 'assessed',
    checked_at: '2026-09-07T01:00:00Z',
    latest_snapshot_id: 88,
    http_status: 200,
    passed: true,
  })
  assert.equal(result.mappingState, 'unmapped')
  assert.equal(result.pageId, null)
  assert.equal(result.state, 'unavailable')
  assert.equal(result.checkedAt, null)
  assert.equal(result.passed, null)
})

test('matched assessment does not invent a whole-page pass result', () => {
  const result = pageCheckDisplay({
    mapping_state: 'matched',
    page_id: 77,
    candidate_count: 1,
    check_state: 'assessed',
    checked_at: '2026-09-07T01:00:00Z',
    latest_snapshot_id: 88,
    http_status: 200,
    passed: null,
  })
  assert.equal(result.state, 'assessed')
  assert.equal(result.pageId, 77)
  assert.equal(result.passed, null)
  assert.equal(result.outcomeLabel, '未提供整页通过结论')

  const contradictory = pageCheckDisplay({
    mapping_state: 'matched',
    page_id: 77,
    check_state: 'not_checked',
    passed: true,
  })
  assert.equal(contradictory.passed, null)
})

test('search clicks display only when explicitly available and preserve zero', () => {
  const contradictory = searchPerformanceDisplay({
    state: 'unavailable',
    article_clicks: 300,
    reason: '没有单篇归因',
  })
  assert.equal(contradictory.articleClicks, null)
  assert.equal(contradictory.valueText, '—')

  const zero = searchPerformanceDisplay({ state: 'available', article_clicks: 0 })
  assert.equal(zero.articleClicks, 0)
  assert.equal(zero.valueText, '0')

  const missing = searchPerformanceDisplay({ state: 'available', article_clicks: null })
  assert.equal(missing.state, 'unavailable')
  assert.equal(missing.articleClicks, null)
})
