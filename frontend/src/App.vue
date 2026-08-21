<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { changePassword, fetchMe, fetchTenants } from './api/auth'
import { fetchAlerts } from './api/alerts'
import { fetchCandidates } from './api/expansion'
import { session } from './store/session'
import { redirectToLogin } from './auth/loginRedirect'
import { SEM_READ_ONLY_MESSAGE, SEM_WRITEBACK_ENABLED } from './constants/semCapabilities'

const route = useRoute()
const router = useRouter()
const currentTitle = computed(() => route.meta.title || '')
const currentWorkflow = computed(() => route.meta.workflow || '')
const bare = computed(() => route.meta.bare) // 门户、诊断等无框页面
const tenantPopoverOpen = ref(false)
const themeStorageKey = 'sem_console_theme'
const currentTheme = ref(localStorage.getItem(themeStorageKey) === 'dark' ? 'dark' : 'light')
const themeLabel = computed(() => (currentTheme.value === 'dark' ? '暗橘' : '亮橘'))
const nextThemeLabel = computed(() => (currentTheme.value === 'dark' ? '亮橘' : '暗橘'))
const consoleClasses = computed(() => [
  'app-console',
  'sem-console',
  currentTheme.value === 'dark' ? 'sem-theme-dark' : 'sem-theme-light',
])

const platformShortcuts = [
  { label: '全域驾驶舱', path: '/deal-sniper/hub/dashboard', icon: '⌂' },
  { label: '平台门户', path: '/deal-sniper/portal', icon: '←' },
]

// 侧边导航徽章（真数据）：异常提醒 open 数、拓词待处理数
const badges = reactive({ alerts: 0, expand: 0 })

async function loadBadges() {
  if (!session.tenantId) return
  const canCall = session.isLoggedIn || import.meta.env.VITE_API_KEY
  if (!canCall) return
  try {
    const [a, e] = await Promise.all([
      fetchAlerts({ tenantId: session.tenantId, status: 'open' }),
      fetchCandidates({ tenantId: session.tenantId, status: 'pending', page: 1, pageSize: 1 }),
    ])
    badges.alerts = a.total_open ?? 0
    badges.expand = e.status_counts?.pending ?? 0
  } catch { /* 徽章失败不打扰 */ }
}

// 侧边导航结构（按 v3.0 工作流）：真实可用功能前置，低频/设置后置。
// 本地无登录(dev API Key)时全显示。
const ALL_GROUPS = computed(() => [
  { label: '智能助手', icon: '✨', children: [
    { label: 'AI 助手', path: '/assistant', key: 'assistant' },
  ] },
  { label: '诊断中心', icon: '🩺', children: [
    { label: '网站体检', path: '/diagnostic-center/', key: 'geo.diagnosis', external: true },
  ] },
  { label: '首次接入', icon: '🚀', children: [
    { label: '授权与同步', path: '/onboarding', key: 'onboarding' },
    { label: '智能搭建', path: '/onboarding/builder', key: 'onboarding' },
  ] },
  { label: '每日盯盘', icon: '📊', badge: badges.alerts, badgeCls: '', children: [
    { label: '数据看板', path: '/monitor/dashboard', key: 'monitor.dashboard' },
    { label: '异常提醒', path: '/monitor/alerts', count: badges.alerts, key: 'monitor.alerts' },
    { label: '客户画像', path: '/monitor/profile', key: 'monitor.profile' },
  ] },
  { label: '优化建议', icon: '⚡', children: [
    { label: '拓词建议', path: '/optimize/expand', count: badges.expand, countLabel: '待审', key: 'optimize.expand', hint: '徽章表示待审拓词建议数量，不代表已执行动作' },
    { label: '关键词工作台', path: '/optimize/keywords', key: 'optimize.keywords' },
    { label: '搜索词报告', path: '/optimize/search-terms', key: 'optimize.searchterms' },
    { label: '否词管理', path: '/optimize/negatives', key: 'optimize.negatives' },
  ] },
  { label: '效果验证', icon: '🔍', children: [
    { label: '调价台账', path: '/verify/adjustments', key: 'verify.adjustments' },
    { label: '待验证调价', path: '/verify/pending', key: 'verify.pending' },
    { label: '线索管理', path: '/verify/leads', key: 'verify.leads' },
  ] },
  { label: '投放管理', icon: '🎯', children: [
    { label: '推广账号', path: '/sem/accounts', key: 'sem.assets' },
    { label: '账户与预算', path: '/manage/account', key: 'manage.account' },
    { label: '计划管理', path: '/manage/campaigns', key: 'manage.campaigns' },
    { label: 'oCPC 投放', path: '/manage/ocpc', key: 'manage.ocpc' },
  ] },
  { label: '客户交付', icon: '📨', children: [
    { label: '分析报告', path: '/delivery/report', key: 'delivery.report' },
  ] },
  { label: '系统设置', icon: '⚙', children: [
    { label: '账号与权限', path: '/settings/accounts', key: 'settings.accounts' },
    { label: '客户与模块', path: '/settings/customers', key: 'settings.customers' },
  ] },
])

const navGroups = computed(() => {
  const noLogin = !session.isLoggedIn // 本地 dev API Key 模式：全显示
  return ALL_GROUPS.value
    .map((g) => ({
      ...g,
      // 叶子项按可见权限过滤；下钻页面不出现在菜单配置中。
      children: g.children.filter((c) => noLogin || session.canView(c.key)),
    }))
    // 没有任何可见叶子的分组整组隐藏
    .filter((g) => g.children.some((c) => c.key && (noLogin || session.canView(c.key))))
})

