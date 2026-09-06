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
