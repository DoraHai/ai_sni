import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'

const viewsDir = resolve(import.meta.dirname, '../src/views/geo')

test('GEO delivery views expose the prototype-first page contracts', () => {
  const contracts = {
    'GeoTicketsView.vue': ['验收工单', '刷新列表', '批量重抓验收', '批量验收', '创建媒体工单'],
    'GeoChannelsView.vue': [
      '分发平台', '刷新连接状态', '添加分发平台', '自有渠道', '内容平台',
      '信源角色', 'AI 引用潜力', '适配引擎',
    ],
    'GeoDistributionView.vue': ['分发记录', '推送草稿', '推送发布', '回填', '复制'],
    'GeoPublishingView.vue': ['发布渠道', '创建渠道', '添加渠道账号', '发布方式'],
  }

  for (const [file, tokens] of Object.entries(contracts)) {
    const source = readFileSync(resolve(viewsDir, file), 'utf8')
    tokens.forEach((token) => assert.ok(source.includes(token), `${file} missing ${token}`))
  }
})

test('batch push treats cancellation as a terminal non-success state', () => {
  const source = readFileSync(
    resolve(viewsDir, 'GeoTaskEditorView.vue'),
    'utf8',
  )

  assert.match(source, /job\.status === 'cancelled'/)
  assert.match(source, /推送已取消/)
})
