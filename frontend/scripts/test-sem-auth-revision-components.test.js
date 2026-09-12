import { afterEach, describe, expect, it, vi } from 'vitest'
import { shallowMount } from '@vue/test-utils'
import { nextTick } from 'vue'

const state = vi.hoisted(() => ({
  accountLoads: [], campaignLoads: [], adgroupLoads: [], keywordLoads: [], detailLoads: [], modeLoads: [], confirmations: [], writes: [],
}))
const deferred = () => {
  let resolve
  let reject
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail })
  return { promise, resolve, reject }
}
const queued = (collection, args) => {
  const request = deferred()
  collection.push({ args, ...request })
  return request.promise
}

vi.mock('element-plus', async (importOriginal) => ({
  ...await importOriginal(),
  ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn() },
  ElMessageBox: {
    confirm: vi.fn(() => {
      const request = deferred()
      state.confirmations.push(request)
      return request.promise
    }),
    prompt: vi.fn(() => {
      const request = deferred()
      state.confirmations.push(request)
      return request.promise
    }),
  },
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { keywordId: '9001' }, query: {} }),
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock('echarts/core', () => ({
  init: vi.fn(() => ({ setOption: vi.fn(), resize: vi.fn(), clear: vi.fn() })),
  use: vi.fn(),
}))
vi.mock('echarts/charts', () => ({ BarChart: {}, HeatmapChart: {}, LineChart: {} }))
vi.mock('echarts/components', () => ({ GridComponent: {}, LegendComponent: {}, MarkLineComponent: {}, TooltipComponent: {} }))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))

vi.mock('../src/api/manage', () => ({
  fetchAccountBudget: vi.fn((args) => queued(state.accountLoads, args)),
  fetchCampaigns: vi.fn((args) => queued(state.campaignLoads, args)),
  fetchAdgroups: vi.fn((args) => queued(state.adgroupLoads, args)),
  fetchRegionOptions: vi.fn(() => Promise.resolve({ regions: [] })),
  setAccountBudget: vi.fn((args) => { state.writes.push(['account-budget', args]); return Promise.resolve({ status: 'dry_run' }) }),
  setCampaignBudget: vi.fn((args) => { state.writes.push(['campaign-budget', args]); return Promise.resolve({ status: 'dry_run' }) }),
  setCampaignPause: vi.fn((args) => { state.writes.push(['campaign-pause', args]); return Promise.resolve({ status: 'dry_run' }) }),
  setCampaignRegion: vi.fn((args) => { state.writes.push(['campaign-region', args]); return Promise.resolve({ status: 'dry_run' }) }),
  setCampaignSchedule: vi.fn((args) => { state.writes.push(['campaign-schedule', args]); return Promise.resolve({ status: 'dry_run' }) }),
  setAdgroupBid: vi.fn((args) => { state.writes.push(['adgroup-bid', args]); return Promise.resolve({ status: 'dry_run' }) }),
  setAdgroupPause: vi.fn((args) => { state.writes.push(['adgroup-pause', args]); return Promise.resolve({ status: 'dry_run' }) }),
  setAdgroupLandingUrl: vi.fn((args) => { state.writes.push(['landing', args]); return Promise.resolve({ status: 'dry_run' }) }),
}))

vi.mock('../src/api/keywords', () => ({
  fetchKeywordList: vi.fn((args) => queued(state.keywordLoads, args)),
  fetchKeywordDetail: vi.fn((args) => queued(state.detailLoads, args)),
  fetchCampaignList: vi.fn(() => Promise.resolve({ campaigns: [] })),
  fetchAdgroupList: vi.fn(() => Promise.resolve({ adgroups: [] })),
  refreshKeywordWorkbench: vi.fn(() => Promise.resolve({ status: 'ok' })),
  batchUpdateCategory: vi.fn(() => Promise.resolve({ updated: 0 })),
  writebackKeywordBatch: vi.fn((args) => { state.writes.push(['keyword-batch', args]); return Promise.resolve({ applied: [], simulated: [], rejected: [], failed: [] }) }),
  writebackKeyword: vi.fn((args) => { state.writes.push(['keyword-bid', args]); return Promise.resolve({ dry_run: true }) }),
  matchTypeWriteback: vi.fn((args) => { state.writes.push(['keyword-match', args]); return Promise.resolve({ dry_run: true }) }),
  pauseKeywordWriteback: vi.fn((args) => { state.writes.push(['keyword-pause', args]); return Promise.resolve({ dry_run: true, writeback: { id: 4, status: 'dry_run' } }) }),
  updateKeywordCategory: vi.fn(() => Promise.resolve({ status: 'ok' })),
}))

