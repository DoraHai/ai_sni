<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { changePassword, fetchMe } from '../../api/auth'
import { fetchSeoTenants } from '../../api/seo'
import { redirectToLogin } from '../../auth/loginRedirect'
import { session } from '../../store/session'

const route = useRoute()
const router = useRouter()
const mobileOpen = ref(false)

const groups = [
  {
    label: '基础资产',
    index: '00',
    items: [
      { label: '网站管理', path: '/seo/sites', perm: 'seo.assets', mark: 'W' },
      { label: '品牌资产中心', path: '/seo/brand-assets', perm: 'seo.keywords', mark: 'B' },
    ],
  },
  {
    label: '今日概览',
    index: '01',
    items: [
      { label: 'SEO 工作台', path: '/seo/dashboard', perm: 'seo.dashboard', mark: '▦' },
      { label: '异常提醒', path: '/seo/alerts', perm: 'seo.alerts', mark: '!' },
    ],
  },
  {
    label: '关键词资产',
    index: '02',
    items: [
      { label: '关键词管理', path: '/seo/keywords', perm: 'seo.keywords', mark: '⌕' },
      { label: '排名监控', path: '/seo/rankings', perm: 'seo.keywords', mark: '↗' },
      { label: '趋势总览', path: '/seo/trends', perm: 'seo.keywords', mark: '⌁' },
      { label: '竞品表现', path: '/seo/competitors', perm: 'seo.competitors', mark: '≋' },
    ],
  },
  {
    label: '内容增长',
    index: '03',
    items: [
      { label: '原创文章', path: '/seo/content/articles', perm: 'seo.content', mark: 'Aa' },
      { label: '文章改写', path: '/seo/content/rewrites', perm: 'seo.content', mark: '↻' },
      { label: '问答运营', path: '/seo/content/qa', perm: 'seo.content', mark: 'Q' },
      { label: '分发平台', path: '/seo/distribution', perm: 'seo.content', mark: '⇧' },
    ],
  },
  {
    label: '站内优化',
    index: '04',
    items: [
      { label: 'TDK / 站内优化', path: '/seo/site', perm: 'seo.site', mark: 'T' },
      { label: '内外链管理', path: '/seo/links', perm: 'seo.links', mark: '链' },
    ],
  },
]

const visibleGroups = computed(() => {
  const devMode = !session.isLoggedIn
  return groups
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => devMode || session.canView(item.perm)),
    }))
    .filter((group) => group.items.length)
})

const title = computed(() => route.meta.title || 'SEO 工作台')
const workflow = computed(() => route.meta.workflow || '搜索增长')
const tenantName = computed(() => (
  session.tenants.find((tenant) => tenant.id === session.tenantId)?.name
  || (session.tenantId ? `客户 #${session.tenantId}` : '请选择客户')
))
const hasSeoTenant = computed(() => (
  session.tenants.some((tenant) => tenant.id === session.tenantId)
))
const accountName = computed(() => (
  session.user?.display_name || session.user?.username || '本地运维'
))
const accountMeta = computed(() => {
  const username = session.user?.username
  const role = session.user?.role_label || (session.isLoggedIn ? 'SEO 用户' : '本地 Key')
  const roleState = session.canManage && !role.includes('管理') ? `${role} · 管理员` : role
  return username && username !== accountName.value ? `${username} · ${roleState}` : roleState
})
const initials = computed(() => Array.from(String(accountName.value)).slice(0, 2).join(''))
const tenantViewKey = computed(() => `${route.fullPath}:${session.tenantId || 'none'}`)
const bannerDescriptions = {
  '网站管理': '维护当前客户的 SEO 网站边界，关键词、排名、页面和内容数据均按网站归属管理。',
  'SEO 工作台': '汇总当前客户的搜索表现、关键词机会、页面健康与内容增长进展。',
  '异常提醒': '集中处理排名下降、承接页缺失、站内技术问题与高风险外链。',
  '品牌资产中心': '维护品牌名称与官方资产，为搜索结果识别和内容生产提供统一依据。',
  '关键词管理': '管理当前客户的关键词资产、分组、意图、目标页面和监控状态。',
  '关键词详情': '查看关键词排名历史、承接页面与可执行的优化诊断。',
  '排名监控': '按网站、搜索引擎与设备跟踪当前客户的自然排名变化。',
  '趋势总览': '从词库资产视角观察首页覆盖、排名分布与周期净增长。',
  '站内优化': '管理页面 TDK、承接关系与技术检测结果，形成可执行优化队列。',
  '原创文章': '围绕目标关键词创建、编辑并跟踪当前客户的原创内容。',
  '文章改写': '基于已有事实和关键词完成内容重构，并保留发布记录。',
  '问答运营': '围绕用户问题生产结构清晰、可持续维护的搜索问答内容。',
  '在线编辑器': '在当前客户与网站范围内完成内容 Brief、正文编辑和发布登记。',
  '问答编辑器': '在当前客户与网站范围内完成问答内容编辑和发布登记。',
  '分发平台': '统一管理内容分发连接、发布任务、结果记录与失败反馈。',
  '内外链管理': '维护站内链接图谱与外链资产，识别孤立页面和链接风险。',
  '竞品监控': '跟踪当前客户的搜索竞品、排名差距与内容变化。',
}
const bannerDescription = computed(() => (
  !session.tenantId
    ? '请先在顶部选择已开通 SEO 的客户后再查看业务数据。'
    : bannerDescriptions[title.value] || `当前数据范围：${tenantName.value}`
))

