<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { currentTenantId, session } from '../../store/session'
import { currentSeoSiteId } from './seoSiteContext'
import { fetchSeoTaskCenter, recoverSeoAiOperation, retrySeoTask } from '../../api/seo'

const router = useRouter()
const data = ref({ items: [], total: 0, summary: {}, schedules: [] })
const filters = reactive({ kind: '', status: '', page: 1 })
const loading = ref(false)
const error = ref('')
const refreshing = ref(true)
const retrying = ref('')
const resultOpen = ref(false)
const resultLoading = ref(false)
const resultText = ref('')
const resultError = ref('')
let sequence = 0
let resultSequence = 0
let timer
const scope = () => `${session.user?.id || 'api_key'}:${currentTenantId.value || ''}:${currentSeoSiteId.value || ''}`
const kinds = { ranking: '自然排名', competitor: '竞品监控', backlink: '外链核验', crawl: '页面抓取', ai: 'AI 内容操作' }
const statuses = { queued: '排队中', running: '运行中', completed: '已完成', partial: '部分完成', failed: '失败', refunded: '已退还额度', expired: '结果已到期' }
const time = value => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
const totalPages = computed(() => Math.max(1, Math.ceil(data.value.total / 20)))
const attentionCount = computed(() => (data.value.summary.failed || 0) + (data.value.summary.partial || 0))
const busyCount = computed(() => (data.value.summary.running || 0) + (data.value.summary.queued || 0))
const rowKey = row => `${row.source}:${row.id}`

async function load() {
  const token = ++sequence
  const requestedScope = scope()
  if (!currentTenantId.value) { data.value = { items: [], total: 0, summary: {}, schedules: [] }; loading.value = false; error.value = ''; return }
  loading.value = true
  error.value = ''
  try {
    const response = await fetchSeoTaskCenter({ tenant_id: currentTenantId.value,
      site_id: currentSeoSiteId.value || undefined, kind: filters.kind || undefined,
      status: filters.status || undefined, page: filters.page, page_size: 20 })
    if (token === sequence && scope() === requestedScope) data.value = response
  } catch (e) {
    if (token === sequence && scope() === requestedScope) error.value = e.message
  } finally { if (token === sequence) loading.value = false }
}

async function retry(row) {
  if (!row.can_retry || retrying.value) return
  const requestedScope = scope()
  const tenantId = currentTenantId.value
  retrying.value = rowKey(row)
  try {
    await ElMessageBox.confirm(`将为网站 #${row.retry_site_id} 新建一次${kinds[row.kind]}任务，仍受现有额度和冷却限制。`, '确认重试', { confirmButtonText: '新建重试任务', cancelButtonText: '取消', type: 'warning' })
    if (scope() !== requestedScope) return
    await retrySeoTask(row.id, { tenant_id: tenantId, site_id: row.retry_site_id, job_type: row.kind })
    if (scope() === requestedScope) { ElMessage.success('重试任务已进入队列'); await load() }
  } catch (e) { if (e?.message && scope() === requestedScope) ElMessage.error(e.message) }
  finally { retrying.value = '' }
}

async function recover(row) {
  if (!row.has_result) return
  const token = ++resultSequence
  const requestedScope = scope()
  resultOpen.value = true; resultLoading.value = true; resultText.value = ''; resultError.value = ''
  try {
    const result = await recoverSeoAiOperation(row.id, currentTenantId.value)
    if (token !== resultSequence || requestedScope !== scope() || !resultOpen.value) return
    resultText.value = [['标题', result.title], ['大纲', result.outline], ['正文', result.content || result.content_html],
      ['反馈', result.feedback], ['建议', result.suggestions?.join('\n')]].filter(([, value]) => value)
      .map(([label, value]) => `${label}\n${value}`).join('\n\n') || JSON.stringify(result, null, 2)
  } catch (e) { if (token === resultSequence && requestedScope === scope()) resultError.value = e.message }
  finally { if (token === resultSequence) resultLoading.value = false }
}

async function copyResult() {
  try { await navigator.clipboard.writeText(resultText.value); ElMessage.success('已复制，可粘贴到编辑器继续核对') }
  catch { ElMessage.warning('复制失败，请选择下方文字手动复制') }
}

function openSource(row) {
  router.push({ path: row.source === 'crawl' ? '/seo/site' : '/seo/content/articles',
    query: row.site_id ? { site_id: row.site_id } : {} })
}

watch(() => [currentTenantId.value, currentSeoSiteId.value, session.user?.id], () => {
  sequence++; resultSequence++; resultOpen.value = false; resultText.value = ''; resultError.value = ''
  data.value = { items: [], total: 0, summary: {}, schedules: [] }; filters.page = 1; load()
})
watch(() => [filters.kind, filters.status], () => { filters.page = 1; load() })
watch(() => filters.page, load)
watch(resultOpen, value => { if (!value) { resultSequence++; resultText.value = ''; resultLoading.value = false } })
onMounted(() => {
  load()
  timer = setInterval(() => { if (refreshing.value && !loading.value && !document.hidden) load() }, 15000)
})
onUnmounted(() => { sequence++; resultSequence++; clearInterval(timer) })
</script>

