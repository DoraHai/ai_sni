import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const routerSource = await readFile(new URL('../src/router/index.js', import.meta.url), 'utf8')

function geoRouteBlock(path) {
  const start = routerSource.indexOf(`\n    path: '${path}'`)
  assert.notEqual(start, -1, `missing route ${path}`)
  const end = routerSource.indexOf('\n  },', start)
  return routerSource.slice(start, end)
}

test('GEO router registers canonical routes and redirects legacy task paths', () => {
  assert.match(routerSource, /path: '\/geo\/evaluation'/)
  assert.match(routerSource, /path: '\/geo\/tickets'/)
  assert.match(routerSource, /path: '\/geo\/publishing-channels'/)
  assert.match(routerSource, /path: '\/geo\/structure'/)
  assert.match(routerSource, /path: '\/geo\/tasks'/)
  assert.match(routerSource, /path: '\/geo\/tasks',[\s\S]*?redirect: \(to\) => \(\{ path: '\/geo\/articles', query: to\.query \}\)/)
})

test('GEO legacy redirects preserve query parameters', () => {
  const legacyPaths = [
    '/geo/recommend', '/geo/answers', '/geo/permissions',
    '/geo/geo-diagnosis', '/geo/visibility/evaluation', '/geo/visibility/patrol',
    '/geo/period-diff', '/geo/gaps', '/geo/gap-workbench', '/geo/periods',
    '/geo/topic-heat', '/geo/ai-trends', '/geo/deliverables', '/geo/workbench',
    '/geo/tasks/:taskId', '/geo/tasks', '/geo/questions', '/geo/citations', '/geo/models',
    '/geo/placements', '/geo/publishing', '/geo/onboarding', '/geo/facts',
  ]

  for (const path of legacyPaths) {
    assert.match(geoRouteBlock(path), /query: to\.query/, `${path} must forward its query`)
  }
  for (const path of ['/geo/units', '/geo/keywords']) {
    assert.match(
      geoRouteBlock(path),
      /query: \{ \.\.\.to\.query, layer: to\.query\.layer \|\| 'keyword' \}/,
      `${path} must retain its keyword-layer default`,
    )
  }
  assert.match(
    geoRouteBlock('/geo/businesses'),
    /query: \{ \.\.\.to\.query, layer: to\.query\.layer \|\| 'business' \}/,
    '/geo/businesses must retain its business-layer default',
  )
  assert.match(
    geoRouteBlock('/geo/businesses/:businessId'),
    /\.\.\.to\.query/,
    '/geo/businesses/:businessId must forward its query',
  )
  const shareRedirect = geoRouteBlock('/geo/deliverables/share')
  assert.match(shareRedirect, /path: `\/geo\/deliverables\/share\/\$\{t\}`, query: to\.query/)
  assert.match(shareRedirect, /path: GEO_WORKBENCH_START, query: to\.query/)
})

test('GEO canonical routes use prototype page titles', () => {
  const canonicalTitles = {
    '/geo/overview': 'GEO 概览',
    '/geo/visibility': 'AI 可见度',
    '/geo/prompts': '提问监控',
    '/geo/competitors': '竞品分析',
    '/geo/sources': '信源分析',
    '/geo/articles': 'GEO 文章',
    '/geo/import': '导入已有文章',
    '/geo/articles/:taskId': '在线编辑器',
    '/geo/articles/:taskId/distribution': '分发记录',
    '/geo/media': '媒体 / 信源策略',
    '/geo/channels': '分发平台',
    '/geo/structure': '官网结构优化',
    '/geo/brand': '品牌信息',
    '/geo/knowledge': '知识库',
    '/geo/ai-settings': 'AI 能力配置',
    '/geo/engines': 'AI 引擎管理',
  }

  for (const [path, title] of Object.entries(canonicalTitles)) {
    const route = geoRouteBlock(path)
    assert.match(route, new RegExp(`title: '${title}'`))
    assert.match(route, new RegExp(`documentTitle: 'GEO 工作台｜${title}'`))
  }
})

test('GEO geo-v2 primary monitoring and knowledge routes use the correct views', () => {
  assert.match(
    geoRouteBlock('/geo/prompts'),
    /component: \(\) => import\('\.\.\/views\/geo\/GeoAskManageView\.vue'\)/,
  )
  assert.match(
    geoRouteBlock('/geo/sources'),
    /component: \(\) => import\('\.\.\/views\/geo\/GeoCitationsView\.vue'\)/,
  )
  assert.match(
    geoRouteBlock('/geo/knowledge'),
    /component: \(\) => import\('\.\.\/views\/geo\/GeoFactsView\.vue'\)/,
  )
  assert.match(
    geoRouteBlock('/geo/structure'),
    /component: \(\) => import\('\.\.\/views\/geo\/GeoStructureView\.vue'\)/,
  )
  assert.match(
    geoRouteBlock('/geo/citations'),
    /redirect: \(to\) => \(\{ path: '\/geo\/sources', query: to\.query \}\)/,
  )
  assert.match(
    geoRouteBlock('/geo/questions'),
    /redirect: \(to\) => \(\{ path: '\/geo\/prompts', query: to\.query \}\)/,
  )
})

test('GEO evaluation canonical route uses the independent evaluation view', () => {
  assert.match(
    geoRouteBlock('/geo/evaluation'),
    /component: \(\) => import\('\.\.\/views\/geo\/GeoEvaluationView\.vue'\)/,
  )
})

test('GEO tickets and channels use independent delivery views', () => {
  assert.match(
    geoRouteBlock('/geo/tickets'),
    /component: \(\) => import\('\.\.\/views\/geo\/GeoTicketsView\.vue'\)/,
  )
  assert.match(
    geoRouteBlock('/geo/channels'),
    /component: \(\) => import\('\.\.\/views\/geo\/GeoChannelsView\.vue'\)/,
  )
  assert.match(
    geoRouteBlock('/geo/publishing-channels'),
    /redirect: \(to\) => \(\{ path: '\/geo\/channels', query: to\.query \}\)/,
  )
  assert.match(
    geoRouteBlock('/geo/articles/:taskId/distribution'),
    /component: \(\) => import\('\.\.\/views\/geo\/GeoDistributionView\.vue'\)/,
  )
})

test('GEO snapshot compatibility route redirects to the merged visibility page', () => {
  assert.match(
    geoRouteBlock('/geo/visibility/snapshots'),
    /redirect: \(to\) => \(\{ path: '\/geo\/visibility', query: to\.query \}\)/,
  )
})
