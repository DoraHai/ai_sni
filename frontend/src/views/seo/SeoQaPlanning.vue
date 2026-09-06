<script setup>
import SeoQaBatchDrafts from './SeoQaBatchDrafts.vue'
import { computed, reactive, ref, watch } from 'vue'
import { seoQaGet, seoQaPost, analyzeSeoQaSemantic } from '../../api/seo'

const props = defineProps({ tenantId: Number, siteId: Number, canEdit: Boolean, revision: Number })
const emit = defineEmits(['open', 'changed'])
const result = ref(null), loading = ref(false), saving = ref(false), error = ref('')
const query = ref(''), view = ref('tree'), chosen = ref([]), action = ref('topic'), value = ref('')
const flags = reactive({ unanswered: false, coverageGap:false, demandFirst: false })
const intents = { learn: '了解与学习', compare: '比较与选择', buy: '购买决策', troubleshoot: '排查问题' }
const statuses = { open: '待选题', selected: '已选题', archived: '归档' }
const scopeKey = computed(() => `${props.tenantId}:${props.siteId}`)
const questions = computed(() => (result.value?.groups || []).flatMap(g => g.intents.flatMap(i => i.questions)))
const byId = computed(() => new Map(questions.value.map(q => [q.id, q])))
const groups = computed(() => (result.value?.groups || []).map(group => ({ ...group, intents: group.intents.map(intent => ({ ...intent,
  questions: intent.questions.filter(q => (!flags.unanswered || !q.answer_count) && (!flags.coverageGap || q.valid_answer_count===0) && (!query.value.trim() || `${q.title} ${q.topic}`.toLowerCase().includes(query.value.trim().toLowerCase()))).sort((a,b)=>flags.demandFirst ? demandPriority(b)-demandPriority(a) || (b.relevance||0)-(a.relevance||0) : 0),
})).filter(i => i.questions.length) })).filter(g => g.intents.length))
function demandPriority(row) {
  const recent = (row.sources || []).some(s => Number.isInteger(s.count) && s.count > 0 && s.period_end
    && Date.parse(s.period_end+'T23:59:59Z') >= Date.now()-30*86400000)
  return recent && !row.answer_count ? 1 : 0
}
const pairs = computed(() => (result.value?.similar_pairs || []).filter(p => !query.value.trim() || `${p.left_title} ${p.right_title}`.toLowerCase().includes(query.value.trim().toLowerCase())))
const semantic = ref(null), history = ref([])
async function loadHistory() {
  if (saving.value || !props.tenantId || !props.siteId) return
  const key=scopeKey.value, ticket=generation
  saving.value=true; error.value=''
  try {
    const response=await seoQaGet('planning/semantic/history',{tenant_id:props.tenantId,site_id:props.siteId})
    if(key===scopeKey.value && ticket===generation) history.value=response.items
  } catch(e) { if(key===scopeKey.value && ticket===generation) error.value=detail(e) }
  finally {saving.value=false}
}
async function recoverSemantic(row) {
  if(saving.value || !row.has_result) return
  const key=scopeKey.value, ticket=generation
  saving.value=true;error.value=''
  try {
    const response=await seoQaGet(`planning/semantic/history/${row.id}`,{tenant_id:props.tenantId,site_id:props.siteId})
    if(key===scopeKey.value && ticket===generation) semantic.value=response
  } catch(e) {if(key===scopeKey.value && ticket===generation) error.value=detail(e)}
  finally {saving.value=false}
}
function semanticPairCurrent(pair) {
  return [pair.left_id,pair.right_id].every(id => {
    const snapshot=semantic.value?.questions?.find(q=>q.id===id)
    return snapshot && byId.value.get(id)?.version===snapshot.version
  })
}
let generation = 0
async function analyzeSemantic() {
  if (!props.canEdit || saving.value || loading.value || chosen.value.length < 2 || chosen.value.length > 30) return
  const key = scopeKey.value, ticket = generation
  const selected = chosen.value.map(id => byId.value.get(id))
  if (selected.some(row => !row)) return
  saving.value = true; error.value = ''; semantic.value = null
  try {
    const response = await analyzeSeoQaSemantic({tenant_id:props.tenantId, site_id:props.siteId,
      items:selected.map(row=>({id:row.id,version:row.version}))})
    if (key === scopeKey.value && ticket === generation) semantic.value = response
  } catch(e) { if (key === scopeKey.value && ticket === generation) error.value = detail(e) }
  finally { saving.value = false }
}

