<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchCustomerProfile, updateCustomerProfile } from '../../api/customerProfile'
import { session } from '../../store/session'

const TENANT_ID = computed(() => session.tenantId)
const canEdit = computed(() => session.canEdit('monitor.profile'))

const loading = ref(false)
const regen = ref(false)
const error = ref('')
const data = ref(null)

const editing = ref(false)
const saving = ref(false)
const eform = reactive({ industry: '', businessDesc: '' })

const fmtMoney = (v) => (v == null ? '—' : '¥ ' + Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 2 }))
const fmtInt = (v) => (v == null ? '—' : Number(v).toLocaleString('zh-CN'))
const fmtPct = (v) => (v == null ? '—' : v + '%')
const fmtCtr = (v) => (v == null ? '—' : (v * 100).toFixed(2) + '%')

const p = computed(() => data.value?.profile || null)
const aiEnabled = computed(() => data.value?.ai_enabled === true)

async function load(refreshSummary = false) {
  if (!TENANT_ID.value) return
  refreshSummary ? (regen.value = true) : (loading.value = true)
  error.value = ''
  try {
    data.value = await fetchCustomerProfile({ tenantId: TENANT_ID.value, refreshSummary })
    if (refreshSummary) ElMessage.success('AI 画像总结已重新生成')
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
    regen.value = false
  }
}

function openEdit() {
  eform.industry = p.value?.basics?.industry === '（未填）' ? '' : (p.value?.basics?.industry || '')
  eform.businessDesc = p.value?.basics?.business_desc || ''
  editing.value = true
}
async function saveEdit() {
  saving.value = true
  try {
    await updateCustomerProfile({ tenantId: TENANT_ID.value, industry: eform.industry, businessDesc: eform.businessDesc })
    ElMessage.success('已保存，AI 总结将按新描述重算')
    editing.value = false
    load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    saving.value = false
  }
}

watch(TENANT_ID, () => load())
onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <div class="page-header">
      <div>
        <div class="page-title">客户画像</div>
        <div class="page-desc">聚合该客户的投放特征 · 同样喂给 AI 调价建议，让 AI「懂这个客户」</div>
      </div>
      <div class="page-actions">
        <el-button v-if="canEdit" @click="openEdit">编辑行业 / 业务</el-button>
        <el-button v-if="canEdit && aiEnabled" :loading="regen" @click="load(true)">重新生成 AI 总结</el-button>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" style="margin-bottom: 14px" />

    <template v-if="p">
      <!-- AI 画像总结 -->
      <div v-if="data.summary" class="ai-summary">
        <div class="ai-tag">AI 眼中的这个客户</div>
        <div class="ai-text">{{ data.summary }}</div>
      </div>
      <div v-else-if="!aiEnabled" class="ai-disabled">未配置 AI（DeepSeek），仅展示结构化画像、无 AI 总结。</div>

      <div class="grid">
        <!-- ① 基础定位 -->
        <div class="card">
          <div class="card-h">基础定位</div>
          <div class="kv"><span>客户</span><b>{{ p.basics.name }}</b></div>
          <div class="kv"><span>行业</span><b>{{ p.basics.industry }}</b></div>
          <div class="kv"><span>品牌词根</span><b>{{ (p.basics.brand_terms || []).join('、') }}</b></div>
          <div class="kv"><span>策略</span><b>{{ p.basics.strategy || '—' }}</b></div>
          <div class="kv"><span>月预算</span><b>{{ fmtMoney(p.basics.monthly_budget) }}</b></div>
          <div v-if="p.basics.business_desc" class="biz">{{ p.basics.business_desc }}</div>
        </div>

        <!-- ② 账户结构 -->
        <div class="card">
          <div class="card-h">账户结构</div>
          <div class="big-row">
            <div><div class="big">{{ fmtInt(p.structure.keywords) }}</div><div class="big-l">关键词</div></div>
            <div><div class="big">{{ p.structure.campaigns }}</div><div class="big-l">计划</div></div>
            <div><div class="big">{{ p.structure.adgroups }}</div><div class="big-l">单元</div></div>
          </div>
          <div class="chips">
            <span v-for="c in p.structure.category_dist" :key="c.category" class="chip">{{ c.label }} {{ c.count }}</span>
          </div>
        </div>

        <!-- ③ 出价习惯 -->
        <div class="card">
          <div class="card-h">出价习惯</div>
          <div v-if="p.bid_habits.avg_diff_vs_guide != null" class="kv">
            <span>vs 百度指导价</span>
            <b :class="p.bid_habits.avg_diff_vs_guide >= 0 ? 'up' : 'down'">
              平均{{ p.bid_habits.avg_diff_vs_guide >= 0 ? '高' : '低' }} {{ fmtMoney(Math.abs(p.bid_habits.avg_diff_vs_guide)) }}
            </b>
          </div>
          <div class="kv"><span>高于指导价占比</span><b>{{ fmtPct(p.bid_habits.above_guide_pct) }}</b></div>
          <div class="sub-h">各分级均价</div>
          <div v-for="a in p.bid_habits.avg_price_by_category" :key="a.label" class="kv small">
            <span>{{ a.label }}</span><b>{{ fmtMoney(a.avg_price) }}</b>
          </div>
        </div>

        <!-- ④ 效果水位 -->
        <div class="card">
          <div class="card-h">效果水位<span v-if="p.performance.window" class="card-sub">近 30 天</span></div>
          <template v-if="p.performance.kpi">
            <div class="kv"><span>点击率</span><b>{{ fmtCtr(p.performance.kpi.ctr) }}</b></div>
            <div class="kv"><span>平均点击成本</span><b>{{ fmtMoney(p.performance.kpi.cpc) }}</b></div>
            <div class="kv"><span>平均排名</span><b>{{ p.performance.kpi.avg_rank ?? '—' }}</b></div>
            <div class="kv"><span>平均质量度</span><b>{{ p.performance.avg_quality ?? '—' }}</b></div>
            <div class="sub-h">设备消费占比</div>
            <div v-for="d in p.performance.device_split" :key="d.device" class="kv small">
              <span>{{ d.device }}</span><b>{{ fmtPct(d.cost_share_pct) }}（{{ fmtMoney(d.cost) }}）</b>
            </div>
          </template>
          <div v-else class="dim">暂无投放数据</div>
        </div>

        <!-- ⑤ 调价行为 -->
        <div class="card">
          <div class="card-h">调价行为<span class="card-sub">近 {{ p.adjust_behavior.window_days }} 天</span></div>
          <div class="big-row">
            <div><div class="big">{{ p.adjust_behavior.total }}</div><div class="big-l">调价次数</div></div>
            <div><div class="big">{{ p.adjust_behavior.avg_abs_pct ?? '—' }}%</div><div class="big-l">平均幅度</div></div>
            <div><div class="big warn">{{ p.adjust_behavior.over_limit }}</div><div class="big-l">超 20%</div></div>
          </div>
          <div class="kv small"><span>加价 / 降价</span><b>{{ p.adjust_behavior.raise_count }} / {{ p.adjust_behavior.lower_count }}</b></div>
        </div>

        <!-- ⑥ AI 建议采纳 -->
        <div class="card">
          <div class="card-h">AI 建议采纳</div>
          <div class="kv"><span>采纳率</span><b class="up">{{ fmtPct(p.adoption.adopt_rate_pct) }}</b></div>
          <div class="kv small"><span>已采纳</span><b>{{ p.adoption.status_counts.adopted || 0 }}</b></div>
          <div class="kv small"><span>已忽略</span><b>{{ p.adoption.status_counts.ignored || 0 }}</b></div>
          <div class="kv small"><span>待处理</span><b>{{ p.adoption.status_counts.pending || 0 }}</b></div>
        </div>
      </div>
    </template>

    <!-- 编辑行业/业务 -->
    <el-dialog v-model="editing" title="编辑行业 / 业务描述" width="460px">
      <el-form label-width="80px">
        <el-form-item label="行业">
          <el-input v-model="eform.industry" placeholder="如：工业泵 / 分离技术" />
        </el-form-item>
        <el-form-item label="业务描述">
          <el-input v-model="eform.businessDesc" type="textarea" :rows="4" placeholder="客户业务/投放定位补充，会喂给 AI 调价建议" maxlength="2000" show-word-limit />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editing = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-header { margin-bottom: 14px; display: flex; justify-content: space-between; align-items: flex-end; }
