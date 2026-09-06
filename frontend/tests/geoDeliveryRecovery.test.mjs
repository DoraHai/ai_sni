import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { ref, computed } from 'vue'
const source = readFileSync(new URL('../src/components/GeoDeliveryRecovery.vue', import.meta.url), 'utf8')
const handlers = source.slice(source.indexOf('async function load()'), source.indexOf('watch(() =>'))
function fixture() {
  const events = []
  const ctx = vm.createContext({ props: { tenantId: 1, taskId: 12 }, epoch: 0,
    rows: { value: [] }, error: { value: '' }, message: { value: '' }, busy: { value: false },
    listGeoDeliveries: async () => ({ items: [] }), resolveGeoDelivery: async () => ({}),
    emit: name => events.push(name),
  })
  vm.runInContext(handlers, ctx)
  return { ctx, events }
}
test('late list cannot restore another customer records', async () => {
  const { ctx } = fixture(); let done
  ctx.listGeoDeliveries = () => new Promise(resolve => { done = resolve })
  const pending = ctx.load()
  ctx.epoch++; ctx.props.tenantId = 2
  done({ items: [{ account_id: 99 }] }); await pending
  assert.equal(ctx.rows.value.length, 0)
})
test('late recovery response emits no success in a different customer', async () => {
  const { ctx, events } = fixture(); let done
  ctx.resolveGeoDelivery = () => new Promise(resolve => { done = resolve })
  const pending = ctx.resolve({ variant_id: 3, delivery_key: 'a', note: '核对', confirmed: true }, 'allow_retry')
  ctx.epoch++; ctx.props.tenantId = 2
  done({}); await pending
  assert.equal(ctx.message.value, ''); assert.deepEqual(events, [])
})
test('customer change during post-recovery refresh does not emit success', async () => {
  const { ctx, events } = fixture(); let done
  ctx.listGeoDeliveries = () => new Promise(resolve => { done = resolve })
  const pending = ctx.resolve({ variant_id: 3, delivery_key: 'a' }, 'allow_retry')
  await new Promise(resolve => setImmediate(resolve))
  ctx.epoch++; ctx.props.tenantId = 2
  done({ items: [] }); await pending
  assert.equal(ctx.message.value, ''); assert.deepEqual(events, [])
})
test('failed recovery retains operator inputs and permits correction', async () => {
  const { ctx } = fixture()
  ctx.resolveGeoDelivery = async () => { throw new Error('正文不匹配') }
  const row = { note: '核对记录', url: 'https://example.com' }
  await ctx.resolve(row, 'confirm_published')
  assert.equal(ctx.busy.value, false); assert.equal(row.note, '核对记录')
  assert.equal(ctx.error.value, '正文不匹配')
})


test('pending view excludes successes and counts only currently actionable records', () => {
  const ctx = vm.createContext({ ref, computed })
  const declarations = source.slice(source.indexOf('const rows ='), source.indexOf('let epoch ='))
  vm.runInContext(declarations + '; result = { rows, pendingRows, visibleRows, actionableCount, showAll };', ctx)
  const state = ctx.result
  state.rows.value = [
    {state:'succeeded'},
    {state:'unknown',can_confirm_published:true,can_allow_retry:true},
    {state:'sending',can_confirm_published:false,can_allow_retry:false,blocked_reason:'等待'},
  ]
  assert.equal(state.pendingRows.value.length, 2)
  assert.equal(state.visibleRows.value.length, 2)
  assert.equal(state.actionableCount.value, 1)
  state.showAll.value = true
  assert.equal(state.visibleRows.value.length, 3)
})
