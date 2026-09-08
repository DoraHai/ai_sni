import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolveSemDetailBatch, semKeywordCard, semScopeCard, semSearchTermCard } from './sem-summary.mjs'

const fixtures = JSON.parse(readFileSync(new URL('../../../../../integrations/sem-cockpit/examples.synthetic.json', import.meta.url), 'utf8'))
const example = name => structuredClone(fixtures.examples.find(item => item.resource === name).response)

test('account scope exposes exclusions and unassigned evidence instead of hiding them', () => {
  const report = example('report')
  report.account_scope = { ...report.account_scope, includes_unassigned: true, excluded_non_active_account_ids: [12] }
  report.accounts.push({ ...report.accounts[0], baidu_account_id: null })
  const card = semScopeCard(report, 7)
  assert.equal(card.state, 'partial')
  assert.match(card.reason, /排除 1 个非在投账户/)
  assert.match(card.reason, /未归属/)
  assert.deepEqual(card.rows.map(row => row.account), [11, '未归属', 12])
})

test('keyword summary keeps missing reports distinct from observed zero', () => {
  const payload = example('keywords')
  payload.items[0].metrics.cost = 0
  payload.items[0].coverage.missing_dates = []
  const card = semKeywordCard(payload, 8)
  assert.equal(card.display, '2')
  assert.equal(card.rows[0].cost, '¥0')
  assert.equal(card.rows[1].cost, '暂无数据')
  assert.equal(card.rows[0].status, '关键词未暂停')
  assert.equal(card.updatedLabel, '2026-09-04T01:00:00+00:00')
})

test('old account-scope contract degrades instead of claiming active-only', () => {
  const report = example('report')
  report.accounts[0].status = 'disabled'
  const card = semScopeCard(report, 10)
  assert.equal(card.label, '账户范围')
  assert.equal(card.state, 'partial')
  assert.match(card.reason, /非在投账户/)
})

test('an access failure invalidates a whole concurrent detail batch', () => {
  const revoked = Object.assign(new Error('revoked'), { code: 'ACCESS_REVOKED' })
  assert.throws(() => resolveSemDetailBatch([
    { status: 'fulfilled', value: example('keywords') },
    { status: 'rejected', reason: revoked },
  ]), error => error === revoked)
  const ordinary = new Error('temporary')
  assert.deepEqual(resolveSemDetailBatch([{ status: 'rejected', reason: ordinary }]), [{ value: null, error: ordinary }])
})

test('search term summary warns when account windows differ', () => {
  const card = semSearchTermCard(example('searchTerms'), 9)
  assert.equal(card.state, 'partial')
  assert.equal(card.display, '3')
  assert.match(card.reason, /同步窗口不一致/)
  assert.equal(card.rows[0].query, '搜索%词')
})