<template>
  <main class="task-center">
    <header class="task-heading">
      <div><p class="eyebrow">SEO / 运行记录</p><h1>自动任务中心</h1><p>查看执行结果、处理失败任务，找回尚未保存的 AI 内容。</p></div>
      <div class="refresh-controls"><label><input v-model="refreshing" type="checkbox"> 自动刷新</label><button :disabled="loading" @click="load">{{ loading ? '刷新中…' : '刷新记录' }}</button></div>
    </header>
    <div v-if="!currentTenantId" class="empty">请先在顶部选择客户。</div>
    <template v-else>
      <section class="task-summary" aria-label="任务概况">
        <article><span>运行与排队</span><strong>{{ busyCount }}</strong><small>进行中的任务不会重复执行</small></article>
        <article><span>需要关注</span><strong class="attention">{{ attentionCount }}</strong><small>失败或部分完成的任务</small></article>
        <article><span>AI 已退还额度</span><strong>{{ data.summary.refunded || 0 }}</strong><small>中断操作会自动补偿</small></article>
      </section>
      <section v-if="data.schedules.length" class="schedules" aria-label="下次调度检查">
        <div v-for="item in data.schedules" :key="item.job_type"><span>{{ kinds[item.job_type] }}</span><b>{{ time(item.next_check_at) }}</b><small>下次调度检查</small></div>
        <p>实际执行还取决于配置、采集间隔、额度及服务运行状态。页面抓取和 AI 操作按需发起。</p>
      </section>
      <section class="task-history">
        <div class="task-filters">
          <h2>任务历史</h2>
          <label>任务类型 <select v-model="filters.kind"><option value="">全部类型</option><option v-for="(label, key) in kinds" :key="key" :value="key">{{ label }}</option></select></label>
          <label>状态 <select v-model="filters.status"><option value="">全部状态</option><option v-for="(label, key) in statuses" :key="key" :value="key">{{ label }}</option></select></label>
        </div>
        <p class="scope-note">仅展示有权限的记录。AI 内容仅本人可取回，保存期限为 30 天；取回不扣额度。全客户定时汇总会单独标明。</p>
        <div v-if="error" class="error" role="alert">加载失败：{{ error }} <button @click="load">重试加载</button></div>
        <div v-else-if="!data.items.length" class="empty">{{ loading ? '正在读取记录…' : '当前筛选下暂无任务记录' }}</div>
        <div v-else class="table-wrap">
          <table><thead><tr><th>任务 / 范围</th><th>状态</th><th>执行情况</th><th>时间</th><th>操作</th></tr></thead>
            <tbody><tr v-for="row in data.items" :key="rowKey(row)">
              <td><strong>{{ kinds[row.kind] }}</strong><small>{{ row.site_id ? `网站 #${row.site_id}` : row.source === 'automation' ? '全客户（定时汇总）' : '未指定网站' }}</small><small class="task-id">#{{ row.id }}</small></td>
              <td><span class="status" :class="row.status">{{ statuses[row.status] || row.status }}</span><small v-if="row.stale" class="attention">长时间未结束，请检查任务</small></td>
              <td><span v-if="row.source !== 'ai'">{{ row.succeeded }} 成功 · {{ row.failed }} 失败 · {{ row.skipped }} 跳过 / {{ row.planned }} 计划</span><span v-else>{{ row.detail }}</span>
                <details v-if="row.source !== 'ai' && row.detail"><summary>查看失败详情</summary><p>{{ row.detail }}</p></details>
              </td>
              <td><time>{{ time(row.started_at) }}</time><small>{{ row.completed_at ? `结束 ${time(row.completed_at)}` : '尚未结束' }}</small></td>
              <td><button v-if="row.has_result" class="primary" @click="recover(row)">取回结果</button>
                <button v-if="row.source === 'automation' && ['failed','partial'].includes(row.status)" :disabled="!row.can_retry || !!retrying" :title="!row.retry_site_id ? '请先选择要重试的网站' : !row.can_retry ? '没有重试权限' : ''" @click="retry(row)">{{ retrying === rowKey(row) ? '提交中…' : '重试任务' }}</button>
                <button v-if="row.source === 'crawl'" @click="openSource(row)">打开站内优化</button>
                <button v-if="row.source === 'ai' && ['refunded','expired'].includes(row.status)" @click="openSource(row)">返回内容列表</button>
              </td>
            </tr></tbody>
          </table>
        </div>
        <footer class="pagination"><span>共 {{ data.total }} 条</span><button :disabled="filters.page <= 1 || loading" @click="filters.page--">上一页</button><span>{{ filters.page }} / {{ totalPages }}</span><button :disabled="filters.page >= totalPages || loading" @click="filters.page++">下一页</button></footer>
      </section>
    </template>
    <el-dialog v-model="resultOpen" title="取回 AI 结果" width="min(760px, 92vw)">
      <p>这份结果不会自动保存或发布。复制后可回到编辑器继续核对。</p>
      <p v-if="resultLoading">正在取回…</p><p v-else-if="resultError" role="alert">{{ resultError }}</p><pre v-else class="recovered-result">{{ resultText }}</pre>
      <template #footer><button :disabled="!resultText || resultLoading" @click="copyResult">复制结果</button><button @click="resultOpen = false">关闭</button></template>
    </el-dialog>
  </main>
