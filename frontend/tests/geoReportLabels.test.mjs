import test from 'node:test'
import assert from 'node:assert/strict'
import { blockedGateItems, checkLabel } from '../src/utils/geoReportLabels.js'

test('checkLabel maps gate codes to Chinese', () => {
  assert.equal(checkLabel('fabrication_lint'), '编造风险扫描')
  assert.equal(checkLabel('channel_variant_ready'), '渠道稿已生成')
  assert.equal(checkLabel('numbers_extractable'), '可抽取数据')
})

test('blockedGateItems splits comma codes and caps visible tags', () => {
  const out = blockedGateItems(
    'numbers_extractable, fabrication_lint, sentence_evidence, channel_variant_ready',
    3,
  )
  assert.deepEqual(
    out.items.map((i) => i.label),
    ['可抽取数据', '编造风险扫描', '逐句证据'],
  )
  assert.equal(out.extra, 1)
  assert.match(out.title, /渠道稿已生成/)
})
