import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { createEditorContext } from '../src/utils/geoEditorContext.js'

const source = readFileSync(new URL('../src/views/geo/GeoTaskEditorView.vue', import.meta.url), 'utf8')
const follow = source.slice(source.indexOf('async function followJob('), source.indexOf('async function cancelActiveJob('))

for (const status of [403, 409]) {
  test(`channel generation preserves the server's ${status} authorization guidance`, async () => {
    const reason = '当前内容未归属你负责的唯一有效项目，请让超管在项目管理核对项目顾问。'
    const c = vm.createContext({
      channelDraftGate: { value: { allowed: true } }, channelPick: { value: ['website'] },
      jobLive: { value: false }, activeJob: { value: null }, busy: { value: '' },
      generateHint: { value: '' }, tenantId: { value: 17 }, taskId: { value: 16 },
      ElMessage: { error: () => {} },
      createGeoVariants: async () => { throw Object.assign(new Error(reason), { status }) },
    })
    c.captureEditorContext = () => createEditorContext(() => [17, 16])
    const gen = source.slice(source.indexOf('async function genVariants('), source.indexOf('const currentVariantMeta'))
    vm.runInContext(gen, c)
    await c.genVariants()
    assert.equal(c.generateHint.value, `渠道稿没有生成成功：${reason}`)
    assert.equal(c.busy.value, '')
  })
}

function fixture() {
  const stored = new Map(), calls = []
  let finish, fail, tick
  const c = vm.createContext({
    tenantId: { value: 17 }, taskId: { value: 16 },
    activeJob: { value: { id: 15, kind: 'create_variants', status: 'running' } },
    recentTaskJobs: { value: [] }, generateHint: { value: '读取母稿环境' }, busy: { value: 'variants' },
    persistJobId: (id) => id ? stored.set('17:16', id) : stored.delete('17:16'),
    staleProgressHint: () => '',
    waitGeoAsyncJob: (tenant, id, options) => {
      calls.push([tenant, id])
      tick = options.onTick
      return new Promise((resolve, reject) => { finish = resolve; fail = reject })
    },
  })
  c.captureEditorContext = () => createEditorContext(() => [c.tenantId.value, c.taskId.value])
  vm.runInContext(follow, c)
  return { c, stored, calls, finish: (j) => finish(j), fail: (e) => fail(e), tick: (j) => tick(j) }
}

test('channel generation follows tenant-scoped running progress and completes normally', async () => {
  const f = fixture(), pending = f.c.followJob(15)
  assert.deepEqual(f.calls, [[17, 15]])
  f.tick({ id: 15, kind: 'create_variants', status: 'running', progress_label: '正在改写渠道稿' })
  assert.equal(f.c.generateHint.value, '正在改写渠道稿')
  f.finish({ id: 15, kind: 'create_variants', status: 'succeeded' })
  assert.equal((await pending).status, 'succeeded')
  assert.equal(f.c.busy.value, '')
  assert.equal(f.stored.size, 0)
})

test('poll transport timeout stops the reading spinner and preserves resumable job ID', async () => {
  const f = fixture(), pending = f.c.followJob(15)
  f.fail(new Error('timeout of 30000ms exceeded HTTP 504'))
  await assert.rejects(pending, /渠道稿生成进度暂时无法读取/)
  assert.equal(f.c.activeJob.value, null)
  assert.equal(f.c.busy.value, '')
  assert.equal(f.stored.get('17:16'), 15)
  assert.match(f.c.generateHint.value, /刷新查看结果.*联系曹总/)
  assert.doesNotMatch(f.c.generateHint.value, /HTTP|504|30000|读取母稿/)
})

test('upstream job failure stops progress and gives a persistent plain-language hint', async () => {
  const f = fixture(), pending = f.c.followJob(15)
  f.finish({ id: 15, kind: 'create_variants', status: 'failed', error: 'provider=fixture; HTTP 500' })
  await assert.rejects(pending, /渠道稿没有生成成功：后台处理没有完成/)
  assert.equal(f.c.activeJob.value.status, 'failed')
  assert.equal(f.c.busy.value, '')
  assert.equal(f.stored.size, 0)
  assert.doesNotMatch(f.c.generateHint.value, /provider|HTTP|500/)
})

