<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { changePassword } from '../api/auth'
import { session } from '../store/session'
import GeoObservationPeriod from './GeoObservationPeriod.vue'

defineProps({
  title: { type: String, required: true },
  sub: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  showPeriod: { type: Boolean, default: true },
})

const router = useRouter()
const tenantHint = computed(() => {
  if (session.tenantId) return ''
  if ((session.tenants || []).length) return '请在左侧选择客户后再看数据'
  return ''
})
const initials = computed(() => {
  const name = String(session.user?.display_name || '').trim()
  if (name) return Array.from(name).slice(0, 2).join('')
  return 'GEO'
})

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
  <div class="geo-wb" v-loading="loading">
    <header class="geo-topbar">
      <div class="geo-topbar-copy">
        <h1>{{ title }}</h1>
        <div v-if="tenantHint" class="sub">{{ tenantHint }}</div>
        <div v-else-if="sub" class="sub">{{ sub }}</div>
      </div>
      <div class="right">
        <GeoObservationPeriod v-if="showPeriod" />
        <slot name="actions" />
        <el-dropdown v-if="session.isLoggedIn" trigger="click" @command="onUserCommand">
          <button type="button" class="geo-avatar" :title="session.user?.display_name">{{ initials }}</button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="password">修改密码</el-dropdown-item>
              <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <div v-else class="geo-avatar" title="本地 Key">{{ initials }}</div>
      </div>
    </header>
    <div class="geo-content">
      <slot />
    </div>
  </div>
</template>