vi.mock('../src/api/writeback', () => ({
  WRITEBACK_CONFIRMATION: 'test-confirmation',
  fetchWritebackMode: vi.fn((tenantId) => queued(state.modeLoads, tenantId)),
}))
vi.mock('../src/api/suggestions', () => ({
  fetchSuggestionAssignees: vi.fn(() => Promise.resolve({ users: [] })),
  fetchSuggestions: vi.fn(() => Promise.resolve({ suggestions: [], total_pending: 0 })),
  updateSuggestionStatus: vi.fn(() => Promise.resolve({})),
  updateSuggestionWorkflow: vi.fn(() => Promise.resolve({ suggestion: { status: 'ignored' } })),
}))
vi.mock('../src/api/alerts', () => ({ resolveAlert: vi.fn(() => Promise.resolve({})) }))

import CampaignManageView from '../src/views/manage/CampaignManageView.vue'
import AdgroupManageView from '../src/views/manage/AdgroupManageView.vue'
import AccountBudgetView from '../src/views/manage/AccountBudgetView.vue'
import KeywordWorkbenchView from '../src/views/optimize/KeywordWorkbenchView.vue'
import KeywordDetailView from '../src/views/monitor/KeywordDetailView.vue'
import { session } from '../src/store/session'

const mountOptions = { global: { directives: { loading: () => {} } } }
const mountedWrappers = []
const mountView = (component) => {
  const wrapper = shallowMount(component, mountOptions)
  mountedWrappers.push(wrapper)
  return wrapper
}
const account = { id: 11, username: 'A', ucid: 'a', status: 'active' }
function login(permission) {
  session.setAuth('auth-revision-test-token', { id: 17, tenant_id: null, permissions: { [permission]: 'edit' } }, false)
  session.setTenants([{ id: 1, name: '测试租户', sem_accounts: [account] }])
  session.setTenant(1)
}
function revoke() {
  session.refreshUser({ id: 17, tenant_id: null, permissions: {} })
}
const dryRunMode = () => ({
  tenant_id: 1,
  mode: 'dry_run',
  live_scopes: [],
  accounts: [{
    baidu_account_id: 11,
    mode: 'dry_run',
    live_scopes: [],
    policy_source: 'legacy_environment',
    policy_reason: 'global_dry_run',
  }],
})
async function settle() {
  await nextTick()
  await Promise.resolve()
  await nextTick()
}

afterEach(() => {
  for (const wrapper of mountedWrappers.splice(0)) wrapper.unmount()
  for (const key of Object.keys(state)) state[key].length = 0
  session.logout()
  document.body.innerHTML = ''
})

