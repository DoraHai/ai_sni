import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const frontendDir = resolve(import.meta.dirname, '..')
const read = (path) => readFileSync(resolve(frontendDir, path), 'utf8')

test('workbench visual tokens are scoped to .geo-wb', () => {
  const css = read('src/styles/geo-v2.css')
  const shell = read('src/components/GeoWorkbenchPage.vue')
  for (const token of [
    '--geo-bg: #f6f7fb',
    '--geo-surface: #ffffff',
    '--geo-text: #16181d',
    '--geo-muted: #7a8393',
    '--geo-line: #e7e9ef',
    '--geo-primary: #5b5ce2',
    '--geo-radius: 12px',
    '--geo-content-width: 1440px',
  ]) {
    assert.ok(css.includes(token), `geo-v2.css missing ${token}`)
  }
  assert.match(shell, /class="geo-wb"/)
  assert.match(shell, /class="geo-content"/)
})

test('each GEO v2 page exposes prototype H1, primary actions, and first-screen headers', () => {
  const contracts = {
    'src/views/geo/GeoOverviewView.vue': [
      'title="GEO 概览"', '+ 添加监控词', '各 AI 引擎可见度趋势', 'AI 声量占比 (SOV)',
      '高曝光提问 (Prompt)', 'AI 引用的内容来源',
    ],
    'src/views/geo/GeoVisibilityDashView.vue': [
      'title="AI 可见度"', '刷新检测', '情感倾向', '品牌被提及的方式', '登记回答快照',
    ],
    'src/views/geo/GeoAskManageView.vue': [
      'title="AI 提问管理"', '业务', '关键词', 'AI 提问', '批量操作', 'CSV 导入',
    ],
    'src/views/geo/GeoCompetitorsView.vue': [
      'title="竞品分析"', '品牌 × AI 引擎 推荐度热力图',
    ],
    'src/views/geo/GeoEvaluationView.vue': [
      'title="评价分析"', '分布', '最近快照',
    ],
    'src/views/geo/GeoCitationsView.vue': [
      'title="信源分析"', '信源平台 × AI 引擎', '被 AI 引用最多的文章', '数据导出',
    ],
    'src/views/geo/GeoTasksView.vue': [
      'title="GEO 文章工作台"', '创建 GEO 文章', 'AI 友好度', '分发记录',
    ],
    'src/views/geo/GeoArticleImportView.vue': [
      'title="导入已有文章"', '粘贴文章', '上传文档', 'URL 导入',
    ],
    'src/views/geo/GeoTaskEditorView.vue': [
      'aria-label="在线编辑器"', '手动发布', '自动发布', 'GEO评分', '优化建议',
    ],
    'src/views/geo/GeoDistributionView.vue': [
      'title="分发记录"', '推送草稿', '推送发布', '回填',
    ],
    'src/views/geo/GeoPlacementsView.vue': [
      'title="媒体 / 信源策略"', '新增信源计划', '官网可信底座',
    ],
    'src/views/geo/GeoChannelsView.vue': [
      'title="分发平台"', '刷新连接状态', '添加分发平台', '信源角色',
    ],
    'src/views/geo/GeoStructureView.vue': [
      'title="官网结构优化"', '重新扫描', '哪些页面需要优化',
    ],
    'src/views/geo/GeoBrandSettingsView.vue': [
      'title="品牌信息"',
    ],
    'src/views/geo/GeoFactsView.vue': [
      'title="知识库"', 'CSV 导入', '事实卡',
    ],
    'src/views/geo/GeoAiSettingsView.vue': [
      'title="AI 能力配置"', '接入配置', 'API Key', '测试连通',
    ],
    'src/views/geo/GeoEnginesView.vue': [
      'title="AI 引擎管理"', '租户监测引擎', '引擎 key', '展示名',
    ],
  }

  for (const [file, tokens] of Object.entries(contracts)) {
    const source = read(file)
    tokens.forEach((token) => assert.ok(source.includes(token), `${file} missing ${token}`))
  }
})
