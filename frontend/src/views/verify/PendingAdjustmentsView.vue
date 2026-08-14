<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  fetchBudgetAdjustments,
  fetchPendingAdjustments,
  genAiVerdict,
  markVerified,
} from '../../api/adjustmentVerify'
import { session } from '../../store/session'

const router = useRouter()
const TENANT_ID = computed(() => session.tenantId)
const canEdit = computed(() => session.canEdit('verify.pending'))

const loading = ref(false)
const error = ref('')
const data = ref(null)
const days = ref(7)
const statusFilter = ref('')
const mode = ref('keyword')
const aiLoading = ref({})

const fmtMoney = (v) => (v == null ? '-' : '¥ ' + Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 2 }))
const fmtCtr = (v) => (v == null ? '-' : (v * 100).toFixed(2) + '%')
const fmtPct = (v) => (v == null ? '-' : Number(v).toFixed(1) + '%')
const fmtTime = (v) => (v ? v.slice(0, 16).replace('T', ' ') : '-')
const aiEnabled = computed(() => data.value?.ai_enabled === true)
const emptyText = computed(() => `最近 ${days.value} 天没有${mode.value === 'budget' ? '预算调整' : '出价调整'}记录`)

const VERDICT_META = {
  achieved: { label: '已达成', cls: 'v-ok' },
  missed: { label: '未达成', cls: 'v-bad' },
  watch: { label: '继续观察', cls: 'v-watch' },
}
const DIR_META = {
  raise: { label: '加价', cls: 'd-up' },
  lower: { label: '降价', cls: 'd-down' },
  flat: { label: '调整', cls: '' },
}

