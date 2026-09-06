import test from 'node:test'
import assert from 'node:assert/strict'
import vm from 'node:vm'
import { readFileSync } from 'node:fs'

import { isPersistedGeoRow } from '../src/utils/geoVirtualDefaults.js'

const channelSource = readFileSync(
  new URL('../src/views/geo/GeoChannelsView.vue', import.meta.url),
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

function channelFixture(id) {
  const calls = []
  const notices = []
  const context = {
    tenantId: { value: 15 },
    channelForm: { value: { id } },
    channelDialogOpen: { value: true },
    channelPayload: () => ({ name: '官网', channel_type: 'website' }),
    isPersistedGeoRow,
    createGeoPublishingChannel: async (payload) => calls.push(['post', payload]),
    patchGeoPublishingChannel: async (...args) => calls.push(['patch', ...args]),
    deleteGeoPublishingChannel: async (...args) => calls.push(['delete', ...args]),
    refresh: async () => calls.push(['refresh']),
    ElMessage: {
      success: (message) => notices.push(['success', message]),
      warning: (message) => notices.push(['warning', message]),
      error: (message) => notices.push(['error', message]),
    },
    ElMessageBox: { confirm: async () => true },
  }
  return { calls, notices, context }
}

test('channel component creates virtual/default rows and patches only persisted rows', async () => {
  for (const id of [null, 'null', 0, -1]) {
    const fixture = channelFixture(id)
    const ctx = runFunctions(channelSource, ['saveChannel'], fixture.context)
    await ctx.saveChannel()
    assert.deepEqual(fixture.calls.map(([method]) => method), ['post', 'refresh'])
  }

  const fixture = channelFixture(7)
  const ctx = runFunctions(channelSource, ['saveChannel'], fixture.context)
  await ctx.saveChannel()
  assert.deepEqual(fixture.calls.map(([method]) => method), ['patch', 'refresh'])
  assert.equal(fixture.calls[0][2], 7)
})

test('channel component never deletes a virtual or invalid row', async () => {
  for (const row of [{ id: null, virtual_default: true }, { id: 'null' }, { id: -2 }]) {
    const fixture = channelFixture(null)
    const ctx = runFunctions(channelSource, ['removeChannel'], fixture.context)
    await ctx.removeChannel(row)
    assert.deepEqual(fixture.calls, [])
    assert.equal(fixture.notices[0][0], 'warning')
  }

  const fixture = channelFixture(null)
  const ctx = runFunctions(channelSource, ['removeChannel'], fixture.context)
  await ctx.removeChannel({ id: 9, name: '官网' })
  assert.deepEqual(fixture.calls.map(([method]) => method), ['delete', 'refresh'])
  assert.equal(fixture.calls[0][2], 9)
})

function placementFixture(editingValue = null) {
  const calls = []
  const notices = []
  const context = {
    tenantId: { value: 15 },
    editing: { value: editingValue },
    dialogOpen: { value: true },
    saving: { value: false },
    form: {
      value: {
        name: '行业媒体',
        channel_type: 'news',
        channel_key: 'media',
        target_url: '',
        status: 'planned',
        priority: 1,
        authority_note: '',
      },
    },
    isPersistedGeoRow,
    createGeoMediaPlacement: async (payload) => calls.push(['post', payload]),
    patchGeoMediaPlacement: async (...args) => calls.push(['patch', ...args]),
    deleteGeoMediaPlacement: async (...args) => calls.push(['delete', ...args]),
    load: async () => calls.push(['load']),
    ElMessage: {
      success: (message) => notices.push(['success', message]),
      warning: (message) => notices.push(['warning', message]),
      error: (message) => notices.push(['error', message]),
    },
    ElMessageBox: { confirm: async () => true },
  }
  return { calls, notices, context }
}

test('placement form creates virtual/default rows and patches only persisted rows', async () => {
  for (const editing of [null, { id: null, virtual_default: true }, { id: 'null' }, { id: -1 }]) {
    const fixture = placementFixture(editing)
    const ctx = runFunctions(placementSource, ['submitForm'], fixture.context)
    await ctx.submitForm()
    assert.deepEqual(fixture.calls.map(([method]) => method), ['post', 'load'])
  }

  const fixture = placementFixture({ id: 11 })
  const ctx = runFunctions(placementSource, ['submitForm'], fixture.context)
  await ctx.submitForm()
  assert.deepEqual(fixture.calls.map(([method]) => method), ['patch', 'load'])
  assert.equal(fixture.calls[0][2], 11)
})

test('placement inline save routes virtual rows to POST and persisted rows to PATCH', async () => {
  const virtual = placementFixture()
  const virtualCtx = runFunctions(placementSource, ['saveRow'], virtual.context)
  await virtualCtx.saveRow({ id: null, virtual_default: true, name: '官网', status: 'planned' })
  assert.deepEqual(virtual.calls.map(([method]) => method), ['post', 'load'])

  const persisted = placementFixture()
  const persistedCtx = runFunctions(placementSource, ['saveRow'], persisted.context)
  await persistedCtx.saveRow({ id: 12, name: '官网', status: 'published' })
  assert.deepEqual(persisted.calls.map(([method]) => method), ['patch', 'load'])
  assert.equal(persisted.calls[0][2], 12)
})

test('placement component never deletes a virtual or invalid row', async () => {
  for (const row of [{ id: null, virtual_default: true }, { id: 'null' }, { id: 0 }]) {
    const fixture = placementFixture()
    const ctx = runFunctions(placementSource, ['remove'], fixture.context)
    await ctx.remove(row)
    assert.deepEqual(fixture.calls, [])
    assert.equal(fixture.notices[0][0], 'warning')
  }

  const fixture = placementFixture()
  const ctx = runFunctions(placementSource, ['remove'], fixture.context)
  await ctx.remove({ id: 13, name: '官网' })
  assert.deepEqual(fixture.calls.map(([method]) => method), ['delete', 'load'])
  assert.equal(fixture.calls[0][2], 13)
})