function active(path) {
  if (path === '/seo/keywords') return route.path === '/seo/keywords' || route.path.startsWith('/seo/keywords/')
  if (path === '/seo/content/articles') return route.path === path || (route.path === '/seo/content/editor' && route.query.type !== 'rewrite')
  if (path === '/seo/content/rewrites') return route.path === path || (route.path === '/seo/content/editor' && route.query.type === 'rewrite')
  if (path === '/seo/content/qa') return route.path === path || route.path === '/seo/content/answer-editor'
  return route.path === path
}

function navigate(path) {
  mobileOpen.value = false
  router.push(path)
}

async function loadContext() {
  if (!session.isLoggedIn) return
  const [me, tenants] = await Promise.allSettled([fetchMe(), fetchSeoTenants()])
  if (me.status === 'fulfilled') session.refreshUser(me.value.user)
  if (tenants.status === 'fulfilled') session.setTenants(tenants.value.tenants || [])
}

function onTenantChange(value) {
  if (!value || value === session.tenantId) return
  session.setTenant(value)
  if (route.path.startsWith('/seo/keywords/')) {
    router.push('/seo/keywords')
  } else if (route.path === '/seo/content/editor') {
    router.push(route.query.type === 'rewrite' ? '/seo/content/rewrites' : '/seo/content/articles')
  } else if (route.path === '/seo/content/answer-editor') {
    router.push('/seo/content/qa')
  }
}

async function onUserCommand(command) {
  if (command === 'logout') {
    session.logout()
    redirectToLogin()
    return
  }
  if (command !== 'password') return
  let oldPassword
  let newPassword
  try {
    ;({ value: oldPassword } = await ElMessageBox.prompt('请输入原密码', '修改密码', { inputType: 'password' }))
    ;({ value: newPassword } = await ElMessageBox.prompt('请输入新密码（至少 8 位）', '修改密码', {
      inputType: 'password',
      inputPattern: /^.{8,}$/,
      inputErrorMessage: '至少 8 位',
    }))
  } catch {
    return
  }
  try {
    await changePassword({ oldPassword, newPassword })
    ElMessage.success('密码已修改')
  } catch (error) {
    ElMessage.error(error.message)
  }
}

watch(() => route.path, () => { mobileOpen.value = false })
onMounted(loadContext)
</script>

