<script setup>
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listGeoActionTickets, createGeoActionTicket, patchGeoActionTicket } from '../api/geo'
import { workTicketPayload, shanghaiToday, ticketOverdue, filterWorkTickets, mergeAssignmentDrafts } from '../utils/geoWorkQueue'
import { geoSnapshotLink } from '../utils/geoRoutes'
import GeoTicketExecution from './GeoTicketExecution.vue'

const props = defineProps({ tenantId: [Number, String], suggestions: { type: Array, default: () => [] }, period: String })
const tickets = ref([]), notes = ref({}), error = ref(''), loading = ref(false), busy = ref(false)
const statusFilter = ref('open'), ownerFilter = ref(''), deadlineFilter = ref(''), search = ref('')
const owners = computed(() => [...new Set(tickets.value.map((t) => t.owner_name).filter(Boolean))].sort())
const assignments = ref({})
const today = ref(shanghaiToday())
const dateTimer = setInterval(() => { today.value = shanghaiToday() }, 60000)
const overdue = computed(() => tickets.value.filter((t) => ticketOverdue(t, today.value)).length)
let generation = 0
const states = { todo: '待开始', doing: '执行中', done: '已验收', reopened: '重新处理', blocked: '受阻' }
const visible = computed(() => filterWorkTickets(tickets.value, { status: statusFilter.value, owner: ownerFilter.value, deadline: deadlineFilter.value, query: search.value, today: today.value }))
const pending = computed(() => tickets.value.filter((t) => t.status !== 'done').length)
const accepted = (item) => tickets.value.some((t) => t.advice_code === `workqueue:v1:${item.id}` && t.status !== 'done')
async function load() {
  const current = ++generation
  error.value = ''; loading.value = false
  today.value = shanghaiToday()
  if (!props.tenantId) return
  loading.value = true
  try {
    const data = await listGeoActionTickets(props.tenantId)
    if (current !== generation) return
    const next = (data.items || []).filter((t) => t.advice_code?.startsWith('workqueue:v1:'))
    assignments.value = mergeAssignmentDrafts(tickets.value, next, assignments.value)
    notes.value = Object.fromEntries(next.map((t) => [t.id, notes.value[t.id] || '']))
    tickets.value = next
  } catch (e) { if (current === generation) error.value = e.message || '待办加载失败' }
  finally { if (current === generation) loading.value = false }
}
async function mutate(action, options = {}) {
  if (busy.value || loading.value || !props.tenantId) return
  const current = generation, owner = props.tenantId
  busy.value = true
  try {
    const saved = await action(owner)
    if (current !== generation) return
    const next = tickets.value.some((t) => t.id === saved.id) ? tickets.value.map((t) => t.id === saved.id ? saved : t) : [saved, ...tickets.value]
    assignments.value = mergeAssignmentDrafts(tickets.value, next, assignments.value)
    tickets.value = next
    if (options.assignmentId === saved.id) assignments.value[saved.id] = { owner_name: saved.owner_name || '', due_date: saved.due_date || '' }
    if (options.noteId === saved.id && notes.value[saved.id] === options.note) notes.value[saved.id] = ''
    ElMessage.success('待办已保存')
  } catch (e) { if (current === generation) ElMessage.error(e.message || '保存失败，请重试') }
  finally { busy.value = false }
}
function add(item) { mutate((owner) => createGeoActionTicket(owner, workTicketPayload(item, props.period))) }
async function state(ticket, status) {
  if (busy.value || loading.value) return
  const current = generation
  let operation_note
  if (status === 'blocked') {
    try {
      const result = await ElMessageBox.prompt('说明卡在哪里、需要谁提供什么协助', '记录受阻原因', {
        inputType: 'textarea', inputValidator: (value) => !!value?.trim() && value.trim().length <= 4000 || '请填写 1–4000 字的受阻原因',
      })
      operation_note = result.value.trim()
    } catch { return }
    if (current !== generation) return
  }
  mutate((owner) => patchGeoActionTicket(owner, ticket.id, { status, operation_note }))
}
function blockedReason(ticket) {
  return [...(ticket.evidence || [])].reverse().find((event) => event.check === 'workflow.status' && event.result === 'blocked')?.note
}
function saveAssignment(ticket) {
  const draft = assignments.value[ticket.id]
  const payload = { owner_name: draft.owner_name.trim() || null, due_date: draft.due_date || null }
  mutate((owner) => patchGeoActionTicket(owner, ticket.id, payload), { assignmentId: ticket.id })
}
function finish(ticket, pass) {
  const note = (notes.value[ticket.id] || '').trim()
  if (!note) { ElMessage.warning('请填写执行结果与核验依据'); return }
  mutate((owner) => patchGeoActionTicket(owner, ticket.id, { manual_pass: pass, verification_note: note }), { noteId: ticket.id, note: notes.value[ticket.id] })
}
function resetFilters() { statusFilter.value = 'open'; ownerFilter.value = ''; deadlineFilter.value = ''; search.value = '' }
function executionSaved(saved) {
  const next = tickets.value.map((ticket) => ticket.id === saved.id ? saved : ticket)
  assignments.value = mergeAssignmentDrafts(tickets.value, next, assignments.value)
  tickets.value = next
}
watch(() => props.tenantId, () => {
  tickets.value = []; assignments.value = {}; notes.value = {}; resetFilters(); load()
}, { immediate: true, flush: 'sync' })
onBeforeUnmount(() => { generation++; clearInterval(dateTimer) })
</script>

