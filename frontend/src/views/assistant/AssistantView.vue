<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { chat, fetchHistory, fetchMemories, createMemory, deleteMemory, adoptAction } from '../../api/assistant'
import { generateBuildDraft } from '../../api/onboardingBuilder'
import { session } from '../../store/session'

const router = useRouter()
const TENANT_ID = computed(() => session.tenantId || (import.meta.env.DEV && import.meta.env.VITE_API_KEY ? 1 : null))
const tenantName = computed(() => session.tenants.find((t) => t.id === session.tenantId)?.name || '')

// 建议跳转目标 → 前端路由
const TARGET_ROUTE = {
  workbench: { path: '/optimize/keywords', label: '关键词工作台' },
  leads: { path: '/verify/leads', label: '线索管理' },
  negatives: { path: '/optimize/negatives', label: '否词管理' },
  search_terms: { path: '/optimize/search-terms', label: '搜索词报告' },
  expand: { path: '/optimize/expand', label: '拓词' },
  dashboard: { path: '/monitor/dashboard', label: '数据看板' },
  builder: { path: '/onboarding/builder', label: '智能搭建' },
}
const MEM_TYPE_LABEL = { goal: '目标', constraint: '约束', preference: '偏好', background: '背景', decision: '决策', other: '其他' }

const EXAMPLES = [
  '我想新建一套百度搜索推广计划',
  '这个月哪些词在烧钱但没带来线索？',
  '苏尔寿本周表现怎么样，帮我总结一下',
  '线索成本现在多少？哪个计划最划算？',
  '有没有该砍的词或该加的否词？',
]

const BUILDER_FIELD_LABELS = {
  landing_url: '落地页链接',
  business_summary: '业务概述',
}
const BUILDER_SCHEDULES = {
  all: {
    label: '全天投放',
    schedule: '周一至周日 00:00-24:00',
    blocks: [{ weekDays: [1, 2, 3, 4, 5, 6, 7], startHour: 0, endHour: 24 }],
  },
  workday: {
    label: '工作日 9:00-18:00',
    schedule: '周一至周五 09:00-18:00',
    blocks: [{ weekDays: [1, 2, 3, 4, 5], startHour: 9, endHour: 18 }],
  },
  daytime: {
    label: '每天 9:00-22:00',
    schedule: '周一至周日 09:00-22:00',
    blocks: [{ weekDays: [1, 2, 3, 4, 5, 6, 7], startHour: 9, endHour: 22 }],
  },
}

// messages: {role:'user'|'assistant', content, suggestions?, pendingMemories?}
const messages = ref([])
const input = ref('')
const sending = ref(false)
const drafting = ref(false)
const memories = ref([])
const scrollEl = ref(null)
const retainDays = ref(90)

const started = computed(() => messages.value.length > 0)
const canUseBuilder = computed(() => session.canView('onboarding') || (import.meta.env.DEV && !!import.meta.env.VITE_API_KEY))

function normalizeBuilder(raw) {
  if (!raw?.intent) return null
  return {
    ...raw,
    status: raw.ready ? 'loading' : 'intake',
    result: null,
    error: '',
  }
}

function builderPayload(builder) {
  const preset = BUILDER_SCHEDULES[builder.schedule_preset] || BUILDER_SCHEDULES.all
  return {
    tenantId: TENANT_ID.value,
    landingUrl: builder.landing_url || '',
    landingText: '',
    businessSummary: builder.business_summary || '',
    goal: builder.goal || '获取高意向线索',
    budget: builder.budget || '',
    regions: builder.regions || '',
    schedulePreset: builder.schedule_preset || 'all',
    schedule: preset.schedule,
    scheduleBlocks: preset.blocks.map((block) => ({ ...block, weekDays: [...block.weekDays] })),
    devicePreference: builder.device_preference || '不限',
  }
}

function draftStats(result) {
  const stats = { campaigns: 0, adgroups: 0, keywords: 0, creatives: 0 }
  for (const campaign of result?.draft?.campaigns || []) {
    stats.campaigns += 1
    for (const adgroup of campaign.adgroups || []) {
      stats.adgroups += 1
      stats.keywords += (adgroup.keywords || []).length
      stats.creatives += (adgroup.creatives || []).length
    }
  }
  return stats
}

