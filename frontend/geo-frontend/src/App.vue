<script setup>
import { onMounted, ref } from 'vue'
import { fetchMe } from '../../src/api/auth'
import client from '../../src/api/client'
import { fetchGeoTenants } from '../../src/api/geo'
import { session } from '../../src/store/session'
import { bootstrapGeoSession, GEO_ADVISOR_SELECT_URL } from '../../src/utils/geoAdvisorTenant.js'

const ready = ref(false)
const guidance = ref(null)

async function bootstrapSession() {
  try {
    guidance.value = await bootstrapGeoSession({
      session, fetchMe,
      readSession: () => Promise.all([
        session.isLoggedIn ? fetchMe() : Promise.resolve(null),
        fetchGeoTenants(),
      ]),
      applySession: (me, tenants) => {
        if (me?.user) session.refreshUser(me.user)
        session.setTenants(tenants.tenants || [])
      },
      listAuthorizedCustomers: () => client.get('/api/v1/auth/tenants'),
      selectTenant: (tenantId) => client.post('/api/v1/auth/select-tenant', { tenant_id: tenantId }),
    })
  } catch {
    guidance.value = { message: '暂时无法读取客户信息，请刷新页面重试', selectCustomer: true }
  } finally {
    ready.value = true
  }
}

onMounted(bootstrapSession)
</script>

<template>
  <template v-if="!guidance">
    <router-view v-if="ready" />
    <div v-else class="geo-boot" role="status" aria-live="polite" aria-label="GEO 工作台加载中">
      <div class="geo-boot__panel">
        <div class="geo-boot__mark" aria-hidden="true">G</div>
        <div class="geo-boot__title">GEO 增长</div>
        <div class="geo-boot__status"><span class="geo-boot__pulse" />正在载入客户工作区</div>
      </div>
    </div>
  </template>
  <div v-else class="geo-boot" role="alert">
    <div class="geo-boot__panel">
      <div class="geo-boot__title">GEO 增长</div>
      <p>{{ guidance.message }}</p>
      <el-button v-if="guidance.selectCustomer" tag="a" :href="GEO_ADVISOR_SELECT_URL" type="primary">去选择客户</el-button>
    </div>
  </div>
</template>
