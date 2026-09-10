import test from 'node:test'
import assert from 'node:assert/strict'
import { geoDemoCards } from './demo-summary.mjs'

const data = () => ({
  summary: { tenant_id: 16, official: false, source_kind: 'synthetic', excluded_from_official_metrics: true,
    demo: { read_only: true }, window: { current: { start: '2026-08-31', end: '2026-09-07', mention_rate: 50, mention_count: 18, sample_count: 36, own_domain_citation_count: 12 } } },
  capabilities: { tenant_id: 16, historical_engine_keys: ['deepseek', 'qwen', 'kimi'], engines: [{ enabled: false }] },
  contextRevision: 1,
})
test('demo shows samples and historical engines without claiming live configuration or official metrics', () => {
  const cards = geoDemoCards(data())
  assert.deepEqual(cards.map(c => c.display), ['50', '18', '12', '36', '3'])
  assert.ok(cards.every(c => c.moduleLabel.includes('演示') && c.sourceLabel.includes('演示')))
  assert.equal(cards[0].periodLabel, '2026-08-31 至 2026-09-06（完整周）')
})
test('wrong tenant or official source is rejected, missing numeric data never becomes zero', () => {
  const bad = data(); bad.summary.official = true
  assert.throws(() => geoDemoCards(bad))
  const other = data(); other.capabilities.tenant_id = 4
  assert.throws(() => geoDemoCards(other))
  const missing = data(); delete missing.summary.window.current.sample_count
  assert.equal(geoDemoCards(missing)[3].display, '—')
})
