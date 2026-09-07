import { afterEach, describe, expect, it, vi } from 'vitest'
import { shallowMount } from '@vue/test-utils'
import { nextTick } from 'vue'

const state = vi.hoisted(() => ({
  campaignLoads: [], keywordLoads: [], detailLoads: [], confirmations: [], writes: [],
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
  fetchCampaigns: vi.fn((args) => queued(state.campaignLoads, args)),
  fetchRegionOptions: vi.fn(() => Promise.resolve({ regions: [] })),
  setCampaignBudget: vi.fn((args) => { state.writes.push(['campaign-budget', args]); return Promise.resolve({ status: 'dry_run' }) }),
  setCampaignPause: vi.fn((args) => { state.writes.push(['campaign-pause', args]); return Promise.resolve({ status: 'dry_run' }) }),
  setCampaignRegion: vi.fn((args) => { state.writes.push(['campaign-region', args]); return Promise.resolve({ status: 'dry_run' }) }),
  setCampaignSchedule: vi.fn((args) => { state.writes.push(['campaign-schedule', args]); return Promise.resolve({ status: 'dry_run' }) }),
  setAdgroupBid: vi.fn((args) => { state.writes.push(['adgroup-bid', args]); return Promise.resolve({ status: 'dry_run' }) }),
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
  pauseKeywordBatch: vi.fn((args) => { state.writes.push(['keyword-pause', args]); return Promise.resolve({ applied: [], simulated: args.keywordIds, failed: [] }) }),
  updateKeywordCategory: vi.fn(() => Promise.resolve({ status: 'ok' })),
}))

vi.mock('../src/api/writeback', () => ({
  WRITEBACK_CONFIRMATION: 'test-confirmation',
  fetchWritebackMode: vi.fn(() => Promise.resolve({ accounts: [{ baidu_account_id: 11, live_scopes: [] }] })),
}))
vi.mock('../src/api/suggestions', () => ({
  fetchSuggestionAssignees: vi.fn(() => Promise.resolve({ users: [] })),
  fetchSuggestions: vi.fn(() => Promise.resolve({ suggestions: [], total_pending: 0 })),
  updateSuggestionStatus: vi.fn(() => Promise.resolve({})),
  updateSuggestionWorkflow: vi.fn(() => Promise.resolve({ suggestion: { status: 'ignored' } })),
}))
vi.mock('../src/api/alerts', () => ({ resolveAlert: vi.fn(() => Promise.resolve({})) }))

import CampaignManageView from '../src/views/manage/CampaignManageView.vue'
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

  it('clears keyword workbench data and cancels an open keyword confirmation after revocation', async () => {
    login('optimize.keywords')
    const wrapper = mountView(KeywordWorkbenchView)
    await settle()
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
    revoke()
    await settle()
    expect(wrapper.vm.data).toBe(null)
    expect(wrapper.vm.landingDialog.visible).toBe(false)
    expect(wrapper.vm.landingDialog.pcFinalUrl).toBe('')
    state.confirmations.at(-1).resolve()
    await action
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
})
