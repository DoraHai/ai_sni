import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'

const fixture = vi.hoisted(() => ({ user: null }))
vi.mock('../src/api/auth', () => ({
  changePassword: vi.fn(),
  fetchMe: vi.fn(async () => ({ user: fixture.user })),
  fetchTenants: vi.fn(async () => ({ tenants: [{ id: 1, name: '客户甲' }, { id: 2, name: '客户乙' }] })),
}))
vi.mock('../src/api/seo', () => ({
  assistSeoContent: vi.fn(), createSeoContentAsset: vi.fn(), updateSeoContentAsset: vi.fn(),
  fetchSeoKeywords: vi.fn(async () => ({ items: [] })),
  fetchSeoContentAssets: vi.fn(async () => ({ items: [{
    id: 11, title: '客户甲待交付文章', draft: '<p>客户甲未保存的交付稿</p>', source_text: '客户甲原文资料', version_count: 1,
  }] })),
}))
vi.mock('../src/api/alerts', () => ({ fetchAlerts: vi.fn(async () => ({})) }))
vi.mock('../src/api/expansion', () => ({ fetchCandidates: vi.fn(async () => ({})) }))
vi.mock('../src/api/writeback', () => ({ fetchWritebackMode: vi.fn(async () => ({})) }))
vi.mock('../src/api/customerProfile', () => ({
  updateCustomerProfile: vi.fn(),
  fetchCustomerProfile: vi.fn(async () => ({ summary: '客户甲的投放画像摘要', profile: {
    basics: { name: '合成客户甲', business_desc: '客户甲业务资料', brand_terms: [] },
    structure: { category_dist: [] }, bid_habits: { avg_price_by_category: [] },
    performance: {}, adjust_behavior: {}, adoption: { status_counts: {} },
  } })),
}))

import App from '../src/App.vue'
import SeoContentEditorView from '../src/views/seo/SeoContentEditorView.vue'
import CustomerProfileView from '../src/views/monitor/CustomerProfileView.vue'
import { session } from '../src/store/session.js'
import client from '../src/api/client.js'
import { fetchCustomerProfile } from '../src/api/customerProfile'

// Unsigned, local display fixtures only. No backend accepts these strings.
const displayToken = claims => `e30.${btoa(JSON.stringify({ sub: '7', ...claims }))}.fixture`
const identity = displayToken({ scope_kind: 'advisor_identity' })
const business = tid => displayToken({ scope_kind: 'advisor_tenant', tid, gid: tid + 100 })
let wrapper
afterEach(() => { wrapper?.unmount(); wrapper = null; session.logout(); vi.clearAllMocks() })

async function openEditor(bare = true) {
  fixture.user = { id: 7, username: 'advisor-fixture', tenant_id: 1, is_advisor: true,
    permissions: { 'seo.site': 'edit', 'seo.content': 'edit' } }
  session.setAuth(identity, fixture.user, false)
  session.replaceAuthForAdvisorTenant(business(1), 1)
  const router = createRouter({ history: createMemoryHistory(), routes: [{
    path: '/seo/editor', component: SeoContentEditorView, meta: { bare },
  }] })
  await router.push('/seo/editor?id=11&type=rewrite')
  await router.isReady()
  wrapper = mount(App, { global: { plugins: [router], stubs: {
    ElConfigProvider: { props: ['locale'], template: '<slot />' },
    ElButton: { template: '<button><slot /></button>' },
    ElAlert: true, ElPopover: true, ElDropdown: true, ElDropdownMenu: true, ElDropdownItem: true,
    ElDialog: true, ElForm: true, ElFormItem: true, ElInput: true,
  } } })
  await flushPromises()
  expect(wrapper.text()).toContain('客户甲原文资料')
  expect(wrapper.get('[contenteditable]').element.innerHTML).toContain('客户甲未保存的交付稿')
}

