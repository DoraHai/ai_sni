import test from 'node:test'
import assert from 'node:assert/strict'
import { createHash, webcrypto } from 'node:crypto'
import vm from 'node:vm'
import { readFileSync } from 'node:fs'
import { reportContext, reportDigest, reportToggle, reportPublishAccount, reportAccountName, reportDeviceLabel } from '../src/utils/geoDistributionReport.js'

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
  const calls = [], writes = [], opened = [], props = { tenantId: 7, projectId: 5, accounts: [], mode: 'devices' }
  const ctx = vm.createContext({ defineProps: () => props, defineEmits: () => () => {},
    ref: value => ({ value }), computed: fn => ({ get value() { return fn() } }), watch: () => {}, onBeforeUnmount: () => {},
    reportContext, reportToggle, reportPublishAccount, reportAccountName, reportDeviceLabel, session: { user: { id: 9 } },
    reportSettings: async () => ({ can_manage: true, enabled: true, scope_enabled: true, revision: 0, scope_revision: 0, devices: [] }),
    setReportSettings: async (tenant, project, body) => { opened.push({ tenant, project, body }); return { ...body, revision: body.expected_revision + 1, scope_revision: body.expected_scope_revision + 1, devices: [] } },
    pairReportDevice: async (tenant, project, body) => { calls.push({ tenant, project, body }); return { pairing_code: 'synthetic' } },
    fetchReportTask: async () => ({ taskId: 'task-1', revision: 7, reportedAccount: { name: '合成上报号' } }),
    setReportPublishAccount: async (tenant, project, id, body) => {
      writes.push({ tenant, project, id, body })
      return { taskId: id, revision: body.expected_revision + 1, reportedAccount: { name: '合成上报号' },
        ...(body.name === null ? {} : { advisorAccount: { name: body.name } }) }
    },
  })
  const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm, '')
  vm.runInContext(script + '\nglobalThis.panel = { loadSettings, pair, reset, account, label, settings, pairing, busy, error, notice, result, startEdit, saveAccount, editing, editName, editRevision }', ctx)
  return { api: ctx.panel, ctx, calls, writes, opened, props }
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
  assert.match(source, /发布公众号：\{\{ reportPublishAccount\(status\) \}\}/)
})

test('blank remark gets Beijing default while read-only prevents requests', async () => {
  const f = panel(); await f.api.loadSettings()
  f.api.label.value = '  '; await f.api.pair(); assert.equal(f.calls.length, 1)
  assert.match(f.calls[0].body.label, /^多号通电脑-\d{2}\/\d{2} \d{2}:\d{2}$/)
  f.api.label.value = '合成电脑'; f.api.settings.value.can_manage = false
  await f.api.pair(); assert.equal(f.calls.length, 1)
  assert.equal(f.opened.length, 0)
})

test('customer/project switch discards late unbound pairing code', async () => {
  const f = panel(); await f.api.loadSettings(); let finish
  f.ctx.pairReportDevice = () => new Promise(resolve => { finish = resolve })
  f.api.label.value = '合成电脑'; f.api.pair()
  f.props.tenantId = 8; f.props.projectId = 6; f.api.reset()
  finish({ pairing_code: 'old-synthetic-code' }); await flush()
  assert.equal(f.api.pairing.value, null)
})

test('default remark uses Beijing date at midnight and preserves supplied remark', () => {
  assert.equal(reportDeviceLabel(' ', new Date('2026-01-02T16:05:00Z')), '多号通电脑-01/03 00:05')
  assert.equal(reportDeviceLabel(' 合成电脑 ', new Date('2026-01-02T16:05:00Z')), '合成电脑')
})

