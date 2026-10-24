import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import Services from '../src/views/settings/PlatformCustomerServices.vue'
import Customers from '../src/views/settings/CustomerModulesView.vue'
import * as api from '../src/api/platformCustomerServices'
import { fetchCustomers } from '../src/api/moduleAssets'
import { session } from '../src/store/session'

vi.mock('../src/store/session', () => ({ session: { user: { tenant_id: null }, isAdvisorSession: false, canEdit: vi.fn(() => true) } }))
vi.mock('../src/api/auth', () => ({ fetchUsers: vi.fn(async () => ({ users: [
  { id: 7, role_id: 2, display_name: '示例顾问', tenant_ids: [1], is_active: true },
  { id: 8, role_id: 2, tenant_ids: [2], is_active: true },
  { id: 9, role_id: 2, tenant_ids: [1], is_active: false },
  { id: 10, role_id: 3, tenant_ids: [1], is_active: true },
] })) }))
vi.mock('../src/api/roles', () => ({ fetchRoles: vi.fn(async () => ({ roles: [{ id: 2, permissions: { 'seo.content': 'edit' } }] })) }))
vi.mock('../src/api/platformCustomerServices', () => ({ fetchManualQuota: vi.fn(), saveManualQuota: vi.fn(), fetchAssignmentSites: vi.fn(), fetchSiteAssignments: vi.fn(), saveSiteAssignment: vi.fn() }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('../src/api/moduleAssets', () => ({ fetchCustomers: vi.fn(), archiveSemAccount: vi.fn(), createCustomer: vi.fn(), fetchSemIdentityRepairCandidates: vi.fn(), fetchSemIdentityRepairPreview: vi.fn(), fetchSemExecutionPolicy: vi.fn(), setCustomerModule: vi.fn(), setSemExecutionPolicy: vi.fn(), updateCustomer: vi.fn() }))
let wrapper
async function open(kind = 'manual') {
  wrapper = mount(Services, { props: { kind, customer: { id: 1, name: '示例客户甲' } }, attachTo: document.body, global: { plugins: [ElementPlus] } })
  await flushPromises()
}
const input = async (label, value) => {
  const el = document.querySelector(`[aria-label="${label}"]`)
  el.value = value; el.dispatchEvent(new Event(el.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true })); await flushPromises()
}
const click = async text => {
  const el = [...document.querySelectorAll('button')].find(b => b.textContent.trim() === text)
  expect(el).toBeTruthy(); el.click(); await flushPromises()
}
beforeEach(() => {
  vi.resetAllMocks()
  session.user = { tenant_id: null }; session.isAdvisorSession = false; session.canEdit.mockReturnValue(true)
  api.fetchManualQuota.mockResolvedValue({ manual_quota: { used: 0, limit: 2 }, manual_limit_revision: 3 })
  api.saveManualQuota.mockImplementation(async b => ({ manual_quota: { used: 0, limit: b.manual_daily_limit }, manual_limit_revision: 4 }))
  api.fetchAssignmentSites.mockResolvedValue({ sites: [{ id: 11, name: '示例网站', status: 'active' }, { id: 12, status: 'archived' }] })
  api.fetchSiteAssignments.mockResolvedValue({ items: [{ id: 20, advisor_user_id: 7, advisor_name: '示例顾问', active: true }] })
  api.saveSiteAssignment.mockImplementation(async b => ({ id: 20, ...b, advisor_name: '示例顾问' }))
})
afterEach(() => { wrapper?.unmount(); document.body.innerHTML = '' })

it.each(['manual', 'seo'])('cancels %s edits through the same close event without saving', async kind => {
  await open(kind)
  if (kind === 'manual') await input('每日手动检测次数', '10')
  else await input('SEO 网站', '11')
  await click('取消')
  expect(wrapper.emitted('close')).toHaveLength(1)
  expect(api.saveManualQuota).not.toHaveBeenCalled()
  expect(api.saveSiteAssignment).not.toHaveBeenCalled()
})

it.each(['0', '-1', '1.5', '101', '99999999999999999999', ''])('blocks invalid manual limit %s without a write or confirmation', async value => {
  await open(); await input('每日手动检测次数', value); await input('修改原因', '按客户需求调整'); await click('保存变更')
  expect(document.body.textContent).toContain('次数须为 1–100 的整数')
  expect(document.querySelector('[role="alertdialog"]')).toBeNull()
  expect(api.saveManualQuota).not.toHaveBeenCalled()
})
it('requires a reason, cancels safely, then saves exactly once with the independent revision', async () => {
  await open(); await input('每日手动检测次数', '100'); await click('保存变更')
  expect(document.body.textContent).toContain('请填写 1–500 字')
  await input('修改原因', ' 按客户需求调整 '); await click('保存变更')
  expect(document.body.textContent).toContain('2 → 100')
  await click('返回修改'); expect(api.saveManualQuota).not.toHaveBeenCalled()
  await click('保存变更'); await click('确认保存')
  expect(api.saveManualQuota).toHaveBeenCalledExactlyOnceWith({ tenant_id: 1, manual_daily_limit: 100, expected_revision: 3, reason: '按客户需求调整' })
  expect(document.body.textContent).toContain('手动检测次数已保存')
})
it('retains input after conflict and requires a fresh read before retry', async () => {
  api.saveManualQuota.mockRejectedValue(Error('版本冲突'))
  await open(); await input('每日手动检测次数', '1'); await input('修改原因', '调整'); await click('保存变更'); await click('确认保存')
  expect(document.body.textContent).toContain('版本冲突')
  expect(document.querySelector('[aria-label="每日手动检测次数"]').value).toBe('1')
  await click('保存变更'); expect(api.saveManualQuota).toHaveBeenCalledTimes(1)
  await click('重新读取'); expect(api.fetchManualQuota).toHaveBeenCalledTimes(2)
})
it('blocks incomplete quota data and shows read failure explicitly', async () => {
  api.fetchManualQuota.mockResolvedValueOnce({ manual_quota: { limit: 2 } })
  await open(); expect(document.body.textContent).toContain('次数或版本信息不完整')
  api.fetchManualQuota.mockRejectedValueOnce(Error('读取失败')); await click('重新读取')
  expect(document.body.textContent).toContain('读取失败'); expect(api.saveManualQuota).not.toHaveBeenCalled()
})
it('validates site/advisor, filters grants and role, confirms deactivation and preserves its row', async () => {
  await open('seo'); await click('保存变更')
  expect(document.body.textContent).toContain('请选择网站和已获该客户授权')
  await input('SEO 网站', '11')
  expect(api.fetchSiteAssignments).toHaveBeenCalledWith(1, 11)
  expect(document.querySelectorAll('[aria-label="顾问"] option')).toHaveLength(2)
  await input('顾问', '7'); await input('分配状态', 'false'); await click('保存变更')
  expect(document.querySelector('[role="alertdialog"]').textContent).toContain('停用分配')
  expect(api.saveSiteAssignment).not.toHaveBeenCalled()
  await click('返回修改'); await click('保存变更'); await click('确认保存')
  expect(api.saveSiteAssignment).toHaveBeenCalledExactlyOnceWith({ tenant_id: 1, site_id: 11, advisor_user_id: 7, active: false })
  expect(document.body.textContent).toContain('SEO 网站分配已保存'); expect(document.body.textContent).toContain('已停用')
})
it('shows SEO write failure and forces site reread before another save', async () => {
  api.saveSiteAssignment.mockRejectedValue(Error('服务暂时不可用'))
  await open('seo'); await input('SEO 网站', '11'); await input('顾问', '7'); await click('保存变更'); await click('确认保存')
  expect(document.body.textContent).toContain('服务暂时不可用')
  expect(document.querySelector('[aria-label="SEO 网站"]').value).toBe('')
  expect(document.querySelector('[aria-label="顾问"]').value).toBe('')
  expect(document.querySelector('.service-panel ul')).toBeNull()
  await click('保存变更'); expect(api.saveSiteAssignment).toHaveBeenCalledTimes(1)
})
it('can deactivate an existing assignment on an archived site, but cannot enable it', async () => {
  await open('seo'); await input('SEO 网站', '12'); await input('顾问', '7')
  expect(document.body.textContent).toContain('该网站已暂停或归档')
  expect(document.querySelector('[aria-label="分配状态"]').value).toBe('false')
  await input('分配状态', 'true'); await click('保存变更')
  expect(document.body.textContent).toContain('暂停或归档网站只能查看或停用已有分配')
  expect(api.saveSiteAssignment).not.toHaveBeenCalled()
  await input('分配状态', 'false'); await click('保存变更'); await click('确认保存')
  expect(api.saveSiteAssignment).toHaveBeenCalledExactlyOnceWith({ tenant_id: 1, site_id: 12, advisor_user_id: 7, active: false })
})
it('explains assignments that the existing backend cannot update and does not create inactive rows', async () => {
  api.fetchSiteAssignments.mockResolvedValue({ items: [{ id: 21, advisor_user_id: 9, advisor_name: '已停用顾问', active: true }] })
  await open('seo'); await input('SEO 网站', '11')
  expect(document.body.textContent).toContain('只读：现有保存接口要求顾问启用')
  expect(document.querySelectorAll('[aria-label="顾问"] option')).toHaveLength(2)
  await input('顾问', '7'); await input('分配状态', 'false'); await click('保存变更')
  expect(document.body.textContent).toContain('该顾问暂无分配，无需停用')
  expect(api.saveSiteAssignment).not.toHaveBeenCalled()
})
it('holds a single immutable request while saving', async () => {
  let resolve
  api.saveManualQuota.mockImplementation(() => new Promise(r => { resolve = r }))
  await open(); await input('修改原因', '调整'); await click('保存变更'); await click('确认保存'); await click('保存变更')
  expect(api.saveManualQuota).toHaveBeenCalledTimes(1)
  expect(document.querySelector('[aria-label="每日手动检测次数"]').disabled).toBe(true)
  resolve({ manual_quota: { used: 0, limit: 2 }, manual_limit_revision: 4 }); await flushPromises()
})
it.each(['tenant', 'advisor', 'permissions'])('does not read or write for forbidden context %s', async kind => {
  if (kind === 'tenant') session.user.tenant_id = 1
  if (kind === 'advisor') session.isAdvisorSession = true
  if (kind === 'permissions') session.canEdit.mockReturnValue(false)
  await open(); expect(document.body.textContent).toContain('需要平台账号管理')
  expect(api.fetchManualQuota).not.toHaveBeenCalled()
})

it('shows service entries only for available modules in the actual customer table', async () => {
  fetchCustomers.mockResolvedValue({ customers: [
    { id: 1, name: '示例客户甲', modules: ['geo', 'seo'].map(module_code => ({ module_code, status: 'active', available: true })) },
    { id: 2, name: '暂停客户', modules: ['geo', 'seo'].map(module_code => ({ module_code, status: 'suspended', available: false })) },
    { id: 3, name: '过期客户', modules: ['geo', 'seo'].map(module_code => ({ module_code, status: 'active', available: false })) },
    { id: 4, name: '未开通客户', modules: [] },
  ] })
  wrapper = mount(Customers, { attachTo: document.body, global: { plugins: [ElementPlus] } })
  await flushPromises()
  const rows = wrapper.findAll('.el-table__row')
  expect(rows).toHaveLength(4)
  for (const label of ['手动检测次数设置', 'SEO 网站分配']) {
    expect(rows[0].text()).toContain(label)
    for (const row of rows.slice(1)) expect(row.text()).not.toContain(label)
  }
})
