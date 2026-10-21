<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { session } from '../../store/session'
import { createDistributionInboxApi } from '../../api/distributionInbox.js'
import { advisorClaims } from '../../utils/geoAdvisorTenant.js'
import { geoAdvisorProject } from '../../store/geoAdvisorProject.js'

const items = ref([]), error = ref(''), loading = ref(false)
const api = createDistributionInboxApi({ getBusiness: (_module, tenant) => {
  const claims = advisorClaims(session.token)
  if (tenant !== session.tenantId || (claims && (claims.scope_kind !== 'advisor_tenant' || claims.tid !== tenant))) return null
  return { token: session.token, revision: `${session.token}:${session.tenantId}:${geoAdvisorProject.projectId}` }
} })
let controller
watch([() => session.token, () => session.tenantId, () => geoAdvisorProject.projectId], async () => {
  controller?.abort(); controller = new AbortController()
  const signal = controller.signal
  items.value = []; error.value = ''; loading.value = false
  if (!session.tenantId) return
  loading.value = true
  try {
    const data = await api.publications(session.tenantId, geoAdvisorProject.projectId || null, signal)
    if (!signal.aborted) items.value = data.items
  } catch (e) { if (!signal.aborted) error.value = e.message }
  finally { if (!signal.aborted) loading.value = false }
}, { immediate: true })
onBeforeUnmount(() => controller?.abort())
const results = { success: '操作人报告成功', failed: '失败', risk_control: '平台风控', verification_required: '需验证', pending_review: '审核中', unknown: '结果未知' }
function safeLink(value) {
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? value : null } catch { return null }
}
</script>

<template>
  <main>
    <h1>GEO 发布记录 · 外部回传</h1>
    <router-link to="/distribution-inbox">多号通回传：待标客户、改标或撤销</router-link>
    <p>收到回传与操作人报告结果分别展示。未关联稿件不核验正文；这些记录不计入原生稿件验收。</p>
    <p v-if="error" role="alert">{{ error }}</p><p v-if="loading" role="status">正在读取</p>
    <p v-else-if="!items.length">暂无当前范围内的外部回传记录<br />
      <span>没选项目的回传不会出现在这里，请到多号通回传收件箱补选项目。</span>
    </p>
    <article v-for="row in items" :key="row.id">
      <h2>{{ row.title || '未提供标题' }} <small>外部回传</small></h2>
      <p>{{ row.platform }} · 发布账号：{{ row.publishedAccount || '未提供' }} · {{ results[row.result] || '结果未知' }}</p>
      <a v-if="safeLink(row.publicUrl)" :href="safeLink(row.publicUrl)" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">{{ row.publicUrl }}</a>
      <p>操作人报告时间：{{ row.occurredAt }} · 收到时间：{{ row.receivedAt }}</p>
      <p>{{ row.assignment?.scopeId ? `项目 #${row.assignment.scopeId}` : '范围待补' }} · {{ row.assignment?.articleId ? '已关联固定版本稿件 · 正文暂不可核验' : '未关联稿件 · 不核验正文' }}</p>
    </article>
  </main>
</template>

<style scoped>
main { padding: 24px; } article { padding: 16px; margin: 16px 0; border: 1px solid #dbe3ef; border-radius: 12px; overflow-wrap: anywhere; } small { font-size: 14px; color: #526b84; }
</style>