test('one-click opens only selected customer/project before pairing with returned revision', async () => {
  const f = panel(); await f.api.loadSettings()
  f.api.settings.value = { can_manage: true, enabled: false, scope_enabled: false, revision: 4, scope_revision: 2 }
  await f.api.pair()
  assert.equal(f.opened.length, 1); assert.equal(f.calls.length, 1)
  assert.deepEqual(JSON.parse(JSON.stringify(f.opened[0])), { tenant: 7, project: 5,
    body: { enabled: true, scope_enabled: true, expected_revision: 4, expected_scope_revision: 2 } })
  assert.equal(f.calls[0].body.expected_revision, 5)
  assert.equal(f.api.notice.value, '已同时开启回传')
})

test('already-open reporting pairs directly', async () => {
  const f = panel(); await f.api.loadSettings(); await f.api.pair()
  assert.equal(f.opened.length, 0); assert.equal(f.calls.length, 1)
})

test('opening failure does not generate pairing code or repeat submit', async () => {
  const f = panel(); await f.api.loadSettings(); f.api.settings.value.enabled = false
  f.ctx.setReportSettings = async () => { throw new Error('synthetic-denied') }
  await f.api.pair()
  assert.equal(f.calls.length, 0); assert.match(f.api.error.value, /未生成配对码/)
  assert.equal(f.api.busy.value, false)
})

test('double click during opening makes one request and a context switch stops subsequent pairing', async () => {
  const f = panel(); await f.api.loadSettings(); f.api.settings.value.enabled = false
  let finish, count = 0
  f.ctx.setReportSettings = () => { ++count; return new Promise(resolve => { finish = resolve }) }
  const pending = f.api.pair(); await f.api.pair()
  assert.equal(count, 1)
  f.props.tenantId = 8; f.props.projectId = 6; f.api.reset()
  finish({ enabled: true, scope_enabled: true, revision: 1, scope_revision: 1 })
  await pending
  assert.equal(f.calls.length, 0); assert.equal(f.api.notice.value, '')
})

test('pairing failure keeps explicit newly enabled state and clear message', async () => {
  const f = panel(); await f.api.loadSettings(); f.api.settings.value.enabled = false
  f.ctx.pairReportDevice = async () => { throw new Error('synthetic-unavailable') }
  await f.api.pair()
  assert.equal(f.api.settings.value.enabled, true)
  assert.equal(f.api.pairing.value, null); assert.equal(f.api.notice.value, '已同时开启回传')
  assert.match(f.api.error.value, /配对码未生成/)
})

test('display prioritizes advisor, then immutable report, then unfilled', () => {
  const status = { advisorAccount: { name: '合成顾问号' }, reportedAccount: { name: '合成上报号' } }
  assert.equal(reportPublishAccount(status), '合成顾问号 （顾问标注）')
  assert.equal(reportPublishAccount({ reportedAccount: status.reportedAccount }), '合成上报号 （多号通上报）')
  assert.equal(reportPublishAccount({}), '未填写')
  assert.equal(reportAccountName(' 合成\u200b号\u3000  测试😀 '), '合成号 测试😀')
})

test('editor fetches fresh revision, saves normalized name and clears without replacing report', async () => {
  for (const clear of [false, true]) {
    const f = panel(); await f.api.loadSettings(); f.api.result.value = { taskId: 'task-1', revision: 1 }
    await f.api.startEdit()
    assert.equal(f.api.editRevision.value, 7)
    f.api.editName.value = ' 合成\u200b编辑号 '
    await f.api.saveAccount(clear)
    assert.equal(f.writes.length, 1)
    assert.equal(f.writes[0].body.expected_revision, 7)
    assert.equal(f.writes[0].body.name, clear ? null : '合成编辑号')
    assert.equal(f.api.result.value.reportedAccount.name, '合成上报号')
    assert.equal(f.api.editing.value, false)
    assert.equal(f.api.settings.value.revision, 8)
    assert.equal(reportPublishAccount(f.api.result.value), clear ? '合成上报号 （多号通上报）' : '合成编辑号 （顾问标注）')
  }
})