.page-title { font-size: 20px; font-weight: 600; color: var(--sem-text); }
.page-desc { font-size: 12px; color: var(--sem-text-sub); margin-top: 4px; }
.page-actions { display: flex; gap: 8px; }

.ai-summary { background: linear-gradient(135deg, #f4f8fd 0%, #eef6ff 100%); border-left: 3px solid var(--sem-primary); border-radius: 8px; padding: 14px 16px; margin-bottom: 16px; }
.ai-tag { font-size: 11px; font-weight: 700; color: var(--sem-primary); margin-bottom: 6px; }
.ai-text { font-size: 13px; line-height: 1.8; color: var(--sem-text); }
.ai-disabled { font-size: 12px; color: #9ca3af; padding: 8px 0 14px; }

.grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.card { background: #fff; border: 1px solid var(--sem-border); border-radius: 10px; padding: 16px 18px; }
.card-h { font-size: 14px; font-weight: 600; color: var(--sem-text); margin-bottom: 12px; display: flex; align-items: baseline; gap: 8px; }
.card-sub { font-size: 11px; font-weight: 400; color: #9ca3af; }
.kv { display: flex; justify-content: space-between; align-items: baseline; padding: 5px 0; font-size: 13px; }
.kv span { color: var(--sem-text-sub); }
.kv b { color: var(--sem-text); font-variant-numeric: tabular-nums; }
.kv.small { font-size: 12px; padding: 3px 0; }
.kv b.up { color: #e24b4a; }
.kv b.down { color: #1d9e75; }
.sub-h { font-size: 11px; color: #9ca3af; margin: 10px 0 4px; }
.biz { margin-top: 10px; padding-top: 10px; border-top: 1px solid #f3f4f6; font-size: 12px; color: var(--sem-text-sub); line-height: 1.7; }

.big-row { display: flex; justify-content: space-around; text-align: center; margin-bottom: 12px; }
.big { font-size: 24px; font-weight: 700; color: var(--sem-text); }
.big.warn { color: #ba7517; }
.big-l { font-size: 11px; color: var(--sem-text-sub); margin-top: 2px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { font-size: 11px; background: #eff4fb; color: #185fa5; padding: 2px 9px; border-radius: 10px; }
.dim { color: #c0c4cc; font-size: 13px; }
</style>