// 展开状态：默认展开当前路由所在组
const openGroups = ref(new Set())
function groupOfPath(path) {
  for (const g of navGroups.value) {
    if (g.children?.some((c) => c.path && (c.path === '/' ? path === '/' : path.startsWith(c.path)))) return g.label
  }
  if (path.startsWith('/monitor/keywords')) return '每日盯盘'
  return null
}
function syncOpenToRoute() {
  const g = groupOfPath(route.path)
  if (g) openGroups.value = new Set([...openGroups.value, g])
}
function toggleGroup(label) {
  const next = new Set(openGroups.value)
  next.has(label) ? next.delete(label) : next.add(label)
  openGroups.value = next
}
const isActive = (c) => c.path && (
  route.path === c.path ||
  (c.path !== '/' && c.path !== '/onboarding' && route.path.startsWith(c.path + '/'))
)
const isCurrentGroup = (g) => groupOfPath(route.path) === g.label

function go(c) {
  if (!c.path || c.disabled) return
  if (c.external) {
    window.location.assign(c.path)
    return
  }
  router.push(c.path)
}

const tenantName = computed(
  () => session.tenants.find((t) => t.id === session.tenantId)?.name || '—',
)
const tenantCountLabel = computed(() => `${session.tenants.length} 客户`)

function tenantInitials(tenant) {
  const trimmed = String(tenant?.name || '').trim()
  if (!trimmed) return '—'
  const ascii = trimmed.match(/[A-Za-z]+/g)?.join('')
  if (ascii && /^[A-Za-z0-9_-]/.test(trimmed)) return ascii.slice(0, 2).toUpperCase()
  return Array.from(trimmed).slice(0, 2).join('')
}

function tenantTone(id) {
  const tones = ['blue', 'green', 'amber', 'violet', 'red']
  return tones[Math.abs(Number(id) || 0) % tones.length]
}

async function loadTenants() {
  if (!session.isLoggedIn) return
  try {
    const t = await fetchTenants()
    session.setTenants(t.tenants)
  } catch { /* 401 拦截器已处理 */ }
}

// 刷新当前用户（角色权限可能被管理员改过 → 侧边栏/按钮即时更新）
async function refreshMe() {
  if (!session.isLoggedIn) return
  try {
    const r = await fetchMe()
    session.refreshUser(r.user)
  } catch { /* 401 拦截器已处理 */ }
}

function onTenantChange(id) {
  session.setTenant(id)
  tenantPopoverOpen.value = false
  // 详情页归属上一个客户,切换后回看板
  if (route.path.startsWith('/monitor/keywords/')) router.push('/monitor/dashboard')
}

async function onUserCommand(cmd) {
  if (cmd === 'logout') {
    session.logout()
    redirectToLogin('/')
    return
  }
  if (cmd === 'password') {
    let oldP, newP
    try {
      ({ value: oldP } = await ElMessageBox.prompt('请输入原密码', '修改密码', { inputType: 'password' }));
      ({ value: newP } = await ElMessageBox.prompt('请输入新密码（至少 8 位）', '修改密码', {
        inputType: 'password', inputPattern: /^.{8,}$/, inputErrorMessage: '至少 8 位',
      }))
    } catch { return }
    try {
      await changePassword({ oldPassword: oldP, newPassword: newP })
      ElMessage.success('密码已修改')
    } catch (e) {
      ElMessage.error(e.message)
    }
  }
}

function toggleTheme() {
  currentTheme.value = currentTheme.value === 'dark' ? 'light' : 'dark'
  localStorage.setItem(themeStorageKey, currentTheme.value)
}

watch(() => session.isLoggedIn, (v) => { if (v) { loadTenants(); loadBadges() } })
watch(() => session.tenantId, loadBadges)
watch(() => route.path, syncOpenToRoute)
onMounted(() => { refreshMe(); loadTenants(); loadBadges(); syncOpenToRoute() })
</script>

