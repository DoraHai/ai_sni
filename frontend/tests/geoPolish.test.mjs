import test from 'node:test'
import assert from 'node:assert/strict'
import vm from 'node:vm'
import { readFileSync } from 'node:fs'
import { shanghaiDate, addDaysIso } from '../src/utils/geoDate.js'
import { manualBlockedReason } from '../src/utils/geoAutopatrol.js'

const ready = () => ({ can_enable: true, coverage: { prompt_count: 1 }, manual_quota: { used: 0, limit: 2 } })
test('manual detection blocks missing questions, server blockers, in-flight and exhausted quota', () => {
  assert.equal(manualBlockedReason(ready()), '')
  for (const data of [null, { ...ready(), can_enable: false }, { ...ready(), blocked_reason: 'no_prompts' },
    { ...ready(), coverage: { prompt_count: 0 } }, { ...ready(), in_flight: true },
    { ...ready(), manual_quota: { used: 2, limit: 2 } }, { ...ready(), blocked_reason: 'future_reason' }]) {
    assert.ok(manualBlockedReason(data))
  }
})

function confirmationFixture(confirm) {
  const props = { tenantId: 7, collecting: false }, events = []
  const source = readFileSync(new URL('../src/components/GeoPatrolSelfService.vue', import.meta.url), 'utf8')
  const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm, '')
  const ctx = vm.createContext({
    defineProps: () => props, defineEmits: () => event => events.push(event),
    reactive: x => x, ref: value => ({ value }), computed: fn => ({ get value() { return fn() } }),
    watch() {}, onBeforeUnmount() {}, fetchPatrolSelfService() {}, putPatrolSelfService() {},
    createSelfServiceController: () => ({ dispose() {} }), PATROL_PLATFORMS: [], manualBlockedReason,
    ElMessageBox: { confirm },
  })
  vm.runInContext(script, ctx)
  vm.runInContext(`state.data = ${JSON.stringify(ready())}`, ctx)
  return { props, events, ctx }
}
test('confirmation explicitly describes quota; cancel sends no manual request', async () => {
  const f = confirmationFixture(async message => {
    assert.match(message, /本次会用掉 1 次手动检测次数/)
    assert.match(message, /失败且无结果会退回次数/)
    throw 'cancel'
  })
  await f.ctx.confirmManual()
  assert.deepEqual(f.events, [])
})
test('confirm emits once; repeated clicks and changed customer cannot start detection', async () => {
  let finish
  const f = confirmationFixture(() => new Promise(resolve => { finish = resolve }))
  const pending = f.ctx.confirmManual()
  await f.ctx.confirmManual()
  finish(); await pending
  assert.deepEqual(f.events, ['manual'])
  const changed = confirmationFixture(() => new Promise(resolve => { finish = resolve }))
  const waiting = changed.ctx.confirmManual()
  changed.props.tenantId = 8
  finish(); await waiting
  assert.deepEqual(changed.events, [])
})
test('server status is checked again after confirmation', async () => {
  let finish
  const f = confirmationFixture(() => new Promise(resolve => { finish = resolve }))
  const pending = f.ctx.confirmManual()
  vm.runInContext("state.data.blocked_reason = 'no_prompts'", f.ctx)
  finish(); await pending
  assert.deepEqual(f.events, [])
})
test('Shanghai calendar handles UTC midnight, year rollover and leap day', () => {
  assert.equal(shanghaiDate(new Date('2026-10-23T16:30:00Z')), '2026-10-24')
  assert.equal(shanghaiDate(new Date('2026-12-31T16:00:00Z')), '2027-01-01')
  assert.equal(addDaysIso('2024-03-01', -1), '2024-02-29')
  assert.equal(addDaysIso('2027-01-01', -13), '2026-12-19')
})
