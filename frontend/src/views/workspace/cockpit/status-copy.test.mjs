import assert from 'node:assert/strict'
import test from 'node:test'
import { urgencyReply } from './status-copy.mjs'

test('does not describe business actions as modules', () => {
  assert.equal(urgencyReply({ unresolvedModules: 0, businessUrgentItems: 6 }),
    '已读取的数据中有 6 项业务事项建议现在处理，可以从行动台账进入。')
  assert.equal(urgencyReply({ unresolvedModules: 2, businessUrgentItems: 6 }),
    '有 2 个模块还未完成数据读取；已读取的数据中有 6 项业务事项建议现在处理。')
})

test('describes unresolved data scope separately', () => {
  assert.equal(urgencyReply({ unresolvedModules: 2, businessUrgentItems: 0 }),
    '有 2 个模块还需要选择业务范围，或处理读取异常。')
  assert.equal(urgencyReply({ unresolvedModules: 0, businessUrgentItems: 0 }), '')
})
