import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'

const viewsDir = resolve(import.meta.dirname, '../src/views/geo')

function assertTokens(file, tokens) {
  const source = readFileSync(resolve(viewsDir, file), 'utf8')
  tokens.forEach((token) => assert.ok(source.includes(token), `${file} missing ${token}`))
}

test('GEO settings views expose the prototype-first page contracts', () => {
  assertTokens('GeoAiSettingsView.vue', ['接入配置', '服务商', 'Base URL', '模型', 'API Key', '测试连通', '监测引擎'])
  assertTokens('GeoEnginesView.vue', ['租户监测引擎', '启用', '引擎 key', '展示名', '排序', '备注', 'AI 能力配置'])
  assertTokens('GeoBrandSettingsView.vue', ['品牌信息'])
  assertTokens('GeoChannelPolishPromptsView.vue', ['渠道成稿提示词'])
  assertTokens('GeoStructureView.vue', [
    '官网结构优化', 'AI 可解析结构', '品牌信息', '重新扫描', '扫描设置',
    '哪些页面需要优化', '官网内容关系完整度', '使用边界',
  ])
})
