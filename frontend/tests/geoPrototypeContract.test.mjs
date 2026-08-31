import test from 'node:test'
import assert from 'node:assert/strict'
import { GEO_PROTOTYPE_GROUPS, GEO_PROTOTYPE_PAGES } from '../src/utils/geoPrototypeContract.js'

test('GEO prototype exposes the geo-v2 sidebar information architecture', () => {
  assert.deepEqual(GEO_PROTOTYPE_GROUPS.map((group) => group.label), [
    '数据看板', '智能监测', '内容与信源', '设置',
  ])
  assert.deepEqual(
    GEO_PROTOTYPE_PAGES.filter((p) => !p.hidden).map((page) => page.label),
    [
      'GEO 概览', 'AI 可见度', '提问监控', '竞品分析', '信源分析',
      'GEO 文章', '媒体 / 信源策略', '分发平台', '官网结构优化',
      '品牌信息', '知识库', 'AI 能力配置', 'AI 引擎管理',
    ],
  )
  assert.deepEqual(
    GEO_PROTOTYPE_PAGES.filter((p) => !p.hidden).map((page) => page.path),
    [
      '/geo/overview', '/geo/visibility', '/geo/prompts', '/geo/competitors', '/geo/sources',
      '/geo/articles', '/geo/media', '/geo/channels', '/geo/structure',
      '/geo/brand', '/geo/knowledge', '/geo/ai-settings', '/geo/engines',
    ],
  )
  assert.deepEqual(
    GEO_PROTOTYPE_PAGES.filter((p) => p.hidden).map((page) => page.id),
    ['evaluation', 'import', 'editor', 'distribution'],
  )
})
