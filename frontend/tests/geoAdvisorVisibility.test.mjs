import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { compile } from '@vue/compiler-dom'
import * as Vue from 'vue'

const source = readFileSync(new URL('../src/views/geo/GeoVisibilityView.vue', import.meta.url), 'utf8')
const handler = source.slice(source.indexOf('async function startCollect()'), source.indexOf('async function reloadAll()'))

function fixture(advisor, reason = '') {
  const calls = [], errors = []
  const context = vm.createContext({
    isAdvisor: { value: advisor }, tenantId: { value: 10 }, collecting: { value: false },
    collectForm: { value: { engine_keys: ['kimi'], prompt_limit: 50, auto_persist: false, prefer_real: false } },
    startVisibilityPatrolRun: async (body) => {
      calls.push(JSON.parse(JSON.stringify(body)))
      if (reason) throw new Error(reason)
      return {}
    },
    ElMessage: { success() {}, error: (message) => errors.push(message) },
    loadSnapshots: async () => {}, loadCollectMeta: async () => {},
  })
  vm.runInContext(handler, context)
  return { context, calls, errors }
}

test('advisor sends only the selected customer despite editable legacy form values', async () => {
  const f = fixture(true)
  await f.context.startCollect()
  assert.deepEqual(f.calls, [{ tenant_id: 10 }])
  assert.equal(f.context.collecting.value, false)
})

test('ordinary editor retains existing collection options', async () => {
  const f = fixture(false)
  await f.context.startCollect()
  assert.equal(f.calls[0].prompt_limit, 50)
  assert.deepEqual(f.calls[0].engine_keys, ['kimi'])
  assert.equal(f.calls[0].run_async, true)
})

test('backend denial appears in plain words and the button is released', async () => {
  const reason = '此客户已有检测正在排队或运行，请等完成后再试'
  const f = fixture(true, reason)
  await f.context.startCollect()
  assert.deepEqual(f.errors, [reason])
  assert.equal(f.context.collecting.value, false)
})

// Render the actual action slot: only one advisor detection button, no snapshot write.
const actions = source.match(/<template #actions>([\s\S]*?)<\/template>/)[1]
const render = new Function('Vue', compile(actions, { mode: 'function' }).code)(Vue)
function buttons(advisor) {
  const tree = render({ isAdvisor: advisor, collecting: false, snapshots: [],
    reloadAll() {}, exportSnapshots() {}, startCollect() {} }, [])
  const found = []
  function visit(node) {
    if (!node || typeof node !== 'object') return
    if (node.type === 'button') found.push(String(node.children).trim())
    if (Array.isArray(node.children)) node.children.forEach(visit)
  }
  visit(tree)
  return found
}
test('advisor action slot exposes one manual detection button and no snapshot registration', () => {
  assert.deepEqual(buttons(true), ['刷新', '导出 CSV', '手动检测一次'])
  assert.ok(buttons(false).includes('登记快照'))
})
