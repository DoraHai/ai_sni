<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { session, advisorClaims, currentTenantId } from '../../store/session'
import { currentSeoSiteId } from './seoSiteContext'
import { createDistributionInboxApi } from '../../api/distributionInbox.js'
import DistributionInbox from './DistributionInbox.vue'

const targets = ref([])
const route = useRoute()
const router = useRouter()
const receiptId = computed(() => typeof route.query.receiptId === 'string' && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(route.query.receiptId) ? route.query.receiptId : '')
const error = ref('')
const owners = ref([])
const identityKey = computed(() => `${session.user?.id || ''}:${session.authRevision}`)
const business = new Map()
const getIdentity = () => session.inboxIdentity
async function prepareBusiness(module, tenant, signal) {
  const context = getIdentity()
  if (!context?.token) throw new Error('身份会话已失效，请重新登录')
  if (!context.scopeKind) {
    business.set(`${module}:${tenant}`, context)
    return
  }
  const response = await fetch('/api/v1/auth/select-tenant', {
    method: 'POST', headers: { Authorization: `Bearer ${context.token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ tenant_id: tenant }), credentials: 'omit', cache: 'no-store', redirect: 'error', signal,
  })
  const data = await response.json()
  if (getIdentity()?.token !== context.token || getIdentity()?.revision !== context.revision) throw new Error('身份已变化，请刷新')
  if (!response.ok) throw new Error(data?.detail?.message || '当前客户授权不可用，请刷新')
  const claims = advisorClaims(data.access_token)
  if (claims?.scope_kind !== 'advisor_tenant' || claims.tid !== tenant || String(claims.sub) !== String(context.userId)) throw new Error('客户会话无效')
  business.set(`${module}:${tenant}`, { token: data.access_token, revision: context.revision })
}
const api = createDistributionInboxApi({ getIdentity, prepareBusiness,
  getBusiness: (module, tenant) => {
    const context = business.get(`${module}:${tenant}`)
    return context?.revision === session.authRevision ? context : null
  },
})
async function reloadTargets() {
  targets.value = []; owners.value = []; error.value = ''; business.clear()
  const key = identityKey.value
  try {
    const response = await api.targets()
    if (key === identityKey.value) { targets.value = response.items; owners.value = response.owners || [] }
  } catch (e) { if (key === identityKey.value) error.value = e.message }
}
watch(identityKey, reloadTargets, { immediate: true })
function linked(row) {
  const assignment = row.assignment
  if (route.query.returnTo !== 'publication-groups' || assignment?.module !== 'seo' || row.id !== receiptId.value ||
      !Number.isSafeInteger(assignment.articleId) || !Number.isSafeInteger(assignment.scopeId) ||
      assignment.articleId < 1 || assignment.scopeId < 1) return
  if (currentTenantId.value !== assignment.tenantId) { error.value = '当前客户已变化，请重新选择客户后查看发布记录'; return }
  currentSeoSiteId.value = assignment.scopeId
  return router.push({ path: '/seo/distribution', query: { view: 'records', articleId: String(assignment.articleId) } })
}
</script>

<template>
  <p v-if="error" role="alert">{{ error }}</p>
  <DistributionInbox :api="api" :identity="identityKey" :targets="targets" :owners="owners" :receipt-id="receiptId" @linked="linked" @refresh-targets="reloadTargets" />
</template>
