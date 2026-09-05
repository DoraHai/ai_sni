import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
const source = readFileSync(new URL('../src/components/GeoWorkTickets.vue', import.meta.url), 'utf8')
const util = readFileSync(new URL('../src/utils/geoWorkQueue.js', import.meta.url), 'utf8')
const { mergeAssignmentDrafts } = await import(`data:text/javascript;base64,${Buffer.from(util).toString('base64')}`)
const handler = source.slice(source.indexOf('async function mutate('), source.indexOf('function add('))
function fixture() {
  const events = []
  const context = vm.createContext({
    busy: { value: false }, loading: { value: false }, props: { tenantId: 7 }, generation: 1,
    tickets: { value: [{ id: 1, owner_name: 'A' }, { id: 2, owner_name: 'B' }] },
    assignments: { value: { 1: { owner_name: '新姓名', due_date: '' }, 2: { owner_name: '未保存 B', due_date: '' } } },
    notes: { value: { 1: '未保存结果', 2: '另一个结果' } }, mergeAssignmentDrafts,
    ElMessage: { success: () => events.push('success'), error: () => events.push('error') },
  })
  vm.runInContext(handler, context)
  return { context, events }
}
test('saving assignment preserves result notes and drafts of another ticket', async () => {
  const { context } = fixture()
  await context.mutate(async () => ({ id: 1, owner_name: '新姓名', due_date: '2026-09-09' }), { assignmentId: 1 })
  assert.equal(context.notes.value[1], '未保存结果')
  assert.equal(context.notes.value[2], '另一个结果')
  assert.equal(context.assignments.value[2].owner_name, '未保存 B')
  assert.equal(context.assignments.value[1].due_date, '2026-09-09')
})
test('late save cannot insert previous customer ticket after context changes', async () => {
  const { context, events } = fixture()
  let resolve
  const pending = context.mutate(() => new Promise((done) => { resolve = done }))
  context.generation++
  context.props.tenantId = 8
  context.tickets.value = []
  resolve({ id: 1, owner_name: 'old' })
  await pending
  assert.equal(context.tickets.value.length, 0)
  assert.deepEqual(events, [])
})
test('failed save preserves inputs and releases busy state', async () => {
  const { context, events } = fixture()
  await context.mutate(async () => { throw new Error('failed') })
  assert.equal(context.notes.value[1], '未保存结果')
  assert.equal(context.assignments.value[1].owner_name, '新姓名')
  assert.equal(context.busy.value, false)
  assert.deepEqual(events, ['error'])
})

test('block reason dialog cannot submit after customer context changes', async () => {
  let resolve
  let mutations = 0
  const context = vm.createContext({ busy: { value: false }, loading: { value: false }, generation: 1,
    ElMessageBox: { prompt: () => new Promise((done) => { resolve = done }) },
    mutate: () => { mutations++ },
  })
  vm.runInContext(source.slice(source.indexOf('async function state('), source.indexOf('function blockedReason(')), context)
  const pending = context.state({ id: 1 }, 'blocked')
  context.generation++
  resolve({ value: '等待资料' })
  await pending
  assert.equal(mutations, 0)
})
