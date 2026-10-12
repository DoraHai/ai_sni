<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchGeoProjects } from '../api/geoProjects'
import { previewGeoManualFinalization, finalizeGeoManualChannel, formatGeoError } from '../api/geoContent'
import { canSubmitGeoReview } from '../utils/geoReviewAccess'
import { session } from '../store/session'

const props = defineProps({ tenantId: [Number, String], task: Object, channel: String, changed: Boolean })
const emit = defineEmits(['updated'])
const open = ref(false), busy = ref(false), projects = ref([]), scope = ref(null), context = ref(null), error = ref('')
const fields = [
  ['confirm_title_body', '已核对保存版本的标题和完整正文'],
  ['confirm_layout', '已核对排版、表格和内嵌配图'],
  ['confirm_facts', '已核对事实来源、引用及跨语言对应'],
  ['confirm_brand_author', '已核对品牌表达与作者署名'],
  ['confirm_platform', '已核对公众号平台要求'],
]
const confirmations = reactive(Object.fromEntries(fields.map(([key]) => [key, false])))
const canOpen = computed(() => props.channel === 'wechat' && canSubmitGeoReview(session.user))
const confirmed = computed(() => fields.every(([key]) => confirmations[key] === true))
let epoch = 0, requestId = ''
watch(() => [props.tenantId, props.task?.id, props.channel], () => { epoch++; open.value = false; context.value = null; busy.value = false })
onBeforeUnmount(() => { epoch++ })

async function inspect() {
  const run = ++epoch, tenant = props.tenantId, id = props.task?.id, channel = props.channel
  context.value = null; error.value = ''; busy.value = true
  for (const [key] of fields) confirmations[key] = false
  try {
    const value = await previewGeoManualFinalization(tenant, id, channel, scope.value)
    if (run !== epoch) return
    const saved = (props.task?.variants || []).find(v => v.channel === channel)
    if (props.changed || value.export_revision !== saved?.export_revision) throw new Error('保存版本已变化，请关闭窗口，刷新并重新核对')
    context.value = value; requestId = crypto.randomUUID()
  } catch (e) { if (run === epoch) error.value = formatGeoError(e, '人工定版检查失败') }
  finally { if (run === epoch) busy.value = false }
}
async function show() {
  if (props.changed) { ElMessage.warning('请先保存当前母稿和渠道稿，再核对定版'); return }
  const run = ++epoch
  open.value = true; busy.value = true; error.value = ''; context.value = null; scope.value = null
  try {
    const value = await fetchGeoProjects(props.tenantId)
    if (run !== epoch) return
    projects.value = (Array.isArray(value) ? value : value.items || value.projects || []).filter(p => p.status === 'active')
    if (projects.value.length === 1) { scope.value = projects.value[0].id; await inspect() }
    else if (!projects.value.length) error.value = '请先配置当前客户的项目和顾问，再进行人工定版'
  } catch (e) { if (run === epoch) error.value = formatGeoError(e, '项目读取失败') }
  finally { if (run === epoch) busy.value = false }
}
async function submit() {
  if (!context.value?.quality_passed || !confirmed.value || props.changed || busy.value) return
  const run = ++epoch, tenant = props.tenantId, id = props.task.id, channel = props.channel
  busy.value = true; error.value = ''
  try {
    const value = await finalizeGeoManualChannel(tenant, id, channel, {
      scope_id: Number(scope.value), expected_variant_id: context.value.variant_id,
      expected_article_id: context.value.article_id, expected_revision: context.value.revision,
      request_id: requestId, ...confirmations,
    })
    if (run !== epoch) return
    if (props.changed) {
      open.value = false
      ElMessage.warning('保存版本已定版；当前本地未保存修改已保留，请保存并重新核对定版')
      return
    }
    open.value = false; emit('updated', value)
    ElMessage.success('人工定版已保存，原预览稿已保留；当前版本需要客户重新审核')
  } catch (e) { if (run === epoch) error.value = formatGeoError(e, '人工定版失败，请刷新后重新核对') }
  finally { if (run === epoch) busy.value = false }
}
</script>

<template>
  <el-button v-if="canOpen" size="small" :disabled="busy || changed" @click="show">人工核对并定版</el-button>
  <el-dialog v-model="open" title="公众号人工定版" width="620px" append-to-body :close-on-click-modal="false">
    <p>保留原预览稿，生成新的人工渠道版本，并重新提交客户审核。此操作不会发布文章。</p>
    <el-select v-model="scope" placeholder="选择当前稿件所属项目" :disabled="busy" @change="inspect">
      <el-option v-for="project in projects" :key="project.id" :value="project.id" :label="project.name" />
    </el-select>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-alert v-if="context && !context.quality_passed" title="真实内容检查尚未通过，请先处理问题再定版" type="warning" :closable="false" />
    <el-alert v-if="context?.requires_master_rebase" title="母稿已有新版本；定版将明确关联当前母稿并要求客户重审，请核对两者一致" type="warning" :closable="false" />
    <ul v-if="context?.issues?.length"><li v-for="issue in context.issues" :key="issue">{{ issue }}</li></ul>
    <div v-if="context?.quality_passed" style="display:flex;flex-direction:column;margin-top:16px">
      <el-checkbox v-for="[key,label] in fields" :key="key" v-model="confirmations[key]" :disabled="busy">{{ label }}</el-checkbox>
    </div>
    <template #footer>
      <el-button :disabled="busy" @click="open=false">取消</el-button>
      <el-button type="primary" :loading="busy" :disabled="!confirmed || !context?.quality_passed || changed" @click="submit">确认人工定版并提交客户重审</el-button>
    </template>
  </el-dialog>
</template>
