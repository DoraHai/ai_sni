import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'

const viewsDir = resolve(import.meta.dirname, '../src/views/geo')

test('GEO monitoring views expose the prototype-first page contracts', () => {
  const contracts = {
    'GeoOverviewView.vue': ['可见度期次对比', 'Demo 最短路径', '计算 Δ'],
    'GeoVisibilityDashView.vue': [
      '情感倾向', '品牌被提及的方式', 'AI 回答示例', '本品牌', '竞品',
      '登记回答快照', '回答原文', '保存快照', '快照列表',
    ],
    'GeoAskManageView.vue': ['AI 提问管理', '业务', '关键词', 'AI 提问', 'AI 提及率', '样本不足', 'AI评价分析'],
    'GeoCompetitorsView.vue': ['竞品提及聚合', '出现次数', '关联提问', '样例提问'],
    'GeoCitationsView.vue': [
      '信源分析', '已识别信源平台', '最常被引平台', '本品牌内容占比', '高价值待铺信源',
      '信源平台 × AI 引擎', '被 AI 引用最多的文章', '信源布局建议', '数据导出',
    ],
    'GeoFactsView.vue': ['知识库', 'CSV 导入', '作者', '可信度', '过期日', '核验'],
  }

  for (const [file, tokens] of Object.entries(contracts)) {
    const source = readFileSync(resolve(viewsDir, file), 'utf8')
    tokens.forEach((token) => assert.ok(source.includes(token), `${file} missing ${token}`))
  }
})
