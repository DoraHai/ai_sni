import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { reactive } from 'vue'
import ElementPlus, { ElSelect, ElDialog, ElMessageBox } from 'element-plus'
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
const routeState = vi.hoisted(() => ({ current: null }))
vi.mock('vue-router', () => ({ useRoute: () => routeState.current, useRouter: () => ({ push: vi.fn() }) }))
let wrapper
const click = async text => {
  const b = [...document.querySelectorAll('button')].find(b => b.textContent.trim() === text)
  expect(b, text).toBeTruthy(); b.click(); await flushPromises()
}
const select = async (index, value) => { wrapper.findAllComponents(ElSelect)[index].vm.$emit('update:modelValue', value); await flushPromises() }
beforeEach(async () => {
  vi.restoreAllMocks()
  vi.clearAllMocks()
  vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm')
  routeState.current = reactive({ path: '/platform/accounts' })
  wrapper = mount(Accounts, { attachTo: document.body, global: { plugins: [ElementPlus] } })
  await flushPromises()
})
afterEach(() => { if (wrapper.exists()) wrapper.unmount(); document.body.innerHTML = '' })

it('immediately reflects repeated disable/enable/disable writes while each fresh list is pending', async () => {
  for (const [action, isActive] of [['停用', false], ['启用', true], ['停用', false]]) {
    let release
    fetchUsers.mockImplementationOnce(() => new Promise(resolve => { release = resolve }))
    await click(action)
    expect(updateUser).toHaveBeenLastCalledWith(9, { is_active: isActive })
    expect(wrapper.find('.status-pill').text()).toBe(isActive ? '启用中' : '已停用')
    const button = wrapper.findAll('button').find(b => b.text() === (isActive ? '停用' : '启用'))
    expect(button.attributes('disabled')).toBeDefined()
    release({ users: [{ ...fixtures.users[0], is_active: isActive }], tenant_options: fixtures.tenants })
    await flushPromises()
    expect(wrapper.find('.status-pill').text()).toBe(isActive ? '启用中' : '已停用')
  }
  expect(fetchUsers).toHaveBeenCalledTimes(4)
})

it('discards an older list that resolves after the latest status write and refresh', async () => {
  fetchUsers.mockRejectedValueOnce(Error('列表暂时不可用'))
  await click('停用')
  expect(wrapper.find('.status-pill').text()).toBe('已停用')
  let releaseOld
  fetchUsers.mockImplementationOnce(() => new Promise(resolve => { releaseOld = resolve }))
  await click('重试')
  fetchUsers.mockResolvedValueOnce({ users: [{ ...fixtures.users[0], is_active: true }], tenant_options: fixtures.tenants })
  await click('启用')
  expect(wrapper.find('.status-pill').text()).toBe('启用中')
  releaseOld({ users: [{ ...fixtures.users[0], is_active: false }], tenant_options: fixtures.tenants })
  await flushPromises()
  expect(wrapper.find('.status-pill').text()).toBe('启用中')
})

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

it.each(['/settings/accounts', '/settings/users', '/sem/accounts', '/platform-other/accounts'])(
  'keeps legacy single-client UI and payload when reused outside platform: %s', async path => {
    routeState.current.path = path
    await flushPromises()
    expect(wrapper.text()).not.toContain('（默认：')
    expect(wrapper.text()).not.toContain('顾问只能看到勾选的客户')
    await click('编辑')
    expect(wrapper.findAllComponents(ElSelect)).toHaveLength(2)
    expect(wrapper.findAllComponents(ElSelect).some(s => s.props('multiple'))).toBe(false)
    expect(document.body.textContent).not.toContain('默认客户')
    expect(document.body.textContent).not.toContain('至少勾选 1 个客户')
    await click('保存')
    expect(updateUser).toHaveBeenCalledWith(9, expect.objectContaining({ tenant_id: 1, clear_tenant: false }))
    const patch = updateUser.mock.calls[0][1]
    for (const key of ['tenant_ids', 'default_tenant_id', 'expected_grants_version']) expect(patch[key]).toBeUndefined()
    await click('新建账号')
    await select(0, 2)
    expect(wrapper.findAllComponents(ElSelect)).toHaveLength(2)
    expect(document.body.textContent).not.toContain('默认客户')
  },
)

it.each(['ADVISOR_GRANTS_CONFLICT', 'ADVISOR_GRANTS_VERSION_REQUIRED', 'ADVISOR_MULTI_TENANT_DISABLED'])(
  'does not expose new grant-specific error UI outside platform: %s', async code => {
    routeState.current.path = '/settings/accounts'
    await flushPromises()
    await click('编辑')
    updateUser.mockRejectedValueOnce(Object.assign(Error('backend detail'), { code, status: 409 }))
    await click('保存')
    expect(fetchUsers).toHaveBeenCalledTimes(1)
    expect(document.body.textContent).toContain('账号保存失败，请稍后重试')
    expect(document.body.textContent).not.toContain('客户授权版本')
    expect(document.body.textContent).not.toContain('客户已被别人修改')
    expect(document.body.textContent).not.toContain('顾问多客户功能尚未开放')
  },
)

it('closes the platform grant form when route context changes during a save', async () => {
  await click('编辑')
  let rejectSave
  updateUser.mockImplementationOnce(() => new Promise((_, reject) => { rejectSave = reject }))
  const saving = click('保存')
  await flushPromises()
  routeState.current.path = '/settings/accounts'
  await flushPromises()
  rejectSave(Object.assign(Error('stale'), { code: 'ADVISOR_GRANTS_CONFLICT', status: 409 }))
  await saving
  await flushPromises()
  expect(wrapper.findAllComponents(ElDialog)[0].props('modelValue')).toBe(false)
  expect(fetchUsers).toHaveBeenCalledTimes(1)
  expect(document.body.textContent).not.toContain('已重新加载，请核对后再保存')
})

it('discards a conflict reload after the account page unmounts', async () => {
  await click('编辑')
  let finishReload
  fetchUsers.mockImplementationOnce(() => new Promise(resolve => { finishReload = resolve }))
  updateUser.mockRejectedValueOnce(Object.assign(Error('stale'), { code: 'ADVISOR_GRANTS_CONFLICT', status: 409 }))
  await click('保存')
  expect(fetchUsers).toHaveBeenCalledTimes(2)
  wrapper.unmount()
  finishReload({ users: fixtures.users, tenant_options: fixtures.tenants })
  await flushPromises()
  expect(document.body.textContent).not.toContain('已重新加载，请核对后再保存')
})

it('lists added and removed clients and cancels without updating grants', async () => {
  await click('编辑')
  expect(document.body.textContent).toContain('历史记录保留（#803）')
  await select(1, [2, 3])
  ElMessageBox.confirm.mockRejectedValueOnce('cancel')
  await click('保存')
  expect(ElMessageBox.confirm).toHaveBeenCalledWith(expect.stringContaining('新增客户：客户丙；移除客户：客户甲'), '确认顾问客户绑定', expect.any(Object))
  expect(updateUser).not.toHaveBeenCalled()
  expect(wrapper.findAllComponents(ElDialog)[0].props('modelValue')).toBe(true)
  await click('保存')
  expect(updateUser).toHaveBeenCalledWith(9, expect.objectContaining({tenant_ids:[2,3], default_tenant_id:2}))
})
