<script setup>
import { useRoute, useRouter } from 'vue-router'
import { session } from '../store/session'

defineProps({
  title: { type: String, required: true },
  sub: { type: String, default: '' },
})

const route = useRoute()
const router = useRouter()

function onTenantChange(event) {
  const id = Number(event.target.value)
  if (!id || id === session.tenantId) return
  session.setTenant(id)
  if (route.path.startsWith('/geo/tasks/')) router.push('/geo/tasks')
  else if (route.path.startsWith('/geo/businesses/')) router.push('/geo/brand')
}
</script>

<template>
  <header class="geo-topbar">
    <div class="geo-topbar-copy">
      <h1>{{ title }}</h1>
      <div v-if="sub" class="sub">{{ sub }}</div>
      <slot />
    </div>
    <label class="geo-tenant-switcher">
      <span>当前客户</span>
      <select
        :value="session.tenantId || ''"
        aria-label="切换客户"
        @change="onTenantChange"
      >
        <option value="" disabled>选择客户</option>
        <option
          v-for="tenant in session.tenants"
          :key="tenant.id"
          :value="tenant.id"
        >{{ tenant.name }}</option>
      </select>
    </label>
    <div class="right">
      <slot name="actions" />
    </div>
  </header>
</template>
