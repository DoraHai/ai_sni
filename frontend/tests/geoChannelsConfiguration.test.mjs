import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'

const source = readFileSync(
  resolve(import.meta.dirname, '../src/views/geo/GeoChannelsView.vue'),
  'utf8',
)

test('GEO channels makes platform, account, and strategy configuration the primary surface', () => {
  for (const token of [
    '平台账号与授权',
    '添加分发平台',
    '添加渠道账号',
    'GEO 发布与信源策略',
    '信源角色',
    'AI 引用潜力',
    '内容策略',
    '适配引擎',
    '刷新连接状态',
    '全部平台',
    '自有渠道',
  ]) {
    assert.ok(source.includes(token), `GeoChannelsView.vue missing ${token}`)
  }
})

test('GEO channels uses publishing-channel and account CRUD APIs', () => {
  for (const name of [
    'createGeoPublishingChannel',
    'patchGeoPublishingChannel',
    'deleteGeoPublishingChannel',
    'createGeoChannelAccount',
    'patchGeoChannelAccount',
    'deleteGeoChannelAccount',
  ]) {
    assert.match(source, new RegExp(`${name}\\(`))
  }
})

test('GEO channels presents readable publishing and account states in one action row', () => {
  for (const token of [
    '自动发布',
    '审核后发布',
    '仅手动发布',
    '待添加账号',
    '待配置凭证',
    'channel-actions',
    'white-space: nowrap',
  ]) {
    assert.ok(source.includes(token), `GeoChannelsView.vue missing ${token}`)
  }
})