<template>
  <div class="seo-workspace">
    <button class="mobile-menu" type="button" aria-label="打开导航" @click="mobileOpen = !mobileOpen">
      <span /> <span /> <span />
    </button>
    <div v-if="mobileOpen" class="mobile-shade" @click="mobileOpen = false" />

    <aside class="seo-rail" :class="{ open: mobileOpen }">
      <div class="seo-brand" @click="navigate('/seo/dashboard')">
        <div class="brand-glyph" aria-hidden="true"><span>S</span></div>
        <div>
          <strong>SEO 工作台</strong>
          <small>搜索引擎获客</small>
        </div>
      </div>

      <nav class="seo-nav" aria-label="SEO 功能导航">
        <section v-for="group in visibleGroups" :key="group.label" class="nav-group">
          <div class="nav-label">{{ group.label }}</div>
          <button
            v-for="item in group.items"
            :key="item.path"
            type="button"
            :class="{ active: active(item.path) }"
            @click="navigate(item.path)"
          >
            <span class="nav-mark">{{ item.mark }}</span>
            <span>{{ item.label }}</span>
          </button>
        </section>
      </nav>

      <div class="rail-footer">
        <a href="/monitor/dashboard"><span>SEM</span>搜索广告工作台</a>
        <a href="/deal-sniper/geo/dashboard.html#/geo/overview"><span>GEO</span>生成式搜索工作台</a>
        <a href="/diagnostic-center/"><span>DX</span>诊断中心</a>
        <a class="portal-link" href="https://gsnipers.snipers.com.cn/deal-sniper/portal">← 返回平台门户</a>
      </div>
    </aside>

    <div class="seo-stage">
      <header class="seo-topbar">
        <div class="page-identity">
          <small>SEO 增长</small>
          <b>/</b>
          <strong>{{ title }}</strong>
        </div>
        <div class="topbar-actions">
          <label class="tenant-select">
            <span>当前客户</span>
            <select :value="session.tenantId || ''" @change="onTenantChange(Number($event.target.value))">
              <option v-if="!session.tenants.length" value="" disabled>暂无已开通 SEO 的客户</option>
              <option v-for="tenant in session.tenants" :key="tenant.id" :value="tenant.id">{{ tenant.name }}</option>
            </select>
          </label>
          <div class="seo-module-state" :class="{ 'is-empty': !hasSeoTenant }" title="仅展示已开通且在有效期内的 SEO 客户">
            <i />
            <span>{{ hasSeoTenant ? 'SEO 已开通' : '待选择 SEO 客户' }}</span>
          </div>
          <div class="seo-account-state">
            <span class="seo-account-state-label">登录账号</span>
            <span class="seo-account-state-copy">
              <strong>{{ accountName }}</strong>
              <small>{{ accountMeta }}</small>
            </span>
          </div>
          <el-dropdown v-if="session.isLoggedIn" trigger="click" @command="onUserCommand">
            <button type="button" class="seo-account-avatar" :title="accountName">{{ initials }}</button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="password">修改密码</el-dropdown-item>
                <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <div v-else class="seo-account-avatar" title="本地 Key">{{ initials }}</div>
        </div>
      </header>
      <section class="seo-page-banner">
        <div>
          <span>{{ workflow }} · SEO WORKSPACE</span>
          <h1>{{ title }}</h1>
          <p>{{ bannerDescription }}</p>
        </div>
        <div class="seo-page-banner-tenant">
          <small>当前数据范围</small>
          <strong>{{ tenantName }}</strong>
        </div>
      </section>
      <main class="seo-content">
        <router-view :key="tenantViewKey" />
      </main>
    </div>
  </div>
</template>

