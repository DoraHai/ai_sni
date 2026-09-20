import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { shallowMount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'

vi.mock('../src/api/ocpc', () => ({ fetchOcpcPackages: vi.fn(), updateOcpcBid: vi.fn() }))
vi.mock('../src/api/writeback', () => ({ requestWritebackApproval: vi.fn(), WRITEBACK_CONFIRMATION: 'CONFIRM_BAIDU_WRITEBACK' }))
vi.mock('element-plus', async (importOriginal) => ({ ...await importOriginal(), ElMessage: { success: vi.fn() } }))
import OcpcView from '../src/views/manage/OcpcView.vue'
import { fetchOcpcPackages, updateOcpcBid } from '../src/api/ocpc'
import { requestWritebackApproval } from '../src/api/writeback'
import { session } from '../src/store/session'

const pkg = { package_id: 23, baidu_account_id: 11, ocpc_bid_type: 1, ocpc_bid: 168,
  package_name: '测试策略', dataflows: [], bound_campaigns: [], assist_trans_types: [] }
const result = (mode = 'dry_run') => ({ total: 1, packages: [{ ...pkg }], execution_mode: mode, summary: {} })
let wrapper
beforeEach(() => {
  vi.resetAllMocks()
  session.setAuth('ocpc-test-token', { id: 17, tenant_id: null, permissions: { 'manage.ocpc': 'edit', 'verify.adjustments': 'edit' } }, false)
  session.setTenants([{ id: 3, name: '测试客户' }, { id: 4, name: '其他客户' }])
  session.setTenant(3)
  fetchOcpcPackages.mockResolvedValue(result())
  updateOcpcBid.mockResolvedValue({ status: 'dry_run', id: 9 })
})
afterEach(() => wrapper?.unmount())
async function mount(mode = 'dry_run') {
  fetchOcpcPackages.mockResolvedValue(result(mode))
  wrapper = shallowMount(OcpcView, { global: { directives: { loading: () => {} } } })
  await flushPromises()
  wrapper.vm.openBidEditor(pkg)
  wrapper.vm.bidInput = '180'
  return wrapper.vm
}
it('records a rehearsal and leaves the displayed bid unchanged', async () => {
  const vm = await mount()
  await vm.submitBid()
  expect(updateOcpcBid).toHaveBeenCalledWith(expect.objectContaining({
    tenantId: 3, accountId: 11, packageId: 23, oldBid: 168, newBid: 180, executionMode: 'dry_run',
  }))
  expect(requestWritebackApproval).not.toHaveBeenCalled()
  expect(vm.data.packages[0].ocpc_bid).toBe(168)
})
it('submits one bound confirmation and an idempotency key in live mode', async () => {
  const vm = await mount('live')
  updateOcpcBid.mockResolvedValue({ status: 'success', id: 8 })
  await vm.submitBid()
  expect(updateOcpcBid).toHaveBeenCalledWith(expect.objectContaining({
    packageId: 23, accountId: 11, oldBid: 168, newBid: 180, executionMode: 'live',
    confirmation: 'CONFIRM_BAIDU_WRITEBACK', idempotencyKey: expect.any(String),
  }))
  expect(requestWritebackApproval).not.toHaveBeenCalled()
})
it.each(['NaN', '0', '10000', '180.001', '300', '168'])('rejects invalid or unchanged bid %s', async (bid) => {
  const vm = await mount()
  vm.bidInput = bid
  await vm.submitBid()
  expect(updateOcpcBid).not.toHaveBeenCalled()
  expect(vm.editError).not.toBe('')
})
it.each(['tenant', 'auth'])('cancels pending preflight when %s changes', async (kind) => {
  const vm = await mount()
  let resolve
  fetchOcpcPackages.mockImplementationOnce(() => new Promise(r => { resolve = r }))
  const pending = vm.submitBid()
  if (kind === 'tenant') session.setTenant(4)
  else session.refreshUser({ id: 17, tenant_id: null, permissions: {} })
  await nextTick()
  resolve(result())
  await pending
  expect(updateOcpcBid).not.toHaveBeenCalled()
  expect(vm.editPackage).toBe(null)
})
it('rejects changed backend execution mode', async () => {
  const vm = await mount()
  fetchOcpcPackages.mockResolvedValue(result('live'))
  await vm.submitBid()
  expect(updateOcpcBid).not.toHaveBeenCalled()
  expect(vm.editError).toContain('已变化')
})
it('ignores duplicate submit while preflight is pending', async () => {
  const vm = await mount()
  let resolve
  fetchOcpcPackages.mockImplementationOnce(() => new Promise(r => { resolve = r }))
  const first = vm.submitBid()
  await vm.submitBid()
  resolve(result())
  await first
  expect(updateOcpcBid).toHaveBeenCalledTimes(1)
})

it('does not submit after leaving the page during preflight', async () => {
  const vm = await mount()
  let resolve
  fetchOcpcPackages.mockImplementationOnce(() => new Promise(r => { resolve = r }))
  const pending = vm.submitBid()
  wrapper.unmount()
  resolve(result())
  await pending
  expect(updateOcpcBid).not.toHaveBeenCalled()
})

it('uses the selected account mode instead of the page fallback', async () => {
  const vm = await mount()
  const livePackage = { ...pkg, execution_mode: 'live' }
  vm.openBidEditor(livePackage)
  vm.bidInput = '180'
  fetchOcpcPackages.mockResolvedValue({ ...result(), packages: [livePackage] })
  updateOcpcBid.mockResolvedValue({ status: 'success', id: 8 })
  await vm.submitBid()
  expect(updateOcpcBid).toHaveBeenCalledWith(expect.objectContaining({ executionMode: 'live' }))
})
