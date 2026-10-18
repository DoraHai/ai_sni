<script setup>
import { roleDescription } from '../../../../integrations/workbench/role-description.mjs'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { advisorTenantLabel, advisorTenantPatch, isAdvisorRole } from './advisorTenants.mjs'
import { advisorMessages } from '../../store/advisorTenant.js'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { createUser, deleteUser, fetchUsers, resetUserPassword, updateUser } from '../../api/auth'
import { createRole, deleteRole, fetchRoles, updateRole } from '../../api/roles'
import { session } from '../../store/session'
import { formatUtcTimestamp } from '../../utils/dateTime'

const route = useRoute()
const router = useRouter()
// The same build serves SEM and platform pages. Grant management belongs only
// to the platform path, even if this component is reused by a legacy SEM route.
const platformContext = computed(() => /^\/platform(?:\/|$)/.test(route.path))
const tab = computed({
  get: () => (route.path.endsWith('/roles') ? 'roles' : 'accounts'),
  set: (value) => router.push(`/platform/${value}`),
})
const loading = ref(false)
const error = ref('')
const usersData = ref(null)
const rolesData = ref(null)
const tenantOptions = ref([])
const permissionDenied = computed(() => error.value?.code === 'PERMISSION_DENIED')

const LEVELS = [
  { v: '', l: '无' },
  { v: 'view', l: '可见' },
  { v: 'edit', l: '可编辑' },
]
const ADMIN_ROLE = '管理员'

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [users, roles] = await Promise.all([
      fetchUsers(),
      fetchRoles(),
    ])
    usersData.value = users
    rolesData.value = roles
    tenantOptions.value = users.tenant_options || []
    return users
  } catch (e) {
    error.value = e
  } finally {
    loading.value = false
  }
}

const roleOptions = computed(() => rolesData.value?.roles || [])
const menus = computed(() => rolesData.value?.menus || [])
const menuGroups = computed(() => {
  const g = {}
  for (const m of menus.value) (g[m.group] ||= []).push(m)
  return Object.entries(g).map(([group, items]) => ({ group, items }))
})
const fmtTime = (v) => formatUtcTimestamp(v, { fallback: '从未登录' })

// ===== 账号 =====
const userDialog = ref(false)
const savingUser = ref(false)
const editingUserId = ref(null)
const editingGrantsVersion = ref(null)
let userFormRevision = 0
const multiTenantDisabled = ref(false)
const editingAdvisor = ref(null)
const userOriginalRoleId = ref(null)
const userFormError = ref('')
const uform = reactive({ username: '', password: '', displayName: '', roleId: null, tenantId: null, tenantIds: [], defaultTenantId: null })
const userIsAdvisor = computed(() => platformContext.value && (userOriginalRoleId.value === uform.roleId && editingAdvisor.value !== null
  ? editingAdvisor.value : isAdvisorRole(roleOptions.value.find(r => r.id === uform.roleId))))
const multiAdvisor = computed(() => userIsAdvisor.value && !multiTenantDisabled.value)
const rowIsAdvisor = row => typeof row.is_advisor === 'boolean' ? row.is_advisor : isAdvisorRole(roleOptions.value.find(r => r.id === row.role_id))
watch(platformContext, () => {
  userFormRevision++
  userDialog.value = false
  userFormError.value = ''
  editingGrantsVersion.value = null
  multiTenantDisabled.value = false
})
watch(() => uform.tenantIds.slice(), ids => {
  if (!ids.includes(uform.defaultTenantId)) uform.defaultTenantId = ids[0] ?? null
})

function openCreateUser() {
  userFormRevision++
  editingUserId.value = null
  editingGrantsVersion.value = null
  editingAdvisor.value = null
  userOriginalRoleId.value = null
  userFormError.value = ''
  Object.assign(uform, { username: '', password: '', displayName: '', roleId: roleOptions.value[0]?.id ?? null, tenantId: null, tenantIds: [], defaultTenantId: null })
  userDialog.value = true
}
function openEditUser(row) {
  userFormRevision++
  editingUserId.value = row.id
  editingGrantsVersion.value = row.grants_version ?? null
  editingAdvisor.value = typeof row.is_advisor === 'boolean' ? row.is_advisor : null
  userOriginalRoleId.value = row.role_id
  userFormError.value = ''
  Object.assign(uform, { username: row.username, password: '', displayName: row.display_name, roleId: row.role_id, tenantId: row.tenant_id,
    tenantIds: [...(row.tenant_ids || [])], defaultTenantId: row.default_tenant_id ?? null })
  userDialog.value = true
}

