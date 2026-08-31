import test from 'node:test'
import assert from 'node:assert/strict'
import { pushBlockLabels } from '../src/utils/geoPushBlockers.js'

test('push blockers use concise business labels instead of credential details', () => {
  assert.deepEqual(
    pushBlockLabels({
      blockReasons: [
        '发布模式不是 auto_publish（在发布渠道里改为 auto_publish）',
        '缺少 webhook 账号+凭证',
      ],
    }),
    ['未开启自动发布', '未配置发布账号'],
  )
  assert.deepEqual(pushBlockLabels({ blockReasons: ['无渠道稿（任务里生成并导出 baijiahao）'] }), ['未生成渠道稿'])
  assert.deepEqual(pushBlockLabels({ blockReasons: [] }), ['该渠道仅支持手动发布'])
})