function builderSettingText(builder) {
  const schedule = BUILDER_SCHEDULES[builder.schedule_preset] || BUILDER_SCHEDULES.all
  return [
    builder.budget ? `日预算 ¥${builder.budget}` : '预算待确认',
    builder.regions || '地域不限',
    schedule.label,
    builder.device_preference || '设备不限',
  ]
}

async function generateAssistantDraft(msg) {
  const builder = msg.builder
  if (!builder?.ready || builder.status === 'loading' && drafting.value) return
  builder.status = 'loading'
  builder.error = ''
  drafting.value = true
  await scrollBottom()
  try {
    builder.result = await generateBuildDraft(builderPayload(builder))
    builder.status = 'ready'
  } catch (e) {
    builder.status = 'error'
    builder.error = e.response?.data?.detail || e.message || '草案生成失败'
  } finally {
    drafting.value = false
    await scrollBottom()
  }
}

function prepareBuilderHandoff(msg, event) {
  const builder = msg.builder
  if (!builder?.result) {
    event?.preventDefault()
    ElMessage.warning('搭建草案尚未生成完成')
    return
  }
  if (!canUseBuilder.value) {
    event?.preventDefault()
    ElMessage.warning('当前账号没有智能搭建页面权限')
    return
  }
  try {
    const handoff = {
      tenantId: TENANT_ID.value,
      createdAt: Date.now(),
      form: builderPayload(builder),
      result: builder.result,
    }
    sessionStorage.setItem(`sem_builder_handoff_${TENANT_ID.value}`, JSON.stringify(handoff))
  } catch (e) {
    event?.preventDefault()
    console.error('智能搭建草案暂存失败', e)
    ElMessage.error('草案暂存失败，请刷新页面后重试')
  }
}

async function loadMemories() {
  try {
    memories.value = (await fetchMemories({ tenantId: TENANT_ID.value })).memories || []
  } catch { /* 忽略 */ }
}

async function loadHistory() {
  try {
    const res = await fetchHistory({ tenantId: TENANT_ID.value })
    retainDays.value = res.retain_days || 90
    messages.value = (res.messages || []).map((m) => ({
      role: m.role, content: m.content, suggestions: [], pendingMemories: [],
    }))
    await scrollBottom()
  } catch { /* 忽略 */ }
}

async function scrollBottom() {
  await nextTick()
  if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
}

async function send(text) {
  const q = (text ?? input.value).trim()
  if (!q || sending.value) return
  input.value = ''
  messages.value.push({ role: 'user', content: q })
  sending.value = true
  await scrollBottom()
  try {
    const res = await chat({ tenantId: TENANT_ID.value, message: q })
    const assistantMessage = {
      role: 'assistant',
      content: res.reply,
      suggestions: res.suggestions || [],
      actions: groupActions(res.actions || []),
      pendingMemories: res.memories || [],
      builder: normalizeBuilder(res.builder),
    }
    messages.value.push(assistantMessage)
    await scrollBottom()
    if (assistantMessage.builder?.ready) await generateAssistantDraft(assistantMessage)
  } catch (e) {
    messages.value.push({ role: 'assistant', content: '出错了：' + (e.response?.data?.detail || e.message), suggestions: [], pendingMemories: [] })
  } finally {
    sending.value = false
    await scrollBottom()
  }
}

function gotoTarget(target) {
  const r = TARGET_ROUTE[target]
  if (r) router.push(r.path)
}

const ACTION_VERB = { adjust_bid: '调价', negative: '加否词', set_budget: '设日预算' }

// 把 AI 拆散的同类动作合并成一张卡（同 type+幅度+匹配方式 → keywords 合并），一键全采纳
function groupActions(actions) {
  const groups = {}
  const standalone = [] // set_budget 是账户级（无关键词），单独成卡不合并
  for (const a of actions || []) {
    if (!a || !a.type) continue
    if (a.type === 'pause') continue // AI 助手不展示一键暂停，暂停需到关键词工作台核查后人工执行
    if (a.type === 'set_budget') {
      standalone.push({
        type: 'set_budget', budget: a.budget, keywords: [], reason: a.reason || '',
        label: a.label || `设账户日预算 ¥${a.budget}`,
      })
      continue
    }
    const key = [a.type, a.adjust_pct ?? '', a.match_mode ?? ''].join('|')
    if (!groups[key]) {
      groups[key] = { type: a.type, adjust_pct: a.adjust_pct, match_mode: a.match_mode, keywords: [], reason: a.reason || '' }
    }
    for (const k of a.keywords || []) {
      if (!groups[key].keywords.includes(k)) groups[key].keywords.push(k)
    }
  }
  return [...standalone, ...Object.values(groups).map((g) => ({ ...g, label: groupLabel(g) }))]
}
function groupLabel(g) {
  const n = g.keywords.length
  if (g.type === 'adjust_bid') return `一键${(g.adjust_pct || 0) > 0 ? '提价' : '降价'} ${n} 个词 ${Math.abs(g.adjust_pct || 0)}%`
  if (g.type === 'negative') return `一键给 ${n} 个词加否词`
  return `采纳 ${n} 个词`
}

