<script setup>
import { onMounted, ref } from 'vue'
import { fetchMe } from '../../src/api/auth'
import { fetchGeoTenants } from '../../src/api/geo'
import { session } from '../../src/store/session'

const ready = ref(false)

async function bootstrapSession() {
  try {
    const [me, tenants] = await Promise.all([
      session.isLoggedIn ? fetchMe() : Promise.resolve(null),
      fetchGeoTenants(),
    ])
    if (me?.user) session.refreshUser(me.user)
    session.setTenants(tenants.tenants || [])
  } catch {
    session.setTenants(session.tenants || [])
  } finally {
    ready.value = true
  }
}

onMounted(bootstrapSession)
</script>

<template>
  <router-view v-if="ready" />
  <div v-else class="geo-boot" role="status" aria-live="polite" aria-label="GEO 工作台加载中">
    <div class="geo-boot__panel">
      <div class="geo-boot__mark" aria-hidden="true">G</div>
      <div class="geo-boot__title">GEO 增长</div>
      <div class="geo-boot__status"><span class="geo-boot__pulse" />正在载入客户工作区</div>
    </div>
  </div>
</template>