<style scoped>
.seo-workspace {
  --accent: #2658d7;
  --accent-soft: #edf3ff;
  --line: #e8eaf0;
  --paper: #f5f7fb;
  min-height: 100vh;
  background: var(--paper);
  color: #17233d;
  font-family: -apple-system, "PingFang SC", "Microsoft YaHei", "Segoe UI", Roboto, sans-serif;
}
.seo-rail {
  position: fixed;
  inset: 0 auto 0 0;
  z-index: 30;
  width: 216px;
  padding: 16px 10px;
  display: flex;
  flex-direction: column;
  gap: 1px;
  overflow-y: auto;
  background: #fff;
  color: #1e2330;
  border-right: 1px solid var(--line);
}
.seo-rail::-webkit-scrollbar { width: 6px; }
.seo-rail::-webkit-scrollbar-thumb { background: #e2e4ea; border-radius: 3px; }
.seo-brand {
  padding: 4px 8px 14px;
  display: flex;
  align-items: center;
  gap: 9px;
  cursor: pointer;
}
.brand-glyph {
  width: 28px;
  height: 28px;
  border-radius: 7px;
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
}
.brand-glyph span { color: white; font-size: 13px; font-weight: 800; }
.seo-brand strong { display: block; font-size: 15px; font-weight: 700; }
.seo-brand small { display: block; margin-top: 1px; color: #6b7280; font-size: 10.5px; font-weight: 500; }
.seo-nav { flex: 1; padding-bottom: 20px; }
.nav-group { margin: 0; }
.nav-label { padding: 13px 10px 5px; color: #9aa1ad; font-size: 10.5px; font-weight: 600; letter-spacing: .06em; }
.nav-group button {
  width: 100%;
  min-height: 34px;
  padding: 6px 10px;
  border: 0;
  border-radius: 8px;
  display: flex;
  align-items: center;
  gap: 9px;
  background: transparent;
  color: #5b6270;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  line-height: 1.35;
  text-align: left;
  transition: .15s ease;
}
.nav-group button:hover, .nav-group button.active { color: var(--accent); background: var(--accent-soft); }
.nav-group button.active { font-weight: 600; }
.nav-mark { width: 16px; color: inherit; font-size: 13.5px; text-align: center; }
.rail-footer { padding-top: 8px; border-top: 1px solid var(--line); }
.rail-footer a { min-height: 32px; padding: 6px 10px; display: flex; align-items: center; gap: 9px; border-radius: 8px; color: #6b7280; font-size: 12px; text-decoration: none; }
.rail-footer a:hover { color: var(--accent); background: var(--accent-soft); }
.rail-footer a span { width: 24px; color: #8b95a5; font-size: 10px; font-weight: 700; }
.rail-footer .portal-link { margin-top: 4px; border-top: 1px solid var(--line); border-radius: 0; color: #6b7280; }
.seo-stage { min-height: 100vh; margin-left: 216px; display: flex; flex-direction: column; }
.seo-topbar {
  position: sticky;
  top: 0;
  z-index: 20;
  min-height: 68px;
  padding: 10px 24px;
  display: flex;
  align-items: center;
  gap: 18px;
  border-bottom: 1px solid #e7e9f0;
  background: rgba(255, 255, 255, .94);
  box-shadow: 0 1px 0 rgba(15, 23, 42, .02);
  backdrop-filter: blur(14px);
}
.page-identity { min-width: 0; display: flex; align-items: center; gap: 9px; color: #9aa1ad; font-size: 12px; white-space: nowrap; }
.page-identity b { color: #d5d8e0; font-weight: 500; }
.page-identity strong { overflow: hidden; color: #3f4654; font-size: 13px; font-weight: 650; text-overflow: ellipsis; }
.topbar-actions { margin-left: auto; display: flex; align-items: center; gap: 10px; }
.tenant-select {
  height: 42px;
  padding: 0 8px 0 13px;
  border: 1px solid #e1e4ec;
  border-radius: 11px;
  display: flex;
  align-items: center;
  gap: 8px;
  background: #fff;
  color: #8a92a3;
  font-size: 11px;
  white-space: nowrap;
}
.tenant-select select {
  min-width: 136px;
  max-width: 210px;
  padding: 7px 28px 7px 8px;
  border: 0;
  outline: 0;
  background: transparent;
  color: #273654;
  font: inherit;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}
.seo-module-state {
  height: 34px;
  padding: 0 11px;
  border: 1px solid #d9eee2;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  background: #f4fbf7;
  color: #25815a;
  font-size: 11px;
  font-weight: 650;
  white-space: nowrap;
}
.seo-module-state i { width: 7px; height: 7px; border-radius: 50%; background: #35b979; box-shadow: 0 0 0 4px rgba(53, 185, 121, .12); }
.seo-module-state.is-empty { border-color: #e5e7eb; background: #f8f9fb; color: #7c8493; }
.seo-module-state.is-empty i { background: #a8afbb; box-shadow: 0 0 0 4px rgba(168, 175, 187, .12); }
.seo-account-state { min-width: 0; padding-left: 12px; border-left: 1px solid #e5e7ed; display: flex; align-items: center; gap: 9px; }
.seo-account-state-label { color: #9aa1ad; font-size: 10.5px; white-space: nowrap; }
.seo-account-state-copy { min-width: 0; }
.seo-account-state-copy strong,
.seo-account-state-copy small { display: block; max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.seo-account-state-copy strong { color: #353b48; font-size: 12px; font-weight: 700; }
.seo-account-state-copy small { margin-top: 2px; color: #98a0af; font-size: 9.5px; }
.seo-account-avatar {
  width: 34px;
  height: 34px;
  padding: 0;
  border: 0;
  border-radius: 10px;
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  box-shadow: 0 5px 14px rgba(37, 99, 235, .2);
  color: #fff;
  font-size: 11px;
  font-weight: 750;
  cursor: pointer;
}
.seo-page-banner {
  min-height: 142px;
  margin: 20px 24px 0;
  padding: 26px 30px;
  border: 1px solid #dbe5fa;
  border-radius: 18px;
  display: flex;
  align-items: center;
  gap: 30px;
  background:
    radial-gradient(circle at 88% 24%, rgba(255,255,255,.95) 0 5%, transparent 5.5%),
    linear-gradient(118deg, #eef4ff 0%, #f8fbff 54%, #e7efff 100%);
  box-shadow: 0 14px 34px rgba(31, 73, 155, .08);
}
.seo-page-banner > div:first-child { min-width: 0; }
.seo-page-banner span { color: #4770c6; font-size: 10px; font-weight: 750; letter-spacing: .12em; }
.seo-page-banner h1 { margin: 8px 0 7px; color: #172b4d; font-size: clamp(23px, 2.2vw, 31px); line-height: 1.15; }
.seo-page-banner p { max-width: 760px; margin: 0; color: #63718a; font-size: 13px; line-height: 1.7; }
.seo-page-banner-tenant { min-width: 180px; margin-left: auto; padding: 14px 16px; border: 1px solid rgba(140, 169, 224, .34); border-radius: 12px; background: rgba(255,255,255,.68); }
.seo-page-banner-tenant small,
.seo-page-banner-tenant strong { display: block; }
.seo-page-banner-tenant small { color: #8a98ae; font-size: 10px; }
.seo-page-banner-tenant strong { margin-top: 5px; overflow: hidden; color: #273d66; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.seo-content { min-width: 0; flex: 1; }
.mobile-menu { display: none; }
@media (max-width: 900px) {
  .seo-rail { transform: translateX(-105%); transition: transform .22s ease; }
  .seo-rail.open { transform: translateX(0); }
  .seo-stage { margin-left: 0; }
  .seo-topbar { min-height: 64px; padding: 10px 12px 10px 58px; }
  .page-identity, .seo-module-state, .seo-account-state { display: none; }
  .topbar-actions { width: 100%; }
  .tenant-select { min-width: 0; flex: 1; }
  .tenant-select select { min-width: 0; width: 100%; }
  .seo-page-banner { min-height: 126px; margin: 14px 14px 0; padding: 22px; }
  .seo-page-banner-tenant { display: none; }
  .mobile-menu { position: fixed; top: 15px; left: 16px; z-index: 45; width: 34px; height: 32px; padding: 7px; border: 1px solid #dce3ee; border-radius: 8px; display: grid; align-content: space-around; background: white; }
  .mobile-menu span { height: 2px; border-radius: 2px; background: #263650; }
  .mobile-shade { position: fixed; inset: 0; z-index: 25; background: rgba(9,16,30,.38); }
}
@media (max-width: 620px) {
  .tenant-select > span { display: none; }
  .seo-page-banner { border-radius: 14px; }
}
</style>
