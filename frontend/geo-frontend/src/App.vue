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
  <router-view v-if="ready" />
</template>
