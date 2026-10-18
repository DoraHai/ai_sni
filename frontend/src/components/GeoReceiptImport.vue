<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchGeoProjects } from '../api/geoProjects'
import { importGeoReceipts } from '../api/geoReceipts'

const props = defineProps({ tenantId: Number, task: Object })
const emit = defineEmits(['imported'])
const projects = ref([]), projectId = ref(null), input = ref(null)
const open = ref(false), busy = ref(false), preview = ref(null), error = ref('')
const scope = computed(() => `${props.tenantId}:${props.task?.id}:${props.task?.article?.id}`)
const availableChannels = computed(() => (props.task?.variants || []).map(v =>
  props.task?.channel_profiles?.find(p => p.key === v.channel)?.display_name
  || props.task?.channel_options?.find(p => p.channel_type === v.channel)?.name
  || '其他已生成渠道（请核对原渠道名称）',
).join('、') || '暂无，请先生成渠道稿')
let generation = 0, previewFile = null

function resetPreview() { preview.value = null; previewFile = null; error.value = '' }
watch(projectId, resetPreview, { flush: 'sync' })
watch(scope, async () => {
  const version = ++generation
  resetPreview(); projects.value = []; projectId.value = null; open.value = false; busy.value = false
  if (!props.tenantId || !props.task?.id) return
  try {
    const result = await fetchGeoProjects(props.tenantId)
    if (version !== generation) return
    projects.value = result.projects || []
    const matching = projects.value.filter(p => p.business_scope?.business_ids?.includes(props.task.business_id))
    if (matching.length === 1) projectId.value = matching[0].id
  } catch { if (version === generation) error.value = '项目列表加载失败，请刷新后重试' }
}, { immediate: true, flush: 'sync' })
onBeforeUnmount(() => { generation++; resetPreview() })

async function previewReceipts(event) {
  const file = event.target.files?.[0]; event.target.value = ''
  if (busy.value) return
  resetPreview()
  if (!file) return
  if (!projectId.value) { error.value = '请先选择这篇文章所属的项目'; return }
  if (file.size > 2 * 1024 * 1024 || !/\.(csv|json)$/i.test(file.name)) {
    error.value = '请选择 2 MB 以内的 CSV 或 JSON 回执文件'; return
  }
  const version = ++generation, selectedProject = projectId.value
  busy.value = true
  try {
    const result = await importGeoReceipts({ tenantId: props.tenantId, projectId: selectedProject,
      taskId: props.task.id, file, dryRun: true })
    if (version !== generation || selectedProject !== projectId.value) return
    preview.value = result; previewFile = file
  } catch (e) { if (version === generation) error.value = e.message || '回执预览失败，请检查文件后重试' }
  finally { if (version === generation) busy.value = false }
}

async function confirmReceipts() {
  if (busy.value || !preview.value?.can_confirm || !previewFile || !projectId.value) return
  const version = generation, file = previewFile
  busy.value = true; error.value = ''
  try {
    const result = await importGeoReceipts({ tenantId: props.tenantId, projectId: projectId.value,
      taskId: props.task.id, file, dryRun: false })
    if (version !== generation) return
    preview.value = result
    if (result.committed) {
      resetPreview(); open.value = false
      ElMessage.success(`已回填 ${result.changed} 条发布链接，重复行已跳过`)
      emit('imported')
    }
  } catch (e) { if (version === generation) error.value = e.message || '导入失败，请重新预览' }
  finally { if (version === generation) busy.value = false }
}

function downloadTemplate(format) {
  const fields = ['article_id', 'platform', 'public_url', 'published_at', 'note']
  const example = { article_id: '999999', platform: '官网 / 博客', public_url: 'https://example.com/demo-article',
    published_at: '2026-10-20T09:30:00+08:00', note: '假数据示例，请替换为本文章和渠道的实际信息' }
  const content = format === 'json' ? JSON.stringify([example], null, 2)
    : '\uFEFF' + fields.join(',') + '\r\n' + fields.map(k => `"${example[k].replaceAll('"', '""')}"`).join(',') + '\r\n'
  const url = URL.createObjectURL(new Blob([content], { type: format === 'json' ? 'application/json' : 'text/csv;charset=utf-8' }))
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = `geo-receipts-template.${format}`; anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
</script>

<template>
  <div class="receipt-import">
    <el-button :disabled="!tenantId || !task?.id || busy" @click="open = true">导入回执</el-button>
    <span>把发布后的链接填进回执，一次上传；先看预览，确认后才回填。</span>
    <el-dialog v-model="open" title="导入回执" width="min(900px, 94vw)" :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy">
      <p>支持 UTF-8 的 CSV 和 JSON，最多 200 行、2 MB。只导入当前文章、当前项目的已发布链接；文章须先通过客户审核。</p>
      <el-select v-model="projectId" placeholder="选择文章所属项目" :disabled="busy" aria-label="文章所属项目">
        <el-option v-for="project in projects" :key="project.id" :label="project.name" :value="project.id" />
      </el-select>
      <p>模板里的文章编号请改为 {{ task?.id }}；渠道可填：{{ availableChannels }}。</p>
      <p>发布时间可留空，留空按导入时刻登记；填写时请按模板带上时区。有错误行时整批不写入，重复行会跳过。</p>
      <el-button @click="downloadTemplate('csv')">下载 CSV 模板</el-button>
      <el-button @click="downloadTemplate('json')">下载 JSON 模板</el-button>
      <el-button :disabled="busy || !projectId" @click="input?.click()">上传回执并预览</el-button>
      <input ref="input" type="file" accept=".csv,.json" hidden @change="previewReceipts">
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
      <el-alert v-if="preview" :title="preview.message" :type="preview.can_confirm ? 'info' : 'warning'" :closable="false" />
      <el-table :data="preview?.rows || []" max-height="360" empty-text="上传文件后，这里会显示每行能不能导入及原因">
        <el-table-column prop="row_number" label="行" width="60" />
        <el-table-column prop="platform" label="渠道" width="120" />
        <el-table-column prop="public_url" label="发布链接" min-width="180" />
        <el-table-column prop="status" label="能否导入" width="100" />
        <el-table-column prop="reason" label="原因" min-width="220" />
      </el-table>
      <template #footer>
        <el-button :disabled="busy" @click="open = false">关闭</el-button>
        <el-button type="primary" :loading="busy" :disabled="busy || !preview?.can_confirm" @click="confirmReceipts">确认导入回执</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.receipt-import { padding: 12px 14px; }
.receipt-import > span { margin-left: 10px; color: #64748b; }
.el-alert { margin-top: 12px; }
</style>
