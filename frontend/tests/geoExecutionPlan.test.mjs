import test from 'node:test'
import assert from 'node:assert/strict'
import vm from 'node:vm'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { reactive, ref, watch, nextTick } from 'vue'
import { recommendedSamples, executionDraft } from '../src/utils/geoTicketExecution.js'

const { parse } = createRequire(import.meta.url)('@babel/parser')
const source = readFileSync(new URL('../src/components/GeoTicketExecution.vue', import.meta.url), 'utf8').split('<script setup>')[1].split('</script>')[0]
const handlers = parse(source, { sourceType: 'module' }).program.body.filter((n) => n.type === 'FunctionDeclaration')
const handler = (name) => { const n = handlers.find((n) => n.id.name === name); return source.slice(n.start, n.end) }

test('saving the same ticket does not reset its loaded execution plan', async () => {
  const node = parse(source, { sourceType: 'module' }).program.body.find((n) => n.type === 'ExpressionStatement' && n.expression.callee?.name === 'watch')
  const props = reactive({ tenantId: 7, ticket: { id: 10 } })
  const c = vm.createContext({ props, watch, executionDraft, generation: 0, planRequest: 0,
    draft: ref({}), error: ref(''), saving: ref(false), plan: ref(null), planError: ref(''), planLoading: ref(false), promptChoice: ref('') })
  const stop = vm.runInContext(source.slice(node.start, node.end), c)
  c.plan.value = { question: 'keep plan' }
  props.ticket = { id: 10, content_task_id: 100 }
  await nextTick()
  assert.equal(c.plan.value.question, 'keep plan')
  assert.equal(c.generation, 1)
  props.tenantId = 8
  await nextTick()
  assert.equal(c.plan.value, null)
  stop()
})

test('recommendation selects three per engine and keeps small groups visible', () => {
  const rows = Array.from({ length: 9 }, (_, i) => ({ id: 9-i, engine: i < 5 ? 'a' : i < 8 ? 'b' : 'c' }))
  assert.deepEqual(recommendedSamples(rows), [9, 8, 7, 4, 3, 2, 1])
})

test('older execution plan response cannot override a newer selection', async () => {
  const queue = []
  const c = vm.createContext({ generation: 1, planRequest: 0, props: { tenantId: 7, ticket: { id: 10 } },
    draft: { value: { taskId: 100 } }, plan: { value: null }, planLoading: { value: false }, planError: { value: '' },
    fetchGeoExecutionPlan: () => new Promise((resolve) => queue.push(resolve)),
  })
  vm.runInContext(handler('loadPlan'), c)
  const first = c.loadPlan()
  c.draft.value.taskId = 200
  const second = c.loadPlan()
  queue[1]({ selected_task_id: 200, before: [{ id: 20 }] })
  await second
  queue[0]({ selected_task_id: 100, before: [{ id: 10 }] })
  await first
  assert.equal(c.plan.value.selected_task_id, 200)
  assert.equal(c.plan.value.before[0].id, 20)
})

for (const fail of [false, true]) {
  test(`prepare response cannot affect another customer (failure=${fail})`, async () => {
    let resolve, reject
    const events = []
    const c = vm.createContext({ generation: 1, props: { tenantId: 7, ticket: { id: 10 }, disabled: false },
      planLoading: { value: false }, saving: { value: false }, error: { value: '' }, plan: { value: { prompt_id: 2 } },
      draft: { value: { note: 'keep local' } }, promptChoice: { value: '' }, executionDraft,
      prepareGeoTicketContent: () => new Promise((a, b) => { resolve = a; reject = b }),
      emit: (...args) => events.push(args), loadPlan: () => events.push('reload'),
    })
    vm.runInContext(handler('prepare'), c)
    const pending = c.prepare()
    c.generation++; c.props.tenantId = 8; c.saving.value = true
    if (fail) reject(new Error('old failure'))
    else resolve({ ticket: { id: 10, content_task_id: 100 } })
    await pending
    assert.deepEqual(events, [])
    assert.equal(c.draft.value.note, 'keep local')
    assert.equal(c.error.value, '')
    assert.equal(c.saving.value, true)
  })
}


for (const name of ['save', 'prepare']) {
  for (const reason of ['loading', 'done', 'missing']) {
    test(`${name} rejects execution edits while ${reason}`, async () => {
      const c = vm.createContext({ saving: { value: false }, props: { disabled: false, ticket: { status: reason === 'done' ? 'done' : 'doing' } },
        planLoading: { value: reason === 'loading' }, plan: { value: reason === 'missing' ? null : {} } })
      vm.runInContext(handler(name), c)
      await c[name]()
      assert.equal(c.saving.value, false)
    })
  }
}

test('child execution saving synchronously locks and unlocks parent actions', () => {
  const node = parse(source, { sourceType: 'module' }).program.body.find((n) =>
    n.type === 'ExpressionStatement' && n.expression.callee?.name === 'watch' && n.expression.arguments[0]?.name === 'saving')
  const events = [], saving = ref(false)
  const c = vm.createContext({ watch, saving, emit: (...args) => events.push(args) })
  const stop = vm.runInContext(source.slice(node.start, node.end), c)
  saving.value = true
  assert.deepEqual(events, [['busy', true]])
  saving.value = false
  assert.deepEqual(events, [['busy', true], ['busy', false]])
  stop()
})
