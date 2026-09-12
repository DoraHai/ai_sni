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

test('links an H4 blocker to safe stored evidence, times, and recovery guidance', () => {
  const [, h4] = describeAcceptanceSummary({
    h3: { status: 'awaiting_human_evidence', system_ready: true, requirements: [] },
    h4: {
      status: 'awaiting_successful_recheck',
      system_ready: false,
      blocking_reasons: ['publication_body_matched'],
      requirements: [requirement('publication_body_matched', '重新抓取的正文与登记渠道稿匹配')],
      monitoring: [{
        publication_ref: { module: 'geo', type: 'publication', id: 9 },
        channel: 'website',
        state: 'unreachable',
        checked_at: '2026-09-11T01:00:00Z',
        next_check_at: '2026-09-11T02:00:00Z',
        failures: 2,
        evidence_valid: false,
        evidence_reasons: ['monitor_not_healthy'],
        last_error: { kind: 'check_incomplete', at: '2026-09-11T01:30:00Z', secret: 'must-not-leak' },
        url: 'https://example.com/private?token=must-not-leak',
      }],
    },
  })

  assert.deepEqual(h4.observations[0], {
    publicationLabel: '发布记录 #9',
    channelLabel: '官网',
    stateLabel: '页面暂时无法检查',
    evidenceValid: false,
    evidenceStatusLabel: '当前检查依据无效',
    checkedAt: '2026/09/11 09:00',
    nextCheckAt: '2026/09/11 10:00',
    failures: 2,
    evidenceReasons: ['最近保存的监测结论尚未通过'],
    checkIncomplete: true,
    recoveryGuide: '请等待系统按计划检查，并在“分发记录 → 发布后监测”查看已有记录。',
  })
  assert.doesNotMatch(JSON.stringify(h4), /must-not-leak/)
})

test('invalid monitor timestamps and unknown evidence stay fail closed', () => {
  const [, h4] = describeAcceptanceSummary({
    h3: {},
    h4: { monitoring: [{ checked_at: '2026-09-11T01:00:00', next_check_at: 123, failures: true, evidence_reasons: ['future_reason'] }] },
  })

  assert.equal(h4.observations[0].checkedAt, null)
  assert.equal(h4.observations[0].nextCheckAt, null)
  assert.equal(h4.observations[0].failures, 0)
  assert.deepEqual(h4.observations[0].evidenceReasons, ['检查依据尚未满足'])
})

test('never presents a stored healthy state as current when its evidence is invalid', () => {
  const [, stale] = describeAcceptanceSummary({
    h3: {},
    h4: { monitoring: [{
      state: 'healthy', evidence_valid: false,
      evidence_reasons: ['fingerprint_missing_or_mismatch'],
    }] },
  })
  const [, current] = describeAcceptanceSummary({
    h3: {},
    h4: { monitoring: [{ state: 'healthy', evidence_valid: true, evidence_reasons: [] }] },
  })

  assert.equal(stale.observations[0].stateLabel, '历史检查曾匹配，当前证据无效')
  assert.equal(stale.observations[0].evidenceStatusLabel, '当前检查依据无效')
  assert.equal(current.observations[0].stateLabel, '正文匹配')
  assert.equal(current.observations[0].evidenceStatusLabel, '当前检查依据有效')
})
