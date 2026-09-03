<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { previewSeoRemediation, fetchSeoContentAssets, createSeoContentAsset, updateSeoContentAsset } from '../../api/seo'
import { remediationHandoff, validRemediationEdits, remediationDraftPatch } from './seoRemediationDraft'

const props = defineProps({ visible: Boolean, tenantId: Number, siteId: Number, page: Object })
const emit = defineEmits(['update:visible'])
const router = useRouter()
const loading = ref(false), saving = ref(false), taskLoading = ref(false)
const error = ref(''), result = ref(null), proposal = ref(null), task = ref(null), savedId = ref(null)
let generation = 0, disposed = false
const editableTask = computed(() => task.value && ['planned', 'drafting'].includes(task.value.status))
const scope = () => ({ tenant_id: props.tenantId, site_id: props.siteId, page_id: props.page?.id })
const current = (token, s) => !disposed && token === generation && props.visible
  && s.tenant_id === props.tenantId && s.site_id === props.siteId && s.page_id === props.page?.id

async function loadTask() {
  const token = generation, s = scope()
  taskLoading.value = true
  try {
    const response = await fetchSeoContentAssets({ tenantId: s.tenant_id, siteId: s.site_id, sourcePageId: s.page_id, pageSize: 1 })
    if (current(token, s)) task.value = response.items?.[0] || null
  } catch (e) { if (current(token, s)) error.value = e.message || '关联任务读取失败，请关闭后重试' }
  finally { if (current(token, s)) taskLoading.value = false }
}

async function generate() {
  if (loading.value || saving.value || !props.visible || !props.page?.id || taskLoading.value || error.value) return
  const token = generation, s = scope()
  loading.value = true
  try {
    const response = await previewSeoRemediation(s)
    if (!current(token, s)) return
    result.value = response
    proposal.value = JSON.parse(JSON.stringify(response.proposal))
    ElMessage.success('AI 整改草稿已生成，尚未保存；请逐项核实')
  } catch (e) { if (current(token, s)) ElMessage.error(e.message || '生成失败，原记录未修改') }
  finally { if (current(token, s)) loading.value = false }
}

async function save() {
  if (saving.value || loading.value || taskLoading.value || error.value || savedId.value || !result.value) return
  if (!validRemediationEdits(proposal.value)) return ElMessage.warning('请补齐 Title、Description、H1 与正文结构建议，并检查长度')
  if (task.value && !editableTask.value) return ElMessage.warning('关联任务不在草稿阶段，不能修改；可复制交接单供人工处理')
  const token = generation, s = scope()
  const handoff = remediationHandoff(result.value, proposal.value)
  saving.value = true
  try {
    let response
    if (task.value) {
      response = await updateSeoContentAsset({ contentId: task.value.id, tenantId: s.tenant_id,
        payload: remediationDraftPatch(task.value, handoff) })
    } else {
      response = await createSeoContentAsset({ tenant_id: s.tenant_id, site_id: s.site_id, source_page_id: s.page_id,
        status: 'drafting', title: `【整改草稿，勿发布】${proposal.value.title.text}`, content_type: 'guide', draft: handoff })
    }
    if (!current(token, s)) return
    savedId.value = response.id
    ElMessage.success('整改交接单已保存到内容草稿，未提交审核、未发布')
  } catch (e) { if (current(token, s)) ElMessage.error(e.message || '保存失败，请核对关联任务后重试') }
  finally { if (current(token, s)) saving.value = false }
}

async function copy() {
  if (!result.value || !validRemediationEdits(proposal.value)) return
  try { await navigator.clipboard.writeText(remediationHandoff(result.value, proposal.value)); ElMessage.success('交接单已复制，未修改任何记录') }
  catch { ElMessage.error('复制失败，请手动复制交接单内容') }
}
function openTask() {
  const id = savedId.value || task.value?.id
  if (id) router.push({ path: '/seo/content/editor', query: { site_id: props.siteId, id, source_page_id: props.page.id } })
}
watch([() => props.visible, () => props.tenantId, () => props.siteId, () => props.page?.id], () => {
  ++generation
  result.value = null; proposal.value = null; task.value = null; savedId.value = null; error.value = ''
  loading.value = false; saving.value = false; taskLoading.value = false
  if (props.visible && props.tenantId && props.siteId && props.page?.id) loadTask()
}, { immediate: true, flush: 'sync' })
onBeforeUnmount(() => { disposed = true; ++generation })
</script>

