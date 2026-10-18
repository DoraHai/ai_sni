import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus, { ElSelect, ElDialog } from 'element-plus'
import Accounts from '../src/views/settings/AccountsRolesView.vue'
import { advisorTenantPatch, isAdvisorRole } from '../src/views/settings/advisorTenants.mjs'
import { createUser, updateUser, fetchUsers } from '../src/api/auth'

const fixtures = vi.hoisted(() => ({
  roles: [{ id: 1, name: '管理员', is_system: true, permissions: {} },
    { id: 2, name: '自定义同事', permissions: { 'seo.site': 'edit', 'seo.content': 'edit' } }],
  users: [{ id: 9, username: 'advisor', display_name: '顾问', role_id: 2, is_advisor: true, tenant_id: 1,
    tenant_ids: [1, 2], default_tenant_id: 2, grants_version: '0123456789abcdef', is_active: true }],
  tenants: [{ id: 1, name: '客户甲' }, { id: 2, name: '客户乙' }, { id: 3, name: '客户丙' }],
}))
vi.mock('../src/api/auth', () => ({
  fetchUsers: vi.fn(async () => ({ users: fixtures.users, tenant_options: fixtures.tenants })),
  createUser: vi.fn(async () => ({})), updateUser: vi.fn(async () => ({})), deleteUser: vi.fn(), resetUserPassword: vi.fn(),
}))
vi.mock('../src/api/roles', () => ({ fetchRoles: vi.fn(async () => ({ roles: fixtures.roles })), createRole: vi.fn(), updateRole: vi.fn(), deleteRole: vi.fn() }))
vi.mock('../src/store/session', () => ({ session: { user: { id: 1 } } }))
vi.mock('vue-router', () => ({ useRoute: () => ({ path: '/platform/accounts' }), useRouter: () => ({ push: vi.fn() }) }))
let wrapper
const click = async text => {
  const b = [...document.querySelectorAll('button')].find(b => b.textContent.trim() === text)
  expect(b, text).toBeTruthy(); b.click(); await flushPromises()
}
const select = async (index, value) => { wrapper.findAllComponents(ElSelect)[index].vm.$emit('update:modelValue', value); await flushPromises() }
beforeEach(async () => {
  vi.clearAllMocks()
  wrapper = mount(Accounts, { attachTo: document.body, global: { plugins: [ElementPlus] } })
  await flushPromises()
})
afterEach(() => { wrapper.unmount(); document.body.innerHTML = '' })

it('uses the existing advisor permission predicate and validates the complete grant selection', () => {
  expect(isAdvisorRole(fixtures.roles[0])).toBe(false)
  expect(isAdvisorRole(fixtures.roles[1])).toBe(true)
  expect(isAdvisorRole({ permissions: { ...fixtures.roles[1].permissions, 'settings.accounts': 'edit' } })).toBe(false)
  expect(() => advisorTenantPatch([], null)).toThrow('至少勾选 1 个客户')
  expect(() => advisorTenantPatch([1, 2], 3)).toThrow('默认客户必须在已勾选的客户内')
  expect(advisorTenantPatch([1, 2, 1], 2)).toEqual({ tenant_ids: [1, 2], default_tenant_id: 2 })
})

it('blocks empty advisor selection, then posts the selected grants and a selected default', async () => {
  await click('新建账号')
  const inputs = document.querySelectorAll('.el-dialog input.el-input__inner')
  for (const [i, text] of [[0, 'newadvisor'], [2, 'fixture-only']]) {
    inputs[i].value = text; inputs[i].dispatchEvent(new Event('input', { bubbles: true }))
  }
  await select(0, 2)
  await click('创建')
  expect(document.body.textContent).toContain('至少勾选 1 个客户')
  expect(createUser).not.toHaveBeenCalled()
  expect(document.body.textContent).not.toContain('不限=全部客户')
  await select(1, [1, 2]); await select(2, 2)
  await click('创建')
  expect(createUser).toHaveBeenCalledWith(expect.objectContaining({ tenant_ids: [1, 2], default_tenant_id: 2 }))
  expect(createUser.mock.calls[0][0].clear_tenant).toBeUndefined()
  expect(createUser.mock.calls[0][0].expected_grants_version).toBeUndefined()
})

it('recalls grants and default, and updates the default after unchecking it', async () => {
  expect(wrapper.text()).toContain('客户甲、客户乙（默认：客户乙）')
  await click('编辑')
  expect(wrapper.findAllComponents(ElSelect)[1].props('modelValue')).toEqual([1, 2])
  expect(wrapper.findAllComponents(ElSelect)[2].props('modelValue')).toBe(2)
  await select(1, [1]); await click('保存')
  expect(updateUser).toHaveBeenCalledWith(9, expect.objectContaining({ tenant_ids: [1], default_tenant_id: 1, expected_grants_version: '0123456789abcdef' }))
  expect(updateUser.mock.calls[0][1].clear_tenant).toBeUndefined()
})

it.each([
  ['ADVISOR_GRANTS_CONFLICT', 409, '该账号的客户已被别人修改，请刷新后再改'],
  ['ADVISOR_GRANTS_VERSION_REQUIRED', 428, '客户授权版本缺失，请刷新后再改'],
])('reloads the account after %s and requires a new explicit save', async (code, status, message) => {
  await click('编辑')
  await select(1, [1])
  fetchUsers.mockResolvedValueOnce({ users: [{ ...fixtures.users[0], tenant_ids: [2, 3], default_tenant_id: 3,
    grants_version: 'fedcba9876543210' }], tenant_options: fixtures.tenants })
  updateUser.mockRejectedValueOnce(Object.assign(Error('stale'), { code, status }))
  await click('保存')
  expect(document.body.textContent).toContain(message)
  expect(fetchUsers).toHaveBeenCalledTimes(2)
  expect(updateUser).toHaveBeenCalledTimes(1)
  expect(wrapper.findAllComponents(ElSelect)[1].props('modelValue')).toEqual([2, 3])
  expect(wrapper.findAllComponents(ElSelect)[2].props('modelValue')).toBe(3)
  await click('保存')
  expect(updateUser).toHaveBeenLastCalledWith(9, expect.objectContaining({ tenant_ids: [2, 3], default_tenant_id: 3,
    expected_grants_version: 'fedcba9876543210' }))
})

it('closes the stale form when conflict reload fails instead of reusing its old version', async () => {
  await click('编辑')
  updateUser.mockRejectedValueOnce(Object.assign(Error('stale'), { code: 'ADVISOR_GRANTS_CONFLICT', status: 409 }))
  fetchUsers.mockRejectedValueOnce(Error('reload unavailable'))
  await click('保存')
  expect(document.body.textContent).toContain('重新加载失败，请刷新页面')
  expect(updateUser).toHaveBeenCalledTimes(1)
  expect(wrapper.findAllComponents(ElDialog)[0].props('modelValue')).toBe(false)
})

it('explains the disabled feature and restores the single tenant control', async () => {
  updateUser.mockRejectedValueOnce(Object.assign(Error('disabled'), { code: 'ADVISOR_MULTI_TENANT_DISABLED' }))
  await click('编辑'); await click('保存')
  expect(document.body.textContent).toContain('顾问多客户功能尚未开放')
  expect(wrapper.findAllComponents(ElSelect)).toHaveLength(2)
  expect(document.body.textContent).not.toContain('不限=全部客户')
})
