import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'

const source = await readFile(new URL('../src/views/seo/SeoDistributionReport.vue', import.meta.url), 'utf8')
const script = source.split('<script setup>')[1].split('</script>')[0].replace(/^import .*$/gm, '')
function fixture() {
  let scopeWatcher
  const calls = []
  const state = {
    props: { tenantId: 4, siteId: 2, identity: '7:1', canEdit: true, connections: [], publications: [], contents: [] },
    defineProps: () => state.props, defineEmits: () => (...args) => calls.push(['emit',...args]), ref: value => ({ value }), reactive: value => value,
    computed: fn => ({ get value() { return fn() } }), watch: (_, callback) => { scopeWatcher = callback },
    crypto: { randomUUID: () => 'synthetic-request' },
    fetchReportSettings: async params => { calls.push(['read', params]); return { can_operate:true, enabled:false, scope_enabled:false, revision:0, scope_revision:0, devices:[], tasks:[] } },
    saveReportSettings: async (...args) => { calls.push(['settings',...args]); return { enabled:true, scope_enabled:true, revision:1, scope_revision:1, devices:[], tasks:[] } },
    createReportPairing: async (...args) => { calls.push(['pair',...args]); return { pairing_code:'synthetic-once' } },
    revokeReportDevice: async (...args) => { calls.push(['revoke',...args]); return {} },
    createReportTask: async (...args) => { calls.push(['task',...args]); return {} },
  }
  vm.createContext(state)
  new vm.Script(script + ';globalThis.handlers={refresh,toggle,pair,dispatch,revoke,resetScope,state,busy,error,pairingCode,form}').runInContext(state)
  return { state, handlers:state.handlers, calls, scopeWatcher }
}

test('late settings response cannot populate the newly selected customer', async () => {
  const { state, handlers } = fixture()
  let finish
  state.fetchReportSettings = () => new Promise(resolve => { finish = resolve })
  const pending = handlers.refresh()
  state.props.tenantId = 6; handlers.resetScope()
  finish({ enabled:true, devices:[{id:'old-customer-device'}] })
  await pending
  assert.equal(handlers.state.value, null)
  assert.equal(handlers.busy.value, false)
})

test('one-time pairing code is cleared on identity changes and late response is discarded', async () => {
  const { state, handlers } = fixture()
  await handlers.refresh()
  Object.assign(handlers.form, { label:'Synthetic', account:40 })
  let finish
  state.createReportPairing = () => new Promise(resolve => { finish = resolve })
  const pending = handlers.pair()
  state.props.identity = '9:2'; handlers.resetScope()
  finish({ pairing_code:'synthetic-old-identity' })
  await pending
  assert.equal(handlers.pairingCode.value, '')
  assert.equal(handlers.form.account, '')
})

test('read-only and disabled controls do not send writes', async () => {
  const { state, handlers, calls } = fixture()
  await handlers.refresh()
  state.props.canEdit = false
  Object.assign(handlers.form, { label:'Synthetic', account:40, device:'synthetic-device', publication:1001 })
  await handlers.toggle(); await handlers.pair(); await handlers.dispatch(); await handlers.revoke({id:'synthetic-device'})
  assert.deepEqual(calls.map(c => c[0]), ['read'])
})

test('team device note is mandatory and trimmed before pairing', async () => {
  const { handlers, calls } = fixture()
  await handlers.refresh()
  Object.assign(handlers.form, { label:'   ', account:40 })
  await handlers.pair()
  assert.equal(calls.filter(c => c[0] === 'pair').length, 0)
  handlers.form.label = '  Synthetic team computer  '
  await handlers.pair()
  assert.equal(calls.find(c => c[0] === 'pair')[2].label, 'Synthetic team computer')
  assert.match(source, /设备备注（必填/)
  assert.match(source, /同一台电脑可分别配对多个客户/)
})

test('empty account list can pair by default and explicit legacy account remains available', async () => {
  const { handlers, calls } = fixture()
  await handlers.refresh()
  handlers.form.label = 'Synthetic team computer'
  await handlers.pair()
  assert.equal(calls.find(c => c[0] === 'pair')[2].account_id, null)
  handlers.form.account = 40
  await handlers.pair()
  assert.equal(calls.filter(c => c[0] === 'pair')[1][2].account_id, 'seo-connection-40')
  assert.match(source, /不指定（由多号通发布时上报）/)
  assert.match(source, /回传公众号：/)
  assert.match(source, /task\.reportedAccount\?\.name \|\| '未上报'/)
})

test('settings write narrows to explicit selected customer/site and both revisions', async () => {
  const { handlers, calls } = fixture()
  await handlers.refresh(); await handlers.toggle()
  const write = calls.find(c => c[0] === 'settings')
  assert.equal(JSON.stringify(write[1]), JSON.stringify({tenant_id:4,site_id:2}))
  assert.equal(JSON.stringify(write[2]), JSON.stringify({enabled:true,scope_enabled:true,expected_revision:0,expected_scope_revision:0}))
})

test('dispatch freezes reviewed source version and hash and refuses stale source', async () => {
  const { state, handlers, calls } = fixture()
  await handlers.refresh()
  Object.assign(handlers.state.value, {enabled:true,scope_enabled:true})
  state.props.publications.push({id:1001,content_id:1000,platform_code:'wechat_browser',status:'manual_required',source_version:1})
  state.props.contents.push({id:1000,version_count:2,payload_hash:'a'.repeat(64)})
  Object.assign(handlers.form, {device:'synthetic-device',publication:1001})
  await handlers.dispatch()
  assert.equal(calls.filter(c => c[0] === 'task').length, 0)
  state.props.contents[0].version_count = 1
  await handlers.dispatch()
  const write = calls.find(c => c[0] === 'task')
  assert.equal(write[2].source_version, 1)
  assert.equal(write[2].payload_hash, 'a'.repeat(64))
})
