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

test('versioned demo scope is labelled as simulation instead of a live account warning', () => {
  const report = example('report')
  report.is_demo = true
  report.accounts[0].status = 'demo'
  const card = semScopeCard(report, 7)
  assert.equal(card.state, 'available')
  assert.equal(card.sourceLabel, '版本化 SEM 内置演示数据')
  assert.match(card.reason, /只读演示数据/)
  assert.match(card.reason, /不触发同步、投放或外部调用/)
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
  payload.items[0].report_association.evidence_status = 'account_mismatch'
  payload.items[0].report_association.other_observed_account_ids = [12]
  payload.items[0].report_association.observed_known_account_ids = [12]
  payload.association_summary.counts = { matched: 0, account_mismatch: 1, no_report: 0 }
  const card = semKeywordCard(payload, 9)
  assert.equal(card.state, 'partial')
  assert.match(card.reason, /本页展示 1 个/)
  assert.match(card.reason, /1 个仅观察到已知的其他账户同 ID 报告/)
  assert.equal(card.rows[0].report, '仅其他已知账户有同 ID 报告')
  assert.equal(card.rows[0].cost, '暂无数据')
})

test('keyword summary keeps report-side unknown ownership distinct from mismatch', () => {
  const payload = example('keywords')
  payload.page_size = 1
  payload.items = [payload.items[1]]
  payload.items[0].report_association.evidence_status = 'report_ownership_unknown'
  payload.items[0].report_association.has_unassigned_reports = true
  const card = semKeywordCard(payload, 9)
  assert.equal(card.state, 'partial')
  assert.match(card.reason, /1 个只观察到归属未知的同 ID 报告/)
  assert.equal(card.rows[0].report, '仅有归属未知报告，未关联')
  assert.equal(card.rows[0].cost, '暂无数据')
})

test('keyword summary retains known mismatch and unknown report evidence together', () => {
  const payload = example('keywords')
  payload.page_size = 1
  payload.items = [payload.items[1]]
  payload.items[0].report_association.status = 'account_mismatch'
  payload.items[0].report_association.evidence_status = 'account_mismatch'
  payload.items[0].report_association.other_observed_account_ids = [12]
  payload.items[0].report_association.observed_known_account_ids = [12]
  payload.items[0].report_association.has_unassigned_reports = true
  const card = semKeywordCard(payload, 9)
  assert.match(card.reason, /1 个仅观察到已知的其他账户同 ID 报告/)
  assert.match(card.reason, /1 个还存在归属未知报告/)
  assert.equal(card.rows[0].report, '仅其他已知账户有同 ID 报告；另有归属未知报告')
})

test('keyword summary exposes unknown ownership without attaching report evidence', () => {
  const payload = example('keywords')
  payload.page_size = 1
  payload.items = [payload.items[1]]
  payload.items[0].baidu_account_id = null
  payload.items[0].report_association.evidence_status = 'ownership_unknown'
  payload.items[0].report_association.other_observed_account_ids = []
  const card = semKeywordCard(payload, 9)
  assert.equal(card.state, 'partial')
  assert.match(card.reason, /本页展示 1 个/)
  assert.match(card.reason, /1 个关键词资产缺少账户归属/)
  assert.equal(card.rows[0].report, '资产账户归属未知，未关联报告')
  assert.equal(card.rows[0].cost, '暂无数据')
})

test('current five-state and legacy three-state payloads degrade without hiding the keyword card', () => {
  const current = example('keywords')
  current.items = [current.items[1]]
  current.total = 1
  delete current.items[0].report_association.evidence_status
  delete current.items[0].report_association.observed_known_account_ids
  current.items[0].report_association.status = 'report_ownership_unknown'
  current.items[0].report_association.has_unassigned_reports = true
  assert.equal(semKeywordCard(current, 10).rows[0].report, '仅有归属未知报告，未关联')

  const legacy = example('keywords')
  legacy.items = [legacy.items[0]]
  legacy.total = 1
  legacy.items[0].baidu_account_id = null
  legacy.items[0].metrics = { cost: 99, click: 9, impression: 90, ctr: 0.1, cpc: 11 }
  legacy.items[0].coverage.status = 'observed'
  legacy.items[0].report_association.status = 'matched'
  delete legacy.items[0].report_association.evidence_status
  delete legacy.items[0].report_association.observed_known_account_ids
  delete legacy.items[0].report_association.has_unassigned_reports
  const legacyCard = semKeywordCard(legacy, 11)
  assert.equal(legacyCard.rows[0].report, '资产账户归属未知，未关联报告')
  assert.equal(legacyCard.rows[0].cost, '暂无数据')
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
