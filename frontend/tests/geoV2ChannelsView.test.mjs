import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const channels = readFileSync(new URL('../src/views/geo/GeoChannelsView.vue', import.meta.url), 'utf8')
const distribution = readFileSync(new URL('../src/views/geo/GeoDistributionView.vue', import.meta.url), 'utf8')
const editor = readFileSync(new URL('../src/views/geo/GeoTaskEditorView.vue', import.meta.url), 'utf8')

test('channels page owns platform strategy and no longer pushes task variants', () => {
  for (const token of [
    'title="分发平台"',
    '刷新连接状态',
    '添加分发平台',
    '全部平台',
    '自有渠道',
    '内容平台',
    '新闻媒体',
    '外链渠道',
    '待接入',
    '信源角色',
    'AI 引用潜力',
    '内容策略',
    '适配引擎',
    'geo_profile',
  ]) {
    assert.ok(channels.includes(token), `GeoChannelsView.vue missing ${token}`)
  }
  assert.match(channels, /startSocialOAuth/)
  assert.match(channels, /verifySocialAccount/)
  assert.match(channels, /refreshConnectionStatus/)
  assert.doesNotMatch(channels, /推送草稿/)
  assert.doesNotMatch(channels, /任务分发/)
  assert.match(channels, /filteredChannels/)
})

test('distribution page owns push, copy, webhook, and URL backfill', () => {
  for (const token of [
    'title="分发记录"',
    '推送草稿',
    '推送发布',
    'Webhook 草稿',
    'Webhook 发布',
    'focusMode',
    '回填',
    '复制',
    'pushGeoVariantWebhook',
    'publishGeoVariant',
  ]) {
    assert.ok(distribution.includes(token), `GeoDistributionView.vue missing ${token}`)
  }
})

test('distribution explains why an existing channel draft cannot be auto-pushed', () => {
  assert.match(distribution, /import \{ pushBlockLabels \} from '\.\.\/\.\.\/utils\/geoPushBlockers'/)
  assert.match(distribution, /function pushBlockText\(row\)/)
  assert.match(distribution, /暂不能自动推送/)
  assert.match(distribution, /<el-tag v-for="label in pushBlockLabels\(row\)"[^>]*>\{\{ label \}\}<\/el-tag>/)
  assert.match(distribution, /去配置渠道/)
  assert.match(distribution, /<el-tooltip[^>]*:disabled="row\.ready"[^>]*:content="pushBlockText\(row\)"/)
})

test('editor publish actions open the distribution route', () => {
  assert.match(editor, /手动发布/)
  assert.match(editor, /自动发布/)
  assert.match(editor, /goDistribution\('manual'\)/)
  assert.match(editor, /goDistribution\('auto'\)/)
  assert.match(editor, /\/geo\/articles\/\$\{taskId\.value\}\/distribution/)
})