<template>
  <section class="tickets" aria-label="GEO 执行待办">
    <h3>执行待办 · 未完成 {{ pending }} · 逾期 {{ overdue }}</h3>
    <p>加入后会保存观察期、原因、动作与验收要求。建议变化不会覆盖已有待办；人工验收表示本次工作完成，不代表 GEO 效果提升。</p>
    <el-button :loading="loading" :disabled="busy || !tenantId" @click="load">刷新待办</el-button>
    <div class="actions" aria-label="待办筛选">
      <label>状态 <select v-model="statusFilter" aria-label="待办状态筛选"><option value="open">未完成</option><option value="">全部状态</option><option v-for="(name, key) in states" :key="key" :value="key">{{ name }}</option></select></label>
      <label>负责人 <select v-model="ownerFilter" aria-label="待办负责人筛选"><option value="">全部负责人</option><option value="__unassigned__">未指定</option><option v-for="owner in owners" :key="owner" :value="owner">{{ owner }}</option></select></label>
      <label>期限 <select v-model="deadlineFilter" aria-label="待办期限筛选"><option value="">全部期限</option><option value="overdue">已逾期</option><option value="today">今天到期</option><option value="unset">未设置期限</option></select></label>
      <input v-model="search" aria-label="搜索执行待办" placeholder="搜索标题、负责人或工作内容" />
      <el-button @click="resetFilters">重置筛选</el-button>
    </div>
    <p>当前显示 {{ visible.length }} / {{ tickets.length }} 项；上方未完成与逾期统计为当前客户全部待办。未完成优先，逾期优先，其后按截止日期排序。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div v-for="item in suggestions" :key="item.id" class="accept-row">
      <span>{{ item.kind }} · {{ item.title }}</span>
      <el-button :disabled="busy || loading || !!error || accepted(item)" @click="add(item)">{{ accepted(item) ? '已在待办中' : '加入执行待办' }}</el-button>
    </div>
    <p v-if="!loading && !error && !visible.length">{{ tickets.length ? '没有符合筛选条件的待办，可重置筛选查看。' : '暂无已保存待办，可从上方建议加入。' }}</p>
    <article v-for="ticket in visible" :key="ticket.id" class="ticket">
      <h4>#{{ ticket.id }} · {{ ticket.title }} <el-tag>{{ states[ticket.status] || ticket.status }}</el-tag></h4>
      <p>负责人：{{ ticket.owner_name || '未指定' }} · 截止日期：{{ ticket.due_date || '未设置' }} <el-tag v-if="ticketOverdue(ticket, today)" type="danger">已逾期</el-tag></p>
      <div v-if="assignments[ticket.id]" class="actions">
        <label>负责人姓名 <input v-model="assignments[ticket.id].owner_name" :aria-label="`工单 ${ticket.id} 负责人姓名`" maxlength="100" placeholder="填写执行人姓名" :disabled="busy" /></label>
        <label>截止日期 <input v-model="assignments[ticket.id].due_date" :aria-label="`工单 ${ticket.id} 截止日期`" type="date" max="9999-12-31" :disabled="busy" /></label>
        <el-button :disabled="busy" @click="saveAssignment(ticket)">保存负责人和日期</el-button>
      </div>
      <p class="assignment-help">负责人按姓名登记；截止日当天不算逾期，按上海日期判断。清空字段后保存可取消设置。</p>
      <p class="details">{{ ticket.action }}</p>
      <p><b>验收要求：</b>{{ ticket.acceptance_desc }}</p>
      <GeoTicketExecution :tenant-id="tenantId" :ticket="ticket" :disabled="busy || loading" @saved="executionSaved" />
      <router-link :to="geoSnapshotLink({ prompt_id: /^workqueue:v1:prompt-(\d+)$/.exec(ticket.advice_code || '')?.[1] })">打开采样与核验记录</router-link>
      <p v-if="ticket.last_note"><b>最近验收记录：</b>{{ ticket.last_note }}</p>
      <el-alert v-if="ticket.status === 'blocked'" :title="blockedReason(ticket) || '此历史待办未记录受阻原因，请补充。'" type="warning" :closable="false" />
      <details class="history">
        <summary>处理与验收记录（最近 {{ (ticket.evidence || []).length }} 条）</summary>
        <p>最多保留最近 6 条；更早记录可能已被覆盖，不代表完整审计历史。</p>
        <p v-if="!ticket.evidence?.length">暂无记录。</p>
        <ol v-else>
          <li v-for="(event, index) in [...ticket.evidence].reverse()" :key="index">
            <b>{{ event.check === 'workflow.assignment' ? '负责人 / 日期调整' : event.check === 'workflow.status' ? '执行状态' : event.result === 'pass' ? '验收通过' : event.result === 'fail' ? '验收未通过' : '核验记录' }}</b>
            <time> {{ event.at }}</time><p class="details">{{ event.note }}</p>
          </li>
        </ol>
      </details>
      <p v-if="ticket.closed_at">完成时间：{{ ticket.closed_at }}</p>
      <template v-if="ticket.status !== 'done'">
        <el-input v-model="notes[ticket.id]" type="textarea" :rows="2" :maxlength="4000" :aria-label="`工单 ${ticket.id} 执行结果`" placeholder="填写做了什么、核验结果及依据，例如采样记录编号或来源页面" />
        <div class="actions">
          <el-button :disabled="busy || ticket.status === 'doing'" @click="state(ticket, 'doing')">开始执行</el-button>
          <el-button :disabled="busy" @click="state(ticket, 'blocked')">{{ ticket.status === 'blocked' ? '补充受阻原因' : '标记受阻' }}</el-button>
          <el-button type="primary" :disabled="busy" @click="finish(ticket, true)">记录结果并验收通过</el-button>
          <el-button :disabled="busy" @click="finish(ticket, false)">记录未达标</el-button>
        </div>
      </template>
      <el-button v-else :disabled="busy" @click="state(ticket, 'reopened')">重新处理</el-button>
    </article>
  </section>
</template>
<style scoped>
.tickets{border-top:2px solid #e2e8f0;margin-top:24px;padding-top:12px}.tickets p{line-height:1.6}.accept-row,.actions{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:12px 0}.accept-row{justify-content:space-between}.ticket{border:1px solid #e2e8f0;border-radius:10px;padding:16px;margin-top:16px}.details{white-space:pre-wrap;overflow-wrap:anywhere}
</style>
