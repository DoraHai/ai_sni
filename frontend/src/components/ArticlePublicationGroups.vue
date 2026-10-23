<script setup>
import { computed, onActivated, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { session } from '../store/session'
import { advisorClaims } from '../utils/geoAdvisorTenant.js'
import { createDistributionInboxApi } from '../api/distributionInbox.js'
import { publicationTime, reportedResult, safePublicationLink } from '../utils/articlePublicationGroups.js'

import { createPublicationRecordsState, publicationPlatform } from '../utils/geoPublicationRecords.js'

const props = defineProps({ tenantId: Number, projectId: Number, taskId: Number, taskTitle: String, focusArticleId: Number })
const revision = ref(0), source = ref('all'), month = ref('')
const authRevision = () => `${session.token}:${session.tenantId}:${JSON.stringify(session.permissions)}`
const api = createDistributionInboxApi({ getBusiness: (_module, tenant) => {
  const claims = advisorClaims(session.token)
  if (tenant !== session.tenantId || (claims && (claims.scope_kind !== 'advisor_tenant' || claims.tid !== tenant))) return null
  return { token: session.token, revision: authRevision() }
} })
const model = createPublicationRecordsState(api, () => { revision.value++ })
const state = computed(() => { revision.value; return { ...model.state } })
function refresh() {
  return model.refresh({ tenantId: props.tenantId, projectId: props.projectId, taskId: props.taskId,
    source: source.value, month: month.value })
}
watch([() => props.tenantId, () => props.projectId, () => props.taskId, authRevision, source, month], refresh, { immediate: true, flush: 'sync' })
let activeOnce = false
onActivated(() => { if (activeOnce) refresh(); activeOnce = true })
const activate = () => { if (document.visibilityState === 'visible') refresh() }
onMounted(() => { window.addEventListener('focus', activate); document.addEventListener('visibilitychange', activate) })
onBeforeUnmount(() => { model.clear(); window.removeEventListener('focus', activate); document.removeEventListener('visibilitychange', activate) })
function taskLink(id) { return { path: `/geo/tasks/${id}`, query: { tenant_id: props.tenantId, project_id: props.projectId } } }
function inboxLink(row) { return { path: '/distribution-inbox', query: { receipt_id: row.external_receipt_id,
  tenant_id: props.tenantId, project_id: props.projectId, ...(props.taskId ? { task_id: props.taskId } : {}) } } }
</script>

<template>
  <section class="publication-groups" aria-label="发布记录">
    <header class="pg-heading">
      <div><span class="pg-eyebrow">项目 #{{ projectId }} · 只读</span><h2>{{ taskId ? '本任务发布记录' : '发布记录' }}</h2></div>
      <button type="button" @click="refresh">刷新</button>
    </header>
    <p class="pg-note">多号通回传仅作发布记录展示，不计入原生验收、报表和导出。</p>
    <p v-if="state.counts" class="pg-counts">系统原生登记 <b>{{ state.counts.native_records }}</b> 条（项目原生口径）</p>
    <div class="pg-filters">
      <label>月份 <input v-model="month" type="month" aria-label="月份" /></label>
      <label>来源 <select v-model="source" aria-label="来源"><option value="all">全部</option><option value="native">系统发布</option><option value="external_report">多号通回传</option></select></label>
      <button v-if="month" type="button" @click="month = ''">全部月份</button>
    </div>
    <p v-if="state.error" role="alert" class="pg-error">读取不完整：{{ state.error }} <button type="button" @click="refresh">重新读取</button></p>
    <p v-if="state.loading" role="status">正在读取发布记录…</p>
    <div class="pg-table-wrap">
      <table><thead><tr><th>文章</th><th>平台</th><th>连接 / 发布账号</th><th>发布链接</th><th>发布依据</th><th>时间（北京时间）</th><th>操作</th></tr></thead>
        <tbody><tr v-for="row in state.items" :key="row.source_key" :data-source-key="row.source_key">
          <td><strong>{{ row.title || '未提供标题' }}</strong><small v-if="row.association_invalid">关联异常，需核对</small></td>
          <td>{{ publicationPlatform(row.channel) }}</td><td>{{ row.account || '未提供' }}</td>
          <td><a v-if="safePublicationLink(row.url)" :href="safePublicationLink(row.url)" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">{{ row.url }}</a><span v-else>暂无安全链接</span></td>
          <td><span class="pg-source" :class="{ external: row.source === 'external_report' }">{{ row.source === 'native' ? '系统发布' : '多号通回传' }}</span>
            <small v-if="row.source === 'native' && row.has_external_report">也有多号通回传</small>
            <small>{{ row.source === 'external_report' ? reportedResult(row.status) : ({ published: '已发布', pending: '待发布', failed: '失败' })[row.status] || row.status }}</small>
          </td><td class="pg-time">{{ publicationTime(row.event_at) }}</td>
          <td><router-link v-if="row.task_id" :to="taskLink(row.task_id)">查看任务</router-link><router-link v-if="row.can_label && row.external_receipt_id" :to="inboxLink(row)">去关联稿件</router-link></td>
        </tr><tr v-if="!state.items.length && !state.error && !state.loading"><td colspan="7">当前范围暂无符合筛选的发布记录。</td></tr></tbody>
      </table>
    </div>
    <nav v-if="state.counts" class="pg-pagination" aria-label="发布记录分页">
      <button type="button" :disabled="state.loading || state.page <= 1" @click="model.read(-1)">上一页</button>
      <span>第 {{ state.page }} / {{ Math.max(1, Math.ceil(state.counts.filtered_records / 20)) }} 页 · 每页 20 条 · 共 {{ state.counts.filtered_records }} 条</span>
      <button type="button" :disabled="state.loading || !state.next" @click="model.read(1)">下一页</button>
    </nav>
    <p class="pg-note">按时间倒序。没选项目的回传请到多号通回传收件箱补选项目。</p>
  </section>
</template>
<style scoped>
.publication-groups{margin:20px 0;padding:22px;border:1px solid #dce3ee;border-radius:14px;background:white;color:#1e293b}.pg-heading{display:flex;justify-content:space-between;align-items:center;gap:12px}h2{margin:6px 0 12px;font-size:21px}.pg-eyebrow,.pg-note,small{font-size:12px;color:#64748b;line-height:1.8}.pg-counts{padding:12px;background:#f1f5ff;border-radius:8px;font-size:14px}.pg-filters{display:flex;gap:18px;align-items:center;flex-wrap:wrap;margin:18px 0}input,select,button{font:inherit;padding:7px 12px;border:1px solid #cbd5e1;border-radius:6px;background:white}button{cursor:pointer;color:#4338ca}button:disabled{opacity:.45;cursor:default}.pg-table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px;table-layout:fixed}th,td{text-align:left;padding:12px 8px;border-bottom:1px solid #e2e8f0;vertical-align:top;overflow-wrap:anywhere}th{background:#f8fafc;color:#475569;font-weight:600}th:first-child{width:20%}th:nth-child(4){width:20%}th:nth-child(6){width:130px}.pg-time{font-variant-numeric:tabular-nums}small,td>a{display:block}.pg-source{display:inline-block;padding:2px 6px;border-radius:4px;background:#eef2ff;color:#4338ca}.pg-source.external{background:#fff7ed;color:#9a3412}a{color:#4f46e5}.pg-error{color:#9f1239;padding:12px;background:#fff1f2}.pg-pagination{display:flex;gap:14px;justify-content:center;align-items:center;flex-wrap:wrap;margin:20px 0 0;font-size:13px}@media(max-width:600px){.publication-groups{padding:12px}table{min-width:900px}.pg-filters{gap:10px}.pg-pagination{gap:8px}}
</style>