function detail(e) { return typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : e.message || '操作失败，请刷新后重试' }
async function load() {
  const ticket = ++generation, key = scopeKey.value
  loading.value = true; error.value = ''; result.value = null; chosen.value = []; semantic.value = null; history.value = []
  if (!props.tenantId || !props.siteId) { loading.value = false; return }
  try {
    const response = await seoQaGet('planning', { tenant_id: props.tenantId, site_id: props.siteId })
    if (ticket === generation && key === scopeKey.value) result.value = response
  } catch (e) { if (ticket === generation && key === scopeKey.value) error.value = detail(e) }
  finally { if (ticket === generation) loading.value = false }
}
async function refreshAfterDrafts() {
  const key=scopeKey.value,ticket=generation
  try {
    const value=await seoQaGet('planning',{tenant_id:props.tenantId,site_id:props.siteId})
    if(key===scopeKey.value&&ticket===generation)result.value=value
  } catch(e) {if(key===scopeKey.value&&ticket===generation)error.value=detail(e)}
}
function toggle(id, checked) {
  if (!props.canEdit || saving.value) return
  if (checked && !chosen.value.includes(id)) {
    if (chosen.value.length >= 100) { error.value = '一次最多选择 100 个问题'; return }
    chosen.value = [...chosen.value, id]
  } else if (!checked) chosen.value = chosen.value.filter(item => item !== id)
}
function selectPair(pair) {
  if (!props.canEdit || saving.value) return
  chosen.value = [pair.left_id, pair.right_id]; action.value = 'topic'; value.value = ''
}
function open(id) { const row = byId.value.get(id); if (row && !saving.value) emit('open', row) }
async function apply() {
  if (!props.canEdit || saving.value || !chosen.value.length || !props.tenantId || !props.siteId) return
  const key = scopeKey.value, selected = chosen.value.map(id => byId.value.get(id))
  if (selected.some(row => !row)) { error.value = '所选问题已变化，请刷新后重试'; return }
  const change = value.value.trim()
  if (!change && action.value !== 'owner') { error.value = '请填写要应用的分类或状态'; return }
  const payload = { tenant_id: props.tenantId, site_id: props.siteId,
    items: selected.map(row => ({ id: row.id, version: row.version })), changes: { [action.value]: change || null } }
  saving.value = true; error.value = ''
  try {
    await seoQaPost('questions/batch', payload)
    if (key !== scopeKey.value) return
    await load(); if (key === scopeKey.value) emit('changed')
  } catch (e) {
    if (key === scopeKey.value) error.value = detail(e)
  } finally { saving.value = false }
}
watch([scopeKey, () => props.revision], () => { chosen.value = []; query.value = ''; value.value = ''; load() }, { immediate: true })
</script>

