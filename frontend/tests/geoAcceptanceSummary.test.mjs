import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { describeAcceptanceSummary } from '../src/utils/geoAcceptanceSummary.js'

const apiSource = readFileSync(new URL('../src/api/geoIntegration.js', import.meta.url), 'utf8')

const requirement = (key, description, source = 'system', satisfied = false) => ({
  key, description, source, satisfied,
})

test('maps H3 blockers to customer Chinese and the exact backend requirement', () => {
  const stages = describeAcceptanceSummary({
    h3: {
      status: 'blocked',
      system_ready: false,
      blocking_reasons: ['customer_review_approved'],
      requirements: [requirement('customer_review_approved', '当前母稿已经客户确认')],
    },
    h4: {
      status: 'blocked_by_h3',
      system_ready: false,
      blocking_reasons: ['h3:customer_review_approved'],
      requirements: [],
    },
  })

  assert.equal(stages[0].statusLabel, '系统前置条件未满足')
  assert.deepEqual(stages[0].blockers[0], {
    key: 'customer_review_approved',
    stage: 'h3',
    label: '当前母稿尚未通过客户确认',
    requirement: '当前母稿已经客户确认',
  })
  assert.equal(stages[1].blockers[0].stage, 'h3')
  assert.equal(stages[1].blockers[0].requirement, '当前母稿已经客户确认')
})

test('shows the H4 recheck blocker and preserves human acceptance as pending', () => {
  const stages = describeAcceptanceSummary({
    h3: {
      status: 'awaiting_human_evidence', system_ready: true, blocking_reasons: [],
      requirements: [requirement('external_channel_exactly_once', '渠道后台确认目标内容恰好发布一次', 'human')],
    },
    h4: {
      status: 'awaiting_successful_recheck', system_ready: false,
      blocking_reasons: ['publication_body_matched'],
      requirements: [requirement('publication_body_matched', '重新抓取的正文与登记渠道稿匹配')],
    },
  })

  assert.equal(stages[0].humanRequirements[0].description, '渠道后台确认目标内容恰好发布一次')
  assert.equal(stages[1].statusLabel, '等待成功复查')
  assert.equal(stages[1].blockers[0].label, '尚无当前渠道稿正文匹配的成功复查')
  assert.equal(stages[1].blockers[0].requirement, '重新抓取的正文与登记渠道稿匹配')
})

test('unknown server reasons stay understandable and never become an action', () => {
  const [stage] = describeAcceptanceSummary({
    h3: { status: 'blocked', blocking_reasons: ['future_check'], requirements: [] },
    h4: {},
  })

  assert.equal(stage.blockers[0].label, '对应验收条件尚未满足')
  assert.equal(stage.blockers[0].requirement, null)
})

test('acceptance summary client uses the query-only integration endpoint', () => {
  const declaration = apiSource.slice(
    apiSource.indexOf('export const acceptanceSummary'),
    apiSource.indexOf('\n)', apiSource.indexOf('export const acceptanceSummary')) + 2,
  )
  assert.match(declaration, /client\.get\(/)
  assert.match(declaration, /\/integration\/read\/content-tasks\/\$\{contentId\}\/acceptance-summary/)
  assert.doesNotMatch(declaration, /client\.(post|put|patch|delete)\(/)
})