describe('SEM auth revision invalidation', () => {
  it('blocks account budget when permission is revoked during account preflight', async () => {
    login('manage.account')
    const wrapper = mountView(AccountBudgetView)
    await settle()
    wrapper.vm.data = {
      status: 'ok', baidu_account_id: 11, budget: 100,
      min_budget: 50, max_budget: 1000,
    }
    wrapper.vm.input = 120

    const action = wrapper.vm.save()
    expect(state.modeLoads).toHaveLength(1)
    expect(state.confirmations).toHaveLength(0)
    revoke()
    state.modeLoads[0].resolve(dryRunMode())
    await action
    expect(state.confirmations).toHaveLength(0)
    expect(state.writes).toHaveLength(0)
  })

  it('blocks campaign pause when permission is revoked during account preflight', async () => {
    login('manage.campaigns')
    const wrapper = mountView(CampaignManageView)
    await settle()
    wrapper.vm.accountId = 11
    await settle()
    const row = { campaign_id: 101, baidu_account_id: 11, campaign_name: 'A计划', pause: false, status: 21 }
    expect(wrapper.vm.accountId).toBe(11)
    expect(wrapper.vm.canWriteAccount(11)).toBe(true)

    const action = wrapper.vm.togglePause(row)
    expect(action).toBeInstanceOf(Promise)
    expect(state.modeLoads).toHaveLength(1)
    const resolvePreflight = state.modeLoads[0].resolve
    expect(resolvePreflight).toEqual(expect.any(Function))
    expect(state.confirmations).toHaveLength(0)
    revoke()
    resolvePreflight(dryRunMode())
    await action
    expect(state.confirmations).toHaveLength(0)
    expect(state.writes).toHaveLength(0)
  })

  it('blocks campaign budget when its account is disabled during account preflight', async () => {
    login('manage.campaigns')
    const wrapper = mountView(CampaignManageView)
    await settle()
    const row = {
      campaign_id: 101, baidu_account_id: 11, campaign_name: 'A计划', budget: 100,
    }

    const action = wrapper.vm.editBudget(row)
    expect(state.confirmations).toHaveLength(1)
    state.confirmations[0].resolve({ value: '120' })
    await settle()
    expect(state.modeLoads).toHaveLength(1)
    session.setTenants([{
      id: 1,
      name: '测试租户',
      sem_accounts: [{ ...account, status: 'disabled' }],
    }])
    session.requestTenantReload()
    state.modeLoads[0].resolve(dryRunMode())
    await action
    expect(state.confirmations).toHaveLength(1)
    expect(state.writes).toHaveLength(0)
  })

  it('blocks adgroup pause when its account is disabled during account preflight', async () => {
    login('manage.adgroups')
    const wrapper = mountView(AdgroupManageView)
    await settle()
    const row = { adgroup_id: 301, baidu_account_id: 11, adgroup_name: 'A单元', pause: false, status: 21 }
    state.adgroupLoads.at(-1).resolve({ adgroups: [row], total: 1, sync: {} })
    await settle()

    const action = wrapper.vm.togglePause(row)
    await settle()
    const preflight = state.modeLoads.at(-1)
    expect(state.confirmations).toHaveLength(0)
    session.setTenants([{
      id: 1,
      name: '测试租户',
      sem_accounts: [{ ...account, status: 'disabled' }],
    }])
    session.requestTenantReload()
    await settle()
    preflight.resolve(dryRunMode())
    await action
    expect(state.confirmations).toHaveLength(0)
    expect(state.writes).toHaveLength(0)
  })

  it('blocks adgroup bid when its account is disabled during account preflight', async () => {
    login('manage.adgroups')
    const wrapper = mountView(AdgroupManageView)
    await settle()
    const row = { adgroup_id: 301, baidu_account_id: 11, adgroup_name: 'A单元', max_price: 1.5 }

    const action = wrapper.vm.editBid(row)
    expect(state.confirmations).toHaveLength(1)
    state.confirmations[0].resolve({ value: '2.00' })
    await settle()
    expect(state.modeLoads).toHaveLength(1)
    session.setTenants([{
      id: 1,
      name: '测试租户',
      sem_accounts: [{ ...account, status: 'disabled' }],
    }])
    session.requestTenantReload()
    state.modeLoads[0].resolve(dryRunMode())
    await action
    expect(state.confirmations).toHaveLength(1)
    expect(state.writes).toHaveLength(0)
  })

  it('clears campaign data and cancels an open campaign prompt after permission revocation', async () => {
    login('manage.campaigns')
    const wrapper = mountView(CampaignManageView)
    await settle()
    wrapper.vm.load()
    await settle()
    const row = { campaign_id: 101, baidu_account_id: 11, campaign_name: 'A计划', budget: 100, pause: false }
    state.campaignLoads.at(-1).resolve({ campaigns: [row], min_budget: 50, max_budget: 1000 })
    await settle()
    expect(wrapper.vm.data.campaigns[0].campaign_id).toBe(101)

    wrapper.vm.load()
    await settle()
    const late = state.campaignLoads.at(-1)
    wrapper.vm.openSchedule(row)
    expect(wrapper.vm.scheduleVisible).toBe(true)
    const action = wrapper.vm.editBudget(row)
    await settle()
    revoke()
    await settle()
    expect(wrapper.vm.data).toBe(null)
    expect(wrapper.vm.scheduleVisible).toBe(false)
    expect(wrapper.vm.scheduleForm.accountId).toBe(null)
    state.confirmations.at(-1).resolve({ value: '120' })
    await action
    expect(state.writes).toHaveLength(0)

    late.resolve({ campaigns: [{ campaign_id: 999 }] })
    await settle()
    expect(wrapper.vm.data).toBe(null)
  })

  it('cancels keyword writeback when permission is revoked during its read-only preflight', async () => {
    login('optimize.keywords')
    const wrapper = mountView(KeywordWorkbenchView)
    await settle()
    state.modeLoads.at(-1).resolve(dryRunMode())
    const row = { keyword_id: 201, baidu_account_id: 11, keyword: 'A词', price: 1.1, pause: false }
    state.keywordLoads.at(-1).resolve({
      total: 1, keywords: [row], totals: { keywords: 1, campaigns: 1, adgroups: 1 },
      category_counts: {}, metrics_window: null,
    })
    await settle()
    expect(wrapper.vm.data.keywords[0].keyword_id).toBe(201)

    wrapper.vm.load()
    await settle()
    const late = state.keywordLoads.at(-1)
    wrapper.vm.openLanding({ ...row, adgroup_id: 301, pc_final_url: 'https://old.example/' })
    expect(wrapper.vm.landingDialog.visible).toBe(true)
    const action = wrapper.vm.applyWriteback(row)
    await settle()
    const preflight = state.modeLoads.at(-1)
    expect(state.modeLoads).toHaveLength(2)
    expect(state.confirmations).toHaveLength(0)
    revoke()
    await settle()
    expect(wrapper.vm.data).toBe(null)
    expect(wrapper.vm.landingDialog.visible).toBe(false)
    expect(wrapper.vm.landingDialog.pcFinalUrl).toBe('')
    expect(state.confirmations).toHaveLength(0)
    expect(state.writes).toHaveLength(0)
    preflight.resolve(dryRunMode())
    await action
    expect(state.confirmations).toHaveLength(0)
    expect(state.writes).toHaveLength(0)

    late.resolve({ total: 1, keywords: [{ keyword_id: 999 }], totals: {}, category_counts: {} })
    await settle()
    expect(wrapper.vm.data).toBe(null)
  })

  it('clears keyword detail and rejects its late reload after permission revocation', async () => {
    login('optimize.keywords')
    const wrapper = mountView(KeywordDetailView)
    await settle()
    const metric = { current: 0, previous: 0, change_pct: null }
    state.detailLoads.at(-1).resolve({
      keyword: { keyword_id: 9001, keyword: 'A词', category: {}, pause: false },
      latest: { bid: 1.1, quality_detail: {} }, period: { start_date: '2026-09-01', end_date: '2026-09-01' },
      kpi: { cost: metric, click: metric, impression: metric, cpc: metric, ctr: metric, avg_rank: metric, conversions: metric, conv_cost: metric },
      trend: [], bid_trend: [], device_split: [], region_analysis: null, schedule_analysis: null,
      alerts: [], bid_coefficients: { effective: {} }, search_queries: [],
    })
    await settle()
    expect(wrapper.vm.data.keyword.keyword_id).toBe(9001)
    wrapper.vm.editPrice = 1.2

    wrapper.vm.load()
    await settle()
    const late = state.detailLoads.at(-1)
    revoke()
    await settle()
    expect(wrapper.vm.data).toBe(null)
    expect(wrapper.vm.editPrice).toBe(null)
    late.resolve({ keyword: { keyword_id: 999 }, period: { start_date: '2026-09-01', end_date: '2026-09-01' } })
    await settle()
    expect(wrapper.vm.data).toBe(null)
  })

  it('cancels match-type writeback when permission is revoked during its preflight', async () => {
    login('optimize.keywords')
    const wrapper = mountView(KeywordWorkbenchView)
    await settle()
    state.modeLoads.at(-1).resolve(dryRunMode())
    const row = { keyword_id: 211, baidu_account_id: 11, keyword: '匹配词', match_type: '短语匹配', price: 1.1, pause: false }
    state.keywordLoads.at(-1).resolve({
      total: 1, keywords: [row], totals: {}, category_counts: {}, metrics_window: null,
    })
    await settle()

    const action = wrapper.vm.openMatchTypeDialog(row, 'exact')
    await settle()
    const preflight = state.modeLoads.at(-1)
    expect(state.confirmations).toHaveLength(0)
    revoke()
    await settle()
    preflight.resolve(dryRunMode())
    await action
    expect(state.confirmations).toHaveLength(0)
    expect(state.writes).toHaveLength(0)
  })

  it('cancels keyword pause when the account is disabled during its preflight', async () => {
    login('optimize.keywords')
    const wrapper = mountView(KeywordWorkbenchView)
    await settle()
    state.modeLoads.at(-1).resolve(dryRunMode())
    const row = { keyword_id: 212, baidu_account_id: 11, keyword: '启停词', price: 1.1, pause: false }
    state.keywordLoads.at(-1).resolve({
      total: 1, keywords: [row], totals: {}, category_counts: {}, metrics_window: null,
    })
    await settle()

    const action = wrapper.vm.togglePause(row)
    await settle()
    const preflight = state.modeLoads.at(-1)
    expect(state.confirmations).toHaveLength(0)
    session.setTenants([{
      id: 1,
      name: '测试租户',
      sem_accounts: [{ ...account, status: 'disabled' }],
    }])
    session.requestTenantReload()
    await settle()
    preflight.resolve(dryRunMode())
    await action
    expect(state.confirmations).toHaveLength(0)
    expect(state.writes).toHaveLength(0)
  })

  it('opens non-funds confirmations only after the account preflight succeeds', async () => {
    login('optimize.keywords')
    const wrapper = mountView(KeywordWorkbenchView)
    await settle()
    state.modeLoads.at(-1).resolve(dryRunMode())
    const row = { keyword_id: 213, baidu_account_id: 11, keyword: '操作词', match_type: '短语匹配', price: 1.1, pause: false }
    state.keywordLoads.at(-1).resolve({
      total: 1, keywords: [row], totals: {}, category_counts: {}, metrics_window: null,
    })
    await settle()

    const matchAction = wrapper.vm.openMatchTypeDialog(row, 'exact')
    await settle()
    expect(state.confirmations).toHaveLength(0)
    state.modeLoads.at(-1).resolve(dryRunMode())
    await settle()
    expect(state.confirmations).toHaveLength(1)
    state.confirmations.at(-1).resolve()
    await matchAction
    expect(state.writes.at(-1)[0]).toBe('keyword-match')

    const pauseAction = wrapper.vm.togglePause(row)
    await settle()
    expect(state.confirmations).toHaveLength(1)
    state.modeLoads.at(-1).resolve(dryRunMode())
    await settle()
    expect(state.confirmations).toHaveLength(2)
    state.confirmations.at(-1).resolve()
    await pauseAction
    expect(state.writes.at(-1)[0]).toBe('keyword-pause')
  })

  it('clears keyword workbench mode and blocks writes when the same account becomes disabled', async () => {
    login('optimize.keywords')
    const wrapper = mountView(KeywordWorkbenchView)
    await settle()
    state.modeLoads.at(-1).resolve(dryRunMode())
    const row = { keyword_id: 301, baidu_account_id: 11, keyword: 'A词', price: 1.1, pause: false }
    state.keywordLoads.at(-1).resolve({
      total: 1, keywords: [row], totals: { keywords: 1, campaigns: 1, adgroups: 1 },
      category_counts: {}, metrics_window: null,
    })
    await settle()
    wrapper.vm.selection = [row]
    wrapper.vm.openLanding({ ...row, adgroup_id: 401, pc_final_url: 'https://old.example/' })
    expect(wrapper.vm.data.keywords[0].keyword_id).toBe(301)
    expect(wrapper.vm.landingDialog.visible).toBe(true)

    session.setTenants([{
      id: 1,
      name: '测试租户',
      sem_accounts: [{ ...account, status: 'disabled' }],
    }])
    session.requestTenantReload()
    await settle()
    expect(wrapper.vm.data).toBe(null)
    expect(wrapper.vm.selection).toHaveLength(0)
    expect(wrapper.vm.landingDialog.visible).toBe(false)

    await wrapper.vm.applyWriteback(row)
    expect(state.confirmations).toHaveLength(0)
    expect(state.writes).toHaveLength(0)
  })
})
