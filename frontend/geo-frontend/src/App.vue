<script setup>
import { onMounted, ref } from 'vue'
import { fetchMe, fetchTenants } from '../../src/api/auth'
import { session } from '../../src/store/session'

const ready = ref(!session.isLoggedIn)

async function bootstrapSession() {
  if (!session.isLoggedIn) {
    ready.value = true
    return
  }

  try {
    const [me, tenants] = await Promise.all([fetchMe(), fetchTenants()])
    session.refreshUser(me.user)
    session.setTenants(tenants.tenants || [])
  } finally {
    ready.value = true
  }
}

onMounted(bootstrapSession)
</script>

<template>
  <div v-if="!ready" class="geo-boot" role="status" aria-live="polite" aria-label="GEO 工作台加载中">
    <div class="geo-boot__panel">
      <div class="geo-boot__mark" aria-hidden="true">G</div>
      <div class="geo-boot__title">GEO 增长</div>
      <div class="geo-boot__status"><span class="geo-boot__pulse" />正在载入客户工作区</div>
    </div>
  </div>
  <router-view v-else />
</template>