test('local polling deadline stops the spinner without declaring the backend failed', async () => {
  const f = fixture(), pending = f.c.followJob(15)
  f.finish({ id: 15, kind: 'create_variants', status: 'running' })
  assert.equal((await pending).status, 'running')
  assert.equal(f.c.activeJob.value, null)
  assert.equal(f.c.busy.value, '')
  assert.equal(f.stored.get('17:16'), 15)
  assert.match(f.c.generateHint.value, /后台仍在生成/)
})

for (const failed of [false, true]) {
  test(`late polling ${failed ? 'failure' : 'result'} cannot affect another tenant`, async () => {
    const f = fixture(), pending = f.c.followJob(15)
    f.c.tenantId.value = 1
    f.c.activeJob.value = { id: 99, status: 'running' }
    f.c.generateHint.value = '新客户进度'
    f.c.busy.value = 'generate'
    f.tick({ id: 15, status: 'running', progress_label: '旧客户进度' })
    if (failed) f.fail(new Error('old timeout'))
    else f.finish({ id: 15, status: 'failed' })
    await pending
    assert.equal(f.c.activeJob.value.id, 99)
    assert.equal(f.c.generateHint.value, '新客户进度')
    assert.equal(f.c.busy.value, 'generate')
  })
}

function buttonFixture() {
  const f = fixture(), messages = [], requests = []
  const task = { id: 16, variants: [{ channel: 'website' }] }
  Object.assign(f.c, {
    channelDraftGate: { value: { allowed: true } }, channelPick: { value: ['website'] },
    jobLive: { value: false }, checkResult: { value: null }, docTab: { value: 'master' },
    variantViewMode: { value: '' }, variantFails: { value: [] },
    ElMessage: Object.fromEntries(['info', 'warning', 'success', 'error'].map((key) => [key,
      (message) => messages.push([key, message])])),
    createGeoVariants: async (...args) => { requests.push(args); return {
      async: true, job: { id: 15, kind: 'create_variants', status: 'pending' },
    } },
    getGeoContentTask: async (tenant, id) => {
      assert.equal(tenant, 17); assert.equal(id, 16); return task
    },
    applyTaskPayload: (payload) => { f.c.task = payload }, applyVariantFromTask: () => {},
    checkGeoContentTask: async () => ({}), formatGateFailRows: () => ({ rows: [] }),
    channelLabel: (channel) => channel,
  })
  vm.runInContext(source.slice(source.indexOf('async function genVariants()'), source.indexOf('const currentVariantMeta =')), f.c)
  return { ...f, messages, requests }
}

test('generate button completes submit, poll and channel-draft refresh for the same tenant', async () => {
  const f = buttonFixture(), pending = f.c.genVariants()
  for (let i = 0; i < 10 && !f.calls.length; i++) await Promise.resolve()
  assert.deepEqual(f.requests[0].slice(0, 3).map((x) => Array.isArray(x) ? [...x] : x), [17, 16, ['website']])
  f.finish({ id: 15, kind: 'create_variants', status: 'succeeded', result_meta: {
    variant_polish: { llm: 1, fallback: 0, rejected: 0 },
  } })
  await pending
  assert.equal(f.c.task.id, 16)
  assert.equal(f.c.docTab.value, 'website')
  assert.equal(f.c.busy.value, '')
  assert.equal(f.messages.at(-1)[0], 'success')
})

test('generate button shows a persistent safe error when the initial request fails', async () => {
  const f = buttonFixture()
  f.c.createGeoVariants = async () => { throw new Error('HTTP 502 provider=fixture') }
  await f.c.genVariants()
  assert.equal(f.c.busy.value, '')
  assert.equal(f.messages.at(-1)[0], 'error')
  assert.match(f.c.generateHint.value, /渠道稿没有生成成功.*联系曹总/)
  assert.doesNotMatch(f.messages.at(-1)[1], /HTTP|provider|502/)
})

test('generate button reports a polling timeout and stops both busy and live-job progress', async () => {
  const f = buttonFixture(), pending = f.c.genVariants()
  for (let i = 0; i < 10 && !f.calls.length; i++) await Promise.resolve()
  f.fail(new Error('timeout of 30000ms exceeded'))
  await pending
  assert.equal(f.c.busy.value, '')
  assert.equal(f.c.activeJob.value, null)
  assert.equal(f.messages.at(-1)[0], 'error')
  assert.match(f.messages.at(-1)[1], /渠道稿生成进度暂时无法读取/)
})
