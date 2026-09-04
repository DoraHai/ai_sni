<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { changePassword } from '../../api/auth'
import { session } from '../../store/session'
import { GEO_WORKBENCH_NAV } from '../../utils/geoPrototypeNavigation'

const route = useRoute()
const router = useRouter()
const mobileOpen = ref(false)
const expandedGroups = ref({
  [GEO_WORKBENCH_NAV[0]?.label]: true,
})
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
const isActive = (item) => route.path === item.path || route.path.startsWith(`${item.path}/`)
const isGroupExpanded = (group) => Boolean(expandedGroups.value[group.label])

function toggleGroup(label) {
  expandedGroups.value = {
    ...expandedGroups.value,
    [label]: !expandedGroups.value[label],
  }
}

function go(path) {
  mobileOpen.value = false
  router.push(path)
}

function onTenantChange(event) {
  const id = Number(event.target.value)
  if (!id || id === session.tenantId) return
  session.setTenant(id)
  if (route.path.startsWith('/geo/tasks/')) router.push('/geo/tasks')
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
  <div class="geo-shell">
    <button class="geo-mobile-toggle" type="button" aria-label="打开 GEO 导航" @click="mobileOpen = true">☰</button>
    <div v-if="mobileOpen" class="geo-mobile-mask" @click="mobileOpen = false" />
    <aside class="geo-shell-side" :class="{ 'is-open': mobileOpen }">
      <div class="geo-shell-brand">
        <span class="geo-shell-logo">G</span>
        <span class="geo-shell-brand-copy"><b>GEO 工作台</b><small>生成式引擎获客</small></span>
        <button class="geo-mobile-close" type="button" aria-label="关闭 GEO 导航" @click="mobileOpen = false">×</button>
      </div>
      <nav class="geo-shell-nav">
        <section v-for="(group, groupIndex) in GEO_WORKBENCH_NAV" :key="group.label" class="geo-nav-group">
          <button
            type="button"
            class="geo-nav-group-toggle"
            :aria-expanded="isGroupExpanded(group)"
            :aria-controls="`geo-nav-group-${groupIndex}`"
            @click="toggleGroup(group.label)"
          >
            <span>{{ group.label }}</span>
            <span class="geo-nav-group-chevron" aria-hidden="true">⌄</span>
          </button>
          <Transition name="geo-nav-section">
            <div
              v-show="isGroupExpanded(group)"
              :id="`geo-nav-group-${groupIndex}`"
              class="geo-nav-group-items"
            >
              <button
                v-for="item in group.children"
                :key="item.path"
                type="button"
                class="geo-shell-nav-item"
                :class="{ active: isActive(item) }"
                @click="go(item.path)"
              >
                <span class="geo-shell-item-icon">{{ item.icon }}</span>
                <span>{{ item.label }}</span>
              </button>
            </div>
          </Transition>
        </section>
      </nav>
      <div class="geo-shell-links">
        <a href="/monitor/dashboard"><span>SEM</span>搜索广告工作台</a>
        <a href="/seo/dashboard"><span>SEO</span>SEO 内容工作台</a>
        <a href="/diagnostic-center/"><span>DX</span>诊断中心</a>
        <a class="portal-link" href="/deal-sniper/portal">← 返回平台门户</a>
      </div>
    </aside>
    <main class="geo-shell-main">
      <header class="geo-accountbar">
        <div class="geo-accountbar-context">
          <span>GEO 增长</span>
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
      <div class="geo-shell-content"><router-view /></div>
    </main>
  </div>
</template>

<style src="../../styles/geo-page.css"></style>
<style src="../../styles/geo-v2.css"></style>
<style src="../../styles/geo-dashboard.css"></style>
<style scoped>
.geo-shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 216px minmax(0, 1fr);
  background: #f6f7fb;
  color: #172033;
}
.geo-shell-side {
  position: sticky;
  top: 0;
  z-index: 30;
  height: 100vh;
  display: flex;
  flex-direction: column;
  padding: 16px 8px 0;
  background: #fff;
  border-right: 1px solid #e8eaf0;
}
.geo-shell-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 8px 14px;
}
.geo-shell-logo {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  flex: none;
  border-radius: 7px;
  color: #fff;
  font-size: 13px;
  font-weight: 750;
  background: linear-gradient(135deg, #7c3aed, #6d28d9);
}
.geo-shell-brand-copy b,
.geo-shell-brand-copy small {
  display: block;
}
.geo-shell-brand-copy b {
  color: #172033;
  font-size: 15px;
  line-height: 1.2;
}
.geo-shell-brand-copy small {
  margin-top: 1px;
  color: #8a94a6;
  font-size: 10.5px;
}
.geo-shell-nav {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 0 0 8px;
}
.geo-nav-group + .geo-nav-group { margin-top: 3px; }
.geo-nav-group-toggle {
  width: 100%;
  min-height: 30px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 0;
  padding: 9px 10px 6px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: #9aa1ad;
  font: inherit;
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: .06em;
  text-align: left;
  cursor: pointer;
}
.geo-nav-group-toggle:hover {
  background: #faf8ff;
  color: #776982;
}
.geo-nav-group-chevron {
  display: inline-grid;
  place-items: center;
  color: #b1a8bb;
  font-size: 15px;
  line-height: 1;
  transform: rotate(-90deg);
  transition: transform .18s ease, color .18s ease;
}
.geo-nav-group-toggle[aria-expanded="true"] .geo-nav-group-chevron {
  color: #7c3aed;
  transform: rotate(0deg);
}
.geo-nav-group-items { overflow: hidden; }
.geo-nav-section-enter-active,
.geo-nav-section-leave-active {
  transition: opacity .16s ease, transform .16s ease;
  transform-origin: top;
}
.geo-nav-section-enter-from,
.geo-nav-section-leave-to {
  opacity: 0;
  transform: translateY(-3px);
}
.geo-shell-nav-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  padding: 7px 8px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: #5b6270;
  font: inherit;
  font-size: 13px;
  font-weight: 500;
  line-height: 1.3;
  text-align: left;
  cursor: pointer;
  white-space: nowrap;
}
.geo-shell-nav-item:hover,
.geo-shell-nav-item.active {
  background: #f5f0ff;
  color: #7c3aed;
  font-weight: 600;
}
.geo-shell-item-icon {
  width: 18px;
  height: 18px;
  display: grid;
  place-items: center;
  flex: none;
  font-size: 13px;
}
.geo-shell-links {
  padding: 8px 2px;
  border-top: 1px solid #e8eaf0;
}
.geo-shell-links a {
  min-height: 32px;
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 6px 8px;
  border-radius: 8px;
  color: #6b7280;
  font-size: 12px;
  text-decoration: none;
}
.geo-shell-links a span:first-child {
  width: 24px;
  color: #8b95a5;
  font-size: 10px;
  font-weight: 700;
}
.geo-shell-links a:hover {
  background: #f5f0ff;
  color: #7c3aed;
}
.geo-shell-links .portal-link {
  margin-top: 4px;
  border-top: 1px solid #e8eaf0;
  border-radius: 0;
}
.geo-shell-main,
.geo-shell-content {
  min-width: 0;
  min-height: 100vh;
}
.geo-shell-main {
  display: flex;
  flex-direction: column;
}
.geo-accountbar {
  position: sticky;
  top: 0;
  z-index: 18;
  min-height: 68px;
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 10px 24px;
  border-bottom: 1px solid #e7e9f0;
  background: rgba(255, 255, 255, .94);
  box-shadow: 0 1px 0 rgba(15, 23, 42, .02);
  backdrop-filter: blur(14px);
}
.geo-accountbar-context {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 9px;
  color: #9aa1ad;
  font-size: 12px;
  white-space: nowrap;
}
.geo-accountbar-context b { color: #d5d8e0; font-weight: 500; }
.geo-accountbar-context strong {
  overflow: hidden;
  color: #3f4654;
  font-size: 13px;
  font-weight: 650;
  text-overflow: ellipsis;
}
.geo-accountbar-controls {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 10px;
}
.geo-tenant-switcher {
  height: 42px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 8px 0 13px;
  border: 1px solid #e1e4ec;
  border-radius: 11px;
  background: #fff;
  color: #8a92a3;
  font-size: 11px;
  white-space: nowrap;
}
.geo-tenant-switcher select {
  min-width: 136px;
  max-width: 210px;
  padding: 7px 28px 7px 8px;
  border: 0;
  outline: 0;
  background: transparent;
  color: #443453;
  font: inherit;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}
.geo-tenant-switcher strong { color: #6b7280; font-size: 12px; }
.geo-module-state {
  height: 34px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 0 11px;
  border: 1px solid #d9eee2;
  border-radius: 999px;
  background: #f4fbf7;
  color: #25815a;
  font-size: 11px;
  font-weight: 650;
  white-space: nowrap;
}
.geo-module-state i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #35b979;
  box-shadow: 0 0 0 4px rgba(53, 185, 121, .12);
}
.geo-module-state.is-empty {
  border-color: #e5e7eb;
  background: #f8f9fb;
  color: #7c8493;
}
.geo-module-state.is-empty i {
  background: #a8afbb;
  box-shadow: 0 0 0 4px rgba(168, 175, 187, .12);
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
.geo-account-state-copy small { display: block; max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.geo-account-state-copy strong { color: #353b48; font-size: 12px; font-weight: 700; }
.geo-account-state-copy small { margin-top: 2px; color: #98a0af; font-size: 9.5px; }
.geo-account-avatar {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 10px;
  background: linear-gradient(135deg, #8b5cf6, #6d28d9);
  box-shadow: 0 5px 14px rgba(109, 40, 217, .2);
  color: #fff;
  font-size: 11px;
  font-weight: 750;
  cursor: pointer;
}
.geo-shell-content {
  flex: 1;
  padding: 0;
}
.geo-mobile-toggle,
.geo-mobile-close {
  display: none;
}
@media (max-width: 900px) {
  .geo-shell {
    display: block;
  }
  .geo-shell-side {
    position: fixed;
    left: 0;
    top: 0;
    width: min(86vw, 260px);
    transform: translateX(-102%);
    transition: transform .2s ease;
    box-shadow: 16px 0 40px rgba(15, 23, 42, .18);
  }
  .geo-shell-side.is-open {
    transform: translateX(0);
  }
  .geo-mobile-mask {
    position: fixed;
    inset: 0;
    z-index: 20;
    background: rgba(15, 23, 42, .38);
  }
  .geo-mobile-toggle {
    position: fixed;
    left: 12px;
    top: 12px;
    z-index: 15;
    width: 36px;
    height: 36px;
    display: grid;
    place-items: center;
    border: 1px solid #e3e8f0;
    border-radius: 9px;
    background: #fff;
    color: #475467;
    font-size: 18px;
  }
  .geo-mobile-close {
    display: block;
    margin-left: auto;
    border: 0;
    background: transparent;
    color: #667085;
    font-size: 24px;
  }
  .geo-accountbar {
    min-height: 64px;
    padding: 10px 12px 10px 58px;
  }
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
