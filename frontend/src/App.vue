<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { changePassword, fetchMe, fetchTenants } from './api/auth'
import { fetchAlerts } from './api/alerts'
import { fetchCandidates } from './api/expansion'
import { session } from './store/session'

const route = useRoute()
const router = useRouter()
const currentTitle = computed(() => route.meta.title || '')
const currentWorkflow = computed(() => route.meta.workflow || '')
const bare = computed(() => route.meta.bare) // 登录页等无框页面
const tenantPopoverOpen = ref(false)

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
  { label: 'GEO 增长', icon: '◈', children: [
    { label: 'GEO 概览', path: '/geo/overview', key: 'geo.content' },
    { label: 'AI 可见度', path: '/geo/visibility', key: 'geo.content' },
    { label: '全自动巡检', path: '/geo/visibility/patrol', key: 'geo.content' },
    { label: '期次对比', path: '/geo/period-diff', key: 'geo.content' },
    { label: '引用域名', path: '/geo/citations', key: 'geo.content' },
    { label: '竞品分析', path: '/geo/competitors', key: 'geo.content' },
    { label: '评价分析', path: '/geo/evaluation', key: 'geo.content' },
    { label: '交付摘要', path: '/geo/deliverables', key: 'geo.content' },
    { label: '内容工作台', path: '/geo/workbench', key: 'geo.content' },
    { label: '内容任务', path: '/geo/tasks', key: 'geo.content' },
    { label: '机会词', path: '/geo/prompts', key: 'geo.content' },
    { label: '事实库', path: '/geo/facts', key: 'geo.content' },
    { label: '跟踪引擎', path: '/geo/engines', key: 'geo.content' },
    { label: 'AI 配置', path: '/geo/ai-settings', key: 'geo.content' },
    { label: '发布渠道', path: '/geo/publishing', key: 'geo.content' },
  ] },
  { label: '首次接入', icon: '🚀', children: [
    { label: '授权与同步', path: '/onboarding', key: 'onboarding' },
    { label: '智能搭建', path: '/onboarding/builder', key: 'onboarding' },
  ] },
  { label: '每日盯盘', icon: '📊', badge: badges.alerts, badgeCls: '', children: [
    { label: '数据看板', path: '/monitor/dashboard', key: 'monitor.dashboard' },
    { label: '异常提醒', path: '/monitor/alerts', count: badges.alerts, key: 'monitor.alerts' },
    { label: '客户画像', path: '/monitor/profile', key: 'monitor.profile' },
    { label: '关键词详情', path: '', disabled: true, hint: '从看板/列表下钻进入', alwaysShow: true },
  ] },
  { label: '优化执行', icon: '⚡', badge: badges.expand, badgeCls: 'info', children: [
    { label: '拓词', path: '/optimize/expand', count: badges.expand, key: 'optimize.expand' },
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
    { label: '账户与预算', path: '/manage/account', key: 'manage.account' },
    { label: '计划管理', path: '/manage/campaigns', key: 'manage.campaigns' },
    { label: 'oCPC 投放', path: '/manage/ocpc', key: 'manage.ocpc' },
  ] },
  { label: '客户交付', icon: '📨', children: [
    { label: '分析报告', path: '/delivery/report', key: 'delivery.report' },
  ] },
  { label: '系统设置', icon: '⚙', children: [
    { label: '账号与权限', path: '/settings/accounts', key: 'settings.accounts' },
  ] },
])

const navGroups = computed(() => {
  const noLogin = !session.isLoggedIn // 本地 dev API Key 模式：全显示
  return ALL_GROUPS.value
    .map((g) => ({
      ...g,
      // 叶子项：下钻类(alwaysShow)始终留；其余按 canView 过滤
      children: g.children.filter((c) => c.alwaysShow || noLogin || session.canView(c.key)),
    }))
    // 没有任何可见叶子(或只剩下钻提示)的分组整组隐藏
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
    router.push('/login')
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

watch(() => session.isLoggedIn, (v) => { if (v) { loadTenants(); loadBadges() } })
watch(() => session.tenantId, loadBadges)
watch(() => route.path, syncOpenToRoute)
onMounted(() => { refreshMe(); loadTenants(); loadBadges(); syncOpenToRoute() })
</script>

<template>
  <router-view v-if="bare" />
  <el-container v-else style="height: 100vh">
    <el-aside width="220px" class="side">
      <div class="brand">
        <div class="brand-name">SEM 智投平台</div>
        <div class="brand-sub">v3.0 · 工作流版</div>
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
              <span v-if="c.count" class="wf-sub-num">{{ c.count > 99 ? '99+' : c.count }}</span>
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
        <div class="main-inner">
          <router-view />
        </div>
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
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
</style>
