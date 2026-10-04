import test from 'node:test'
import assert from 'node:assert/strict'
import { aiTdkStatus, aiTdkFields, aiTdkCount, aiTdkResultText } from '../src/api/seoAiTdk.js'

test('AI TDK status and fields stay explicit', () => {
  assert.deepEqual(aiTdkFields.map(field => field.key), ['title', 'description', 'keywords'])
  assert.equal(aiTdkStatus('ai_draft'), 'AI草稿')
  assert.equal(aiTdkStatus('modified'), '已修改')
  assert.equal(aiTdkCount('页面 A'), 4)
  assert.match(aiTdkResultText([{ page_id: 1, status: 'generated' }, { page_id: 2, status: 'error', error: '超时' }]), /#2：超时/)
})
