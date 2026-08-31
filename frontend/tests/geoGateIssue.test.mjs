import test from 'node:test'
import assert from 'node:assert/strict'
import { explainGateIssue, formatGateFailRows } from '../src/utils/geoGateIssue.js'
import * as gateIssueModule from '../src/utils/geoGateIssue.js'

test('explainGateIssue turns ungrounded percent into an actionable title', () => {
  const out = explainGateIssue('无依据表述：数字「20%」')
  assert.match(out.title, /「20%」/)
  assert.match(out.title, /AI 候选渠道稿/)
  assert.match(out.hint, /当前显示的回退稿可能不包含该数字/)
})

test('explainGateIssue turns paragraph quota into counts', () => {
  const out = explainGateIssue(
    '完整论述段落不足（4/5）：每个小标题下至少两段完整叙述（每段约≥100字）',
  )
  assert.equal(out.title, '完整论述只有 4 段，需要 5 段')
  assert.match(out.hint, /100/)
})

test('formatGateFailRows lists channel then readable issue', () => {
  const { rows, extra } = formatGateFailRows(
    [
      { channel: 'website', issues: ['无依据表述：数字「20%」'] },
      { channel: 'wechat', issues: ['完整论述段落不足（4/5）：每个小标题下至少两段完整叙述'] },
    ],
    (k) => ({ website: '官网', wechat: '微信' }[k]),
  )
  assert.equal(extra, 0)
  assert.equal(rows[0].channel, '官网')
  assert.match(rows[0].title, /「20%」/)
  assert.equal(rows[1].channel, '微信')
  assert.equal(rows[1].title, '完整论述只有 4 段，需要 5 段')
})

test('legacy candidate-only numbers are hidden when the saved body does not contain them', () => {
  assert.equal(typeof gateIssueModule.filterGateIssuesForBody, 'function')
  const issues = gateIssueModule.filterGateIssuesForBody(
    [
      '无依据表述：数字「6个」',
      '完整论述段落不足（3/5）：现在 3 段，需要 5 段',
    ],
    '当前保存的渠道回退稿没有该数字。',
  )

  assert.deepEqual(issues, ['完整论述段落不足（3/5）：现在 3 段，需要 5 段'])
})