<template>
  <section class="qa-planning" :aria-busy="loading">
    <header><div><h2>选题规划</h2><p>按主题和意图组织问题，先找到尚未回答的需求，再安排内容工作。</p></div><el-button :loading="loading" :disabled="saving" @click="load">刷新规划</el-button></header>
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <template v-if="result">
      <SeoQaBatchDrafts :tenant-id="tenantId" :site-id="siteId" :can-edit="canEdit" :questions="chosen.map(id=>byId.get(id)).filter(Boolean)" @changed="refreshAfterDrafts" @open="row=>emit('open',row)"/>
      <div class="plan-stats"><div><strong>{{ result.included }}</strong><span>本次纳入问题</span></div><div><strong>{{ result.unanswered_count }}</strong><span>尚无回答草稿</span></div><div><strong>{{ result.reviewed_count }}</strong><span>有已审核内容</span></div><div><strong>{{ result.similar_pair_count }}</strong><span>文本重合候选对</span></div></div>
      <div class="plan-stats"><div><strong>{{ result.valid_covered_count ?? '未知' }}</strong><span>有有效审核回答</span></div><div><strong>{{ result.coverage_gap_count ?? '未知' }}</strong><span>尚无有效审核回答</span></div><div><strong>{{ result.observed_question_count ?? '未知' }}</strong><span>当前版本曾公开匹配</span></div></div><p class="plan-note">有效审核回答须当前证据关联有效；不是独立事实核实。公开匹配按最近观测，不代表实时存续或账号归属。</p><p class="plan-note">{{ result.definitions.scope }}。{{ result.truncated ? `共 ${result.total} 个未归档问题，本页未涵盖全部。` : '' }}已审核数量不等于已核验发布数量。</p>
      <div class="plan-toolbar"><el-button :type="view==='tree'?'primary':'default'" @click="view='tree'">主题问题树</el-button><el-button :type="view==='pairs'?'primary':'default'" @click="view='pairs'">相似问题候选</el-button><el-input v-model="query" placeholder="筛选本次规划中的问题或主题" clearable/><el-checkbox v-if="view==='tree'" v-model="flags.unanswered">只看尚无回答的问题</el-checkbox><el-checkbox v-if="view==='tree'" v-model="flags.coverageGap">只看尚无有效审核回答</el-checkbox><el-checkbox v-if="view==='tree'" v-model="flags.demandFirst">组内优先近期有需求且未回答</el-checkbox></div>
      <p v-if="flags.demandFirst" class="plan-note">每个主题/意图组内，优先统计结束日期在近 30 天、导入频次大于 0 且尚无回答的问题，再按人工业务相关性排序。不同指标或时间窗口不求和、不比较总热度；数据是用户导入，未由系统核实。</p>
      <div class="plan-batch" v-if="canEdit"><strong>已选 {{ chosen.length }} / 100</strong><el-select v-model="action" @change="value=''"><el-option value="topic" label="归入主题"/><el-option value="owner" label="分配负责人"/><el-option value="intent" label="设置意图"/><el-option value="status" label="设置选题状态"/></el-select><el-select v-if="action==='intent'" v-model="value" placeholder="选择意图"><el-option v-for="(label,key) in intents" :key="key" :value="key" :label="label"/></el-select><el-select v-else-if="action==='status'" v-model="value" placeholder="选择状态"><el-option v-for="(label,key) in statuses" :key="key" :value="key" :label="label"/></el-select><el-input v-else v-model="value" :placeholder="action==='owner'?'负责人；留空清除分配':'填写主题名称'" maxlength="120"/><el-button type="primary" :loading="saving" :disabled="loading || !chosen.length" @click="apply">应用到所选问题</el-button><el-button :disabled="saving" @click="chosen=[]">清空选择</el-button></div>
      <div v-if="canEdit" class="plan-toolbar"><el-button :disabled="saving || loading || chosen.length < 2 || chosen.length > 30" @click="analyzeSemantic">AI 分析所选问题的语义</el-button><span class="plan-note">选择 2–30 个问题，消耗一次 SEO AI 用量；结果需人工确认。</span></div>
      <div class="plan-toolbar"><el-button :disabled="saving || loading" @click="loadHistory">刷新本人分析记录</el-button><span class="plan-note">最近 20 次，结果保留 30 天；取回不再次扣费。网络中断后可重试原选择。</span></div>
      <div v-for="item in history" :key="item.id" class="plan-toolbar"><span class="plan-note">{{ new Date(item.created_at).toLocaleString('zh-CN') }} · {{ {running:'处理中',succeeded:'已完成',refunded:'已退款'}[item.status] || item.status }}</span><el-button :disabled="saving || !item.has_result" @click="recoverSemantic(item)">取回分析结果</el-button></div>
      <div v-if="semantic"><p class="plan-note">历史结果按分析时的问题版本展示；问题已更新或不在当前规划中时，请重新分析。</p><p class="plan-note">{{ semantic.meaning }}</p><el-empty v-if="!semantic.pairs.length" description="本次未返回语义候选，不代表已证明所有问题不同"/><article v-for="pair in semantic.pairs" :key="`${pair.left_id}:${pair.right_id}`" class="plan-pair"><div><button :disabled="saving" @click="open(pair.left_id)">{{ pair.left_title }}</button><button :disabled="saving" @click="open(pair.right_id)">{{ pair.right_title }}</button><p>AI 判断：{{ pair.reason }}</p></div><el-button :disabled="saving || !canEdit || !semanticPairCurrent(pair)" @click="selectPair(pair)">选择这两个问题归类</el-button></article></div>
      <p v-if="chosen.length" class="plan-note">所选：{{ chosen.map(id=>byId.get(id)?.title).filter(Boolean).join('；') }}。批量操作只修改选题信息，保留每条问题的来源、回答和发布记录。</p>
      <template v-if="view==='tree'">
        <el-empty v-if="!groups.length" description="没有符合条件的问题，可以先录入问题或调整筛选。"/>
        <details v-for="group in groups" :key="group.topic" open class="plan-group"><summary><strong>{{ group.topic }}</strong><span>{{ group.question_count }} 个问题 · {{ group.unanswered_count }} 个尚无回答（筛选前）</span></summary>
          <section v-for="intent in group.intents" :key="intent.intent" class="plan-intent"><h3>{{ intents[intent.intent] || intent.intent }}</h3><div v-for="question in intent.questions" :key="question.id" class="plan-question"><el-checkbox v-if="canEdit" :model-value="chosen.includes(question.id)" :disabled="saving" :aria-label="`选择：${question.title}`" @change="checked=>toggle(question.id,checked)"/><button class="plan-title" :disabled="saving" @click="open(question.id)">{{ question.title }}</button><span>{{ question.answer_count ? `${question.answer_count} 个回答 · ${question.reviewed_answer_count} 个已审核` : '尚无回答' }}</span><span>有效审核 {{ question.valid_answer_count ?? '未知' }} · 需更新 {{ question.stale_answer_count ?? '未知' }}</span><span>{{ question.owner || '待分配' }}</span><el-tag v-if="demandPriority(question)" size="small">近 30 天导入需求 · 待回答</el-tag><el-tag size="small" v-if="question.sources.length > 0 && question.sources.every(s=>s.kind==='suggestion')" type="warning">建议问题</el-tag></div></section>
        </details>
      </template>
      <template v-else><p class="plan-note">{{ result.definitions.similarity }} 数字或型号不同的标题不会进入同一候选对；文本相似仍可能代表不同需求。</p><el-empty v-if="!pairs.length" description="当前范围未发现满足阈值的文本重合候选"/><article v-for="pair in pairs" :key="`${pair.left_id}:${pair.right_id}`" class="plan-pair"><div><button :disabled="saving" @click="open(pair.left_id)">{{ pair.left_title }}</button><button :disabled="saving" @click="open(pair.right_id)">{{ pair.right_title }}</button><p>文本重合 {{ pair.overlap_pct }}% · {{ pair.reason }}</p></div><el-button v-if="canEdit" :disabled="saving" @click="selectPair(pair)">选择这两个问题归类</el-button></article></template>
    </template>
  </section>
