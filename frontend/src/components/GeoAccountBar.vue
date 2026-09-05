<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { changePassword } from '../api/auth'
import { session } from '../store/session'

const route = useRoute()
const router = useRouter()

const tenantName = computed(() => {
  const tenant = session.tenants.find((item) => item.id === session.tenantId)
  if (tenant?.name) return tenant.name
  if (session.tenantId) return `客户 #${session.tenantId}`
  return '未选择客户'
})
const hasGeoTenant = computed(() => (
  session.tenants.some((item) => item.id === session.tenantId)
))
const accountName = computed(() => (
  session.user?.display_name || session.user?.username || '本地运维'
))
const accountMeta = computed(() => {
  const username = session.user?.username
  const role = session.user?.role_label || 'GEO 用户'
  return username && username !== accountName.value ? `${username} · ${role}` : role
})
const initials = computed(() => Array.from(String(accountName.value)).slice(0, 2).join(''))
const pageTitle = computed(() => route.meta.title || 'GEO 工作台')

function onTenantChange(event) {
  const id = Number(event.target.value)
  if (!id || id === session.tenantId) return
  session.setTenant(id)
  if (route.path.startsWith('/geo/tasks/')) router.push('/geo/tasks')
  else if (route.path.startsWith('/geo/businesses/')) router.push('/geo/brand')
}

async function onUserCommand(cmd) {
  if (cmd === 'logout') {
    session.logout()
    router.push('/login')
    return
  }
  if (cmd !== 'password') return
  let oldP
  let newP
  try {
    ;({ value: oldP } = await ElMessageBox.prompt('请输入原密码', '修改密码', { inputType: 'password' }))
    ;({ value: newP } = await ElMessageBox.prompt('请输入新密码（至少 8 位）', '修改密码', {
      inputType: 'password',
      inputPattern: /^.{8,}$/,
      inputErrorMessage: '至少 8 位',
    }))
  } catch {
    return
  }
  try {
    await changePassword({ oldPassword: oldP, newPassword: newP })
    ElMessage.success('密码已修改')
  } catch (e) {
    ElMessage.error(e.message)
  }
}
</script>

<template>
  <header class="geo-accountbar">
    <div class="geo-accountbar-context">
      <span>GEO 增长工作流</span>
      <b>/</b>
      <strong>{{ pageTitle }}</strong>
    </div>
    <div class="geo-accountbar-controls">
      <label class="geo-tenant-switcher">
        <span>当前客户</span>
        <select
          :value="session.tenantId || ''"
          aria-label="切换客户"
          @change="onTenantChange"
        >
          <option value="" disabled>{{ session.tenants.length ? tenantName : '选择客户' }}</option>
          <option v-for="tenant in session.tenants" :key="tenant.id" :value="tenant.id">{{ tenant.name }}</option>
        </select>
      </label>
      <div
        class="geo-module-state"
        :class="{ 'is-empty': !hasGeoTenant }"
        title="仅展示已开通且在有效期内的 GEO 客户"
      >
        <i />
        <span>{{ hasGeoTenant ? 'GEO 已开通' : '待选择 GEO 客户' }}</span>
      </div>
      <div class="geo-account-state">
        <span class="geo-account-state-label">登录账号</span>
        <span class="geo-account-state-copy">
          <strong>{{ accountName }}</strong>
          <small>{{ accountMeta }}</small>
        </span>
      </div>
      <el-dropdown v-if="session.isLoggedIn" trigger="click" @command="onUserCommand">
        <button type="button" class="geo-account-avatar" :title="accountName">{{ initials }}</button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="password">修改密码</el-dropdown-item>
            <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
      <div v-else class="geo-account-avatar" title="本地 Key">{{ initials }}</div>
    </div>
  </header>
</template>

<style scoped>
.geo-accountbar {
  position: sticky;
  top: 0;
  z-index: 18;
  min-height: 60px;
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 8px 24px;
  border-bottom: 1px solid #e7e9f0;
  background: rgba(255, 255, 255, .96);
  box-shadow: 0 1px 0 rgba(15, 23, 42, .02);
  backdrop-filter: blur(14px);
}
.geo-accountbar-context {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 9px;
  color: #969daa;
  font-size: 12px;
  white-space: nowrap;
}
.geo-accountbar-context b { color: #d5d8e0; font-weight: 500; }
.geo-accountbar-context strong {
  overflow: hidden;
  color: #303645;
  font-size: 13px;
  font-weight: 700;
  text-overflow: ellipsis;
}
.geo-accountbar-controls {
  min-width: 0;
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 10px;
}
.geo-tenant-switcher {
  height: 38px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 7px 0 12px;
  border: 1px solid #dddfe7;
  border-radius: 10px;
  background: #fff;
  color: #8a92a3;
  font-size: 11px;
  white-space: nowrap;
}
.geo-tenant-switcher:focus-within {
  border-color: #b99be8;
  box-shadow: 0 0 0 3px rgba(124, 58, 237, .08);
}
.geo-tenant-switcher select {
  min-width: 132px;
  max-width: 210px;
  padding: 6px 26px 6px 6px;
  border: 0;
  outline: 0;
  background: transparent;
  color: #443453;
  font: inherit;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}
.geo-module-state {
  height: 30px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 0 10px;
  border: 1px solid #d9eee2;
  border-radius: 999px;
  background: #f4fbf7;
  color: #25815a;
  font-size: 11px;
  font-weight: 650;
  white-space: nowrap;
}
.geo-module-state i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #35b979;
  box-shadow: 0 0 0 3px rgba(53, 185, 121, .12);
}
.geo-module-state.is-empty {
  border-color: #e5e7eb;
  background: #f8f9fb;
  color: #7c8493;
}
.geo-module-state.is-empty i {
  background: #a8afbb;
  box-shadow: 0 0 0 3px rgba(168, 175, 187, .12);
}
.geo-account-state {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 9px;
  padding-left: 12px;
  border-left: 1px solid #e5e7ed;
}
.geo-account-state-label { color: #9aa1ad; font-size: 10.5px; white-space: nowrap; }
.geo-account-state-copy { min-width: 0; }
.geo-account-state-copy strong,
.geo-account-state-copy small {
  display: block;
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.geo-account-state-copy strong { color: #353b48; font-size: 12px; font-weight: 700; }
.geo-account-state-copy small { margin-top: 1px; color: #98a0af; font-size: 9.5px; }
.geo-account-avatar {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 50%;
  background: #7c3aed;
  box-shadow: 0 5px 14px rgba(109, 40, 217, .18);
  color: #fff;
  font-size: 10px;
  font-weight: 750;
  cursor: pointer;
}
@media (max-width: 900px) {
  .geo-accountbar { min-height: 60px; padding: 8px 12px 8px 58px; }
  .geo-accountbar-context,
  .geo-module-state,
  .geo-account-state { display: none; }
  .geo-accountbar-controls { width: 100%; }
  .geo-tenant-switcher { min-width: 0; flex: 1; }
  .geo-tenant-switcher select { min-width: 0; width: 100%; }
}
@media (max-width: 560px) {
  .geo-tenant-switcher > span { display: none; }
}
</style>
