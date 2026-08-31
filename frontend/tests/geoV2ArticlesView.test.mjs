import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const view = readFileSync(new URL('../src/views/geo/GeoTasksView.vue', import.meta.url), 'utf8')
const api = readFileSync(new URL('../src/api/geoContent.js', import.meta.url), 'utf8')

test('article workbench loads list summaries and workbench tabs from the real API', () => {
  assert.match(api, /export function listGeoContentTasks\(tenantId, params = \{\}\)/)
  assert.match(view, /params\.workbench_tab = workbenchTab\.value/)
  assert.match(view, /listGeoContentTasks\(tenantId\.value, params\)/)
  assert.match(view, /row\.geo_score/)
  assert.match(view, /row\.publication_channels/)
  assert.match(view, /row\.engine_keys/)
})

test('article workbench matches the prototype list, tabs, and create dialog', () => {
  for (const token of [
    'title="GEO 文章工作台"',
    '＋ 创建 GEO 文章',
    'label: \'全部\'',
    'label: \'草稿\'',
    'label: \'待润色\'',
    'label: \'待发布\'',
    'label: \'已发布\'',
    'label="文章"',
    'label="目标提问"',
    'label="适配引擎"',
    'label="AI 友好度"',
    'label="发布信源"',
    '分发记录',
    '引用回流',
    '从目标提问创建',
    '导入已有文章',
    "router.push('/geo/import')",
  ]) {
    assert.ok(view.includes(token), `GeoTasksView.vue missing ${token}`)
  }
  assert.match(view, /\/geo\/articles\/\$\{row\.id\}\/distribution/)
})

test('article workbench keeps the prototype principles and groups secondary row actions', () => {
  for (const token of ['独家信息', '事实可核验', '明确来源', '定义 / 对比 / FAQ', '不堆关键词']) {
    assert.ok(view.includes(token), `GeoTasksView.vue missing principle ${token}`)
  }
  assert.match(view, /class="geo-flow-step"/)
  assert.match(view, /<el-dropdown[^>]*@command="\(command\) => handleRowAction\(row, command\)"/)
  assert.match(view, /<el-dropdown-item command="distribution">分发记录<\/el-dropdown-item>/)
  assert.match(view, /<el-dropdown-item command="citations">引用回流<\/el-dropdown-item>/)
  assert.match(view, /function handleRowAction\(row, command\)/)
})

test('article workbench uses the prototype dark hero and a text-only more menu', () => {
  assert.match(view, /\.geo-intro \{[\s\S]*background: #1f2b34/)
  assert.match(view, /\.geo-flow \{[\s\S]*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/)
  assert.match(view, /\.geo-flow-no \{[\s\S]*background: #62d5cf/)
  assert.match(view, />更多<\/el-button>/)
  assert.doesNotMatch(view, /更多⌄/)
})