function actionSummary(a) {
  if (a.type === 'set_budget') return `设账户日预算：¥${a.budget}`
  const verb = ACTION_VERB[a.type] || a.type
  const extra = a.type === 'adjust_bid' && a.adjust_pct != null
    ? `（${a.adjust_pct > 0 ? '+' : ''}${a.adjust_pct}%）`
    : (a.type === 'negative' ? `（${a.match_mode === 'phrase' ? '短语否' : '精确否'}）` : '')
  const kws = a.keywords || []
  const shown = kws.slice(0, 6).join('、') + (kws.length > 6 ? ` 等 ${kws.length} 个词` : '')
  return `${verb}${extra}：${shown}`
}

// 一键采纳：二次确认 → 执行 → 把结果作为一条系统消息追加
async function adopt(action, msg) {
  if (action._done) return
  if (action.type === 'pause') {
    ElMessage.warning('暂停关键词需先到关键词工作台核查后人工执行')
    return
  }

  // set_budget：账户级（无关键词），单独确认 + 执行
  if (action.type === 'set_budget') {
    if (action.budget == null) return ElMessage.warning('该建议没有预算金额')
    try {
      await ElMessageBox.confirm(
        `将把账户日预算设为 ¥${action.budget}。受演练/护栏/台账保护。确认采纳？`,
        '确认采纳', { confirmButtonText: '确认执行', cancelButtonText: '再想想', type: 'warning' },
      )
    } catch { return }
    try {
      const res = await adoptAction({ tenantId: TENANT_ID.value, type: 'set_budget', budget: action.budget })
      action._done = true
      const tag = res.dry_run ? '（演练模式：仅记台账，未真改线上）' : ''
      messages.value.push({
        role: 'assistant',
        content: `已采纳「设日预算」${tag}\n${(res.results?.[0]?.detail) || ''}`,
        suggestions: [], actions: [], pendingMemories: [],
      })
      await scrollBottom()
    } catch (e) {
      ElMessage.error(e.response?.data?.detail || e.message)
    }
    return
  }

  const kws = action.keywords || []
  if (!kws.length) return ElMessage.warning('该建议没有具体关键词')
  try {
    await ElMessageBox.confirm(
      `将执行：${actionSummary(action)}\n共 ${kws.length} 个词。受演练/护栏/台账保护。确认采纳？`,
      '确认采纳', { confirmButtonText: '确认执行', cancelButtonText: '再想想', type: 'warning' },
    )
  } catch { return }
  try {
    const res = await adoptAction({
      tenantId: TENANT_ID.value, type: action.type, keywords: kws,
      adjustPct: action.adjust_pct, matchMode: action.match_mode,
    })
    const ok = res.results.filter((r) => r.status === 'success' || r.status === 'dry_run').length
    const skip = res.results.filter((r) => r.status === 'skipped').length
    const fail = res.results.filter((r) => r.status === 'failed').length
    action._done = true
    const tag = res.dry_run ? '（演练模式：仅记台账，未真改线上）' : ''
    messages.value.push({
      role: 'assistant',
      content: `已采纳「${ACTION_VERB[action.type] || action.type}」${tag}\n成功 ${ok}｜跳过 ${skip}｜失败 ${fail}`
        + (skip || fail ? '\n' + res.results.filter((r) => r.status !== 'success' && r.status !== 'dry_run').map((r) => `· ${r.keyword}：${r.detail}`).join('\n') : ''),
      suggestions: [], actions: [], pendingMemories: [],
    })
    await scrollBottom()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  }
}