<template>
  <el-dialog :model-value="visible" title="AI 辅助整改（单页草稿）" width="min(980px, 96vw)"
    :close-on-click-modal="!loading && !saving" :close-on-press-escape="!loading && !saving" :show-close="!loading && !saving"
    @update:model-value="emit('update:visible', $event)">
    <p class="url">页面 #{{ page?.id }} · {{ page?.url }}</p>
    <el-alert title="点击生成才读取本页公开正文并发送给已配置 AI。程序检测负责事实，AI 只给整改草稿，必须人工核实；不改官网、索引设置或当前 TDK。每天每客户最多 20 次。" type="info" :closable="false" />
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <p v-if="taskLoading">读取已有内容任务…</p>
    <p v-else-if="task">已关联任务 #{{ task.id }} · {{ task.title }}。{{ editableTask ? '保存时追加交接单，保留原有正文；不会覆盖原建议。' : '任务已进入后续流程，不自动改动，可复制交接单。' }}</p>
    <p v-else>保存时创建关联此页的内容草稿；后续使用原有人工审核流程。</p>
    <el-button :loading="loading" :disabled="saving || taskLoading || !!error || !!result" @click="generate">读取公开正文并生成（1 次 AI）</el-button>
    <template v-if="result && proposal">
      <p>{{ result.note }}</p>
      <p>正文读取时间：{{ result.evidence.fetched_at }}。静态 HTML 提取，不执行网页脚本或样式渲染。{{ result.evidence.truncated ? '仅取正文前 12000 字，不是全页审查。' : '' }}</p>
      <div class="comparison" v-for="(label, key) in { title: 'Title', description: 'Description', h1: 'H1' }" :key="key">
        <h3>{{ label }}</h3><p>当前原文（程序读取）：{{ result.evidence.current[key] || '空' }}</p>
        <label>AI 建议（可人工编辑）<textarea v-model="proposal[key].text" :aria-label="`AI 建议 ${label}`" :maxlength="key === 'description' ? 500 : 180" :disabled="!!savedId || saving" rows="3" /></label>
        <p>AI 理由：{{ proposal[key].reason }} · 引用：{{ proposal[key].evidence_ids.join('、') }}</p>
      </div>
      <h3>正文结构建议（不是已存在内容）</h3>
      <div v-for="(item, index) in proposal.outline" :key="index" class="comparison">
        <textarea v-model="item.text" :aria-label="`正文结构 ${index + 1}`" maxlength="1500" :disabled="!!savedId || saving" rows="3" />
        <p>AI 理由：{{ item.reason }} · 引用：{{ item.evidence_ids.join('、') }}</p>
      </div>
      <details><summary>展开程序提取的原始证据，核对 AI 引用</summary><p v-for="item in result.evidence.evidence" :key="item.id">[{{ item.id }}] {{ item.text || '空' }}</p></details>
    </template>
    <template #footer>
      <el-button :disabled="loading || saving" @click="emit('update:visible', false)">关闭</el-button>
      <el-button v-if="result" :disabled="saving" @click="copy">复制整改交接单</el-button>
      <el-button v-if="task || savedId" @click="openTask" :disabled="loading || saving">查看关联内容任务</el-button>
      <el-button v-if="result" type="primary" :loading="saving" :disabled="loading || !!savedId || (!!task && !editableTask) || !!error" @click="save">{{ savedId ? `已保存到任务 #${savedId}` : task ? '追加到已有草稿' : '保存为关联内容草稿' }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.url{overflow-wrap:anywhere}p{font-size:13px;line-height:1.7;white-space:pre-wrap;overflow-wrap:anywhere}.comparison{padding:12px 0;border-bottom:1px solid #e3e8ef}h3{font-size:15px}textarea{display:block;box-sizing:border-box;width:100%;margin-top:8px;padding:10px;border:1px solid #b8c4d6;border-radius:6px;font:inherit;resize:vertical}details{margin:15px 0}summary{cursor:pointer}
</style>
