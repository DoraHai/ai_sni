import test from 'node:test'
import assert from 'node:assert/strict'
import {questionScopeQuery, validQuestionScope, evaluationLabel, isBrandEvaluation} from '../src/utils/geoQuestionScope.js'

test('all remains all; only deliberate drilling sets dimensions', () => {
  assert.deepEqual(questionScopeQuery({tenant_id: '101'}, 'question'), {tenant_id: '101', layer: 'question'})
  const selected = {tenant_id: '101', business_id: '1', unit_id: '11', tag: 'old'}
  assert.deepEqual(questionScopeQuery(selected, 'keyword', {business_id: '2'}),
    {tenant_id: '101', layer: 'keyword', business_id: '2'})
  assert.deepEqual(questionScopeQuery(selected, 'business'), {tenant_id: '101', layer: 'business'})
  assert.deepEqual(validQuestionScope(1, 21, [{id: 1}], [{id: 21, business_id: 2}]), {business_id: 1, unit_id: null})
  assert.deepEqual(validQuestionScope(999, 21, [{id: 1}], [{id: 21, business_id: 2}]), {business_id: null, unit_id: null})
})

test('saved answers and actual brand evaluations have separate denominators', () => {
  assert.match(evaluationLabel(4, 0), /已保存 4 条回答；有效品牌评价 0 条，暂不能判断评价/)
  for (const n of [1, 2]) assert.match(evaluationLabel(4, n), /小样本，至少 3 条/)
  assert(!evaluationLabel(4, 0).includes('0%'))
  assert.equal(isBrandEvaluation({mentions_brand: false, sentiment: 'positive'}), false)
  assert.equal(isBrandEvaluation({mentions_brand: true, sentiment: 'unknown'}), false)
  assert.equal(isBrandEvaluation({mentions_brand: true, sentiment: 'positive'}), true)
})