// 确认 AI 抽取的记忆 → 入库
async function confirmMemory(msg, mem, idx) {
  try {
    await createMemory({ tenantId: TENANT_ID.value, memType: mem.type, content: mem.content, source: 'assistant' })
    msg.pendingMemories.splice(idx, 1)
    ElMessage.success('已记住')
    loadMemories()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  }
}
function dismissMemory(msg, idx) {
  msg.pendingMemories.splice(idx, 1)
}

async function removeMemory(m) {
  try {
    await deleteMemory({ tenantId: TENANT_ID.value, id: m.id })
    memories.value = memories.value.filter((x) => x.id !== m.id)
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  }
}

// 切换客户：清空当前显示并重载该客户的历史与记忆
watch(TENANT_ID, () => { messages.value = []; loadMemories(); loadHistory() })

onMounted(() => { loadMemories(); loadHistory() })
</script>

<template>
  <div class="chat-page">
    <div class="chat-col">
      <!-- 欢迎态 -->
      <div v-if="!started" class="welcome">
        <div class="welcome-icon">✨</div>
        <div class="welcome-title">AI 优化助手</div>
        <div class="welcome-sub">问我关于「{{ tenantName || '当前客户' }}」的投放——消费、转化、线索、该砍的词…我基于实时数据回答并给建议。</div>
        <div class="examples">
          <div v-for="e in EXAMPLES" :key="e" class="example-chip" @click="send(e)">{{ e }}</div>
        </div>
      </div>

      <!-- 对话流 -->
      <div v-else ref="scrollEl" class="messages">
        <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
          <div class="bubble">{{ m.content }}</div>
          <!-- 建议跳转 -->
          <div v-if="m.suggestions?.length" class="suggestions">
            <div v-for="(s, si) in m.suggestions" :key="si" class="sg">
              <span class="sg-reason">{{ s.reason }}</span>
              <el-button v-if="TARGET_ROUTE[s.target]" size="small" type="primary" plain @click="gotoTarget(s.target)">
                {{ s.label || ('去' + TARGET_ROUTE[s.target].label) }} →
              </el-button>
            </div>
          </div>
          <!-- 智能搭建：对话负责收集与生成摘要，完整编辑留在搭建页 -->
          <div v-if="m.builder" class="builder-card" :class="m.builder.status">
            <div class="builder-head">
              <div class="builder-mark">AI</div>
              <div class="builder-head-copy">
                <strong>智能搭建</strong>
                <span>{{ m.builder.status === 'intake' ? '正在收集搭建信息' : m.builder.status === 'ready' ? '草案已生成' : m.builder.status === 'error' ? '草案生成失败' : '正在生成草案' }}</span>
              </div>
              <span class="builder-safe">演练模式</span>
            </div>

            <div v-if="m.builder.status === 'intake'" class="builder-intake">
              <span>还需要补充</span>
              <b v-for="field in m.builder.missing || []" :key="field">{{ BUILDER_FIELD_LABELS[field] || field }}</b>
            </div>

            <div v-else-if="m.builder.status === 'loading'" class="builder-loading">
              <span class="builder-loader" />
              <div>
                <strong>正在读取落地页并筛选高意向关键词</strong>
                <span>随后会生成计划、单元、关键词和创意草案</span>
              </div>
            </div>

            <div v-else-if="m.builder.status === 'error'" class="builder-error">
              <span>{{ m.builder.error }}</span>
              <el-button size="small" type="primary" plain @click="generateAssistantDraft(m)">重新生成</el-button>
            </div>

            <template v-else-if="m.builder.status === 'ready'">
              <div class="builder-summary">{{ m.builder.result?.draft?.summary || '已生成一版可编辑的百度搜索推广草案。' }}</div>
              <div class="builder-stats">
                <span><b>{{ draftStats(m.builder.result).campaigns }}</b> 计划</span>
                <span><b>{{ draftStats(m.builder.result).adgroups }}</b> 单元</span>
                <span><b>{{ draftStats(m.builder.result).keywords }}</b> 关键词</span>
                <span><b>{{ draftStats(m.builder.result).creatives }}</b> 创意</span>
              </div>
              <div class="builder-settings">
                <span v-for="item in builderSettingText(m.builder)" :key="item">{{ item }}</span>
              </div>
              <div class="builder-foot">
                <span>进入后可逐项修改、勾选并演练写入</span>
                <a
                  v-if="canUseBuilder"
                  class="builder-open"
                  href="/onboarding/builder"
                  data-testid="assistant-builder-open"
                  @click="prepareBuilderHandoff(m, $event)"
                >
                  进入智能搭建编辑 →
                </a>
                <el-button v-else size="small" type="primary" disabled>进入智能搭建编辑 →</el-button>
              </div>
            </template>
          </div>
          <!-- 可执行动作：一键采纳（点了才执行，受演练/护栏/台账保护） -->
          <div v-for="(a, ai) in m.actions || []" :key="'act' + ai" class="act-card" :class="{ done: a._done }">
            <div class="act-info">
              <span class="act-verb" :class="a.type">{{ ACTION_VERB[a.type] || a.type }}</span>
              <span class="act-text">{{ actionSummary(a) }}</span>
              <span v-if="a.reason" class="act-reason">{{ a.reason }}</span>
            </div>
            <el-button size="small" type="primary" :disabled="a._done" @click="adopt(a, m)">
              {{ a._done ? '已采纳' : (a.label || '采纳并执行') }}
            </el-button>
          </div>
          <!-- AI 想记住的关键信息（待确认） -->
          <div v-for="(mem, mi) in m.pendingMemories || []" :key="'mem' + mi" class="mem-confirm">
            <span class="mem-type">{{ MEM_TYPE_LABEL[mem.type] || '记忆' }}</span>
            <span class="mem-text">{{ mem.content }}</span>
            <el-button size="small" type="success" plain @click="confirmMemory(m, mem, mi)">记住</el-button>
            <el-button size="small" text @click="dismissMemory(m, mi)">忽略</el-button>
          </div>
        </div>
        <div v-if="sending" class="msg assistant"><div class="bubble typing">{{ drafting ? '正在生成搭建草案…' : '思考中…' }}</div></div>
      </div>

      <!-- 输入区 -->
      <div class="composer">
        <div class="composer-box">
          <el-input
            v-model="input"
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 6 }"
            resize="none"
            class="composer-input"
            placeholder="问我关于这个客户投放的任何问题…"
            @keydown.enter.exact.prevent="send()"
          />
          <button class="send-btn" :disabled="!input.trim() || sending" :title="sending ? '思考中' : '发送'" @click="send()">
            <span v-if="!sending">↑</span><span v-else class="send-loading" />
          </button>
        </div>
        <div class="composer-hint">
          <span>Enter 发送 · Shift+Enter 换行</span>
          <span class="retain-note">聊天记录保留近 {{ retainDays }} 天，更早的自动清理（客户记忆不受影响）</span>
        </div>
      </div>
    </div>

    <!-- 记忆侧栏：客户目标/约束（长期记住，每轮喂给 AI） -->
    <div class="mem-col">
      <div class="mem-head">客户记忆</div>
      <div class="mem-hint">AI 长期记住的目标/约束/偏好，每次对话都会参考。不会随对话变长而丢失。</div>
      <div v-if="!memories.length" class="mem-empty">还没有。在对话里告诉我你的目标（如"线索成本控制在 200 以内"），确认后就记在这里。</div>
      <div v-for="m in memories" :key="m.id" class="mem-item">
        <span class="mem-type">{{ m.type_label }}</span>
        <span class="mem-text">{{ m.content }}</span>
        <span class="mem-del" @click="removeMemory(m)">×</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-page { display: flex; gap: 16px; height: calc(100vh - 128px); min-height: 540px; }
