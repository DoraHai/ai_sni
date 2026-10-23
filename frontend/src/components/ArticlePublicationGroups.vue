<script setup>
import { computed, onActivated, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { session } from '../store/session'
import { advisorClaims } from '../utils/geoAdvisorTenant.js'
import { createDistributionInboxApi } from '../api/distributionInbox.js'
import { createPublicationGroupsState, publicationTime, reportedResult, safePublicationLink } from '../utils/articlePublicationGroups.js'

const props = defineProps({ tenantId: Number, projectId: Number, taskId: Number, taskTitle: String, focusArticleId: Number })
const revision = ref(0), source = ref('all'), expanded = ref({})
const authRevision = () => `${session.token}:${session.tenantId}:${JSON.stringify(session.permissions)}`
const api = createDistributionInboxApi({ getBusiness: (_module, tenant) => {
  const claims = advisorClaims(session.token)
  if (tenant !== session.tenantId || (claims && (claims.scope_kind !== 'advisor_tenant' || claims.tid !== tenant))) return null
  return { token: session.token, revision: authRevision() }
} })
const model = createPublicationGroupsState(api, () => { revision.value++ })
const state = computed(() => { revision.value; return { ...model.state } })
const groups = computed(() => state.value.groups.filter(g => props.taskId || source.value === 'all'
  || (source.value === 'native' ? g.native_count > 0 : g.external_count > 0)))
const matches = row => source.value === 'all' || row.source === source.value
let refreshVersion = 0
async function refresh() {
  const current = ++refreshVersion
  expanded.value = props.taskId ? { [props.taskId]: true } : {}
  await model.refresh({ module: 'geo', tenantId: props.tenantId, projectId: props.projectId, taskId: props.taskId })
  if (current !== refreshVersion || !props.focusArticleId || props.taskId || state.value.error) return
  const id = props.focusArticleId
  if (!model.state.groups.some(g => g.group_article_id === id)) {
    model.state.groups.push({ group_article_id: id, task_id: id, title: `已定位任务 #${id}`, focus_only: true })
    revision.value++
  }
  expanded.value = { ...expanded.value, [id]: true }
  await model.detail(id)
}
watch([() => props.tenantId, () => props.projectId, () => props.taskId, () => props.focusArticleId, authRevision], refresh, { immediate: true, flush: 'sync' })
let activeOnce = false
onActivated(() => { if (activeOnce) refresh(); activeOnce = true })
const activate = () => { if (document.visibilityState === 'visible') refresh() }
onMounted(() => { window.addEventListener('focus', activate); document.addEventListener('visibilitychange', activate) })
onBeforeUnmount(() => { refreshVersion++; model.clear(); window.removeEventListener('focus', activate); document.removeEventListener('visibilitychange', activate) })
function toggle(group) {
  const id = group.group_article_id
  expanded.value = { ...expanded.value, [id]: !expanded.value[id] }
  if (expanded.value[id] && !state.value.details[id]) model.detail(id)
}
function taskLink(id) { return { path: `/geo/tasks/${id}`, query: { tenant_id: props.tenantId, project_id: props.projectId } } }
function inboxLink(row) { return { path: '/distribution-inbox', query: { receipt_id: row.external_receipt_id,
  tenant_id: props.tenantId, project_id: props.projectId, ...(props.taskId ? { task_id: props.taskId } : {}) } } }
</script>

<template>
  <section class="publication-groups" aria-label="按文章查看发布记录">
    <header class="pg-heading">
      <div><span class="pg-eyebrow">项目 #{{ projectId }} · 只读发布记录</span><h2>{{ taskId ? '本任务发布记录' : '按文章查看发布记录' }}</h2></div>
      <button type="button" @click="refresh">刷新</button>
    </header>
    <p class="pg-note">系统登记与外部回传分别保留。外部结果是操作人报告，不计入原生验收、报表和导出。</p>
    <div v-if="state.counts" class="pg-counts" aria-label="项目全范围统计">
      <span>系统原生登记 <b>{{ state.counts.native_records }}</b> 条</span>
      <span>外部回传 <b>{{ state.counts.external_records }}</b> 条</span>
      <span>有记录文章 <b>{{ state.counts.article_groups }}</b> 篇</span>
    </div>
    <p v-if="state.counts" class="pg-note">以上为项目全范围统计；来源筛选只改变下方展示。各项单位独立。</p>
    <p v-if="state.error" role="alert" class="pg-error">读取不完整：{{ state.error }} <button type="button" @click="refresh">重新读取</button></p>
    <fieldset class="pg-filters"><legend>记录来源</legend>
      <label><input v-model="source" type="radio" value="all" />全部来源</label>
      <label><input v-model="source" type="radio" value="native" />系统原生</label>
      <label><input v-model="source" type="radio" value="external_report" />外部回传</label>
    </fieldset>
    <p v-if="state.loading.linked" role="status">正在读取文章…</p>
    <p v-if="!taskId && state.counts" class="pg-note">本页 {{ state.groups.length }} 篇 · 当前筛选可见 {{ groups.length }} 篇 / 全范围 {{ state.counts.article_groups }} 篇 · 按最近记录时间倒序</p>
    <p v-if="!groups.length && !state.error && !state.loading.linked">当前范围暂无符合筛选的文章记录。</p>
    <article v-for="group in groups" :key="group.group_article_id" class="pg-article" :data-article-id="group.group_article_id">
      <header class="pg-article-heading">
        <button type="button" class="pg-expand" :aria-expanded="!!expanded[group.group_article_id]" @click="toggle(group)">
          <span>{{ expanded[group.group_article_id] ? '▾' : '▸' }}</span> #{{ group.group_article_id }} {{ taskId ? taskTitle || group.title : group.title }}
        </button>
        <span v-if="!taskId && !group.focus_only" class="pg-note">系统 {{ group.native_count }} 条 / 外部 {{ group.external_count }} 条</span>
        <router-link v-if="!taskId" :to="taskLink(group.group_article_id)">查看任务</router-link>
      </header>
      <div v-if="expanded[group.group_article_id]" class="pg-details">
        <p v-if="state.loading[`detail:${group.group_article_id}`]" role="status">正在读取文章明细…</p>
        <div v-for="row in (state.details[group.group_article_id] || []).filter(matches)" :key="row.source_key" class="pg-row">
          <div class="pg-row-label"><span class="pg-source" :class="{ external: row.source === 'external_report' }">{{ row.source === 'native' ? '系统原生' : '外部回传' }}</span><b>{{ row.channel || '未提供平台' }}</b>
            <span v-if="row.article_version_no">关联母稿 v{{ row.article_version_no }}<span v-if="row.current_version_no && row.current_version_no !== row.article_version_no">；当前 v{{ row.current_version_no }}</span></span>
            <span v-if="row.variant_id">渠道稿 #{{ row.variant_id }}</span>
          </div>
          <a v-if="safePublicationLink(row.url)" :href="safePublicationLink(row.url)" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">{{ row.url }}</a>
          <span v-else class="pg-note">暂无可公开查看的安全链接</span>
          <template v-if="row.source === 'external_report'">
            <p>{{ reportedResult(row.status) }} · 正文暂不可核验</p>
            <p class="pg-note">报告时间：{{ publicationTime(row.reported_at) }} · 收到时间：{{ publicationTime(row.received_at) }}（北京时间）</p>
          </template>
          <template v-else>
            <p>系统登记状态：{{ ({ published: '已发布', pending: '待发布', failed: '失败' })[row.status] || row.status || '未知' }} · 核验证据请查看原生发布监测</p>
            <p class="pg-note">发布登记时间：{{ publicationTime(row.published_at) }}（北京时间）</p>
          </template>
        </div>
        <p v-if="state.details[group.group_article_id]" class="pg-note">本文章已加载 {{ state.details[group.group_article_id].length }} 条明细，筛选可见 {{ state.details[group.group_article_id].filter(matches).length }} 条。</p>
        <button v-if="state.cursors[`detail:${group.group_article_id}`]" type="button" :disabled="state.loading[`detail:${group.group_article_id}`]" @click="model.detail(group.group_article_id, true)">继续加载该文章明细</button>
      </div>
    </article>
    <nav v-if="!taskId && state.counts" class="pg-pagination" aria-label="文章分页">
      <button type="button" :disabled="state.loading.linked || !(state.pages.linked > 1)" @click="model.list('linked', 'previous')">上一页</button>
      <span>第 {{ state.pages.linked || 1 }} 页 / 共 {{ Math.max(1, Math.ceil(state.counts.article_groups / 20)) }} 页 · 每页 20 篇 · 共 {{ state.counts.article_groups }} 篇</span>
      <button type="button" :disabled="state.loading.linked || !state.cursors.linked" @click="model.list('linked', true)">下一页</button>
    </nav>
    <template v-if="!taskId">
      <details v-for="bucket in ['unlinked', 'invalid']" :key="bucket" class="pg-bucket" :open="bucket === 'unlinked'">
        <summary>{{ bucket === 'unlinked' ? '待关联' : '关联异常（仅内部）' }} <span v-if="state.counts">{{ state.counts[bucket === 'unlinked' ? 'unlinked_records' : 'invalid_records'] }} 条</span></summary>
        <p class="pg-note">{{ bucket === 'unlinked' ? '当前项目已标客户但未选稿件的外部回传。' : '原关联无法验证，请由有权人员核对；此处不显示目标稿件标题。' }}</p>
        <p v-if="state.loading[bucket]" role="status">正在读取…</p>
        <p v-else-if="!state[bucket].length && !state.error">暂无记录</p>
        <div v-for="row in state[bucket]" :key="row.source_key" class="pg-row">
          <strong>{{ row.title || (bucket === 'invalid' ? '关联目标需重新核对' : '未提供标题') }}</strong>
          <p>{{ row.channel || '未提供平台' }} · {{ reportedResult(row.status) }} · {{ bucket === 'unlinked' ? '未关联稿件，不核验正文' : '关联异常，需核对' }}</p>
          <a v-if="safePublicationLink(row.url)" :href="safePublicationLink(row.url)" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">{{ row.url }}</a>
          <p class="pg-note">报告时间：{{ publicationTime(row.reported_at) }} · 收到时间：{{ publicationTime(row.received_at) }}（北京时间）</p>
          <router-link v-if="row.can_label && session.canEdit('geo.content')" :to="inboxLink(row)">去关联稿件</router-link>
          <p v-else class="pg-note">请由回传所属顾问或有权管理员处理。</p>
        </div>
        <nav v-if="state.counts" class="pg-pagination" :aria-label="bucket === 'unlinked' ? '待关联分页' : '关联异常分页'">
          <button type="button" :disabled="state.loading[bucket] || !(state.pages[bucket] > 1)" @click="model.list(bucket, 'previous')">上一页</button>
          <span>第 {{ state.pages[bucket] || 1 }} 页 · 每页 20 条 · 共 {{ state.counts[bucket === 'unlinked' ? 'unlinked_records' : 'invalid_records'] }} 条</span>
          <button type="button" :disabled="state.loading[bucket] || !state.cursors[bucket]" @click="model.list(bucket, true)">下一页</button>
        </nav>
      </details>
      <p class="pg-note">没选项目的回传不会出现在这里，请到多号通回传收件箱补选项目。</p>
    </template>
  </section>
</template>

<style scoped>
.pg-pagination{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:16px 0;font-size:13px;color:#64748b}
.publication-groups{padding:24px;background:#fff;border:1px solid #dce3ed;border-radius:16px;color:#1e293b;overflow-wrap:anywhere;margin:20px 0}.pg-heading,.pg-article-heading,.pg-row-label{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.pg-heading{justify-content:space-between}.pg-heading h2{margin:5px 0;font-size:22px}.pg-eyebrow{font-size:12px;color:#6366a2;letter-spacing:.04em}.pg-note{font-size:13px;color:#64748b;line-height:1.7}.pg-counts{display:flex;gap:12px;flex-wrap:wrap;padding:16px 0}.pg-counts span{background:#f5f7fc;padding:12px 16px;border-radius:8px}.pg-counts b{font-size:24px;margin:0 4px;color:#4338ca}.pg-filters{display:flex;gap:18px;border:0;padding:8px 0 18px;flex-wrap:wrap}.pg-filters legend{font-size:12px;color:#64748b}.pg-filters label{display:flex;gap:5px;align-items:center}.pg-article{border:1px solid #e2e8f0;border-radius:10px;margin:12px 0;overflow:hidden}.pg-article-heading{padding:14px 16px;background:#f8fafc}.pg-expand{border:0;background:transparent;text-align:left;flex:1;font-weight:600;min-width:180px}.pg-details{padding:0 16px 14px}.pg-row{padding:16px 0;border-top:1px solid #e7edf4;font-size:14px}.pg-row p{margin:8px 0}.pg-row a{display:block;margin:10px 0}.pg-source{background:#eef2ff;color:#4338ca;border-radius:5px;padding:4px 8px;font-size:12px}.pg-source.external{background:#fff7ed;color:#9a3412}.pg-bucket{padding:16px;border:1px solid #e2e8f0;border-radius:10px;margin-top:20px}.pg-bucket summary{cursor:pointer;font-weight:600}.pg-error{padding:12px;background:#fff1f2;color:#9f1239;border-radius:8px}button{padding:8px 12px;border:1px solid #cbd5e1;border-radius:6px;background:#fff;cursor:pointer;color:#334155}button:disabled{opacity:.5;cursor:wait}a{color:#4f46e5}button:focus-visible,a:focus-visible,summary:focus-visible{outline:2px solid #6366f1;outline-offset:3px}@media(max-width:600px){.publication-groups{padding:16px;margin:12px 0}.pg-heading h2{font-size:19px}.pg-counts{gap:8px}.pg-counts span{padding:9px 12px;flex:1;min-width:110px}.pg-counts b{font-size:20px}.pg-article-heading{padding:12px}.pg-expand{min-width:100%;padding:4px}.pg-details{padding:0 12px 12px}.pg-filters{gap:12px}.pg-bucket{padding:12px}}
</style>
