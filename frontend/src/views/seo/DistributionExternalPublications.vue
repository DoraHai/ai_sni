<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { session, advisorClaims } from '../../store/session'
import { createDistributionInboxApi } from '../../api/distributionInbox.js'
const props = defineProps({ tenantId: Number, scopeId: Number })
const items = ref([])
const error = ref('')
let controller
const api = createDistributionInboxApi({ getIdentity: () => session.inboxIdentity, getBusiness: (module, tenant) => {
  const claims = advisorClaims(session.token)
  if (claims && (claims.scope_kind !== 'advisor_tenant' || claims.tid !== tenant)) return null
  return { token: session.token, revision: session.authRevision }
} })
watch(() => [props.tenantId, props.scopeId, session.authRevision], async () => {
  controller?.abort(); controller = new AbortController()
  const signal = controller.signal
  items.value = []; error.value = ''
  if (!props.tenantId) return
  try {
    const result = await api.publications('seo', props.tenantId, props.scopeId || null, signal)
    if (!signal.aborted) items.value = result.items
  } catch (e) { if (!signal.aborted) error.value = e.message }
}, { immediate: true })
onBeforeUnmount(() => controller?.abort())
const results = { success: '操作人报告成功', failed: '失败', risk_control: '平台风控', verification_required: '需验证', pending_review: '审核中', unknown: '结果未知' }
</script>
<template>
  <section class="external-records">
    <h2>外部回传记录</h2>
    <p>收到回传与页面正文核验分别展示；这些记录不计入稿件验收。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-else-if="!items.length">暂无外部回传记录</p>
    <article v-for="row in items" :key="row.id">
      <p>外部回传 · {{ row.platform }} · {{ row.title || '未提供标题' }} · 发布账号：{{ row.publishedAccount || '未提供' }}</p>
      <a v-if="row.publicUrl" :href="row.publicUrl" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">{{ row.publicUrl }}</a>
      <p>已收到 · {{ results[row.result] }} · {{ row.verificationStatus === 'unlinked' ? '未关联稿件，不核验正文' : '正文暂不可核验' }} · {{ row.occurredAt }}</p>
    </article>
  </section>
</template>
<style scoped>.external-records { padding: 20px; margin-bottom: 16px; background: white; border: 1px solid #dbe3ef; border-radius: 12px; overflow-wrap: anywhere; } article { border-top: 1px solid #dbe3ef; padding: 10px 0; }</style>
