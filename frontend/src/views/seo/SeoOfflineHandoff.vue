<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { exportSeoOfflineOrders, importSeoOfflineReceipts } from '../../api/seo'
import { offlinePlatforms } from './seoOfflinePlatforms.js'

const props = defineProps({ tenantId: Number, siteId: Number, identity: String, contents: Array })
const emit = defineEmits(['imported'])
const scope = computed(() => `${props.tenantId}:${props.siteId}:${props.identity}`)
const orderDialog = ref(false), receiptDialog = ref(false), busy = ref(false), input = ref(null)
const selected = ref([]), candidates = ref([]), preview = ref(null)
const form = reactive({ platform: offlinePlatforms[0], account: '', scheduled_at: '' })
let previewFile = null, previewScope = '', generation = 0

function openOrders() {
  if (!props.tenantId || !props.siteId) return ElMessage.warning('请先选择客户和网站')
  candidates.value = (props.contents || []).filter(c => ['ready', 'published'].includes(c.status))
    .map(c => ({ article_id: String(c.id), title: c.title, source_version: c.version_count, payload_hash: c.payload_hash }))
  selected.value = []
  orderDialog.value = true
}
async function exportOrders() {
  if (busy.value || !selected.value.length || !form.account.trim()) return
  const requested = scope.value
  busy.value = true
  try {
    const blob = await exportSeoOfflineOrders({ tenant_id: props.tenantId, site_id: props.siteId,
      articles: selected.value.map(id => {
        const { article_id, source_version, payload_hash } = candidates.value.find(c => c.article_id === id)
        return { article_id, source_version, payload_hash }
      }), target_platform: form.platform, target_account: form.account.trim(), scheduled_at: form.scheduled_at || null })
    if (requested !== scope.value) return
    const url = URL.createObjectURL(blob), anchor = document.createElement('a')
    anchor.href = url; anchor.download = 'seo-offline-orders.zip'; anchor.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    orderDialog.value = false
    ElMessage.success('发布单与回执模板已下载，请在多号通人工发布')
  } catch (e) { if (requested === scope.value) ElMessage.error(e.message) }
  finally { busy.value = false }
}
async function previewReceipts(event) {
  const file = event.target.files?.[0]; event.target.value = ''
  if (!file || busy.value) return
  if (!props.tenantId || !props.siteId) return ElMessage.warning('请先选择客户和网站')
  if (file.size > 2 * 1024 * 1024 || !/\.(json|csv)$/i.test(file.name)) return ElMessage.warning('请选择2MiB以内的JSON或CSV回执')
  const requested = scope.value, sequence = ++generation
  preview.value = null; previewFile = null; busy.value = true
  try {
    const result = await importSeoOfflineReceipts({ tenantId: props.tenantId, siteId: props.siteId, file, dryRun: true })
    if (requested !== scope.value || sequence !== generation) return
    preview.value = result; previewFile = file; previewScope = requested; receiptDialog.value = true
  } catch (e) { if (requested === scope.value && sequence === generation) ElMessage.error(e.message) }
  finally { busy.value = false }
}
async function commitReceipts() {
  if (busy.value || !previewFile || !preview.value || previewScope !== scope.value) return
  const requested = scope.value, file = previewFile
  busy.value = true
  try {
    const result = await importSeoOfflineReceipts({ tenantId: props.tenantId, siteId: props.siteId, file, dryRun: false })
    if (requested !== scope.value) return
    if (result.committed) {
      receiptDialog.value = false; previewFile = null; preview.value = null
      ElMessage.success(`已导入人工回执，变更 ${result.changed} 条`); emit('imported')
    }
  } catch (e) { if (requested === scope.value) ElMessage.error(e.message) }
  finally { busy.value = false }
}
watch(scope, () => {
  generation++; previewFile = null; preview.value = null; previewScope = ''
  orderDialog.value = false; receiptDialog.value = false; selected.value = []; candidates.value = []
  form.account = ''; form.scheduled_at = ''
})
</script>

<template>
  <el-button :disabled="busy || !tenantId || !siteId" @click="openOrders">导出发布单</el-button>
  <el-button :disabled="busy || !tenantId || !siteId" @click="input?.click()">导入回执</el-button>
  <input ref="input" type="file" accept=".json,.csv" hidden @change="previewReceipts">
  <el-dialog v-model="orderDialog" title="多号通离线发布单" width="min(620px, calc(100vw - 32px))">
    <p>从当前已加载的审核通过稿件中选择，最多20篇。多号通单独安装，人工发布后填写回执模板。</p>
    <el-form label-position="top">
      <el-form-item label="稿件" required><el-select v-model="selected" multiple :multiple-limit="20" filterable><el-option v-for="c in candidates" :key="c.article_id" :label="c.title" :value="c.article_id" /></el-select></el-form-item>
      <el-form-item label="目标平台" required><el-select v-model="form.platform"><el-option v-for="p in offlinePlatforms" :key="p" :label="p" :value="p" /></el-select></el-form-item>
      <el-form-item label="目标账号备注（请勿填写凭据）" required><el-input v-model="form.account" maxlength="120" /></el-form-item>
      <el-form-item label="人工排期（可空，带时区）"><el-input v-model="form.scheduled_at" placeholder="2026-10-20T09:30:00+08:00" /></el-form-item>
    </el-form>
    <template #footer><el-button :loading="busy" :disabled="!selected.length || !form.account.trim()" @click="exportOrders">下载JSON+CSV</el-button></template>
  </el-dialog>
  <el-dialog v-model="receiptDialog" title="人工回执预检" width="760px">
    <p>整批预检通过后再确认导入；published 仅表示人工报告，failed/unknown 不计为成功。</p>
    <el-table :data="preview?.rows || []" max-height="400">
      <el-table-column prop="article_id" label="稿件ID" /><el-table-column prop="platform" label="平台" />
      <el-table-column prop="account" label="账号" /><el-table-column prop="status" label="人工状态" />
      <el-table-column prop="unchanged" label="已登记相同回执" />
    </el-table>
    <template #footer><el-button :loading="busy" :disabled="!preview" @click="commitReceipts">确认导入回执</el-button></template>
  </el-dialog>
</template>
