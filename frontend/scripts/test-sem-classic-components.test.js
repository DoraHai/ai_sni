import { afterEach, describe, expect, it, vi } from 'vitest'
import { shallowMount } from '@vue/test-utils'
import { nextTick } from 'vue'

const state = vi.hoisted(() => ({ loads: [], budgetLoads: [], prompts: [], confirmations: [], writes: [] }))
const deferred = () => {
  let resolve
  let reject
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail })
  return { promise, resolve, reject }
}

vi.mock('element-plus', async (importOriginal) => ({
  ...await importOriginal(),
  ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn() },
  ElMessageBox: {
    prompt: vi.fn(() => {
      const request = deferred()
      state.prompts.push(request)
      return request.promise
    }),
    confirm: vi.fn(() => {
      const request = deferred()
      state.confirmations.push(request)
      return request.promise
    }),
  },
}))

vi.mock('../src/api/searchTerms', () => ({
  fetchSearchTerms: vi.fn((args) => {
    const request = deferred()
    state.loads.push({ args, ...request })
    return request.promise
  }),
  syncSearchTerms: vi.fn(() => Promise.reject(new Error('sync not expected'))),
  addNegative: vi.fn((args) => { state.writes.push(['negative', args]); return { dry_run: true } }),
  expandKeyword: vi.fn((args) => { state.writes.push(['expand', args]); return { dry_run: true } }),
}))

vi.mock('../src/api/manage', () => ({
  fetchAccountBudget: vi.fn((args) => {
    const request = deferred()
    state.budgetLoads.push({ args, ...request })
    return request.promise
  }),
  setAccountBudget: vi.fn((args) => {
    state.writes.push(['account-budget', args])
    return Promise.resolve({ status: 'dry_run', old_budget: 100, new_budget: args.budget })
  }),
}))

import SearchTermsView from '../src/views/optimize/SearchTermsView.vue'
import AccountBudgetView from '../src/views/manage/AccountBudgetView.vue'
import { session } from '../src/store/session'

afterEach(() => {
  state.loads.length = 0
  state.budgetLoads.length = 0
  state.prompts.length = 0
  state.confirmations.length = 0
  state.writes.length = 0
  session.logout()
  document.body.innerHTML = ''
})

describe('SEM classic account context', () => {
  it('rejects late account data and writes after account switch or unmount', async () => {
    session.setAuth('component-test-token', {
      id: 7,
      tenant_id: null,
      permissions: { 'optimize.searchterms': 'edit' },
    }, false)
    session.setTenants([{
      id: 1,
      name: '测试租户',
      sem_accounts: [
        { id: 11, username: 'A', ucid: 'a', status: 'active' },
        { id: 12, username: 'B', ucid: 'b', status: 'active' },
      ],
    }])
    session.setTenant(1)

    const wrapper = shallowMount(SearchTermsView, { global: { directives: { loading: () => {} } } })
    await nextTick()
    expect(wrapper.vm.selectedAccountId).toBe(null)

    wrapper.vm.selectedAccountId = 11
    await nextTick()
    const loadA = state.loads.find((item) => item.args.baiduAccountId === 11)
    expect(loadA).toBeTruthy()
    wrapper.vm.selectedAccountId = 12
    await nextTick()
    const loadB = state.loads.find((item) => item.args.baiduAccountId === 12)
    expect(loadB).toBeTruthy()

    loadA.resolve({ total: 1, account_scope: { mode: 'single', baidu_account_id: 11 }, search_terms: [{ id: 'A' }] })
    await nextTick()
    expect(wrapper.vm.data?.search_terms?.[0]?.id).not.toBe('A')
    const rowB = { id: 2, baidu_account_id: 12, query_word: 'B词', adgroup_id: 102, adgroup_name: 'B单元' }
    loadB.resolve({ total: 1, account_scope: { mode: 'single', baidu_account_id: 12 }, search_terms: [rowB] })
    await nextTick()
    expect(wrapper.vm.data.search_terms[0].id).toBe(2)

    const confirming = wrapper.vm.expand(rowB)
    await nextTick()
    wrapper.vm.selectedAccountId = 11
    await nextTick()
    state.prompts.at(-1).resolve({ value: '1.25' })
    await confirming
    expect(state.writes).toHaveLength(0)

    const loadA2 = state.loads.filter((item) => item.args.baiduAccountId === 11).at(-1)
    const rowA = { id: 3, baidu_account_id: 11, query_word: 'A词', adgroup_id: 101, adgroup_name: 'A单元' }
    loadA2.resolve({ total: 1, account_scope: { mode: 'single', baidu_account_id: 11 }, search_terms: [rowA] })
    await nextTick()
    const unmounting = wrapper.vm.expand(rowA)
    await nextTick()
    wrapper.unmount()
    state.prompts.at(-1).resolve({ value: '1.50' })
    await unmounting
    expect(state.writes).toHaveLength(0)
  })

  it('never submits an account A budget after switching to account B', async () => {
    session.setAuth('component-test-token', {
      id: 7,
      tenant_id: null,
      permissions: { 'manage.account': 'edit' },
    }, false)
    session.setTenants([{
      id: 1,
      name: '测试租户',
      sem_accounts: [
        { id: 11, username: 'A', ucid: 'a', status: 'active' },
        { id: 12, username: 'B', ucid: 'b', status: 'active' },
      ],
    }])
    session.setTenant(1)

    const wrapper = shallowMount(AccountBudgetView, { global: { directives: { loading: () => {} } } })
    await nextTick()
    expect(wrapper.vm.selectedAccountId).toBe(null)

    wrapper.vm.selectedAccountId = 11
    await nextTick()
    const loadA = state.budgetLoads.find((item) => item.args.baiduAccountId === 11)
    loadA.resolve({ status: 'ok', baidu_account_id: 11, budget: 100, min_budget: 50, max_budget: 1000 })
    await nextTick()
    wrapper.vm.input = 120
    const confirmingA = wrapper.vm.save()
    await nextTick()

    wrapper.vm.selectedAccountId = 12
    await nextTick()
    expect(wrapper.vm.data).toBe(null)
    expect(wrapper.vm.input).toBe(null)
    state.confirmations.at(-1).resolve()
    await confirmingA
    expect(state.writes).toHaveLength(0)

    const loadB = state.budgetLoads.find((item) => item.args.baiduAccountId === 12)
    loadB.resolve({ status: 'ok', baidu_account_id: 12, budget: 200, min_budget: 50, max_budget: 1000 })
    await nextTick()
    wrapper.vm.input = 220
    const unmounting = wrapper.vm.save()
    await nextTick()
    wrapper.unmount()
    state.confirmations.at(-1).resolve()
    await unmounting
    expect(state.writes).toHaveLength(0)
  })
})
