<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import GeoDistributionInbox from '../../components/GeoDistributionInbox.vue'
import { createDistributionInboxApi } from '../../api/distributionInbox.js'
import { createGeoInboxSession } from '../../utils/geoInboxSession.js'
import { session } from '../../store/session'

const targets = ref([]), owners = ref([]), error = ref(''), identity = ref('')
const auth = createGeoInboxSession({ session, storage: sessionStorage })
const base = createDistributionInboxApi({ getIdentity: auth.identity, getBusiness: auth.business })
const api = { ...base,
  async label(module, tenant, ...args) { await auth.prepare(tenant, args.at(-1)); return base.label(module, tenant, ...args) },
  async unlabel(module, tenant, ...args) { await auth.prepare(tenant, args.at(-1)); return base.unlabel(module, tenant, ...args) },
}
let controller
watch([() => session.token, () => session.user, () => session.tenantId], async () => {
  controller?.abort(); controller = new AbortController()
  const signal = controller.signal
  auth.clear(); targets.value = []; owners.value = []; error.value = ''
  identity.value = auth.identity()?.revision || ''
  if (!identity.value) { error.value = '请重新登录人员身份后打开收件箱'; return }
  try {
    const data = await base.targets(signal)
    if (signal.aborted) return
    targets.value = (data.items || []).map(t => ({ tenantId: t.tenantId, name: t.name,
      modules: (t.modules || []).filter(m => ['seo', 'geo'].includes(m)), scopes: t.scopes || [],
    })).filter(t => t.modules.length)
    owners.value = data.inboxAdmin ? data.owners || [] : []
  } catch (e) { if (!signal.aborted) error.value = e.message }
}, { immediate: true })
onBeforeUnmount(() => { controller?.abort(); auth.clear() })
</script>

<template>
  <nav><router-link to="/geo/overview">返回 GEO 工作台</router-link> · <router-link to="/geo/external-publications">外部发布记录</router-link></nav>
  <p v-if="error" role="alert">{{ error }}</p>
  <GeoDistributionInbox v-if="identity" :api="api" :identity="identity" :targets="targets" :owners="owners" />
</template>
