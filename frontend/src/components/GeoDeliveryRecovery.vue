<script setup>
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import { listGeoDeliveries, resolveGeoDelivery } from '../api/geoContent'
const props = defineProps({ tenantId: Number, taskId: Number })
const emit = defineEmits(['resolved'])
const rows = ref([])
const error = ref('')
const message = ref('')
const busy = ref(false)
const showAll = ref(false)
const pendingRows = computed(() => rows.value.filter(row => ['sending', 'unknown', 'failed'].includes(row.state)))
const visibleRows = computed(() => showAll.value ? rows.value : pendingRows.value)
const actionableCount = computed(() => pendingRows.value.filter(row => row.can_confirm_published || row.can_allow_retry).length)
let epoch = 0
const labels = { sending: '发送中', unknown: '结果未确认', failed: '发送失败或已允许重试', succeeded: '已确认成功' }
async function load() {
  const run = ++epoch
  rows.value = []; error.value = ''; message.value = ''; busy.value = false
  if (!props.tenantId || !props.taskId) return
  try {
    const data = await listGeoDeliveries(props.taskId, props.tenantId)
    if (run !== epoch) return
    rows.value = (data.items || []).map(row => ({ ...row, url: '', note: '', confirmed: false }))
    return true
  } catch (e) { if (run === epoch) error.value = e.message || '读取发布记录失败' }
}
async function resolve(row, action) {
  if (busy.value) return
  const run = epoch
  busy.value = true; error.value = ''; message.value = ''
  try {
    await resolveGeoDelivery(props.taskId, row.variant_id, row.delivery_key, {
      tenant_id: props.tenantId, action, note: row.note,
      published_url: row.url || null, confirmed_not_published: row.confirmed,
    })
    if (run !== epoch) return
    if (!await load()) return
    message.value = action === 'allow_retry' ? '已允许重试；需要再次点击发布，系统没有自动发送。' : '已抓取核实并补齐发布记录。'
    emit('resolved')
  } catch (e) { if (run === epoch) error.value = e.message || '核对失败' }
  finally { if (run === epoch) busy.value = false }
}
watch(() => [props.tenantId, props.taskId], load, { immediate: true })
onBeforeUnmount(() => { epoch++ })
</script>

<template>
  <section class="gd-card recovery">
    <div class="gd-hd"><h3>发布结果核对与恢复</h3><el-button :disabled="busy" @click="load">刷新记录</el-button></div>
    <p>发送超时后请先核对渠道后台。核实已发布会抓取链接比对正文；允许重试不会自动发送，也不会计入任务完成。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-alert v-if="message" :title="message" type="success" :closable="false" />
    <p v-if="rows.length">待处理 {{ pendingRows.length }} 条，其中现在可处理 {{ actionableCount }} 条。
      <el-checkbox v-model="showAll">显示已成功记录</el-checkbox>
    </p>
    <p v-if="!visibleRows.length && !error">{{ rows.length ? '暂无待处理记录。' : '暂无发送记录。' }}</p>
    <article v-for="row in visibleRows" :key="row.delivery_key" class="delivery">
      <strong>{{ row.channel }} · 账号 #{{ row.account_id }} · {{ row.mode === 'draft' ? '草稿' : '发布' }} · {{ labels[row.state] || row.state }}</strong>
      <p>最近更新：{{ row.updated_at }}</p>
      <p v-if="row.blocked_reason && row.state !== 'succeeded'" role="status">暂不能处理：{{ row.blocked_reason }}</p>
      <p v-if="row.state === 'sending' && row.available_at">最早核对时间：{{ row.available_at }}；到时请刷新，系统会重新检查状态。</p>
      <template v-if="row.can_confirm_published || row.can_allow_retry">
        <el-input v-model="row.note" :disabled="busy" type="textarea" maxlength="1000" placeholder="核对说明（至少 10 字，请勿填写账号密码）" aria-label="核对说明" />
        <div v-if="row.can_confirm_published" class="recovery-actions">
          <el-input v-model="row.url" :disabled="busy" placeholder="https:// 已发布文章链接" aria-label="已发布文章链接" />
          <el-button :disabled="busy || row.note.trim().length < 10 || !row.url.startsWith('https://')" @click="resolve(row, 'confirm_published')">抓取核实已发布</el-button>
        </div>
        <el-checkbox v-if="row.can_allow_retry" v-model="row.confirmed" :disabled="busy">我已核对渠道后台，确认没有生成对应文章或草稿</el-checkbox>
        <el-button v-if="row.can_allow_retry" :disabled="busy || !row.confirmed || row.note.trim().length < 10" @click="resolve(row, 'allow_retry')">允许重新尝试</el-button>
      </template>
      <p v-for="(event, index) in row.recovery_history || []" :key="index">
        {{ event.at }} · 操作人员 #{{ event.user_id }} · {{ event.action === 'allow_retry' ? '允许重试' : '已抓取核实' }}：{{ event.note }}
      </p>
    </article>
  </section>
</template>

<style scoped>
.recovery { margin-bottom: 14px; padding: 14px; }
.recovery p { color: #64748b; font-size: 13px; overflow-wrap: anywhere; }
.delivery { border-top: 1px solid #e2e8f0; padding: 16px 0; }
.recovery-actions { display: flex; gap: 8px; margin: 10px 0; flex-wrap: wrap; }
.recovery-actions .el-input { flex: 1; min-width: 220px; }
.delivery :deep(.el-checkbox) { height: auto; white-space: normal; margin: 10px 12px 10px 0; }
.delivery :deep(.el-checkbox__label) { white-space: normal; }
</style>