async function submitUser() {
  if (savingUser.value) return
  if (!editingUserId.value && (!uform.username || uform.password.length < 8)) {
    ElMessage.warning('用户名必填，密码至少 8 位')
    return
  }
  if (!uform.roleId) { ElMessage.warning('请选择角色'); return }
  let scope
  userFormError.value = ''
  try {
    if (multiAdvisor.value) {
      scope = advisorTenantPatch(uform.tenantIds, uform.defaultTenantId)
      if (editingUserId.value) scope.expected_grants_version = editingGrantsVersion.value
    }
    else {
      if (userIsAdvisor.value && !uform.tenantId) throw Error('至少勾选 1 个客户')
      scope = { tenant_id: uform.tenantId ?? undefined, ...(!userIsAdvisor.value ? { clear_tenant: uform.tenantId == null } : {}) }
    }
  } catch (e) { userFormError.value = e.message; return }
  savingUser.value = true
  const submittedUserId = editingUserId.value
  const submittedRevision = userFormRevision
  try {
    if (editingUserId.value) {
      await updateUser(editingUserId.value, {
        role_id: uform.roleId,
        display_name: uform.displayName || undefined,
        ...scope,
      })
      ElMessage.success('账号已更新')
    } else {
      await createUser({ ...uform, ...scope })
      ElMessage.success(`账号「${uform.username}」已创建`)
    }
    if (submittedRevision === userFormRevision) userDialog.value = false
    load()
  } catch (e) {
    if (submittedRevision !== userFormRevision || !userDialog.value) return
    if (platformContext.value && (['ADVISOR_GRANTS_CONFLICT', 'ADVISOR_GRANTS_VERSION_REQUIRED'].includes(e.code)
        || [409, 428].includes(e.status))) {
      const message = advisorMessages[e.code] || advisorMessages.ADVISOR_GRANTS_CONFLICT
      // Discard the stale form/version. Reload before another explicit save.
      editingGrantsVersion.value = null
      const users = await load()
      if (submittedRevision !== userFormRevision || !userDialog.value) return
      const fresh = users?.users?.find(row => row.id === submittedUserId)
      if (fresh) {
        openEditUser(fresh)
        userFormError.value = `${message}；已重新加载，请核对后再保存`
      } else {
        userDialog.value = false
      }
      ElMessage.error(fresh ? userFormError.value : `${message}；重新加载失败，请刷新页面`)
      return
    }
    if (platformContext.value && e.code === 'ADVISOR_MULTI_TENANT_DISABLED') multiTenantDisabled.value = true
    userFormError.value = platformContext.value ? advisorMessages[e.code] || e.message
      : e.code?.startsWith('ADVISOR_') ? '账号保存失败，请稍后重试' : e.message
    ElMessage.error(userFormError.value)
  } finally {
    savingUser.value = false
  }
}