</template>

<style scoped>
.qa-planning{background:white;border:1px solid #e0e7ed;border-radius:14px;padding:24px;color:#18334a}.qa-planning header{display:flex;justify-content:space-between;gap:16px;align-items:center}.qa-planning h2{font-size:20px;margin:0}.qa-planning header p,.plan-note{font-size:13px;color:#6a7d8d;line-height:1.8}.plan-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:24px 0}.plan-stats>div{display:flex;flex-direction:column;gap:8px;background:#f3f8f9;padding:18px;border-radius:10px}.plan-stats strong{font-size:26px;color:#087f8c}.plan-stats span{font-size:12px;color:#607589}.plan-toolbar,.plan-batch{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:18px 0}.plan-toolbar .el-input{width:280px}.plan-batch{padding:16px;background:#f6f8fb;border-radius:10px}.plan-batch .el-select{width:155px}.plan-batch .el-input{width:230px}.plan-batch strong{font-size:13px}.plan-group{border:1px solid #e0e8ed;border-radius:10px;margin:18px 0;padding:18px}.plan-group summary{cursor:pointer}.plan-group summary span{font-size:12px;color:#6a7d8d;margin-left:15px}.plan-intent{border-left:2px solid #bfdedb;margin-left:8px;padding:0 0 0 16px}.plan-intent h3{font-size:13px;color:#087f8c;margin-top:20px}.plan-question{display:flex;align-items:center;gap:12px;border-top:1px solid #f0f3f6;padding:12px 0}.plan-question>span{font-size:12px;color:#6a7d8d}.plan-title{flex:1;text-align:left}.plan-title,.plan-pair button:not(.el-button){border:0;background:none;color:#245578;cursor:pointer;font-size:14px;line-height:1.6}.plan-pair{display:flex;justify-content:space-between;align-items:center;gap:15px;border:1px solid #e2e9ef;border-radius:9px;padding:18px;margin:14px 0}.plan-pair button:not(.el-button){display:block;text-align:left}.plan-pair p{font-size:12px;color:#6a7d8d}@media(max-width:700px){.qa-planning{padding:16px}.plan-stats{grid-template-columns:repeat(2,1fr)}.plan-question,.plan-pair{align-items:flex-start;flex-wrap:wrap}.plan-title{flex-basis:75%}.plan-group summary span{display:block;margin:8px 0}.plan-group{padding:12px}.plan-intent{margin-left:0;padding-left:10px}}
</style>