describe('advisor customer data in mounted routes', () => {
  it('clears an ordinary user profile when the new customer is identity-blocked', async () => {
    fixture.user = { id: 8, username: 'ordinary-fixture', tenant_id: null,
      permissions: { 'monitor.profile': 'view' } }
    session.setAuth('ordinary-local-fixture', fixture.user, false)
    session.setTenant(1)
    const router = createRouter({ history: createMemoryHistory(), routes: [{
      path: '/monitor/profile', component: CustomerProfileView,
    }] })
    await router.push('/monitor/profile')
    await router.isReady()
    wrapper = mount(App, { global: { plugins: [router], directives: { loading: () => {} }, stubs: {
      ElConfigProvider: { props: ['locale'], template: '<slot />' },
      ElButton: { template: '<button><slot /></button>' },
      ElAlert: true, ElPopover: true, ElDropdown: true, ElDropdownMenu: true, ElDropdownItem: true,
      ElDialog: true, ElForm: true, ElFormItem: true, ElInput: true, CategoryDrilldownModal: true,
    } } })
    await flushPromises()
    expect(wrapper.text()).toContain('客户甲业务资料')
    fetchCustomerProfile.mockRejectedValueOnce(Object.assign(new Error('synthetic identity blocked'), { status: 409 }))
    session.setTenant(2)
    await flushPromises()
    expect(wrapper.text()).not.toContain('客户甲的投放画像摘要')
    expect(wrapper.text()).not.toContain('客户甲业务资料')
  })

  it('rejects a late response after an ordinary tenant switch, including a round trip', async () => {
    fixture.user = { id: 8, tenant_id: null, permissions: { 'monitor.profile': 'view' } }
    session.setAuth('ordinary-local-fixture', fixture.user, false)
    session.setTenant(1)
    let finish
    const pending = client.get('/api/v1/customer-profile?tenant_id=1', {
      adapter: config => new Promise(resolve => {
        finish = () => resolve({ data: { summary: 'stale customer A' }, status: 200, headers: {}, config })
      }),
    })
    await flushPromises()
    session.setTenant(2)
    session.setTenant(1)
    finish()
    await expect(pending).rejects.toMatchObject({ code: 'AUTH_CONTEXT_CHANGED' })
    const revision = session.authRevision
    session.setTenant(1)
    expect(session.authRevision).toBe(revision)
  })

  it.each([true, false])('removes loaded content and editor DOM after grant revocation (bare=%s)', async bare => {
    await openEditor(bare)
    await expect(client.get('/api/v1/seo/content-assets?tenant_id=1', {
      adapter: config => Promise.reject({ config, response: { status: 401, data: { detail: { code: 'ADVISOR_GRANT_REVOKED' } } } }),
    })).rejects.toMatchObject({ code: 'ADVISOR_GRANT_REVOKED' })
    await nextTick()
    await flushPromises()
    expect(session.tenantId).toBeNull()
    expect(wrapper.text()).not.toContain('客户甲原文资料')
    expect(wrapper.html()).not.toContain('客户甲未保存的交付稿')
    expect(wrapper.html()).not.toContain('客户甲待交付文章')
  })

  it('clears the live SEM customer profile after the selected grant is revoked', async () => {
    fixture.user = { id: 7, username: 'advisor-fixture', tenant_id: 1, is_advisor: true,
      permissions: { 'seo.site': 'edit', 'seo.content': 'edit', 'monitor.profile': 'view' } }
    session.setAuth(identity, fixture.user, false)
    session.replaceAuthForAdvisorTenant(business(1), 1)
    const router = createRouter({ history: createMemoryHistory(), routes: [{
      path: '/monitor/profile', component: CustomerProfileView,
    }] })
    await router.push('/monitor/profile')
    await router.isReady()
    wrapper = mount(App, { global: { plugins: [router], directives: { loading: () => {} }, stubs: {
      ElConfigProvider: { props: ['locale'], template: '<slot />' },
      ElButton: { template: '<button><slot /></button>' },
      ElAlert: true, ElPopover: true, ElDropdown: true, ElDropdownMenu: true, ElDropdownItem: true,
      ElDialog: true, ElForm: true, ElFormItem: true, ElInput: true, CategoryDrilldownModal: true,
    } } })
    await flushPromises()
    expect(wrapper.text()).toContain('客户甲的投放画像摘要')
    expect(wrapper.text()).toContain('客户甲业务资料')
    await expect(client.get('/api/v1/customer-profile?tenant_id=1', {
      adapter: config => Promise.reject({ config, response: { status: 401, data: { detail: { code: 'ADVISOR_GRANT_REVOKED' } } } }),
    })).rejects.toMatchObject({ code: 'ADVISOR_GRANT_REVOKED' })
    await flushPromises()
    expect(session.tenantId).toBeNull()
    expect(wrapper.text()).not.toContain('客户甲的投放画像摘要')
    expect(wrapper.text()).not.toContain('客户甲业务资料')
  })

  it('clears the identity backup and customer drafts after logout in another tab', () => {
    const user = { id: 7, tenant_id: 1, is_advisor: true, permissions: { 'seo.content': 'edit' } }
    session.setAuth(identity, user, true)
    sessionStorage.setItem('seo_pending_rewrite_source', '客户甲原文资料')
    expect(sessionStorage.getItem('sem_advisor_identity_v1')).not.toBeNull()
    localStorage.clear()
    window.dispatchEvent(new StorageEvent('storage', { key: 'sem_auth_v1', newValue: null, storageArea: localStorage }))
    expect(session.isLoggedIn).toBe(false)
    expect(sessionStorage.getItem('sem_advisor_identity_v1')).toBeNull()
    expect(sessionStorage.getItem('seo_pending_rewrite_source')).toBeNull()
  })
})