async function resetPassword(row) {
  let value = ''
  try {
    const result = await ElMessageBox.prompt(
      `为账号“${row.username}”设置新密码。现有密码不会显示或恢复。`,
      '重置密码',
      {
        inputType: 'password',
        inputPattern: /^.{8,100}$/,
        inputErrorMessage: '密码长度需为 8–100 位',
        confirmButtonText: '确认重置',
      },
    )
    value = result.value
    await ElMessageBox.confirm(
      `确认重置“${row.username}”的密码？本阶段不会自动注销该账号已有会话。`,
      '确认重置密码',
      { type: 'warning' },
    )
  } catch { return }
  try {
    await resetUserPassword(row.id, value)
    ElMessage.success('密码已重置；系统不会回显新密码')
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function toggleActive(row) {
  const action = row.is_active ? '停用' : '启用'
  try {
    await ElMessageBox.confirm(`确认${action}账号「${row.username}」？`, action + '账号', { type: 'warning' })
  } catch { return }
  try {
    await updateUser(row.id, { is_active: !row.is_active })
    ElMessage.success(`已${action}`)
    load()
  } catch (e) { ElMessage.error(e.message) }
}

async function removeUser(row) {
  try {
    await ElMessageBox.confirm(`确认删除账号「${row.username}」？账号将停用，历史记录会保留。`, '删除账号', { type: 'warning' })
  } catch { return }
  try {
    await deleteUser(row.id)
    ElMessage.success('账号已删除（停用）')
    await load()
  } catch (e) { ElMessage.error(e.message || '删除账号失败') }
}

// ===== 角色 =====
const roleDialog = ref(false)
const savingRole = ref(false)
const editingRoleId = ref(null)
const rform = reactive({ name: '', description: '', isSystem: false, perms: {} })

function levelOptions(menuKey) {
  // 账号与权限只有「无 / 可编辑」（可见无意义：管理动作都是写）
  return menuKey === 'settings.accounts' ? [LEVELS[0], LEVELS[2]] : LEVELS
}
function cellDisabled(menuKey) {
  return rform.isSystem
    && rform.name === ADMIN_ROLE
    && ['settings.accounts', 'settings.customers'].includes(menuKey)
}

function openCreateRole() {
  editingRoleId.value = null
  rform.name = ''
  rform.description = ''
  rform.isSystem = false
  rform.perms = Object.fromEntries(menus.value.map((m) => [m.key, '']))
  roleDialog.value = true
}
function openEditRole(r) {
  editingRoleId.value = r.id
  rform.name = r.name
  rform.description = r.description || ''
  rform.isSystem = r.is_system
  rform.perms = Object.fromEntries(menus.value.map((m) => [m.key, r.permissions?.[m.key] || '']))
  roleDialog.value = true
}

async function submitRole() {
  if (!rform.name.trim()) { ElMessage.warning('角色名必填'); return }
  const permissions = {}
  for (const [k, v] of Object.entries(rform.perms)) if (v) permissions[k] = v
  if (rform.isSystem && rform.name === ADMIN_ROLE) {
    permissions['settings.accounts'] = 'edit'
    permissions['settings.customers'] = 'edit'
  }
  savingRole.value = true
  try {
    if (editingRoleId.value) {
      await updateRole(editingRoleId.value, {
        name: rform.isSystem ? undefined : rform.name.trim(),
        description: rform.description,
        permissions,
      })
      ElMessage.success('角色已更新')
    } else {
      await createRole({ name: rform.name.trim(), description: rform.description, permissions })
      ElMessage.success('角色已创建')
    }
    roleDialog.value = false
    load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    savingRole.value = false
  }
}

async function removeRole(r) {
  try {
    await ElMessageBox.confirm(`确认删除角色「${r.name}」？`, '删除角色', { type: 'warning' })
  } catch { return }
  try {
    await deleteRole(r.id)
    ElMessage.success('角色已删除')
    load()
  } catch (e) { ElMessage.error(e.message) }
}

function permSummary(r) {
  const e = Object.values(r.permissions || {}).filter((v) => v === 'edit').length
  const v = Object.values(r.permissions || {}).filter((v) => v === 'view').length
  return `${e} 可编辑 · ${v} 可见`
}

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <div class="page-header">
      <div>
        <div class="page-title">{{ tab === 'accounts' ? '账号' : '角色与权限' }}</div>
        <div class="page-desc">{{ platformContext ? '平台级账号和角色管理；顾问只能看到勾选的客户' : '平台级账号和角色管理；单客户绑定用于限制业务数据范围' }}</div>
      </div>
      <div class="page-actions">
        <el-button v-if="tab === 'accounts'" type="primary" @click="openCreateUser">新建账号</el-button>
        <el-button v-else type="primary" @click="openCreateRole">新建角色</el-button>
      </div>
    </div>

    <el-alert v-if="error" :title="permissionDenied ? '当前账号不能管理同事和角色' : error.message" :description="permissionDenied ? '需要 settings.accounts 的“可编辑”权限。请联系现有管理员调整角色；这不是数据为空。' : '请重试；若持续失败，请记录当前时间并联系管理员。'" type="error" :closable="false" show-icon style="margin-bottom: 14px"><template #default><el-button size="small" @click="load">重试</el-button></template></el-alert>

    <p class="platform-table-hint">表格可左右滑动，查看全部信息和操作。</p>
    <el-tabs v-model="tab">
      <!-- ===== 账号 ===== -->
      <el-tab-pane label="账号" name="accounts">
        <div class="table-panel">
          <el-table :data="usersData?.users || []" row-key="id">
            <el-table-column label="用户名" min-width="140">
              <template #default="{ row }">
                <b>{{ row.username }}</b>
                <span v-if="row.display_name !== row.username" class="sub"> · {{ row.display_name }}</span>
              </template>
            </el-table-column>
            <el-table-column label="角色" width="130">
              <template #default="{ row }"><span class="role-pill">{{ row.role_label }}</span></template>
            </el-table-column>
            <el-table-column label="可见客户" min-width="120">
              <template #default="{ row }">{{ platformContext ? advisorTenantLabel(row, tenantOptions, rowIsAdvisor(row)) : row.tenant_name || '全部客户' }}</template>
            </el-table-column>
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <span class="status-pill" :class="row.is_active ? 'on' : 'off'"><span class="status-dot" />{{ row.is_active ? '启用中' : '已停用' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="最近登录" width="140">
              <template #default="{ row }"><span class="sub">{{ fmtTime(row.last_login_at) }}</span></template>
            </el-table-column>
            <el-table-column label="操作" width="360">
              <template #default="{ row }">
                <el-button size="small" @click="openEditUser(row)">编辑</el-button>
                <el-button size="small" plain @click="resetPassword(row)">重置密码</el-button>
                <el-button
                  size="small" :type="row.is_active ? 'danger' : 'success'" plain
                  :disabled="row.id === session.user?.id"
                  @click="toggleActive(row)"
                >{{ row.is_active ? '停用' : '启用' }}</el-button>
                <el-button size="small" type="danger" plain :disabled="row.id === session.user?.id" @click="removeUser(row)">删除</el-button>
              </template>
            </el-table-column>
            <template #empty>
              <div class="empty-line">
                当前没有登录账号记录。新建账号时请按角色限定客户。
              </div>
            </template>
          </el-table>
        </div>
      </el-tab-pane>

      <!-- ===== 角色 ===== -->
      <el-tab-pane label="角色" name="roles">
        <div class="table-panel">
          <el-table :data="roleOptions" row-key="id">
            <el-table-column label="角色" min-width="140">
              <template #default="{ row }">
                <b>{{ row.name }}</b>
                <span v-if="row.is_system" class="sys-tag">内置</span>
              </template>
            </el-table-column>
            <el-table-column label="说明" min-width="200">
              <template #default="{ row }"><span class="sub">{{ roleDescription(row, menus) || '—' }}</span></template>
            </el-table-column>
            <el-table-column label="权限" width="150">
              <template #default="{ row }"><span class="sub">{{ permSummary(row) }}</span></template>
            </el-table-column>
            <el-table-column label="账号数" width="80" align="center">
              <template #default="{ row }">{{ row.user_count }}</template>
            </el-table-column>
            <el-table-column label="操作" width="170">
              <template #default="{ row }">
                <el-button size="small" @click="openEditRole(row)">配置权限</el-button>
                <el-button size="small" type="danger" plain :disabled="row.is_system || row.user_count > 0" @click="removeRole(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 账号 dialog -->
    <el-dialog class="platform-responsive-dialog" v-model="userDialog" :title="editingUserId ? '编辑账号' : '新建账号'" width="460px">
      <el-form label-width="84px">
        <el-form-item label="用户名" required>
          <el-input v-model="uform.username" :disabled="!!editingUserId" placeholder="登录用，2-50 字符" />
        </el-form-item>
        <el-form-item label="显示名">
          <el-input v-model="uform.displayName" placeholder="选填" />
        </el-form-item>
        <el-form-item v-if="!editingUserId" label="初始密码" required>
          <el-input v-model="uform.password" type="password" show-password :placeholder="editingUserId ? '留空=不改' : '至少 8 位'" />
        </el-form-item>
        <el-form-item label="角色" required>
          <el-select v-model="uform.roleId" placeholder="选择角色" style="width: 100%">
            <el-option v-for="r in roleOptions" :key="r.id" :label="r.name" :value="r.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="限定客户">
          <el-select v-if="multiAdvisor" v-model="uform.tenantIds" multiple placeholder="至少勾选 1 个客户" style="width: 100%" aria-label="限定客户">
            <el-option v-for="t in tenantOptions" :key="t.id" :label="t.name" :value="t.id" />
          </el-select>
          <el-select v-else v-model="uform.tenantId" :placeholder="userIsAdvisor ? '请选择客户' : '不限=全部客户（可顶栏切换）'" :clearable="!userIsAdvisor" style="width: 100%">
            <el-option v-for="t in tenantOptions" :key="t.id" :label="t.name" :value="t.id" />
          </el-select>
          <div v-if="userIsAdvisor" class="sub">顾问只能看到勾选的客户；至少勾选 1 个客户</div>
        </el-form-item>
        <el-form-item v-if="multiAdvisor" label="默认客户" required>
          <el-select v-model="uform.defaultTenantId" placeholder="从已勾选客户中选择" style="width: 100%" aria-label="默认客户">
            <el-option v-for="t in tenantOptions.filter(t => uform.tenantIds.includes(t.id))" :key="t.id" :label="t.name" :value="t.id" />
          </el-select>
        </el-form-item>
        <el-alert v-if="multiTenantDisabled && userIsAdvisor" title="顾问多客户功能尚未开放" type="info" :closable="false" />
        <el-alert v-if="userFormError" :title="userFormError" type="error" :closable="false" role="alert" />
      </el-form>
      <template #footer>
        <el-button @click="userDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingUser" @click="submitUser">{{ editingUserId ? '保存' : '创建' }}</el-button>
      </template>
    </el-dialog>

    <!-- 角色 dialog（权限矩阵） -->
    <el-dialog class="platform-responsive-dialog" v-model="roleDialog" :title="editingRoleId ? '配置角色权限' : '新建角色'" width="560px">
      <el-form label-width="72px">
        <el-form-item label="角色名" required>
          <el-input v-model="rform.name" :disabled="rform.isSystem" :placeholder="rform.isSystem ? '内置角色不可改名' : '如：投放专员'" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="rform.description" placeholder="选填" />
        </el-form-item>
      </el-form>
      <div class="matrix">
        <div class="matrix-head"><span>菜单权限</span><span class="mh-hint">每个菜单：无 / 可见 / 可编辑</span></div>
        <div v-for="g in menuGroups" :key="g.group" class="matrix-group">
          <div class="mg-title">{{ g.group }}</div>
          <div v-for="m in g.items" :key="m.key" class="matrix-row">
            <span class="mr-label">{{ m.label }}</span>
            <el-radio-group v-model="rform.perms[m.key]" size="small" :disabled="cellDisabled(m.key)">
              <el-radio-button v-for="o in levelOptions(m.key)" :key="o.v" :label="o.v">{{ o.l }}</el-radio-button>
            </el-radio-group>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="roleDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingRole" @click="submitRole">{{ editingRoleId ? '保存' : '创建' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-header { margin-bottom: 14px; display: flex; justify-content: space-between; align-items: flex-end; }
.page-title { font-size: 20px; font-weight: 600; color: var(--sem-text); }
.page-desc { font-size: 12px; color: var(--sem-text-sub); margin-top: 4px; }
.table-panel { background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; overflow: hidden; }
.sub { font-size: 12px; color: var(--sem-text-sub); }
.empty-line { font-size: 12px; color: var(--sem-text-sub); padding: 18px 0; }
.role-pill { font-size: 11px; padding: 2px 9px; border-radius: 10px; background: #eff4fb; color: #185fa5; }
.sys-tag { margin-left: 6px; font-size: 10px; padding: 1px 6px; border-radius: 4px; background: #fef1e1; color: #ba7517; }
.status-pill { font-size: 11px; padding: 2px 8px; border-radius: 10px; display: inline-flex; align-items: center; gap: 4px; }
.status-pill.on { background: #e5f4ed; color: var(--sem-success); }
.status-pill.off { background: #f3f4f6; color: var(--sem-text-sub); }
.status-dot { width: 5px; height: 5px; border-radius: 50%; background: currentColor; }

.matrix { border: 1px solid var(--sem-border); border-radius: 8px; padding: 4px 14px 12px; max-height: 360px; overflow-y: auto; }
.matrix-head { display: flex; justify-content: space-between; align-items: baseline; padding: 8px 0; position: sticky; top: 0; background: #fff; font-size: 13px; font-weight: 600; }
.mh-hint { font-size: 11px; font-weight: 400; color: #9ca3af; }
.matrix-group { margin-top: 6px; }
.mg-title { font-size: 11px; color: var(--sem-text-sub); margin: 6px 0 4px; }
.matrix-row { display: flex; justify-content: space-between; align-items: center; padding: 5px 0 5px 8px; }
.mr-label { font-size: 13px; color: var(--sem-text); }
</style>
