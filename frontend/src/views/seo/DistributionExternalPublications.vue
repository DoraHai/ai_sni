<script setup>
import { computed, nextTick, onActivated, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { session, advisorClaims } from '../../store/session'
import { createDistributionInboxApi } from '../../api/distributionInbox.js'
import ArticlePublicationGroups from '../../components/ArticlePublicationGroups.vue'
import { createPublicationGroupsState } from './publicationGroupsState.js'
import { publicationEvidence } from './seoPublicationEvidence'
const props = defineProps({ tenantId: Number, scopeId: Number, nativeRecords: { type: Array, default: () => [] }, canViewCapture: Boolean })
const emit = defineEmits(['attempts', 'capture', 'read-error'])
const router = useRouter()
const route = useRoute()
const element = ref(null)
let refreshVersion = 0
const version = ref(0)
const api = createDistributionInboxApi({ getIdentity: () => session.inboxIdentity, getBusiness: (module, tenant) => {
  const claims = advisorClaims(session.token)
  if (claims && (claims.scope_kind !== 'advisor_tenant' || claims.tid !== tenant)) return null
  return { token: session.token, revision: session.authRevision }
} })
const model = createPublicationGroupsState(api, () => { version.value++; emit('read-error', !!model.state.error) })
const state = computed(() => { version.value; return { ...model.state } })
const native = item => props.nativeRecords.find(row => row.id === item.native_publication_id)
const context = () => ({ tenant: props.tenantId, scope: props.scopeId })
async function refresh() {
  const requestVersion = ++refreshVersion
  await model.refresh(context())
  if (requestVersion !== refreshVersion || model.state.error || !model.state.counts) return
  const hint = typeof route.query.articleId === 'string' && /^[1-9][0-9]{0,15}$/.test(route.query.articleId) ? Number(route.query.articleId) : null
  if (!Number.isSafeInteger(hint)) return
  const bucket = model.state.buckets.linked
  // Exact identity navigation may target an older article beyond page one.
  // Continue the authorized index; never guess a title or fabricate a parent.
  while (!bucket.items.some(row => row.group_article_id === hint) && bucket.more && !bucket.error) {
    await model.more('linked')
    if (requestVersion !== refreshVersion || model.state.error) return
  }
  const row = bucket.items.find(item => item.group_article_id === hint)
  if (!row) return
  await model.details(row)
  if (requestVersion !== refreshVersion) return
  await nextTick()
  const target = element.value?.querySelector(`[data-group-id="${hint}"]`)
  if (target) { target.open = true; target.querySelector('summary')?.focus(); target.scrollIntoView?.({ block: 'center' }) }
}
function focusRefresh() { if (document.visibilityState === 'visible') void refresh() }
function link(item) {
  return router.push({ path: '/seo/distribution-inbox', query: { receiptId: item.external_receipt_id,
    returnTo: 'publication-groups', tenantId: String(props.tenantId), scopeId: String(props.scopeId) } })
}
watch(() => [props.tenantId, props.scopeId, session.authRevision, session.token, route.query.articleId], refresh, { immediate: true })
onMounted(() => { window.addEventListener('focus', focusRefresh); document.addEventListener('visibilitychange', focusRefresh) })
onActivated(refresh)
onBeforeUnmount(() => { refreshVersion++; model.clear(); window.removeEventListener('focus', focusRefresh); document.removeEventListener('visibilitychange', focusRefresh) })
</script>
<template>
  <div ref="element"><ArticlePublicationGroups :state="state" :scope-selected="!!tenantId && !!scopeId" @refresh="refresh" @more="model.more" @details="model.details" @link="link">
    <template #native-actions="{ item }"><p v-if="native(item)">{{ publicationEvidence(native(item)) }} <button @click="emit('attempts', native(item))">尝试记录</button><button v-if="canViewCapture" @click="emit('capture', native(item))">截图与核验证据</button></p></template>
  </ArticlePublicationGroups></div>
</template>
<style scoped>button { margin: 4px 8px; padding: 5px 8px; border: 1px solid #d1dce9; background: white; color: #225794; border-radius: 5px; cursor: pointer; }</style>