<template>
  <router-view v-if="bare" />
  <el-container v-else :class="consoleClasses" style="height: 100vh">
    <el-aside width="220px" class="side">
      <div class="brand">
        <div class="brand-mark">
          <span class="brand-logo">S</span>
          <span>
            <div class="brand-name">SEM 智投平台</div>
            <div class="brand-sub">v3.0 · 工作流版</div>
          </span>
        </div>
      </div>
      <div class="nav-scroll">
        <div class="nav-section-title">代运营工作流</div>
        <div
          v-for="g in navGroups"
          :key="g.label"
          class="wf-group"
          :class="{ open: openGroups.has(g.label) }"
        >
          <div class="wf-trigger" :class="{ current: isCurrentGroup(g) }" @click="toggleGroup(g.label)">
            <span class="wf-icon">{{ g.icon }}</span>
            <span class="wf-name">{{ g.label }}</span>
            <span v-if="g.badge" class="wf-badge" :class="g.badgeCls">{{ g.badge > 99 ? '99+' : g.badge }}</span>
            <span class="wf-toggle">›</span>
          </div>
          <div class="wf-sub">
            <div
              v-for="c in g.children"
              :key="c.label"
              class="wf-sub-item"
              :class="{ active: isActive(c), disabled: c.disabled || !c.path }"
              :title="c.hint || ''"
              @click="go(c)"
            >
              <span class="wf-sub-dot" />{{ c.label }}
              <span v-if="c.count" class="wf-sub-num">{{ c.countLabel }} {{ c.count > 99 ? '99+' : c.count }}</span>
            </div>
          </div>
        </div>
      </div>
      <nav class="side-shortcuts" aria-label="跨模块快捷入口">
        <div class="shortcut-group shortcut-group-muted">
          <router-link
            v-for="item in platformShortcuts"
            :key="item.path"
            class="shortcut-link"
            :to="item.path"
          >
            <span class="shortcut-icon" aria-hidden="true">{{ item.icon }}</span>
            <span>{{ item.label }}</span>
          </router-link>
        </div>
      </nav>
    </el-aside>

    <el-container>
      <el-header class="topbar" height="48px">
        <el-breadcrumb separator="/">
          <el-breadcrumb-item>{{ currentWorkflow }}</el-breadcrumb-item>
          <el-breadcrumb-item>{{ currentTitle }}</el-breadcrumb-item>
        </el-breadcrumb>
        <div class="topbar-right">
          <button class="theme-toggle" type="button" @click="toggleTheme">
            <span class="theme-dot" aria-hidden="true"></span>
            {{ themeLabel }} · 切换{{ nextThemeLabel }}
          </button>
          <template v-if="session.isLoggedIn">
            <el-popover
              v-if="session.tenants.length > 1"
              v-model:visible="tenantPopoverOpen"
              placement="bottom-end"
              :width="286"
              trigger="click"
              popper-class="tenant-popover"
            >
              <template #reference>
                <button class="tenant-trigger" type="button">
                  <span class="tenant-trigger-label">当前客户：</span>
                  <span class="tenant-trigger-name">{{ tenantName }}</span>
                  <span class="tenant-trigger-caret">▾</span>
                </button>
              </template>
              <div class="tenant-panel">
                <div class="tenant-panel-kicker">切换客户 / 聚合视图</div>
                <button class="tenant-all" type="button" disabled>
                  <span class="tenant-avatar tenant-avatar-all">全</span>
                  <span class="tenant-copy">
                    <span class="tenant-title">全部客户聚合视图</span>
                    <span class="tenant-meta">{{ tenantCountLabel }} · 聚合看板待接入</span>
                  </span>
                </button>
                <div class="tenant-section-title">单一客户（数据完全隔离）</div>
                <button
                  v-for="t in session.tenants"
                  :key="t.id"
                  class="tenant-option"
                  :class="{ active: t.id === session.tenantId }"
                  type="button"
                  @click="onTenantChange(t.id)"
                >
                  <span class="tenant-avatar" :class="'tone-' + tenantTone(t.id)">
                    {{ tenantInitials(t) }}
                  </span>
                  <span class="tenant-copy">
                    <span class="tenant-title">{{ t.name }}</span>
                    <span class="tenant-meta">独立账户数据 · 客户 ID {{ t.id }}</span>
                  </span>
                  <span v-if="t.id === session.tenantId" class="tenant-check">✓</span>
                </button>
              </div>
            </el-popover>
            <span v-else class="tenant-static">客户：<b>{{ tenantName }}</b></span>
            <span class="role-badge">{{ session.user?.role_label }}</span>
            <el-dropdown @command="onUserCommand">
              <span class="user-chip">{{ session.user?.display_name }} ▾</span>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="password">修改密码</el-dropdown-item>
                  <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
          <span v-else class="dev-badge">本地 API Key 模式</span>
        </div>
      </el-header>
      <el-main class="main">
        <div v-if="!SEM_WRITEBACK_ENABLED" class="readonly-banner">
          <b>只读演练</b>
          <span>{{ SEM_READ_ONLY_MESSAGE }}</span>
        </div>
        <div class="main-inner">
          <router-view />
        </div>
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.readonly-banner { display: flex; align-items: center; gap: 10px; margin: 0 18px 12px; padding: 9px 13px; border: 1px solid #f1c27d; border-radius: 8px; background: #fff8eb; color: #7a4b0b; font-size: 12px; line-height: 1.5; }
.readonly-banner b { flex: none; padding: 1px 7px; border-radius: 10px; background: #f3b85b; color: #4f2c00; font-size: 11px; }
/* 侧边栏按原型 v3.0 sidebar 复刻（logo / wf-group / wf-badge / wf-sub-item） */
.side { background: #fff; border-right: 1px solid var(--sem-border); display: flex; flex-direction: column; }
.brand { padding: 18px 20px 14px; border-bottom: 1px solid #f3f4f6; }
.brand-name { font-size: 15px; font-weight: 600; color: var(--sem-primary); }
.brand-sub { font-size: 11px; color: #9ca3af; margin-top: 4px; }
.nav-scroll { flex: 1; overflow-y: auto; padding: 14px 0 24px; }
.nav-section-title { padding: 0 20px 6px; font-size: 11px; color: #9ca3af; font-weight: 500; letter-spacing: 0.3px; }

.wf-group { user-select: none; }
.wf-trigger { padding: 9px 20px; cursor: pointer; color: #4b5563; font-size: 13px; display: flex; align-items: center; gap: 8px; transition: background 0.1s; }
.wf-trigger:hover { background: #f9fafb; }
.wf-trigger.current { color: var(--sem-primary); font-weight: 500; }
.wf-icon { width: 16px; height: 16px; display: inline-flex; align-items: center; justify-content: center; font-size: 13px; }
.wf-name { flex: 1; }
.wf-badge { font-size: 10px; padding: 1px 6px; border-radius: 8px; font-weight: 500; background: #fef6f6; color: #e24b4a; }
.wf-badge.info { background: #eff4fb; color: var(--sem-primary); }
.wf-toggle { font-size: 12px; color: #9ca3af; transition: transform 0.15s; }
.wf-group.open .wf-toggle { transform: rotate(90deg); }
.wf-sub { display: none; padding-bottom: 4px; }
.wf-group.open .wf-sub { display: block; }
.wf-sub-item { padding: 7px 20px 7px 44px; cursor: pointer; color: #6b7280; font-size: 12px; display: flex; align-items: center; gap: 6px; border-left: 3px solid transparent; }
.wf-sub-item:hover { background: #f9fafb; color: var(--sem-primary); }
.wf-sub-item.active { background: #eff4fb; color: var(--sem-primary); font-weight: 500; border-left-color: var(--sem-primary); }
.wf-sub-item.disabled { cursor: default; color: #c0c4cc; }
.wf-sub-item.disabled:hover { background: none; color: #c0c4cc; }
.wf-sub-dot { width: 4px; height: 4px; border-radius: 50%; background: #d1d5db; flex-shrink: 0; }
.wf-sub-item.active .wf-sub-dot { background: var(--sem-primary); }
.wf-sub-num { font-size: 10px; color: #9ca3af; margin-left: auto; }

.side-shortcuts {
  flex: 0 0 auto;
  margin: 0;
  padding: 12px 20px 18px;
  border-top: 1px solid #e5e9ef;
  background: #fff;
}
.shortcut-group { padding: 0; }
.shortcut-link {
  min-height: 34px;
  padding: 0;
  display: flex;
  align-items: center;
  gap: 7px;
  color: #7b8493;
  font-size: 12px;
  font-weight: 500;
  text-decoration: none;
  transition: color 0.15s ease;
}
.shortcut-link:hover {
  color: var(--sem-primary);
}
.shortcut-icon {
  width: 16px;
  display: inline-flex;
  justify-content: flex-start;
  color: inherit;
  font-size: 14px;
  font-weight: 500;
}
.shortcut-group-muted { background: transparent; }

.topbar { background: #fff; border-bottom: 1px solid var(--sem-border); display: flex; align-items: center; justify-content: space-between; }
.topbar-right { display: flex; align-items: center; gap: 12px; }
.theme-toggle {
  height: 30px;
  padding: 0 11px;
  border: 1px solid transparent;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}
.theme-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: currentColor;
}
.tenant-trigger {
  height: 30px;
  max-width: 230px;
  padding: 6px 12px;
  border: 0;
  border-radius: 6px;
  background: #f3f4f6;
  color: var(--sem-text);
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  box-shadow: none;
  font-size: 12px;
  line-height: 1;
  user-select: none;
}
.tenant-trigger:hover { background: #e9edf3; }
.tenant-trigger-label { color: #6b7280; white-space: nowrap; }
.tenant-trigger-name {
  color: var(--sem-primary);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tenant-trigger-caret { color: #4b5563; font-size: 11px; line-height: 1; margin-left: 2px; transform: translateY(-1px); }
.tenant-static { font-size: 12px; color: var(--sem-text-sub); }
.tenant-static b { color: var(--sem-primary); }
.role-badge { font-size: 11px; padding: 3px 9px; border-radius: 10px; font-weight: 500; }
.role-badge.admin { background: #fef1e1; color: #ba7517; }
.role-badge.operator { background: #eff4fb; color: #185fa5; }
.role-badge.client { background: #e5f4ed; color: #1d9e75; }
.user-chip { font-size: 12px; color: var(--sem-text); cursor: pointer; user-select: none; }
.dev-badge { font-size: 11px; color: #9ca3af; }
.main { background: var(--sem-bg); }
/* 宽屏封顶内容宽度，左对齐，避免卡片被拉得过宽、整页显得贴边空旷 */
.main-inner { max-width: 1440px; }

:global(.tenant-popover.el-popper) {
  padding: 0;
  border: 1px solid #e5ebf2;
  border-radius: 8px;
  box-shadow: 0 16px 38px rgba(15, 23, 42, 0.13);
  overflow: hidden;
}
.tenant-panel {
  padding: 13px 8px 10px;
  background: #fff;
}
.tenant-panel-kicker,
.tenant-section-title {
  padding: 0 9px;
  color: #9aa6b5;
  font-size: 11px;
  font-weight: 700;
}
.tenant-panel-kicker { margin-bottom: 10px; }
.tenant-section-title {
  margin: 10px 0 6px;
  padding-top: 10px;
  border-top: 1px solid #eef2f6;
}
.tenant-all,
.tenant-option {
  width: 100%;
  min-height: 44px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr) 14px;
  align-items: center;
  gap: 9px;
  padding: 7px 9px;
  text-align: left;
}
.tenant-all { cursor: not-allowed; opacity: 0.96; }
.tenant-option { cursor: pointer; color: var(--sem-text); }
.tenant-option:hover { background: #f6f9fd; }
.tenant-option.active {
  background: #edf4ff;
  box-shadow: none;
}
.tenant-avatar {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0;
  flex: 0 0 auto;
}
.tenant-avatar-all { background: #178092; }
.tenant-avatar.tone-blue { background: #2069b4; }
.tenant-avatar.tone-green { background: #26a77a; }
.tenant-avatar.tone-amber { background: #ca8321; }
.tenant-avatar.tone-violet { background: #7657c8; }
.tenant-avatar.tone-red { background: #e55353; }
.tenant-copy {
  min-width: 0;
  display: grid;
  gap: 2px;
}
.tenant-title {
  color: #1f2937;
  font-size: 13px;
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tenant-meta {
  color: #9aa4b2;
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tenant-check {
  color: var(--sem-primary);
  font-size: 15px;
  font-weight: 700;
  justify-self: end;
}

/* SEM 暗色工作台：基于海外仓 Next UI 的视觉语言，限定在现有 Vue 壳层内。 */
.sem-console {
  --sem-dark-bg: #090909;
  --sem-dark-panel: #141414;
  --sem-dark-panel-soft: rgba(22, 22, 22, 0.84);
  --sem-dark-border: rgba(255, 255, 255, 0.09);
  --sem-dark-border-strong: rgba(255, 255, 255, 0.15);
  --sem-dark-text: #eeeeee;
  --sem-dark-muted: #8e8e8e;
  --sem-dark-dim: #626262;
  --sem-accent: #ff6a1a;
  --sem-accent-soft: rgba(255, 106, 26, 0.14);
  --sem-accent-border: rgba(255, 106, 26, 0.44);
  --sem-blue-soft: rgba(78, 163, 255, 0.14);
  --sem-green-soft: rgba(61, 214, 140, 0.14);

  background: var(--sem-dark-bg);
  color: var(--sem-dark-text);
}

.sem-console > .side {
  width: 244px !important;
  min-width: 244px !important;
  flex: 0 0 244px !important;
  overflow: hidden !important;
  background: #080808;
  border-right: 1px solid var(--sem-dark-border);
}

.sem-console > .el-container {
  min-width: 0;
}

.sem-console .brand {
  padding: 20px 18px 16px;
  border-bottom: 1px solid var(--sem-dark-border);
}

.sem-console .brand-mark {
  display: flex;
  align-items: center;
  gap: 10px;
}

.sem-console .brand-logo {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(180deg, #ff8c42 0%, #ff6a1a 100%);
  color: #fff;
  font-weight: 800;
  box-shadow: 0 8px 22px rgba(255, 106, 26, 0.24);
}

.sem-console .brand-name {
  color: #fff;
  font-size: 14px;
  font-weight: 700;
}

.sem-console .brand-sub,
.sem-console .nav-section-title,
.sem-console .wf-toggle,
.sem-console .dev-badge,
.sem-console .tenant-static {
  color: var(--sem-dark-muted);
}

.sem-console .nav-scroll {
  padding: 14px 12px 24px;
}

.sem-console .nav-section-title {
  padding: 0 10px 8px;
  letter-spacing: 0.04em;
}

.sem-console .wf-group {
  margin-bottom: 6px;
}

.sem-console .wf-trigger {
  min-height: 38px;
  padding: 0 10px;
  border: 1px solid transparent;
  border-radius: 8px;
  color: #c8c8c8;
  font-size: 13px;
}

.sem-console .wf-trigger:hover {
  background: rgba(255, 255, 255, 0.045);
  color: #fff;
}

.sem-console .wf-trigger.current {
  background: var(--sem-accent-soft);
  border-color: var(--sem-accent-border);
  color: #fff;
  font-weight: 650;
}

.sem-console .wf-badge {
  background: rgba(255, 59, 59, 0.18);
  color: #ff8a8a;
}

.sem-console .wf-badge.info {
  background: var(--sem-blue-soft);
  color: #8fc4ff;
}

.sem-console .wf-sub {
  padding: 4px 0 2px;
}

.sem-console .wf-sub-item {
  min-height: 32px;
  margin: 1px 0;
  padding: 0 10px 0 36px;
  border-left: 0;
  border-radius: 8px;
  color: #949494;
}

.sem-console .wf-sub-item:hover {
  background: rgba(255, 255, 255, 0.045);
  color: #fff;
}

.sem-console .wf-sub-item.active {
  background: rgba(255, 106, 26, 0.1);
  color: #ffb07a;
  border-left-color: transparent;
}

.sem-console .wf-sub-item.disabled,
.sem-console .wf-sub-item.disabled:hover {
  color: #4f4f4f;
  background: transparent;
}

.sem-console .wf-sub-dot {
  background: #505050;
}

.sem-console .wf-sub-item.active .wf-sub-dot {
  background: var(--sem-accent);
}

.sem-console .side-shortcuts {
  padding: 12px 18px 18px;
  background: #080808;
  border-top: 1px solid var(--sem-dark-border);
}

.sem-console .shortcut-link {
  color: var(--sem-dark-muted);
}

.sem-console .shortcut-link:hover {
  color: #ffb07a;
}

.sem-console .topbar {
  height: 60px;
  padding: 0 16px;
  background: rgba(9, 9, 9, 0.88);
  border-bottom: 1px solid var(--sem-dark-border);
  backdrop-filter: blur(16px);
}

.sem-console .main {
  background:
    radial-gradient(circle at 20% 0%, rgba(255, 106, 26, 0.08), transparent 34%),
    linear-gradient(180deg, #0b0b0b 0%, #111 100%);
  color: var(--sem-dark-text);
  min-width: 0;
  overflow-x: hidden;
  padding: 16px 16px 24px;
}

.sem-console .main-inner {
  width: 100%;
  max-width: 1480px;
}

/* 运营表格统一约束：面板可在收窄时正确参与 flex 布局。 */
:global(.sem-console .table-panel) {
  min-width: 0;
}

.sem-console .tenant-trigger,
.sem-console .role-badge,
.sem-console .user-chip,
.sem-console .dev-badge {
  border: 1px solid var(--sem-dark-border-strong);
  background: rgba(255, 255, 255, 0.045);
  color: #e2e2e2;
}

.sem-console .tenant-trigger:hover,
.sem-console .user-chip:hover {
  background: rgba(255, 255, 255, 0.075);
}

.sem-console .tenant-trigger-name,
.sem-console .tenant-static b {
  color: #ffb07a;
}

.sem-console .role-badge {
  color: #9bd2ff;
}

.sem-console .user-chip {
  min-height: 30px;
  padding: 6px 10px;
  border-radius: 999px;
}

:global(.sem-console .el-breadcrumb__inner),
:global(.sem-console .el-breadcrumb__separator) {
  color: #a8a8a8 !important;
}

:global(.sem-console .el-breadcrumb__item:last-child .el-breadcrumb__inner) {
  color: #f0f0f0 !important;
  font-weight: 650;
}

:global(.sem-console .el-card),
:global(.sem-console .el-table),
:global(.sem-console .el-tabs__content),
:global(.sem-console .el-collapse-item__wrap) {
  background: var(--sem-dark-panel-soft);
  border-color: var(--sem-dark-border);
  color: var(--sem-dark-text);
}

:global(.sem-console .el-card) {
  border-radius: 8px;
  box-shadow: 0 12px 34px rgba(0, 0, 0, 0.24);
}

:global(.sem-console .el-table th.el-table__cell),
:global(.sem-console .el-table tr),
:global(.sem-console .el-table td.el-table__cell) {
  background: transparent;
  color: #dedede;
  border-bottom-color: var(--sem-dark-border);
}

:global(.sem-console .el-table th.el-table__cell) {
  color: #969696;
  font-weight: 650;
}

:global(.sem-console .el-table--enable-row-hover .el-table__body tr:hover > td.el-table__cell) {
  background: rgba(255, 255, 255, 0.045);
}

:global(.sem-console .el-input__wrapper),
:global(.sem-console .el-select__wrapper),
:global(.sem-console .el-textarea__inner),
:global(.sem-console .el-date-editor.el-input__wrapper),
:global(.sem-console .el-date-editor .el-range-input) {
  background: rgba(255, 255, 255, 0.045);
  border-color: transparent;
  box-shadow: 0 0 0 1px var(--sem-dark-border-strong) inset;
  color: #e8e8e8;
}

:global(.sem-console .el-input__inner),
:global(.sem-console .el-select__placeholder),
:global(.sem-console .el-date-editor .el-range-input) {
  color: #e8e8e8;
}

:global(.sem-console .el-button) {
  border-radius: 8px;
}

:global(.sem-console .el-button--primary) {
  border-color: transparent;
  background: linear-gradient(180deg, #ff8c42 0%, #ff6a1a 100%);
  box-shadow: 0 8px 20px rgba(255, 106, 26, 0.2);
}

:global(.sem-console .el-button:not(.el-button--primary)) {
  background: rgba(255, 255, 255, 0.045);
  border-color: var(--sem-dark-border-strong);
  color: #e2e2e2;
}

:global(.sem-console .page-title) {
  color: #fff !important;
}

:global(.sem-console .page-desc),
:global(.sem-console .subtle),
:global(.sem-console .muted) {
  color: var(--sem-dark-muted) !important;
}

:global(.sem-console .page-header),
:global(.sem-console .panel),
:global(.sem-console .kpi-card),
:global(.sem-console .ai-insight),
:global(.sem-console .filter-row),
:global(.sem-console .batch-bar),
:global(.sem-console .source-card),
:global(.sem-console .alert-card),
:global(.sem-console .workbench-toolbar) {
  background: rgba(22, 22, 22, 0.82) !important;
  border-color: var(--sem-dark-border) !important;
  color: var(--sem-dark-text) !important;
  box-shadow: 0 12px 34px rgba(0, 0, 0, 0.22);
  backdrop-filter: blur(14px);
}

:global(.sem-console .page-header) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  border: 1px solid var(--sem-dark-border);
  border-radius: 8px;
  padding: 16px 18px;
  margin-bottom: 14px;
}

:global(.sem-console .page-header > div:first-child) {
  min-width: 180px;
  flex: 1 1 180px;
}

:global(.sem-console .dash-toolbar) {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex: 1 1 520px;
  flex-wrap: wrap;
  color: #d8d8d8;
}

:global(.sem-console .date-quick-options),
:global(.sem-console .quick-btns),
:global(.sem-console .media-filter) {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

:global(.sem-console .media-label),
:global(.sem-console .freshness),
:global(.sem-console .panel-sub),
:global(.sem-console .kpi-label),
:global(.sem-console .kpi-vs),
:global(.sem-console .empty-line) {
  color: var(--sem-dark-muted) !important;
}

:global(.sem-console .quick-btn) {
  height: 32px;
  padding: 0 12px;
  border: 1px solid var(--sem-dark-border-strong) !important;
  border-radius: 8px !important;
  background: rgba(255, 255, 255, 0.045) !important;
  color: #e8e8e8 !important;
  cursor: pointer;
}

:global(.sem-console .quick-btn:hover),
:global(.sem-console .quick-btn.active) {
  border-color: var(--sem-accent-border) !important;
  background: var(--sem-accent-soft) !important;
  color: #fff !important;
}

:global(.sem-console .kpi-value),
:global(.sem-console .num),
:global(.sem-console .panel-title) {
  color: #f5f5f5 !important;
}

:global(.sem-console .kpi-delta.up) {
  color: #3dd68c !important;
}

:global(.sem-console .kpi-delta.down) {
  color: #ff8a8a !important;
}

:global(.sem-console .el-select__selected-item),
:global(.sem-console .el-range-separator),
:global(.sem-console .el-date-editor .el-range-separator) {
  color: #dcdcdc !important;
}

.sem-console .nav-scroll,
.sem-console .main {
  scrollbar-color: #666 #111;
}

.sem-console .nav-scroll::-webkit-scrollbar,
.sem-console .main::-webkit-scrollbar {
  width: 10px;
}

.sem-console .nav-scroll::-webkit-scrollbar-track,
.sem-console .main::-webkit-scrollbar-track {
  background: #101010;
}

.sem-console .nav-scroll::-webkit-scrollbar-thumb,
.sem-console .main::-webkit-scrollbar-thumb {
  background: #3a3a3a;
  border-radius: 999px;
  border: 2px solid #101010;
}

/* 亮橘主题：浅灰工作台 + 白色面板 + 橘色运营强调，参考用户提供的 SEM 看板图。 */
.sem-theme-light {
  --sem-light-bg: #f6f7f9;
  --sem-light-panel: #ffffff;
  --sem-light-panel-soft: rgba(255, 255, 255, 0.94);
  --sem-light-border: #e6e8ec;
  --sem-light-border-strong: #d9dde4;
  --sem-light-text: #22262d;
  --sem-light-muted: #7a828e;
  --sem-light-dim: #a2a9b3;
  --sem-accent: #e86f1c;
  --sem-accent-soft: #fff2e9;
  --sem-accent-border: rgba(232, 111, 28, 0.42);
  --sem-blue-soft: #eef6ff;
  --sem-green-soft: #eefaf5;

  background: var(--sem-light-bg);
  color: var(--sem-light-text);
}

.sem-theme-light .side {
  background: rgba(255, 255, 255, 0.96);
  border-right: 1px solid var(--sem-light-border);
  box-shadow: 8px 0 26px rgba(21, 29, 43, 0.035);
}

.sem-theme-light .brand {
  border-bottom: 1px solid var(--sem-light-border);
}

.sem-theme-light .brand-logo {
  background: linear-gradient(180deg, #f59b46 0%, #e86f1c 100%);
  box-shadow: 0 8px 20px rgba(232, 111, 28, 0.22);
}

.sem-theme-light .brand-name {
  color: #9b5b21;
}

.sem-theme-light .brand-sub,
.sem-theme-light .nav-section-title,
.sem-theme-light .wf-toggle,
.sem-theme-light .tenant-static,
.sem-theme-light .dev-badge,
.sem-theme-light .shortcut-link {
  color: var(--sem-light-muted);
}

.sem-theme-light .wf-trigger {
  color: #4f5662;
}

.sem-theme-light .wf-trigger:hover {
  background: #f8f3ee;
  color: #1f2933;
}

.sem-theme-light .wf-trigger.current {
  background: linear-gradient(90deg, #fff4eb 0%, #fff 100%);
  border-color: #f0c9ac;
  color: #a95a1d;
  box-shadow: inset 3px 0 0 #e86f1c;
}

.sem-theme-light .wf-trigger.current .wf-icon {
  color: #c9671e;
  background: #fff0e4;
  border-radius: 5px;
}

.sem-theme-light .wf-sub-item {
  color: #838b96;
}

.sem-theme-light .wf-sub-item:hover {
  background: #fbf5ef;
  color: #a95a1d;
}

.sem-theme-light .wf-sub-item.active {
  background: #fff2e9;
  color: #c9671e;
}

.sem-theme-light .wf-sub-item.disabled,
.sem-theme-light .wf-sub-item.disabled:hover {
  color: #c5cbd3;
}

.sem-theme-light .wf-sub-dot {
  background: #c9ced6;
}

.sem-theme-light .wf-badge {
  background: #fff0ed;
  color: #c94d43;
}

.sem-theme-light .wf-badge.info {
  background: #fff4e9;
  color: #d97820;
}

.sem-theme-light .side-shortcuts {
  background: rgba(255, 255, 255, 0.96);
  border-top: 1px solid var(--sem-light-border);
}

.sem-theme-light .shortcut-link:hover {
  color: #c9671e;
}

.sem-theme-light .topbar {
  background: rgba(255, 255, 255, 0.92);
  border-bottom: 1px solid var(--sem-light-border);
  box-shadow: 0 8px 22px rgba(21, 29, 43, 0.035);
}

.sem-theme-light .main {
  background:
    radial-gradient(circle at 16% 0%, rgba(232, 111, 28, 0.08), transparent 30%),
    linear-gradient(180deg, #f7f8fa 0%, #f2f4f7 100%);
  color: var(--sem-light-text);
}

.sem-theme-light .tenant-trigger,
.sem-theme-light .role-badge,
.sem-theme-light .user-chip,
.sem-theme-light .dev-badge,
.sem-theme-light .theme-toggle {
  border: 1px solid var(--sem-light-border-strong);
  background: #fff;
  color: #3d4652;
}

.sem-theme-light .theme-toggle {
  color: #b86221;
}

.sem-theme-light .tenant-trigger:hover,
.sem-theme-light .user-chip:hover,
.sem-theme-light .theme-toggle:hover {
  background: #fff7f0;
  border-color: #efc8aa;
}

.sem-theme-light .tenant-trigger-name,
.sem-theme-light .tenant-static b {
  color: #b86221;
}

.sem-theme-light .role-badge {
  color: #28705a;
}

:global(.sem-theme-light .el-breadcrumb__inner),
:global(.sem-theme-light .el-breadcrumb__separator) {
  color: #7e8793 !important;
}

:global(.sem-theme-light .el-breadcrumb__item:last-child .el-breadcrumb__inner) {
  color: #22262d !important;
}

:global(.sem-theme-light .el-card),
:global(.sem-theme-light .el-table),
:global(.sem-theme-light .el-tabs__content),
:global(.sem-theme-light .el-collapse-item__wrap),
:global(.sem-theme-light .page-header),
:global(.sem-theme-light .panel),
:global(.sem-theme-light .kpi-card),
:global(.sem-theme-light .ai-insight),
:global(.sem-theme-light .filter-row),
:global(.sem-theme-light .batch-bar),
:global(.sem-theme-light .source-card),
:global(.sem-theme-light .alert-card),
:global(.sem-theme-light .workbench-toolbar) {
  background: var(--sem-light-panel-soft) !important;
  border-color: var(--sem-light-border) !important;
  color: var(--sem-light-text) !important;
  box-shadow: 0 10px 28px rgba(21, 29, 43, 0.055);
  backdrop-filter: blur(12px);
}

:global(.sem-theme-light .page-title),
:global(.sem-theme-light .kpi-value),
:global(.sem-theme-light .num),
:global(.sem-theme-light .panel-title),
:global(.sem-theme-light .el-table td.el-table__cell) {
  color: var(--sem-light-text) !important;
}

:global(.sem-theme-light .page-desc),
:global(.sem-theme-light .subtle),
:global(.sem-theme-light .muted),
:global(.sem-theme-light .media-label),
:global(.sem-theme-light .freshness),
:global(.sem-theme-light .panel-sub),
:global(.sem-theme-light .kpi-label),
:global(.sem-theme-light .kpi-vs),
:global(.sem-theme-light .empty-line) {
  color: var(--sem-light-muted) !important;
}

:global(.sem-theme-light .el-table th.el-table__cell),
:global(.sem-theme-light .el-table tr),
:global(.sem-theme-light .el-table td.el-table__cell) {
  background: #fff;
  border-bottom-color: var(--sem-light-border);
}

:global(.sem-theme-light .el-table th.el-table__cell) {
  color: #6f7783;
}

:global(.sem-theme-light .el-table--enable-row-hover .el-table__body tr:hover > td.el-table__cell) {
  background: #fff7f0;
}

:global(.sem-theme-light .el-input__wrapper),
:global(.sem-theme-light .el-select__wrapper),
:global(.sem-theme-light .el-textarea__inner),
:global(.sem-theme-light .el-date-editor.el-input__wrapper),
:global(.sem-theme-light .el-date-editor .el-range-input) {
  background: #fff;
  box-shadow: 0 0 0 1px var(--sem-light-border-strong) inset;
  color: var(--sem-light-text);
}

:global(.sem-theme-light .el-input__inner),
:global(.sem-theme-light .el-select__placeholder),
:global(.sem-theme-light .el-select__selected-item),
:global(.sem-theme-light .el-date-editor .el-range-input),
:global(.sem-theme-light .el-range-separator),
:global(.sem-theme-light .el-date-editor .el-range-separator) {
  color: #2f3742 !important;
}

:global(.sem-theme-light .el-button--primary) {
  background: linear-gradient(180deg, #f38d35 0%, #e86f1c 100%);
  box-shadow: 0 8px 18px rgba(232, 111, 28, 0.24);
}

:global(.sem-theme-light .el-button:not(.el-button--primary)) {
  background: #fff;
  border-color: var(--sem-light-border-strong);
  color: #344050;
}

:global(.sem-theme-light .quick-btn) {
  border-color: var(--sem-light-border-strong) !important;
  background: #fff !important;
  color: #4b5563 !important;
}

:global(.sem-theme-light .quick-btn:hover),
:global(.sem-theme-light .quick-btn.active) {
  border-color: var(--sem-accent-border) !important;
  background: linear-gradient(180deg, #f38d35 0%, #e86f1c 100%) !important;
  color: #fff !important;
  box-shadow: 0 8px 16px rgba(232, 111, 28, 0.2);
}

:global(.sem-theme-light .hint-icon) {
  border-color: #e8bc98;
  background: #fff8f2;
  color: #c9671e;
}

:global(.sem-theme-light .hint-icon:hover) {
  border-color: #e86f1c;
  background: #fff0e4;
  color: #a95316;
}

:global(.sem-theme-light .ai-insight) {
  background: linear-gradient(120deg, #fff7ed 0%, #fff 42%, #f8fbff 100%) !important;
}

.sem-theme-light .nav-scroll,
.sem-theme-light .main {
  scrollbar-color: #d2d7df #f5f6f8;
}

.sem-theme-light .nav-scroll::-webkit-scrollbar-track,
.sem-theme-light .main::-webkit-scrollbar-track {
  background: #f5f6f8;
}

.sem-theme-light .nav-scroll::-webkit-scrollbar-thumb,
.sem-theme-light .main::-webkit-scrollbar-thumb {
  background: #d2d7df;
  border-color: #f5f6f8;
}
</style>
