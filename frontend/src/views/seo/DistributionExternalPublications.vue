<script setup>
import { computed, onActivated, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { session, advisorClaims } from '../../store/session'
import { createDistributionInboxApi } from '../../api/distributionInbox.js'
import ArticlePublicationGroups from '../../components/ArticlePublicationGroups.vue'
import { createPublicationRecordsState } from './publicationGroupsState.js'
import { publicationEvidence } from './seoPublicationEvidence'
const props = defineProps({ tenantId: Number, scopeId: Number, nativeRecords: { type: Array, default: () => [] }, canViewCapture: Boolean })
const emit = defineEmits(['attempts', 'capture', 'read-error'])
const router = useRouter()
const route = useRoute()
const element = ref(null)
const version = ref(0)
const api = createDistributionInboxApi({ getIdentity: () => session.inboxIdentity, getBusiness: (module, tenant) => {
  const claims = advisorClaims(session.token)
  if (claims && (claims.scope_kind !== 'advisor_tenant' || claims.tid !== tenant)) return null
  return { token: session.token, revision: session.authRevision }
} })
const model = createPublicationRecordsState(api, () => { version.value++; emit('read-error', !!model.state.error) })
const state = computed(() => { version.value; return { ...model.state } })
const filters = ref({ month: null, source: 'all' })
const native = item => props.nativeRecords.find(row => row.id === item.native_publication_id)
const context = () => ({ tenant: props.tenantId, scope: props.scopeId, ...filters.value })
async function refresh() { await model.refresh(context()) }
function filter(values) { filters.value = values; void refresh() }
function focusRefresh() { if (document.visibilityState === 'visible') void refresh() }
function link(item) {
  return router.push({ path: '/seo/distribution-inbox', query: { receiptId: item.external_receipt_id,
    returnTo: 'publication-groups', tenantId: String(props.tenantId), scopeId: String(props.scopeId) } })
}
watch(() => [props.tenantId, props.scopeId, session.authRevision, session.token, route.query.articleId], refresh, { immediate: true })
onMounted(() => { window.addEventListener('focus', focusRefresh); document.addEventListener('visibilitychange', focusRefresh) })
onActivated(refresh)
onBeforeUnmount(() => { model.clear(); window.removeEventListener('focus', focusRefresh); document.removeEventListener('visibilitychange', focusRefresh) })
</script>
<template>
  <div ref="element"><ArticlePublicationGroups :state="state" :scope-selected="!!tenantId && !!scopeId" @refresh="refresh" @more="model.more" @previous="model.previous" @filter="filter" @link="link">
    <template #native-evidence="{ item }">{{ publicationEvidence(item) }}</template>
    <template #native-actions="{ item }"><span v-if="native(item)"><button @click="emit('attempts', native(item))">尝试记录</button><button v-if="canViewCapture" @click="emit('capture', native(item))">截图与核验证据</button></span></template>
  </ArticlePublicationGroups></div>
</template>
<style scoped>button { margin: 4px 8px; padding: 5px 8px; border: 1px solid #d1dce9; background: white; color: #225794; border-radius: 5px; cursor: pointer; }</style>