</template>

<style scoped>
.task-center{max-width:1440px;margin:auto;padding:26px;color:#223047}.task-heading{display:flex;justify-content:space-between;align-items:center;gap:20px;margin-bottom:24px}.eyebrow{font-size:11px;letter-spacing:2px;color:#71829c;margin:0 0 7px}h1{font-size:26px;margin:0 0 10px}.task-heading p:not(.eyebrow){font-size:13px;color:#728197;margin:0}.refresh-controls{display:flex;align-items:center;gap:14px;font-size:12px}.refresh-controls label{display:flex;align-items:center;gap:5px}button,select{font:inherit;border:1px solid #dbe2eb;background:white;border-radius:7px;padding:8px 12px;color:#315274}button{cursor:pointer;font-size:12px;white-space:nowrap}button:disabled{opacity:.45;cursor:not-allowed}button.primary{background:#2864e8;color:white;border-color:#2864e8}.task-summary{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:18px}.task-summary article{background:white;border:1px solid #e0e6ee;border-radius:12px;padding:19px 23px;display:grid;gap:7px}.task-summary span{font-size:12px;color:#66788e}.task-summary strong{font-size:30px}.task-summary small,.schedules small{color:#8591a2;font-size:11px}.attention{color:#c97617!important}.schedules{display:flex;flex-wrap:wrap;gap:14px 35px;background:#edf3fa;border:1px solid #dbe5f1;border-radius:10px;padding:15px 20px;margin-bottom:22px}.schedules div{display:grid;gap:4px}.schedules span{font-size:11px;color:#67788c}.schedules b{font-size:12px}.schedules p{width:100%;margin:0;color:#75879c;font-size:11px}.task-history{background:white;border:1px solid #e0e6ee;border-radius:12px;overflow:hidden}.task-filters{display:flex;gap:18px;align-items:center;flex-wrap:wrap;padding:18px 20px 8px}.task-filters h2{font-size:15px;margin:0 auto 0 0}.task-filters label{font-size:12px;color:#63768e;display:flex;gap:8px;align-items:center}.scope-note{font-size:11px;color:#7e8ca0;margin:0;padding:8px 20px 16px}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;text-align:left;font-size:12px}th{background:#f6f8fb;font-size:11px;font-weight:500;color:#7b899b;padding:12px 16px}td{padding:17px 16px;border-top:1px solid #edf0f4;vertical-align:top;min-width:110px}td:nth-child(3){max-width:300px;overflow-wrap:anywhere}td strong{font-size:13px}td small{display:block;color:#8995a5;font-size:10px;margin-top:5px}.task-id{max-width:180px;overflow:hidden;text-overflow:ellipsis}.status{display:inline-block;border-radius:12px;padding:4px 9px;background:#f0f3f7;color:#64748b;white-space:nowrap}.status.running,.status.queued,.status.partial{background:#fff3da;color:#ac751e}.status.completed{background:#e7f6ed;color:#218654}.status.failed{background:#fff0ee;color:#c45846}details{margin-top:8px}summary{cursor:pointer;color:#a4612c}details p{white-space:pre-wrap;line-height:1.6}.pagination{display:flex;align-items:center;justify-content:flex-end;gap:14px;border-top:1px solid #edf0f4;padding:14px 20px;font-size:12px;color:#7e8ca0}.pagination>span:first-child{margin-right:auto}.empty{padding:60px 20px;text-align:center;color:#8592a5;font-size:13px}.error{padding:20px;color:#bb5348}.recovered-result{white-space:pre-wrap;overflow-wrap:anywhere;max-height:55vh;overflow:auto;font:13px/1.8 inherit;padding:15px;background:#f5f7fa;border-radius:8px}td button+button{margin-left:5px}@media(max-width:800px){.task-center{padding:16px}.task-heading{align-items:flex-start;flex-direction:column}.task-summary{grid-template-columns:1fr;gap:8px}.task-summary article{padding:12px 16px;grid-template-columns:1fr auto;align-items:center}.task-summary small{grid-column:1/-1}.task-summary strong{font-size:24px}.task-filters{gap:12px}.task-filters h2{width:100%}.schedules{gap:14px}.schedules div{flex:1;min-width:160px}}
</style>