.chat-col { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.mem-col { width: 280px; flex: none; background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; padding: 14px; overflow-y: auto; }
@media (max-width: 1100px) { .mem-col { display: none; } }

/* 欢迎态 */
.welcome { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; }
.welcome-icon { font-size: 40px; }
.welcome-title { font-size: 24px; font-weight: 700; color: var(--sem-text); margin-top: 10px; }
.welcome-sub { font-size: 13px; color: var(--sem-text-sub); margin-top: 8px; max-width: 520px; line-height: 1.7; }
.examples { display: flex; flex-wrap: wrap; gap: 10px; justify-content: center; margin-top: 24px; max-width: 620px; }
.example-chip { padding: 10px 16px; background: #fff; border: 1px solid var(--sem-border); border-radius: 20px; font-size: 13px; color: var(--sem-text); cursor: pointer; transition: all 0.12s; }
.example-chip:hover { border-color: var(--sem-primary); color: var(--sem-primary); background: #eff4fb; }

/* 对话流 */
.messages { flex: 1; overflow-y: auto; padding: 8px 4px; }
.msg { margin-bottom: 16px; display: flex; flex-direction: column; }
.msg.user { align-items: flex-end; }
.msg.assistant { align-items: flex-start; }
.bubble { max-width: 76%; padding: 10px 14px; border-radius: 12px; font-size: 13px; line-height: 1.7; white-space: pre-wrap; word-break: break-word; }
.msg.user .bubble { background: var(--sem-primary); color: #fff; border-bottom-right-radius: 3px; }
.msg.assistant .bubble { background: #fff; border: 1px solid var(--sem-border); color: var(--sem-text); border-bottom-left-radius: 3px; }
.bubble.typing { color: #9ca3af; }

.suggestions { margin-top: 8px; display: flex; flex-direction: column; gap: 6px; max-width: 76%; }
.sg { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.sg-reason { font-size: 12px; color: var(--sem-text-sub); }

.builder-card {
  width: min(680px, 76%); margin-top: 8px; overflow: hidden;
  background: #fff; border: 1px solid #cddcec; border-radius: 8px;
  box-shadow: 0 8px 24px rgba(30, 64, 97, 0.08);
}
.builder-head { min-height: 52px; display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-bottom: 1px solid #e8eef5; background: #f8fafc; }
.builder-mark { width: 30px; height: 30px; display: grid; place-items: center; flex: none; border-radius: 6px; background: var(--sem-primary); color: #fff; font-size: 11px; font-weight: 700; }
.builder-head-copy { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 1px; }
.builder-head-copy strong { font-size: 13px; color: var(--sem-text); }
.builder-head-copy span { font-size: 11px; color: var(--sem-text-sub); }
.builder-safe { flex: none; padding: 2px 7px; border: 1px solid #bfe3d4; border-radius: 10px; color: #167a5a; background: #f0faf6; font-size: 10px; font-weight: 600; }
.builder-intake { min-height: 54px; display: flex; align-items: center; flex-wrap: wrap; gap: 7px; padding: 12px; color: var(--sem-text-sub); font-size: 12px; }
.builder-intake b { padding: 3px 8px; border-radius: 4px; background: #fff7e8; color: #9b6515; font-size: 11px; font-weight: 600; }
.builder-loading { min-height: 76px; display: flex; align-items: center; gap: 12px; padding: 14px; }
.builder-loading > div { display: flex; flex-direction: column; gap: 4px; }
.builder-loading strong { color: var(--sem-text); font-size: 12px; }
.builder-loading span:not(.builder-loader) { color: var(--sem-text-sub); font-size: 11px; }
.builder-loader { width: 28px; height: 28px; flex: none; border: 3px solid #dce8f4; border-top-color: var(--sem-primary); border-radius: 50%; animation: spin 0.8s linear infinite; }
.builder-error { min-height: 58px; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px; color: var(--sem-danger); font-size: 12px; }
.builder-summary { padding: 12px 12px 8px; color: var(--sem-text); font-size: 12px; font-weight: 600; line-height: 1.6; }
.builder-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); margin: 0 12px; border: 1px solid #e4ebf3; border-radius: 6px; overflow: hidden; }
.builder-stats span { min-height: 48px; display: flex; align-items: baseline; justify-content: center; gap: 4px; padding: 11px 6px; color: var(--sem-text-sub); font-size: 11px; }
.builder-stats span + span { border-left: 1px solid #e4ebf3; }
.builder-stats b { color: var(--sem-primary); font-size: 17px; font-variant-numeric: tabular-nums; }
.builder-settings { display: flex; flex-wrap: wrap; gap: 6px; padding: 10px 12px 12px; }
.builder-settings span { padding: 3px 7px; border-radius: 4px; background: #f2f5f8; color: #526170; font-size: 10px; }
.builder-foot { min-height: 50px; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 9px 12px; border-top: 1px solid #e8eef5; background: #fbfcfd; }
.builder-foot > span { color: var(--sem-text-sub); font-size: 11px; }
.builder-open {
  min-height: 28px; display: inline-flex; align-items: center; justify-content: center;
  padding: 0 11px; border: 1px solid var(--sem-primary); border-radius: 4px;
  background: var(--sem-primary); color: #fff; font-size: 12px; line-height: 1;
  text-decoration: none; white-space: nowrap; transition: background 0.15s, border-color 0.15s;
}
.builder-open:hover { background: #2b73b9; border-color: #2b73b9; color: #fff; }

.act-card { margin-top: 8px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; background: #eff4fb; border: 1px solid #cfe0f3; border-radius: 8px; padding: 8px 12px; max-width: 76%; }
.act-card.done { opacity: 0.6; }
.act-info { flex: 1; min-width: 160px; display: flex; flex-direction: column; gap: 2px; }
.act-verb { font-size: 10px; padding: 1px 7px; border-radius: 10px; font-weight: 600; align-self: flex-start; }
.act-verb.pause { background: #fef1e1; color: #ba7517; }
.act-verb.adjust_bid { background: #f2ebfb; color: #6b47b5; }
.act-verb.negative { background: #fdeaea; color: var(--sem-danger); }
.act-text { font-size: 12px; color: var(--sem-text); }
.act-reason { font-size: 11px; color: var(--sem-text-sub); }

.mem-confirm { margin-top: 8px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; background: #f0f9f4; border: 1px solid #cce9d8; border-radius: 8px; padding: 8px 12px; max-width: 76%; }
.mem-type { font-size: 10px; padding: 1px 7px; border-radius: 10px; background: #eff4fb; color: var(--sem-primary); font-weight: 600; flex: none; }
.mem-text { font-size: 12px; color: var(--sem-text); flex: 1; min-width: 120px; }

/* 输入区：居中圆角胶囊 + 圆形发送按钮 */
.composer { align-self: center; width: 100%; max-width: 760px; padding-top: 12px; }
.composer-box {
  display: flex; align-items: flex-end; gap: 8px;
  background: #fff; border: 1px solid var(--sem-border); border-radius: 24px;
  padding: 5px 6px 5px 18px; box-shadow: 0 2px 12px rgba(17, 24, 39, 0.06);
  transition: border-color 0.15s, box-shadow 0.15s;
}
.composer-box:focus-within { border-color: var(--sem-primary); box-shadow: 0 2px 16px rgba(24, 95, 165, 0.12); }
.composer-input { flex: 1; }
.composer-input :deep(.el-textarea__inner) {
  border: none; box-shadow: none; background: transparent; resize: none;
  padding: 8px 0; font-size: 14px; line-height: 1.6; color: var(--sem-text);
}
.send-btn {
  flex: none; width: 34px; height: 34px; border-radius: 50%; border: none;
  background: var(--sem-primary); color: #fff; font-size: 18px; font-weight: 700;
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  transition: opacity 0.15s, background 0.15s;
}
.send-btn:hover:not(:disabled) { opacity: 0.88; }
.send-btn:disabled { background: #cbd5e1; cursor: not-allowed; }
.send-loading { width: 13px; height: 13px; border: 2px solid rgba(255, 255, 255, 0.5); border-top-color: #fff; border-radius: 50%; animation: spin 0.7s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.composer-hint { display: flex; justify-content: space-between; font-size: 11px; color: #9ca3af; margin-top: 8px; padding: 0 12px; }
.retain-note { color: #c0c4cc; }

@media (max-width: 760px) {
  .bubble, .suggestions, .act-card, .mem-confirm, .builder-card { max-width: 92%; }
  .builder-card { width: 92%; }
  .builder-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .builder-stats span:nth-child(3) { border-left: none; border-top: 1px solid #e4ebf3; }
  .builder-stats span:nth-child(4) { border-top: 1px solid #e4ebf3; }
  .builder-foot { align-items: flex-start; flex-direction: column; }
  .composer-hint { justify-content: flex-end; }
  .composer-hint > span:first-child { display: none; }
}

/* 记忆侧栏 */
.mem-head { font-size: 14px; font-weight: 600; color: var(--sem-text); }
.mem-hint { font-size: 11px; color: #9ca3af; margin: 6px 0 12px; line-height: 1.6; }
.mem-empty { font-size: 12px; color: #9ca3af; line-height: 1.6; }
.mem-item { display: flex; align-items: flex-start; gap: 6px; padding: 8px 0; border-bottom: 1px solid #f3f4f6; }
.mem-item .mem-text { font-size: 12px; line-height: 1.5; }
.mem-del { color: #c0c4cc; cursor: pointer; font-size: 14px; flex: none; }
.mem-del:hover { color: var(--sem-danger); }
</style>
