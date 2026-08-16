<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { changePassword, fetchMe, fetchTenants } from './api/auth'
import { fetchAlerts } from './api/alerts'
import { fetchCandidates } from './api/expansion'
import { useObservationPeriod } from './composables/useObservationPeriod'
import { session } from './store/session'

const route = useRoute()
const router = useRouter()
const currentTitle = computed(() => route.meta.title || '')
const currentWorkflow = computed(() => route.meta.workflow || '')
const bare = computed(() => route.meta.bare) // 登录页等无框页面
/** 母稿编辑器等宽屏工作台：取消内容区 max-width，吃满主栏 */
const fluidMain = computed(() =>
  route.path.startsWith('/geo/tasks/') || route.meta.fluidMain === true,
)
const isGeoRoute = computed(() => route.path.startsWith('/geo'))
const {
  days: observationDays,
  label: observationLabel,
  allowedDays: observationAllowedDays,
  setDays: setObservationDays,
} = useObservationPeriod()
const tenantPopoverOpen = ref(false)

const roleTone = computed(() => {
  const label = String(session.user?.role_label || '')
  const role = String(session.user?.role || '')
  const blob = `${label}${role}`.toLowerCase()
  if (/admin|管理|超管/.test(blob)) return 'admin'
  if (/client|客户|只读/.test(blob)) return 'client'
  if (/operator|运营|投放/.test(blob)) return 'operator'
  return 'operator'
})

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
  // GEO：压成两层——内容 / 监测报表平级 / 配置；AI 动态归情报配置
  { label: 'GEO 增长', icon: '◈', children: [
    { label: '内容生产', children: [
      { label: '优化业务', path: '/geo/businesses', key: 'geo.content' },
      { label: 'GEO 开户向导', path: '/geo/onboarding', key: 'geo.content' },
      { label: '优化意图词', path: '/geo/prompts', key: 'geo.content' },
      { label: '缺口工作台', path: '/geo/gaps', key: 'geo.content' },
      { label: '事实库', path: '/geo/facts', key: 'geo.content' },
      { label: '优化文章', path: '/geo/tasks', key: 'geo.content' },
      { label: '发布渠道', path: '/geo/publishing', key: 'geo.content' },
      { label: '媒体阵地', path: '/geo/placements', key: 'geo.content' },
    ] },
    { label: '效果监测', children: [
      { label: 'GEO 概览', path: '/geo/overview', key: 'geo.content' },
      { label: 'AI 可见度', path: '/geo/visibility', key: 'geo.content', exact: true },
      { label: '优化期次', path: '/geo/periods', key: 'geo.content' },
      { label: '交付摘要', path: '/geo/deliverables', key: 'geo.content' },
      { label: '更多', children: [
        { label: '全自动巡检', path: '/geo/visibility/patrol', key: 'geo.content' },
        { label: 'AI 引用分析', path: '/geo/citations', key: 'geo.content' },
        { label: '竞品监测', path: '/geo/competitors', key: 'geo.content' },
        { label: '评价与位置', path: '/geo/evaluation', key: 'geo.content' },
        { label: '话题覆盖热度', path: '/geo/topic-heat', key: 'geo.content' },
      ] },
    ] },
    { label: '能力与情报', children: [
      { label: '引擎配置', path: '/geo/engines', key: 'geo.content' },
      { label: 'AI 配置', path: '/geo/ai-settings', key: 'geo.content' },
      { label: '渠道成稿提示词', path: '/geo/channel-polish-prompts', key: 'geo.content' },
      { label: 'AI 动态与策略', path: '/geo/ai-trends', key: 'geo.content' },
    ] },
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

function filterNavItems(items, noLogin) {
  return (items || [])
    .map((c) => {
      if (c.children?.length) {
        const kids = filterNavItems(c.children, noLogin)
        if (!kids.length) return null
        return { ...c, children: kids }
      }
      if (c.alwaysShow || noLogin || (c.key && session.canView(c.key))) return c
      return null
    })
    .filter(Boolean)
}

function collectLeafPaths(items, out = []) {
  for (const c of items || []) {
    if (c.children?.length) collectLeafPaths(c.children, out)
    else if (c.path) out.push(c.path)
  }
  return out
}

function itemMatchesPath(item, path) {
  if (!item?.path) return false
  if (path === item.path) return true
  if (item.exact) return false
  if (item.path === '/' || item.path === '/onboarding') return false
  // /geo/visibility 不应高亮 /geo/visibility/patrol
  if (item.path === '/geo/visibility') return false
  return path.startsWith(item.path + '/')
}

function findPathTrail(items, path, trail = []) {
  for (const c of items || []) {
    const next = [...trail, c.label]
    if (c.children?.length) {
      const hit = findPathTrail(c.children, path, next)
      if (hit) return hit
    } else if (itemMatchesPath(c, path)) {
      return next
    }
  }
  return null
}

const navGroups = computed(() => {
  const noLogin = !session.isLoggedIn // 本地 dev API Key 模式：全显示
  return ALL_GROUPS.value
    .map((g) => ({
      ...g,
      children: filterNavItems(g.children, noLogin),
    }))
    .filter((g) => collectLeafPaths(g.children).length > 0)
})

// 一级组 + 二级/三级折叠键（如 "GEO 增长/做内容"、"GEO 增长/做内容/内容资产"）
const openGroups = ref(new Set())
const openSections = ref(new Set())

function groupOfPath(path) {
  for (const g of navGroups.value) {
    if (findPathTrail(g.children, path)) return g.label
  }
  if (path.startsWith('/monitor/keywords')) return '每日盯盘'
  return null
}

function syncOpenToRoute() {
  const g = groupOfPath(route.path)
  if (!g) return
  openGroups.value = new Set([...openGroups.value, g])
  const group = navGroups.value.find((x) => x.label === g)
  const trail = group ? findPathTrail(group.children, route.path) : null
  if (!trail?.length) return
  const next = new Set(openSections.value)
  let acc = g
  for (const label of trail.slice(0, -1)) {
    acc = `${acc}/${label}`
    next.add(acc)
  }
  openSections.value = next
}

function toggleGroup(label) {
  const next = new Set(openGroups.value)
  next.has(label) ? next.delete(label) : next.add(label)
  openGroups.value = next
}

function toggleSection(sectionKey) {
  const next = new Set(openSections.value)
  next.has(sectionKey) ? next.delete(sectionKey) : next.add(sectionKey)
  openSections.value = next
}

const isActive = (c) => itemMatchesPath(c, route.path)
const isCurrentGroup = (g) => groupOfPath(route.path) === g.label
function sectionHasActive(section, path = route.path) {
  return !!findPathTrail(section.children || [], path)
}

function go(c) {
  if (!c.path || c.disabled) return
  if (c.external) {
    window.location.assign(c.path)
    return
  }
  router.push(c.path)
}

const tenantName = computed(() => {
  const hit = session.tenants.find((t) => t.id === session.tenantId)
  if (hit?.name) return hit.name
  if (session.tenantId) return `客户 #${session.tenantId}`
  return '未选择客户'
})
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
  try {
    const t = await fetchTenants()
    session.setTenants(t.tenants || [])
  } catch {
    /* 未登录且无 Key 时保持空列表 */
  }
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
  if (route.path.startsWith('/monitor/keywords/')) router.push('/monitor/dashboard')
  else if (route.path.startsWith('/geo/tasks/')) router.push('/geo/tasks')
  else if (route.path.startsWith('/geo/businesses/')) router.push('/geo/businesses')
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
    <el-aside width="228px" class="side">
      <div class="brand">
        <div class="brand-mark" aria-hidden="true">{{ isGeoRoute ? 'G' : 'S' }}</div>
        <div class="brand-copy">
          <div class="brand-name">{{ isGeoRoute ? 'GEO 增长' : 'SEM 智投平台' }}</div>
          <div class="brand-sub">{{ isGeoRoute ? tenantName : 'v3.0 · 工作流版' }}</div>
        </div>
      </div>
      <div class="nav-scroll">
        <div class="nav-section-title">{{ isGeoRoute ? 'GEO 工作流' : '代运营工作流' }}</div>
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
            <template v-for="c in g.children" :key="c.label">
              <!-- 二级分组（如 做内容 / 看效果 / 配置项） -->
              <div v-if="c.children?.length" class="wf-section" :class="{ open: openSections.has(`${g.label}/${c.label}`) }">
                <div
                  class="wf-section-trigger"
                  :class="{ current: sectionHasActive(c) }"
                  @click="toggleSection(`${g.label}/${c.label}`)"
                >
                  <span class="wf-section-name">{{ c.label }}</span>
                  <span class="wf-section-toggle">›</span>
                </div>
                <div class="wf-section-body">
                  <template v-for="s in c.children" :key="s.label">
                    <!-- 三级分组（如 内容资产 / 可见度监测） -->
                    <div
                      v-if="s.children?.length"
                      class="wf-branch"
                      :class="{ open: openSections.has(`${g.label}/${c.label}/${s.label}`) }"
                    >
                      <div
                        class="wf-branch-trigger"
                        :class="{ current: sectionHasActive(s) }"
                        @click="toggleSection(`${g.label}/${c.label}/${s.label}`)"
                      >
                        <span class="wf-sub-dot" />
                        <span class="wf-branch-name">{{ s.label }}</span>
                        <span class="wf-section-toggle">›</span>
                      </div>
                      <div class="wf-branch-body">
                        <div
                          v-for="leaf in s.children"
                          :key="leaf.label"
                          class="wf-sub-item depth-3"
                          :class="{ active: isActive(leaf), disabled: leaf.disabled || !leaf.path }"
                          :title="leaf.hint || ''"
                          @click="go(leaf)"
                        >
                          <span class="wf-sub-dot" />{{ leaf.label }}
                          <span v-if="leaf.count" class="wf-sub-num">{{ leaf.count > 99 ? '99+' : leaf.count }}</span>
                        </div>
                      </div>
                    </div>
                    <!-- 二级下的直接叶子 -->
                    <div
                      v-else
                      class="wf-sub-item depth-2"
                      :class="{ active: isActive(s), disabled: s.disabled || !s.path }"
                      :title="s.hint || ''"
                      @click="go(s)"
                    >
                      <span class="wf-sub-dot" />{{ s.label }}
                      <span v-if="s.count" class="wf-sub-num">{{ s.count > 99 ? '99+' : s.count }}</span>
                    </div>
                  </template>
                </div>
              </div>
              <!-- 一级组下的直接叶子（非 GEO 嵌套结构） -->
              <div
                v-else
                class="wf-sub-item"
                :class="{ active: isActive(c), disabled: c.disabled || !c.path }"
                :title="c.hint || ''"
                @click="go(c)"
              >
                <span class="wf-sub-dot" />{{ c.label }}
                <span v-if="c.count" class="wf-sub-num">{{ c.count > 99 ? '99+' : c.count }}</span>
              </div>
            </template>
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
      <el-header class="topbar" height="52px">
        <div class="crumb-block">
          <div class="crumb-kicker">当前位置</div>
          <el-breadcrumb separator="/">
            <el-breadcrumb-item>{{ currentWorkflow || '工作台' }}</el-breadcrumb-item>
            <el-breadcrumb-item>{{ currentTitle || '—' }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        <div class="topbar-right">
          <div
            v-if="isGeoRoute"
            class="obs-period"
            title="GEO 报表默认观察期（上海日历日）；全时段指标会在页面单独标注"
          >
            <span class="obs-period-label">观察期</span>
            <el-select
              :model-value="observationDays"
              size="small"
              class="obs-period-select"
              @change="setObservationDays"
            >
              <el-option
                v-for="d in observationAllowedDays"
                :key="d"
                :label="`近 ${d} 天`"
                :value="d"
              />
            </el-select>
            <span class="obs-period-range">{{ observationLabel }}</span>
          </div>
          <template v-if="session.tenants.length">
            <el-popover
              v-model:visible="tenantPopoverOpen"
              placement="bottom-end"
              :width="286"
              trigger="click"
              popper-class="tenant-popover"
            >
              <template #reference>
                <button class="tenant-trigger" type="button" title="切换客户">
                  <span class="tenant-trigger-label">当前客户</span>
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
            <span class="role-badge" :class="roleTone">{{ session.user?.role_label || session.user?.display_name || '本地 Key' }}</span>
            <el-dropdown @command="onUserCommand">
              <span class="user-chip">
                <span class="user-avatar" aria-hidden="true">
                  {{ (session.user?.display_name || '?').slice(0, 1) }}
                </span>
                {{ session.user?.display_name }}
                <span class="user-caret">▾</span>
              </span>
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
        <div class="main-inner" :class="{ fluid: fluidMain }">
          <router-view />
        </div>
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
/* 侧边栏按原型 v3.0 sidebar 复刻（logo / wf-group / wf-badge / wf-sub-item） */
.side {
  background: linear-gradient(180deg, #ffffff 0%, #fbfcfe 100%);
  border-right: 1px solid var(--sem-border);
  display: flex;
  flex-direction: column;
}
.brand {
  padding: 16px 18px 14px;
  border-bottom: 1px solid var(--sem-border-soft);
  display: flex;
  align-items: center;
  gap: 10px;
}
.brand-mark {
  width: 32px;
  height: 32px;
  border-radius: 9px;
  display: grid;
  place-items: center;
  font-size: 14px;
  font-weight: 750;
  color: #fff;
  background: linear-gradient(145deg, #1a6bb8 0%, #134c84 100%);
  box-shadow: 0 6px 14px rgba(24, 95, 165, 0.25);
  flex: 0 0 auto;
}
.brand-copy { min-width: 0; }
.brand-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--sem-text);
  letter-spacing: 0.01em;
  line-height: 1.2;
}
.brand-sub { font-size: 11px; color: var(--sem-text-muted); margin-top: 3px; }
.nav-scroll { flex: 1; overflow-y: auto; padding: 12px 0 20px; }
.nav-section-title {
  padding: 2px 20px 8px;
  font-size: 11px;
  color: var(--sem-text-muted);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: none;
}

.wf-group { user-select: none; }
.wf-trigger {
  margin: 0 8px;
  padding: 9px 12px;
  border-radius: 8px;
  cursor: pointer;
  color: #4b5563;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 8px;
  transition: background 0.15s ease, color 0.15s ease;
}
.wf-trigger:hover { background: #f3f6fa; }
.wf-trigger.current { color: var(--sem-primary); font-weight: 600; background: var(--sem-primary-soft); }
.wf-icon { width: 16px; height: 16px; display: inline-flex; align-items: center; justify-content: center; font-size: 13px; }
.wf-name { flex: 1; }
.wf-badge { font-size: 10px; padding: 1px 6px; border-radius: 8px; font-weight: 500; background: #fef6f6; color: #e24b4a; }
.wf-badge.info { background: #eff4fb; color: var(--sem-primary); }
.wf-toggle { font-size: 12px; color: #9ca3af; transition: transform 0.15s; }
.wf-group.open .wf-toggle { transform: rotate(90deg); }
.wf-sub { display: none; padding-bottom: 4px; }
.wf-group.open .wf-sub { display: block; }
.wf-sub-item {
  position: relative;
  margin: 1px 8px;
  padding: 7px 12px 7px 20px;
  border-radius: 8px;
  cursor: pointer;
  color: #6b7280;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
  border-left: 0;
  transition: background 0.15s ease, color 0.15s ease;
}
.wf-sub-item.depth-2 { padding-left: 32px; }
.wf-sub-item.depth-3 { padding-left: 44px; font-size: 11.5px; }
.wf-sub-item:hover { background: #f3f6fa; color: var(--sem-primary); }
.wf-sub-item.active {
  background: var(--sem-primary-soft);
  color: var(--sem-primary);
  font-weight: 600;
}
/* 选中标记用独立色条，避免 inset 阴影被圆角裁成括号形 */
.wf-sub-item.active::before {
  content: '';
  position: absolute;
  left: 6px;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 15px;
  border-radius: 2px;
  background: var(--sem-primary);
}
.wf-sub-item.disabled { cursor: default; color: #c0c4cc; }
.wf-sub-item.disabled:hover { background: none; color: #c0c4cc; }
.wf-sub-dot { width: 4px; height: 4px; border-radius: 50%; background: #d1d5db; flex-shrink: 0; }
.wf-sub-item.active .wf-sub-dot { background: var(--sem-primary); }
.wf-sub-num { font-size: 10px; color: #9ca3af; margin-left: auto; }

/* GEO 二级 / 三级折叠 */
.wf-section { margin: 2px 0; }
.wf-section-trigger {
  margin: 1px 8px;
  border-radius: 8px;
  padding: 7px 12px 7px 20px;
  cursor: pointer;
  color: #4b5563;
  font-size: 12px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 6px;
}
.wf-section-trigger:hover { background: #f3f6fa; color: var(--sem-primary); }
.wf-section-trigger.current { color: var(--sem-primary); }
.wf-section-name { flex: 1; }
.wf-section-toggle { font-size: 11px; color: #9ca3af; transition: transform 0.15s; }
.wf-section.open > .wf-section-trigger .wf-section-toggle,
.wf-branch.open > .wf-branch-trigger .wf-section-toggle { transform: rotate(90deg); }
.wf-section-body { display: none; }
.wf-section.open > .wf-section-body { display: block; }

.wf-branch { margin: 0; }
.wf-branch-trigger {
  margin: 1px 8px;
  border-radius: 8px;
  padding: 6px 12px 6px 32px;
  cursor: pointer;
  color: #6b7280;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.wf-branch-trigger:hover { background: #f3f6fa; color: var(--sem-primary); }
.wf-branch-trigger.current { color: var(--sem-primary); }
.wf-branch-name { flex: 1; }
.wf-branch-body { display: none; }
.wf-branch.open > .wf-branch-body { display: block; position: relative; }
/* 层级引导线：把最深一层的同组项串起来 */
.wf-branch.open > .wf-branch-body::before {
  content: '';
  position: absolute;
  left: 34px;
  top: 3px;
  bottom: 3px;
  width: 1px;
  background: #e6ebf2;
}

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

.obs-period {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-right: 10px;
  padding: 4px 10px;
  border-radius: 999px;
  background: #f0f6fc;
  border: 1px solid #d6e6f5;
  max-width: min(420px, 42vw);
}
.obs-period-label {
  font-size: 11px;
  font-weight: 700;
  color: #185fa5;
  flex-shrink: 0;
}
.obs-period-select {
  width: 100px;
}
.obs-period-range {
  font-size: 11px;
  color: #64748b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
@media (max-width: 1100px) {
  .obs-period-range { display: none; }
}
.topbar {
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--sem-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  gap: 16px;
}
.crumb-block { min-width: 0; }
.crumb-kicker {
  font-size: 10px;
  font-weight: 650;
  letter-spacing: 0.06em;
  color: var(--sem-text-muted);
  margin-bottom: 1px;
}
.crumb-block :deep(.el-breadcrumb__inner) {
  font-weight: 500;
  color: var(--sem-text-sub);
}
.crumb-block :deep(.el-breadcrumb__item:last-child .el-breadcrumb__inner) {
  color: var(--sem-text);
  font-weight: 650;
}
.topbar-right { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; justify-content: flex-end; }
.tenant-trigger {
  height: 32px;
  max-width: 240px;
  padding: 0 12px;
  border: 1px solid #e5ebf2;
  border-radius: 999px;
  background: #f7f9fc;
  color: var(--sem-text);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  box-shadow: none;
  font-size: 12px;
  line-height: 1;
  user-select: none;
  transition: background 0.15s ease, border-color 0.15s ease;
}
.tenant-trigger:hover { background: #eef3f9; border-color: #d5e0ec; }
.tenant-trigger-label { color: #6b7280; white-space: nowrap; }
.tenant-trigger-name {
  color: var(--sem-primary);
  font-weight: 650;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tenant-trigger-caret { color: #4b5563; font-size: 11px; line-height: 1; }
.tenant-static {
  font-size: 12px;
  color: var(--sem-text-sub);
  padding: 6px 10px;
  border-radius: 999px;
  background: #f7f9fc;
  border: 1px solid #e5ebf2;
}
.tenant-static b { color: var(--sem-primary); }
.role-badge {
  font-size: 11px;
  padding: 4px 10px;
  border-radius: 999px;
  font-weight: 600;
  background: #f3f4f6;
  color: #6b7280;
}
.role-badge.admin { background: #fef1e1; color: #ba7517; }
.role-badge.operator { background: #eff4fb; color: #185fa5; }
.role-badge.client { background: #e5f4ed; color: #1d9e75; }
.user-chip {
  height: 32px;
  padding: 0 10px 0 4px;
  border-radius: 999px;
  border: 1px solid #e5ebf2;
  background: #fff;
  font-size: 12px;
  color: var(--sem-text);
  cursor: pointer;
  user-select: none;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.user-chip:hover { border-color: #d5e0ec; background: #f8fafc; }
.user-avatar {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 11px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(145deg, #3e84c8, #185fa5);
}
.user-caret { color: #9ca3af; font-size: 10px; }
.dev-badge {
  font-size: 11px;
  color: #7c6a1f;
  background: #fff8e1;
  border: 1px solid #f0e2a8;
  padding: 4px 9px;
  border-radius: 999px;
}
.main {
  background:
    radial-gradient(1200px 400px at 0% 0%, rgba(24, 95, 165, 0.05), transparent 55%),
    radial-gradient(900px 360px at 100% 0%, rgba(29, 158, 117, 0.04), transparent 50%),
    var(--sem-bg);
}
/* 主栏吃满可用宽度，避免大屏右侧大片留白 */
.main-inner {
  max-width: none;
  width: 100%;
  padding: 12px 16px 28px;
}
.main-inner.fluid {
  max-width: none;
  padding: 10px 12px 24px;
}

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
