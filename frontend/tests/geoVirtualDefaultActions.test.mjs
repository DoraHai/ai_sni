import test from 'node:test'
import assert from 'node:assert/strict'
import vm from 'node:vm'
import { readFileSync } from 'node:fs'

import { isPersistedGeoRow } from '../src/utils/geoVirtualDefaults.js'

const publishingSource = readFileSync(
  new URL('../src/views/geo/GeoPublishingView.vue', import.meta.url),
  'utf8',
)
const placementSource = readFileSync(
  new URL('../src/views/geo/GeoPlacementsView.vue', import.meta.url),
  'utf8',
)

function extractFunction(source, name) {
  const asyncStart = source.indexOf(`async function ${name}(`)
  const start = asyncStart >= 0 ? asyncStart : source.indexOf(`function ${name}(`)
  assert.notEqual(start, -1, `missing function ${name}`)
  const brace = source.indexOf('{', start)
  let depth = 0
  for (let i = brace; i < source.length; i += 1) {
    if (source[i] === '{') depth += 1
    if (source[i] === '}') depth -= 1
    if (depth === 0) return source.slice(start, i + 1)
  }
  throw new Error(`unterminated function ${name}`)
}

function runFunctions(source, names, context) {
  const sandbox = vm.createContext(context)
  vm.runInContext(names.map((name) => extractFunction(source, name)).join('\n'), sandbox)
  return sandbox
}

function fixture() {
  const calls = []
  const notices = []
  return {
    calls,
    notices,
    context: {
      tenantId: { value: 15 },
      isPersistedGeoRow,
      createGeoPublishingChannel: async (payload) => calls.push(['create-channel', payload]),
      patchGeoPublishingChannel: async (...args) => calls.push(['patch-channel', ...args]),
      deleteGeoPublishingChannel: async (...args) => calls.push(['delete-channel', ...args]),
      patchGeoMediaPlacement: async (...args) => calls.push(['patch-placement', ...args]),
      deleteGeoMediaPlacement: async (...args) => calls.push(['delete-placement', ...args]),
      load: async () => calls.push(['load']),
      ElMessage: {
        success: (message) => notices.push(['success', message]),
        warning: (message) => notices.push(['warning', message]),
        error: (message) => notices.push(['error', message]),
      },
      ElMessageBox: { confirm: async () => true },
    },
  }
}

test('current publishing view saves a virtual channel through POST and stored channel through PATCH', async () => {
  const virtual = fixture()
  Object.assign(virtual.context, {
    chForm: { value: {} },
    createChOpen: { value: false },
    editChForm: { value: {} },
    editChOpen: { value: false },
  })
  const virtualCtx = runFunctions(
    publishingSource,
    ['typeSupportsWebhook', 'defaultModeForType', 'openEditChannel', 'createChannel'],
    virtual.context,
  )
  virtualCtx.openEditChannel({
    id: null,
    virtual_default: true,
    name: '默认官网',
    channel_type: 'website',
    publish_mode: 'auto_publish',
    enabled: true,
  })
  assert.equal(virtual.context.createChOpen.value, true)
  assert.equal(virtual.context.editChOpen.value, false)
  await virtualCtx.createChannel()
  assert.deepEqual(virtual.calls.map(([method]) => method), ['create-channel', 'load'])
  assert.equal(virtual.calls[0][1].tenant_id, 15)

  const stored = fixture()
  Object.assign(stored.context, {
    chForm: { value: {} },
    createChOpen: { value: false },
    editChForm: { value: {} },
    editChOpen: { value: false },
  })
  const storedCtx = runFunctions(
    publishingSource,
    ['typeSupportsWebhook', 'defaultModeForType', 'openEditChannel', 'saveEditChannel'],
    stored.context,
  )
  storedCtx.openEditChannel({
    id: 8,
    name: '已保存官网',
    publish_mode: 'manual_only',
    enabled: true,
  })
  assert.equal(stored.context.editChOpen.value, true)
  await storedCtx.saveEditChannel()
  assert.deepEqual(stored.calls.map(([method]) => method), ['patch-channel', 'load'])
  assert.equal(stored.calls[0][2], 8)
})

test('publishing actions never patch or delete a virtual channel', async () => {
  for (const name of ['toggleChannel', 'removeChannel']) {
    const f = fixture()
    const ctx = runFunctions(publishingSource, [name], f.context)
    await ctx[name]({ id: null, virtual_default: true, name: '默认官网' })
    assert.deepEqual(f.calls, [])
    assert.equal(f.notices[0][0], 'warning')
  }

  const f = fixture()
  const ctx = runFunctions(publishingSource, ['removeChannel'], f.context)
  await ctx.removeChannel({ id: 9, name: '已保存官网' })
  assert.deepEqual(f.calls.map(([method]) => method), ['delete-channel', 'load'])
})

test('account binding resolves only to persisted channel ids', () => {
  const makeContext = (storedRows) => ({
    persistedChannels: { value: storedRows },
    autoChannels: { value: [] },
    activeTab: { value: 'all' },
    accForm: { value: {} },
    createAccOpen: { value: false },
    SOCIAL_TYPES: new Set(['wechat', 'zhihu', 'baijiahao', 'toutiao']),
    ElMessage: { warning: () => {} },
  })
  const names = [
    'channelById',
    'typeSupportsWebhook',
    'typeSupportsSocial',
    'defaultAuthForChannel',
    'openCreateAccount',
  ]

  const empty = makeContext([])
  const emptyCtx = runFunctions(publishingSource, names, empty)
  emptyCtx.openCreateAccount(null)
  assert.equal(empty.createAccOpen.value, false)
  assert.equal(empty.accForm.value.channel_id, undefined)

  const stored = makeContext([{ id: 17, channel_type: 'website', virtual_default: false }])
  const storedCtx = runFunctions(publishingSource, names, stored)
  storedCtx.openCreateAccount('null')
  assert.equal(stored.createAccOpen.value, true)
  assert.equal(stored.accForm.value.channel_id, 17)
})

test('placement actions never patch or delete a virtual suggestion', async () => {
  for (const name of ['markPublished', 'remove']) {
    const f = fixture()
    const ctx = runFunctions(placementSource, [name], f.context)
    await ctx[name]({ id: null, virtual_default: true, name: '默认媒体' })
    assert.deepEqual(f.calls, [])
    assert.equal(f.notices[0][0], 'warning')
  }

  const f = fixture()
  const ctx = runFunctions(placementSource, ['markPublished'], f.context)
  await ctx.markPublished({ id: 11, name: '已保存媒体' })
  assert.deepEqual(f.calls.map(([method]) => method), ['patch-placement', 'load'])
})
