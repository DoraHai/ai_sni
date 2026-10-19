import test from 'node:test'
import assert from 'node:assert/strict'
import { createHash, webcrypto } from 'node:crypto'
import vm from 'node:vm'
import { readFileSync } from 'node:fs'
import { reportContext, reportDigest, reportToggle } from '../src/utils/geoDistributionReport.js'

test('tenant/project/identity epochs discard delayed results after reset', () => {
  const scope = reportContext(), pending = scope.capture()
  assert.equal(scope.current(pending), true)
  scope.reset()
  assert.equal(scope.current(pending), false)
  const second = scope.capture()
  scope.reset()
  assert.equal(scope.current(second), false)
})
test('Chinese, newline, escaping and emoji digest agrees with JSON.stringify UTF-8', async () => {
  const variant = { title: '中文😀', body_markdown: '第一行\n"第二行\\' }
  const expected = createHash('sha256').update(JSON.stringify(['geo-article-100', variant.title, variant.body_markdown, []])).digest('hex')
  assert.equal(await reportDigest(100, variant, webcrypto.subtle), expected)
})
test('closing a scope preserves a disabled tenant switch', () => {
  assert.deepEqual(reportToggle({ enabled: false, scope_enabled: true, revision: 2, scope_revision: 1 }),
    { enabled: false, scope_enabled: false, expected_revision: 2, expected_scope_revision: 1 })
})

const source = readFileSync(new URL('../src/components/GeoDistributionReport.vue', import.meta.url), 'utf8')
function panel() {
  const calls = [], props = { tenantId: 7, projectId: 5, accounts: [] }
  const ctx = vm.createContext({ defineProps: () => props, defineEmits: () => () => {},
    ref: value => ({ value }), computed: fn => ({ get value() { return fn() } }), watch: () => {}, onBeforeUnmount: () => {},
    reportContext, reportToggle, session: { user: { id: 9 } },
    reportSettings: async () => ({ can_manage: true, revision: 0, devices: [] }),
    pairReportDevice: async (tenant, project, body) => { calls.push({ tenant, project, body }); return { pairing_code: 'synthetic' } },
  })
  const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm, '')
  vm.runInContext(script + '\nglobalThis.panel = { loadSettings, pair, reset, account, label, settings, pairing }', ctx)
  return { api: ctx.panel, ctx, calls, props }
}
const flush = () => new Promise(resolve => setImmediate(resolve))

test('no accounts still generates a pairing with null account; selected legacy account is preserved', async () => {
  for (const account of [null, 12]) {
    const f = panel(); await f.api.loadSettings()
    f.api.label.value = ' 合成团队电脑 '; f.api.account.value = account
    f.api.pair(); await flush()
    assert.equal(f.calls.length, 1)
    assert.equal(f.calls[0].body.account_id, account === null ? null : '12')
    assert.equal(f.calls[0].body.label, '合成团队电脑')
    assert.equal(f.calls[0].tenant, 7); assert.equal(f.calls[0].project, 5)
  }
  assert.doesNotMatch(source, /disabled="[^"]*\|\| !account/)
  assert.match(source, /回传公众号：\{\{ status.reportedAccount\?\.name \|\| '未上报' \}\}/)
})

test('blank remark and read-only permission prevent requests with no account selected', async () => {
  const f = panel(); await f.api.loadSettings()
  f.api.label.value = '  '; f.api.pair(); await flush(); assert.equal(f.calls.length, 0)
  f.api.label.value = '合成电脑'; f.api.settings.value.can_manage = false
  f.api.pair(); await flush(); assert.equal(f.calls.length, 0)
})

test('customer/project switch discards late unbound pairing code', async () => {
  const f = panel(); await f.api.loadSettings(); let finish
  f.ctx.pairReportDevice = () => new Promise(resolve => { finish = resolve })
  f.api.label.value = '合成电脑'; f.api.pair()
  f.props.tenantId = 8; f.props.projectId = 6; f.api.reset()
  finish({ pairing_code: 'old-synthetic-code' }); await flush()
  assert.equal(f.api.pairing.value, null)
})
