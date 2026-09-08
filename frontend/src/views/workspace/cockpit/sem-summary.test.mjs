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
  assert.equal(card.rows[0].report, '同账户报告已关联')
  assert.equal(card.rows[1].report, '窗口内无报告')
  assert.equal(card.updatedLabel, '2026-09-04T01:00:00+00:00')
})

test('keyword summary exposes account mismatch as a current-page boundary', () => {
  const payload = example('keywords')
  payload.page_size = 1
  payload.items = [payload.items[1]]
  payload.items[0].report_association.status = 'account_mismatch'
  payload.items[0].report_association.other_observed_account_ids = [null]
  payload.association_summary.counts = { matched: 0, account_mismatch: 1, no_report: 0, ownership_unknown: 0 }
  const card = semKeywordCard(payload, 9)
  assert.equal(card.state, 'partial')
  assert.match(card.reason, /本页展示 1 个/)
  assert.match(card.reason, /1 个仅观察到其他账户的同 ID 报告/)
  assert.equal(card.rows[0].report, '仅其他账户有同 ID 报告')
  assert.equal(card.rows[0].cost, '暂无数据')
})

test('keyword summary exposes unknown ownership without attaching report evidence', () => {
  const payload = example('keywords')
  payload.page_size = 1
  payload.items = [payload.items[1]]
  payload.items[0].baidu_account_id = null
  payload.items[0].report_association.status = 'ownership_unknown'
  payload.items[0].report_association.other_observed_account_ids = []
  payload.association_summary.counts = { matched: 0, account_mismatch: 0, no_report: 0, ownership_unknown: 1 }
  const card = semKeywordCard(payload, 9)
  assert.equal(card.state, 'partial')
  assert.match(card.reason, /本页展示 1 个/)
  assert.match(card.reason, /1 个关键词缺少账户归属/)
  assert.equal(card.rows[0].report, '账户归属未知，未关联报告')
  assert.equal(card.rows[0].cost, '暂无数据')
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
  const stale = Object.assign(new Error('stale sibling'), { code: 'STALE_RESPONSE' })
  assert.throws(() => resolveSemDetailBatch([
    { status: 'rejected', reason: stale },
    { status: 'rejected', reason: revoked },
  ]), error => error === revoked)
  const ordinary = new Error('temporary')
  assert.deepEqual(resolveSemDetailBatch([{ status: 'rejected', reason: ordinary }]), [{ value: null, error: ordinary }])
})

test('search term summary warns when account windows differ', () => {
  const payload = example('searchTerms')
  payload.total = 51
  const card = semSearchTermCard(payload, 9)
  assert.equal(card.state, 'partial')
  assert.equal(card.display, '51')
  assert.match(card.reason, /本页展示 3 条，共 51 条/)
  assert.match(card.reason, /同步窗口不一致/)
  assert.equal(card.rows[0].query, '搜索%词')
})