test('editor rejects invalid length and revision conflict requires fresh edit', async () => {
  const f = panel(); await f.api.loadSettings(); f.api.result.value = { taskId: 'task-1' }
  await f.api.startEdit(); f.api.editName.value = '😀'.repeat(61)
  await f.api.saveAccount(); assert.equal(f.writes.length, 0)
  f.api.editName.value = '😀'.repeat(60)
  f.ctx.setReportPublishAccount = async () => { throw Object.assign(new Error('synthetic-conflict'), { code: 'SOURCE_CHANGED' }) }
  await f.api.saveAccount()
  assert.equal(f.api.editing.value, false); assert.match(f.api.error.value, /重新点编辑/)
  assert.equal(f.api.result.value.advisorAccount, undefined)
})

test('read-only hides primary/edit/close buttons and does not fetch editor or submit', async () => {
  const f = panel(); await f.api.loadSettings(); f.api.settings.value.can_manage = false
  f.api.result.value = { taskId: 'task-1' }
  let fetched = 0; f.ctx.fetchReportTask = async () => { ++fetched }
  await f.api.startEdit(); await f.api.pair()
  assert.equal(fetched, 0); assert.equal(f.calls.length, 0); assert.equal(f.writes.length, 0)
  assert.match(source, /<el-button v-if="canManage"[^>]*@click="pair"/)
  assert.match(source, /<el-button v-if="canManage"[^>]*@click="startEdit"/)
  assert.match(source, /v-if="canManage && settings.enabled && settings.scope_enabled"/)
})

test('page load fetches ledger annotation and stale editor response is discarded', async () => {
  const f = panel(); f.props.mode = 'task'
  f.props.task = { variants: [{ channel: 'wechat', adapt_meta: { distribution_report_v1: { taskId: 'task-1' } } }] }
  f.ctx.fetchReportTask = async () => ({ taskId: 'task-1', revision: 8, advisorAccount: { name: '已存顾问号' } })
  await f.api.loadSettings(); assert.equal(f.api.result.value.advisorAccount.name, '已存顾问号')
  let finish; f.ctx.fetchReportTask = () => new Promise(resolve => { finish = resolve })
  const pending = f.api.startEdit(); f.props.tenantId = 8; f.api.reset()
  finish({ taskId: 'task-1', revision: 8, advisorAccount: { name: '旧客户号' } }); await pending
  assert.equal(f.api.editing.value, false); assert.equal(f.api.result.value, null)
})

test('initial ledger fetch blocks edits until its snapshot has arrived', async () => {
  const f = panel(); f.props.mode = 'task'
  f.props.task = { variants: [{ channel: 'wechat', adapt_meta: { distribution_report_v1: { taskId: 'task-1' } } }] }
  let finish, reads = 0
  f.ctx.fetchReportTask = () => { ++reads; return new Promise(resolve => { finish = resolve }) }
  const pending = f.api.loadSettings(); await flush()
  assert.equal(f.api.busy.value, true)
  await f.api.startEdit(); assert.equal(reads, 1)
  finish({ taskId: 'task-1', revision: 4, advisorAccount: { name: '最新顾问号' } }); await pending
  assert.equal(f.api.busy.value, false)
  assert.equal(f.api.result.value.advisorAccount.name, '最新顾问号')
})

test('annotation save response after customer switch cannot restore old name or revision', async () => {
  const f = panel(); await f.api.loadSettings(); f.api.result.value = { taskId: 'task-1' }
  await f.api.startEdit(); f.api.editName.value = '旧客户编辑号'
  let finish; f.ctx.setReportPublishAccount = () => new Promise(resolve => { finish = resolve })
  const pending = f.api.saveAccount()
  f.props.tenantId = 8; f.props.projectId = 6; f.api.reset()
  finish({ taskId: 'task-1', revision: 8, advisorAccount: { name: '旧客户编辑号' } }); await pending
  assert.equal(f.api.result.value, null); assert.equal(f.api.settings.value, null)
  assert.equal(f.api.editing.value, false)
})