async function load() {
  if (!TENANT_ID.value) return
  loading.value = true
  error.value = ''
  try {
    const fetcher = mode.value === 'budget' ? fetchBudgetAdjustments : fetchPendingAdjustments
    data.value = await fetcher({
      tenantId: TENANT_ID.value,
      days: days.value,
      status: statusFilter.value,
    })
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function delta(after, before, key) {
  if (!after || !before || after[key] == null || before[key] == null) return null
  return Math.round((after[key] - before[key]) * 100) / 100
}

function budgetDelta(after, before, key) {
  if (!after || !before || after[key] == null || before[key] == null) return null
  return Math.round((after[key] - before[key]) * 10) / 10
}

async function runAi(item) {
  aiLoading.value = { ...aiLoading.value, [item.dedup_key]: true }
  try {
    const r = await genAiVerdict({ tenantId: TENANT_ID.value, dedupKey: item.dedup_key })
    if (r.enabled === false) ElMessage.warning('未配置 DeepSeek，AI 研判不可用')
    else {
      ElMessage.success('AI 研判完成')
      load()
    }
  } catch (e) {
    ElMessage.error('AI 研判失败：' + e.message)
  } finally {
    aiLoading.value = { ...aiLoading.value, [item.dedup_key]: false }
  }
}

async function setVerdict(item, verdict) {
  try {
    await markVerified({ tenantId: TENANT_ID.value, dedupKey: item.dedup_key, verdict })
    ElMessage.success('已标记：' + VERDICT_META[verdict].label)
    load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function reopen(item) {
  try {
    await markVerified({ tenantId: TENANT_ID.value, dedupKey: item.dedup_key, reopen: true })
    load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

watch([TENANT_ID, days, statusFilter, mode], load)
onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <div class="page-header">
      <div>
        <div class="page-title">待验证调价</div>
        <div class="page-desc">对比调整前后效果，核对是否达成目标；预算调整复用同一套人工验证状态。</div>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" style="margin-bottom: 14px" />

    <div class="toolbar">
      <el-radio-group v-model="mode" size="small">
        <el-radio-button label="keyword">关键词调价</el-radio-button>
        <el-radio-button label="budget">预算调整</el-radio-button>
      </el-radio-group>
      <el-radio-group v-model="days" size="small">
        <el-radio-button :label="7">近 7 天</el-radio-button>
        <el-radio-button :label="30">近 30 天</el-radio-button>
      </el-radio-group>
      <el-radio-group v-model="statusFilter" size="small">
        <el-radio-button label="">全部</el-radio-button>
        <el-radio-button label="pending">待验证</el-radio-button>
        <el-radio-button label="verified">已验证</el-radio-button>
      </el-radio-group>
      <span v-if="data" class="summary">
        共 {{ data.summary.total }} · 待验证 <b>{{ data.summary.pending }}</b> · 已验证 {{ data.summary.verified }}
      </span>
    </div>

    <div v-for="it in mode === 'keyword' ? (data?.items || []) : []" :key="it.dedup_key" class="adj-card" :class="{ verified: it.review.status === 'verified' }">
      <div class="adj-head">
        <a v-if="it.keyword_id" class="kw" @click="router.push(`/monitor/keywords/${it.keyword_id}?from=adjustments`)">{{ it.keyword }} →</a>
        <span v-else class="kw plain">{{ it.keyword }}</span>
        <span class="dir" :class="DIR_META[it.direction]?.cls">{{ DIR_META[it.direction]?.label || '调整' }}</span>
        <span class="bid">{{ it.old_value }} → {{ it.new_value }}</span>
        <span v-if="it.change_pct != null" class="pct" :class="it.change_pct >= 0 ? 'up' : 'down'">{{ it.change_pct >= 0 ? '+' : '' }}{{ it.change_pct }}%</span>
        <span v-if="it.over_limit" class="over">超 20%</span>
        <span class="time">{{ fmtTime(it.opt_time) }}</span>
        <span class="st" :class="it.review.status === 'verified' ? 'st-ok' : 'st-pending'">{{ it.review.status === 'verified' ? '已验证' : '待验证' }}</span>
      </div>

      <table class="eff">
        <thead><tr><th></th><th>日均消费</th><th>日均点击</th><th>日均展现</th><th>点击率</th><th>平均排名</th></tr></thead>
        <tbody>
          <tr><td class="rowh">调价前</td>
            <td>{{ it.effect.before ? fmtMoney(it.effect.before.cost_per_day) : '-' }}</td>
            <td>{{ it.effect.before?.click_per_day ?? '-' }}</td>
            <td>{{ it.effect.before?.impression_per_day ?? '-' }}</td>
            <td>{{ fmtCtr(it.effect.before?.ctr) }}</td>
            <td>{{ it.effect.before?.avg_rank ?? '-' }}</td>
          </tr>
          <tr><td class="rowh">调价后<span v-if="it.effect.after" class="days">（{{ it.effect.after.days }}天）</span></td>
            <td>{{ it.effect.after ? fmtMoney(it.effect.after.cost_per_day) : '调后数据未到' }}</td>
            <td>{{ it.effect.after?.click_per_day ?? '-' }}</td>
            <td>{{ it.effect.after?.impression_per_day ?? '-' }}</td>
            <td>{{ fmtCtr(it.effect.after?.ctr) }}</td>
            <td>
              {{ it.effect.after?.avg_rank ?? '-' }}
              <span v-if="delta(it.effect.after, it.effect.before, 'avg_rank') != null"
                    class="dlt" :class="delta(it.effect.after, it.effect.before, 'avg_rank') <= 0 ? 'good' : 'bad'">
                {{ delta(it.effect.after, it.effect.before, 'avg_rank') <= 0 ? '前移' : '后退' }} {{ Math.abs(delta(it.effect.after, it.effect.before, 'avg_rank')) }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>

      <div v-if="it.ai.verdict" class="ai" :class="VERDICT_META[it.ai.verdict]?.cls">
        <b>AI 研判：{{ VERDICT_META[it.ai.verdict]?.label }}</b> · {{ it.ai.reason }}
      </div>

      <div class="adj-foot">
        <template v-if="it.review.status === 'verified'">
          <span class="vd" :class="VERDICT_META[it.review.verdict]?.cls" v-if="it.review.verdict">人工判定：{{ VERDICT_META[it.review.verdict]?.label }}</span>
          <span v-if="it.review.note" class="note">备注：{{ it.review.note }}</span>
          <span class="foot-spacer" />
          <button v-if="canEdit" class="act" @click="reopen(it)">改回待验证</button>
        </template>
        <template v-else>
          <button v-if="canEdit && aiEnabled" class="act" :disabled="aiLoading[it.dedup_key]" @click="runAi(it)">
            {{ aiLoading[it.dedup_key] ? 'AI 研判中...' : (it.ai.verdict ? '重新 AI 研判' : 'AI 研判') }}
          </button>
          <span class="foot-spacer" />
          <template v-if="canEdit">
            <span class="judge-label">判定：</span>
            <button class="act v-ok" @click="setVerdict(it, 'achieved')">达成</button>
            <button class="act v-bad" @click="setVerdict(it, 'missed')">未达成</button>
            <button class="act v-watch" @click="setVerdict(it, 'watch')">观察</button>
          </template>
        </template>
      </div>
    </div>

    <div v-for="it in mode === 'budget' ? (data?.items || []) : []" :key="it.dedup_key" class="adj-card budget-card" :class="{ verified: it.review.status === 'verified' }">
      <div class="adj-head">
        <span class="kw plain">{{ it.scope === 'account' ? '账户日预算' : (it.campaign_name || `计划 ${it.entity_id}`) }}</span>
        <span class="dir">{{ it.scope === 'account' ? '账户级' : '计划级' }}</span>
        <span class="bid">{{ fmtMoney(it.old_budget) }} → {{ fmtMoney(it.new_budget) }}</span>
        <span v-if="it.change_pct != null" class="pct" :class="it.change_pct >= 0 ? 'up' : 'down'">{{ it.change_pct >= 0 ? '+' : '' }}{{ it.change_pct }}%</span>
        <span class="time">{{ fmtTime(it.action_time) }}</span>
        <span class="st" :class="it.review.status === 'verified' ? 'st-ok' : 'st-pending'">{{ it.review.status === 'verified' ? '已验证' : '待验证' }}</span>
      </div>

      <table class="eff">
        <thead><tr><th></th><th>日均消费</th><th>预算使用率</th><th>撞线天数占比</th></tr></thead>
        <tbody>
          <tr><td class="rowh">调整前</td>
            <td>{{ it.effect.before ? fmtMoney(it.effect.before.cost_per_day) : '-' }}</td>
            <td>{{ fmtPct(it.effect.before?.usage_pct) }}</td>
            <td>{{ fmtPct(it.effect.before?.overrun_day_pct) }}</td>
          </tr>
          <tr><td class="rowh">调整后</td>
            <td>{{ it.effect.after ? fmtMoney(it.effect.after.cost_per_day) : '调整后数据未到' }}</td>
            <td>
              {{ fmtPct(it.effect.after?.usage_pct) }}
              <span v-if="budgetDelta(it.effect.after, it.effect.before, 'usage_pct') != null"
                    class="dlt" :class="budgetDelta(it.effect.after, it.effect.before, 'usage_pct') <= 0 ? 'good' : 'bad'">
                {{ budgetDelta(it.effect.after, it.effect.before, 'usage_pct') >= 0 ? '+' : '' }}{{ budgetDelta(it.effect.after, it.effect.before, 'usage_pct') }}%
              </span>
            </td>
            <td>
              {{ fmtPct(it.effect.after?.overrun_day_pct) }}
              <span v-if="budgetDelta(it.effect.after, it.effect.before, 'overrun_day_pct') != null"
                    class="dlt" :class="budgetDelta(it.effect.after, it.effect.before, 'overrun_day_pct') <= 0 ? 'good' : 'bad'">
                {{ budgetDelta(it.effect.after, it.effect.before, 'overrun_day_pct') >= 0 ? '+' : '' }}{{ budgetDelta(it.effect.after, it.effect.before, 'overrun_day_pct') }}%
              </span>
            </td>
          </tr>
        </tbody>
      </table>

      <div class="adj-foot">
        <template v-if="it.review.status === 'verified'">
          <span class="vd" :class="VERDICT_META[it.review.verdict]?.cls" v-if="it.review.verdict">人工判定：{{ VERDICT_META[it.review.verdict]?.label }}</span>
          <span v-if="it.review.note" class="note">备注：{{ it.review.note }}</span>
          <span class="foot-spacer" />
          <button v-if="canEdit" class="act" @click="reopen(it)">改回待验证</button>
        </template>
        <template v-else>
          <span class="foot-spacer" />
          <template v-if="canEdit">
            <span class="judge-label">判定：</span>
            <button class="act v-ok" @click="setVerdict(it, 'achieved')">达成</button>
            <button class="act v-bad" @click="setVerdict(it, 'missed')">未达成</button>
            <button class="act v-watch" @click="setVerdict(it, 'watch')">观察</button>
          </template>
        </template>
      </div>
    </div>

    <div v-if="!loading && !(data?.items || []).length" class="empty">{{ emptyText }}</div>
  </div>
</template>

<style scoped>
.page-header { margin-bottom: 14px; }
.page-title { font-size: 20px; font-weight: 600; color: var(--sem-text); }
.page-desc { font-size: 12px; color: var(--sem-text-sub); margin-top: 4px; }
.toolbar { display: flex; gap: 16px; align-items: center; margin-bottom: 14px; flex-wrap: wrap; }
.summary { font-size: 12px; color: var(--sem-text-sub); }
.summary b { color: var(--sem-danger); }

.adj-card { background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; padding: 14px 18px; margin-bottom: 10px; border-left: 4px solid #ba7517; }
.adj-card.verified { border-left-color: #1d9e75; opacity: 0.92; }
.budget-card { border-left-color: #185fa5; }
.budget-card.verified { border-left-color: #1d9e75; }
.adj-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.kw { font-size: 15px; font-weight: 700; color: var(--sem-primary); cursor: pointer; }
.kw:hover { text-decoration: underline; }
.kw.plain { color: var(--sem-text); cursor: default; }
.dir { font-size: 11px; padding: 2px 8px; border-radius: 4px; background: #f3f4f6; color: #4b5563; }
.dir.d-up { background: #fde4e4; color: #b91c1c; }
.dir.d-down { background: #d8efe2; color: #15724b; }
.bid { font-size: 13px; color: var(--sem-text); font-variant-numeric: tabular-nums; }
.pct { font-size: 12px; font-weight: 600; }
.pct.up { color: #e24b4a; }
.pct.down { color: #1d9e75; }
.over { font-size: 11px; background: #fef2f2; color: #b91c1c; padding: 1px 7px; border-radius: 4px; }
.time { font-size: 11px; color: #9ca3af; margin-left: auto; }
.st { font-size: 11px; padding: 2px 8px; border-radius: 10px; }
.st-pending { background: #fcf6ea; color: #ba7517; }
.st-ok { background: #e5f4ed; color: #1d9e75; }

.eff { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.eff th { text-align: center; color: #9ca3af; font-weight: 500; padding: 5px 8px; font-size: 11px; }
.eff td { text-align: center; padding: 6px 8px; border-top: 1px solid #f3f4f6; font-variant-numeric: tabular-nums; }
.eff .rowh { text-align: left; color: var(--sem-text-sub); }
.days { color: #c0c4cc; font-size: 11px; }
.dlt { font-size: 11px; margin-left: 4px; }
.dlt.good { color: #1d9e75; }
.dlt.bad { color: #e24b4a; }

.ai { margin-top: 10px; padding: 8px 12px; border-radius: 6px; font-size: 12.5px; line-height: 1.6; background: #f4f8fd; }
.ai.v-ok { background: #f0faf4; }
.ai.v-bad { background: #fef5f5; }
.ai.v-watch { background: #fcf8ef; }

.adj-foot { display: flex; align-items: center; gap: 8px; margin-top: 12px; padding-top: 10px; border-top: 1px solid #f3f4f6; font-size: 12px; color: var(--sem-text-sub); flex-wrap: wrap; }
.foot-spacer { flex: 1; }
.judge-label { color: #9ca3af; }
.act { font-size: 11px; padding: 4px 11px; border-radius: 4px; border: 1px solid var(--sem-border); background: #fff; color: #4b5563; cursor: pointer; }
.act:hover { border-color: var(--sem-primary); color: var(--sem-primary); }
.act:disabled { opacity: 0.6; cursor: not-allowed; }
.act.v-ok:hover { border-color: #1d9e75; color: #1d9e75; }
.act.v-bad:hover { border-color: #e24b4a; color: #e24b4a; }
.act.v-watch:hover { border-color: #ba7517; color: #ba7517; }
.vd { font-size: 11px; padding: 2px 8px; border-radius: 10px; }
.vd.v-ok { background: #e5f4ed; color: #1d9e75; }
.vd.v-bad { background: #fef2f2; color: #b91c1c; }
.vd.v-watch { background: #fcf6ea; color: #ba7517; }
.note { font-size: 11px; color: var(--sem-text-sub); }
.empty { padding: 28px; text-align: center; color: #9ca3af; font-size: 12px; background: #fafbfc; border-radius: 8px; border: 1px dashed var(--sem-border); }
</style>
