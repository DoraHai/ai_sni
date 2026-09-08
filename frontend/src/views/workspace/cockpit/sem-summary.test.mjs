import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { semKeywordCard, semScopeCard, semSearchTermCard } from './sem-summary.mjs'

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
  const card = semKeywordCard(example('keywords'), 8)
  assert.equal(card.display, '2')
  assert.equal(card.rows[0].cost, '已观测小计 ¥10')
  assert.equal(card.rows[1].cost, '暂无数据')
})

test('search term summary warns when account windows differ', () => {
  const card = semSearchTermCard(example('searchTerms'), 9)
  assert.equal(card.state, 'partial')
  assert.equal(card.display, '3')
  assert.match(card.reason, /同步窗口不一致/)
  assert.equal(card.rows[0].query, '搜索%词')
})
