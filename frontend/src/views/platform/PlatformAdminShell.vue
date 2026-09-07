<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { session } from '../../store/session'

const route = useRoute()
const router = useRouter()
const links = computed(() => [
  session.canEdit('settings.customers')
    ? { label: '客户与业务', path: '/platform/customers' }
    : null,
  session.canEdit('settings.accounts')
    ? { label: '账号', path: '/platform/accounts' }
    : null,
  session.canEdit('settings.accounts')
    ? { label: '角色与权限', path: '/platform/roles' }
    : null,
].filter(Boolean))

function leavePlatform() {
  router.push('/workspace')
}
</script>

<template>
  <div class="platform-shell">
    <header class="platform-topbar">
      <div>
        <b>G-Snipers 平台管理</b>
        <span>全局客户、账号与权限</span>
      </div>
      <div class="platform-actions">
        <span>{{ session.user?.display_name || session.user?.username }}</span>
        <el-button @click="leavePlatform">返回工作台</el-button>
      </div>
    </header>
    <div class="platform-body">
      <aside>
        <div class="platform-kicker">平台管理</div>
        <router-link
          v-for="item in links"
          :key="item.path"
          :to="item.path"
          :class="{ active: route.path === item.path }"
        >{{ item.label }}</router-link>
      </aside>
      <main>
        <router-view />
      </main>
    </div>
  </div>
</template>

<style scoped>
.platform-shell{min-height:100vh;background:#f4f6fa;color:#172033}.platform-topbar{height:64px;padding:0 24px;background:#fff;border-bottom:1px solid #e4e8f0;display:flex;align-items:center;justify-content:space-between}.platform-topbar>div:first-child{display:flex;align-items:baseline;gap:12px}.platform-topbar b{font-size:18px}.platform-topbar span,.platform-kicker{color:#697386;font-size:13px}.platform-actions{display:flex;align-items:center;gap:14px}.platform-body{display:grid;grid-template-columns:220px minmax(0,1fr);min-height:calc(100vh - 65px)}aside{padding:22px 14px;background:#fff;border-right:1px solid #e4e8f0;display:flex;flex-direction:column;gap:6px}.platform-kicker{padding:0 12px 10px;text-transform:uppercase}aside a{padding:11px 12px;border-radius:8px;color:#3d4657;text-decoration:none}aside a:hover,aside a.active{background:#eef2ff;color:#4338ca;font-weight:600}main{padding:24px;overflow:auto}@media(max-width:760px){.platform-body{grid-template-columns:1fr}aside{flex-direction:row;border-right:0;border-bottom:1px solid #e4e8f0}.platform-kicker{display:none}main{padding:14px}}
</style>
