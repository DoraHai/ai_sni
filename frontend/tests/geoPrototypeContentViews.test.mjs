import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'

const viewsDir = resolve(import.meta.dirname, '../src/views/geo')

test('GEO content views expose the prototype-first page contracts', () => {
  const contracts = {
    'GeoTasksView.vue': [
      'GEO 文章', '创建 GEO 文章', 'AI 友好度', '分发记录', '导入已有文章',
      '从目标提问创建', '发布信源', '适配引擎',
    ],
    'GeoTaskEditorView.vue': [
      '在线编辑器', '事实绑定', '生成母稿', '检查就绪', '渠道适配',
      '创作要求', 'GEO评分', '优化建议', '参考资料',
      '正在生成母稿', 'AI 生成母稿',
    ],
    'GeoPlacementsView.vue': [
      '媒体 / 信源策略', '新增信源计划', '高权重信源', 'AI 已引用媒体', '待补渠道',
      '信源优先级矩阵', '官网可信底座', '发布计划', '引用效果回流', '布局清单',
    ],
  }

  for (const [file, tokens] of Object.entries(contracts)) {
    const source = readFileSync(resolve(viewsDir, file), 'utf8')
    tokens.forEach((token) => assert.ok(source.includes(token), `${file} missing ${token}`))
  }
})
