import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const api = readFileSync(new URL('../src/api/geoContent.js', import.meta.url), 'utf8')
const view = readFileSync(new URL('../src/views/geo/GeoDistributionView.vue', import.meta.url), 'utf8')
const router = readFileSync(new URL('../src/router/index.js', import.meta.url), 'utf8')

test('GEO task distribution page is reachable from existing task links', () => {
  assert.match(router, /path: 'tasks\/:taskId\/distribution'/)
  assert.match(router, /GeoDistributionView\.vue/)
})

test('GEO distribution asset API uses the authenticated same-origin endpoints', () => {
  assert.match(api, /listGeoDistributionAssets/)
  assert.match(api, /uploadGeoDistributionAsset/)
  assert.match(api, /deleteGeoDistributionAsset/)
  assert.match(api, /fetchGeoDistributionAssetContent/)
  assert.match(api, /\/api\/v1\/geo\/distribution-assets/)
  assert.match(api, /form\.append\('tenant_id'/)
  assert.match(api, /form\.append\('scope_id'/)
  assert.match(api, /form\.append\('variant_id'/)
  assert.match(api, /form\.append\('sort_order'/)
  assert.match(api, /form\.append\('file'/)
})

test('advisor UI supports bounded upload, preview and delete without an approval bypass', () => {
  assert.match(view, />\u4e0a\u4f20\u914d\u56fe</)
  assert.match(view, />\u5220\u9664</)
  assert.match(view, /accept="image\/png,image\/jpeg"/)
  assert.match(view, /file\.size > 20_000_000/)
  assert.match(view, /distributionAssets\.value\.length >= 20/)
  assert.match(view, /\u65e7\u5ba2\u6237\u5ba1\u6838\u5df2\u4f5c\u5e9f/)
  assert.match(view, /\u672a\u901a\u8fc7\u5ba2\u6237\u5ba1\u6838/)
  assert.doesNotMatch(view, /reviewGeoContentTask|\u5ba2\u6237\u786e\u8ba4\u901a\u8fc7/)
})

test('asset preview object URLs are revoked on refresh and unmount', () => {
  assert.match(view, /function clearAssetUrls\(\)/)
  assert.match(view, /URL\.revokeObjectURL/)
  assert.match(view, /onBeforeUnmount\(\(\) => \{ contextVersion\+\+; loadVersion\+\+;[\s\S]*?clearAssetUrls\(\)/)
})

test('file picker and delete confirmation keep their original tenant and project context', () => {
  assert.match(view, /pendingAssetSelection = \{/)
  assert.match(view, /const selected = pendingAssetSelection/)
  assert.match(view, /tenantId\.value !== selected\.tenant/)
  assert.match(view, /projectId\.value !== selected\.scope/)
  assert.match(view, /uploadGeoDistributionAsset\(selected\.tenant, selected\.scope, selected\.variant/)
  assert.match(view, /deleteGeoDistributionAsset\(selected\.tenant, selected\.scope, selected\.variant, selected\.assetId\)/)
})

test('an uncertain asset mutation clears previews and is not automatically retried', () => {
  assert.match(view, /function clearAssetState\(\)/)
  assert.match(view, /catch \(e\) \{[\s\S]*?clearAssetState\(\)[\s\S]*?上传配图失败/)
  assert.match(view, /catch \(e\) \{[\s\S]*?clearAssetState\(\)[\s\S]*?删除配图失败/)
  assert.doesNotMatch(view, /retryAsset|setTimeout\([^)]*uploadAsset|setTimeout\([^)]*deleteAsset/)
})

test('live permission loss disables asset changes and clears existing previews', () => {
  assert.match(view, /canManageAssets = computed\(\(\) => session\.canEdit\('geo\.assets'\) && session\.canEdit\('geo\.content'\)\)/)
  assert.match(view, /watch\(\[tenantId, taskId, canManageAssets\]/)
  assert.match(view, /if \(!canManageAssets\.value \|\| !redVariant\.value/)
  assert.match(view, /:disabled="!canManageAssets \|\| !redVariant/)
})
