<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { createSeoPageCapture, fetchSeoPageCapture, fetchSeoPageCaptureImage, fetchSeoPageCaptures, uploadSeoPageCapture } from '../../api/seo'
import { pageCaptureError, pageCaptureStatus, pageCaptureTarget, pageCaptureUploadCheck, pageCaptureWarningCount, shouldPollPageCapture, suggestManualPageCapture } from './seoPageCapture'

const props = defineProps({ tenantId: Number, siteId: Number, canEdit: Boolean,
  relationType: { type: String, default: 'site_page' }, page: { type: Object, required: true } })
const capture = ref(null)
const imageUrl = ref('')
const error = ref('')
const loading = ref(false)
const uploading = ref(false)
const fileInput = ref(null)
let timer
let generation = 0
let attempts = 0
let startedAt = 0

const inProgress = computed(() => loading.value || ['pending', 'running'].includes(capture.value?.status))
const warningCount = computed(() => pageCaptureWarningCount(capture.value?.warnings))
const recommendUpload = computed(() => props.relationType === 'publication' && capture.value?.status === 'failed' && suggestManualPageCapture(capture.value?.error_code))
function clearImage() {
  if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
  imageUrl.value = ''
}
function stop() { ++generation; clearTimeout(timer); timer = undefined; clearImage() }
function message(e) { return e?.code ? pageCaptureError(e.code) : (e?.message || '请求失败') }

async function showCapture(row, token) {
  if (token !== generation) return
  capture.value = row
  clearImage()
  if (row.status === 'succeeded') {
    try {
      const blob = await fetchSeoPageCaptureImage({ captureId: row.id, tenantId: props.tenantId })
      if (token === generation) imageUrl.value = URL.createObjectURL(blob)
    } catch (e) { if (token === generation) error.value = `图片加载失败：${message(e)}` }
  }
}

async function poll(captureId, token) {
  if (token !== generation) return
  try {
    const row = await fetchSeoPageCapture({ captureId, tenantId: props.tenantId })
    if (token !== generation) return
    await showCapture(row, token)
    if (token !== generation) return
    if (shouldPollPageCapture(row.status, attempts, Date.now() - startedAt)) {
      ++attempts
      timer = setTimeout(() => poll(captureId, token), 2000)
    } else if (['pending', 'running'].includes(row.status)) {
      capture.value = { ...row, status: 'failed', error_code: 'timeout' }
    }
  } catch (e) {
    if (token === generation) { error.value = message(e); capture.value = { ...capture.value, status: 'failed' } }
  }
}

async function loadLatest() {
  stop(); capture.value = null; error.value = ''; loading.value = true
  const token = generation
  try {
    const response = await fetchSeoPageCaptures({
      tenantId: props.tenantId, siteId: props.siteId,
      relationType: props.relationType, relationId: props.page.id,
    })
    if (token !== generation) return
    const row = response.items?.[0]
    if (!row) return
    startedAt = Date.now(); attempts = 0
    if (['pending', 'running'].includes(row.status)) await poll(row.id, token)
    else await showCapture(row, token)
  } catch (e) { if (token === generation) error.value = message(e) }
  finally { if (token === generation) loading.value = false }
}

async function createCapture() {
  stop(); error.value = ''; loading.value = true
  const token = generation
  try {
    const created = await createSeoPageCapture(pageCaptureTarget({ tenantId: props.tenantId, siteId: props.siteId, page: props.page, relationType: props.relationType }))
    if (token !== generation) return
    capture.value = { id: created.id, status: created.status }
    startedAt = Date.now(); attempts = 0
    await poll(created.id, token)
  } catch (e) { if (token === generation) error.value = message(e) }
  finally { if (token === generation) loading.value = false }
}

async function uploadFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  const validation = pageCaptureUploadCheck(file)
  if (validation) { error.value = pageCaptureError(validation); return }
  error.value = ''; uploading.value = true
  const token = generation
  try {
    const row = await uploadSeoPageCapture({ tenantId: props.tenantId, siteId: props.siteId, relationId: props.page.id, file })
    if (token === generation) { stop(); await showCapture(row, generation) }
  } catch (e) { if (token === generation) error.value = message(e) }
  finally { uploading.value = false }
}

watch(() => [props.tenantId, props.siteId, props.relationType, props.page.id], loadLatest, { immediate: true })
onBeforeUnmount(stop)
</script>

<template>
  <section class="capture-panel">
    <div class="capture-heading"><h4>页面截图</h4><div class="capture-actions"><el-button v-if="canEdit" type="primary" :disabled="inProgress || uploading || !tenantId || !siteId" @click="createCapture">{{ inProgress ? '截图中…' : '截图' }}</el-button><el-button v-if="canEdit && relationType === 'publication'" :type="recommendUpload ? 'warning' : 'primary'" :disabled="uploading || !tenantId || !siteId" @click="fileInput?.click()">{{ uploading ? '上传中…' : '上传截图' }}</el-button><input ref="fileInput" type="file" accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp" hidden @change="uploadFile" /></div></div>
    <p v-if="error" class="capture-error">{{ error }}</p>
    <template v-if="capture">
      <p>状态：{{ pageCaptureStatus(capture.status) }}<span v-if="capture.status === 'failed'"> · {{ pageCaptureError(capture.error_code) }}</span></p>
      <p v-if="recommendUpload" class="capture-hint">该平台需要登录或人机验证，建议手动截图后上传</p>
      <template v-if="capture.status === 'succeeded'">
        <p>{{ capture.source === 'manual' ? '人工上传' : '自动截图' }}</p>
        <a v-if="imageUrl" :href="imageUrl" target="_blank" rel="noopener noreferrer" title="查看原图"><img :src="imageUrl" alt="页面截图缩略图" class="capture-thumbnail" /></a>
        <p>截取时间：{{ capture.captured_at ? new Date(capture.captured_at).toLocaleString('zh-CN', { hour12: false }) : '—' }}</p>
        <p>最终 URL：{{ capture.final_url || '—' }}</p>
        <p>HTTP 状态：{{ capture.http_status ?? '—' }}</p>
        <p v-if="warningCount">部分资源未加载：{{ warningCount }} 个</p>
      </template>
    </template>
    <p v-else-if="!loading && !error">暂无截图记录</p>
  </section>
</template>

<style scoped>
.capture-panel{border:1px solid #e3e9f0;border-radius:10px;padding:16px;margin:18px 0;overflow-wrap:anywhere}
.capture-heading{display:flex;justify-content:space-between;align-items:center;gap:12px}
.capture-heading h4{margin:0}
.capture-actions{display:flex;align-items:center;gap:8px}
.capture-error{color:#c45656}
.capture-hint{color:#b76b15;font-weight:600}
.capture-thumbnail{display:block;max-width:100%;width:320px;height:auto;border:1px solid #e3e9f0;border-radius:6px}
</style>
