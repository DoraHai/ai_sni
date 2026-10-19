<script setup>
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  fetchTaskPushTargets,
  getGeoContentTask,
  listGeoChannelAccounts,
  listGeoPublishingChannels,
  publishGeoVariant,
  pushGeoVariantWebhook,
} from '../../api/geoContent'
import GeoPublicationMonitor from '../../components/GeoPublicationMonitor.vue'
import GeoDistributionReport from '../../components/GeoDistributionReport.vue'
import GeoReceiptImport from '../../components/GeoReceiptImport.vue'
import GeoDeliveryRecovery from '../../components/GeoDeliveryRecovery.vue'
import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
import { useGeoTenant } from '../../composables/useGeoTenant'
import { pushBlockLabels } from '../../utils/geoPushBlockers'
import { BACKFILL_CHANNELS, backfillChannelLabel, customChannelError, isHttpsPublicationUrl } from '../../utils/geoBackfillChannels'

const route = useRoute()
const router = useRouter()
const { tenantId } = useGeoTenant()
const loading = ref(false)
const busy = ref('')
const error = ref('')
const channels = ref([])
const accounts = ref([])
const task = ref(null)
const pushTargets = ref([])
const webhookAccountId = ref(null)
const webhookUrl = ref('')
const backfillChannel = ref('')
const customChannelName = ref('')
const backfillSourceVariantId = ref(null)
const backfillUrl = ref('')
const backfillNote = ref('')

const CHANNEL_CN = {
  website: '官网 CMS', docs: '文档', wechat: '微信公众号', zhihu: '知乎',
  baijiahao: '百家号', toutiao: '今日头条', industry_media: '行业媒体',
}
const taskId = computed(() => Number(route.params.taskId || route.query.task_id || 0) || null)
const focusMode = computed(() => String(route.query.mode || ''))
function channelLabel(key) { return CHANNEL_CN[key] || key || '—' }
function pushBlockText(row) {
  return pushBlockLabels(row).join(' · ')
}
function openChannelSettings() { router.push('/geo/publishing') }
const variantByChannel = computed(() => new Map((task.value?.variants || []).map((variant) => [variant.channel, variant])))
const backfillOptions = computed(() => [
  ...BACKFILL_CHANNELS.filter(item => item.value !== 'other'),
  ...(task.value?.variants || []).filter(v => !BACKFILL_CHANNELS.some(item => item.value === v.channel))
    .map(v => ({ value: v.channel, label: channelLabel(v.channel) })),
  BACKFILL_CHANNELS.find(item => item.value === 'other'),
])
const needsBackfillSource = computed(() => backfillChannel.value === 'other' || !variantByChannel.value.has(backfillChannel.value))
const publicationRevision = computed(() => Math.max(0, ...(task.value?.publications || []).map(p => p.id)))
const distributionRows = computed(() => {
  if (pushTargets.value.length) {
    return pushTargets.value.map((target) => {
      const key = target.adapt_key || target.channel_type
      const variant = variantByChannel.value.get(key)
      return {
        key,
        name: target.channel_name || channelLabel(key),
        title: variant?.title || '—',
        status: variant?.status || (target.has_variant ? 'ready' : 'missing'),
        stale: !!variant?.stale,
        ready: !!target.ready,
        accountId: target.account_id || target.default_account_id || null,
        blockReasons: target.block_reasons || [],
        variant,
      }
    })
  }
  return (task.value?.variants || []).map((variant) => ({
    key: variant.channel,
    name: channelLabel(variant.channel),
    title: variant.title || '—',
    status: variant.status || '—',
    stale: !!variant.stale,
    ready: false,
    accountId: null,
    blockReasons: ['无兼容推送账号'],
    variant,
  }))
})
const webhookAccounts = computed(() => accounts.value.filter((account) => {
  const channel = channels.value.find((item) => item.id === account.channel_id)
  return channel?.enabled && ['website', 'docs'].includes(channel.channel_type) && channel.publish_mode === 'auto_publish' && account.auth_type === 'webhook'
}))

let contextVersion = 0
let loadVersion = 0
function sameContext(version) { return version === contextVersion }

async function load() {
  const version = contextVersion, request = ++loadVersion
  const current = () => sameContext(version) && request === loadVersion
  channels.value = []; accounts.value = []; task.value = null; pushTargets.value = []
  loading.value = false
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    return
  }
  if (!taskId.value) {
    error.value = '缺少文章任务'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const [channelResult, accountResult, taskResult, targets] = await Promise.all([
      listGeoPublishingChannels(tenantId.value, false),
      listGeoChannelAccounts(tenantId.value),
      getGeoContentTask(tenantId.value, taskId.value),
      fetchTaskPushTargets(tenantId.value, taskId.value).catch(() => ({ targets: [] })),
    ])
    if (!current()) return
    channels.value = channelResult.items || []
    accounts.value = accountResult.items || []
    task.value = taskResult
    pushTargets.value = targets.targets || []
    if (!webhookAccountId.value && webhookAccounts.value.length) webhookAccountId.value = webhookAccounts.value[0].id
    if (!backfillChannel.value && taskResult.variants?.length) backfillChannel.value = taskResult.variants[0].channel
  } catch (e) {
    if (current()) error.value = e.message || '加载分发记录失败'
  } finally {
    if (current()) loading.value = false
  }
}

async function copyVariant(row) {
  if (loading.value || !task.value) return
  const version = contextVersion
  const text = row.variant?.body_markdown || row.variant?.body_plain || row.variant?.body_html
  if (!text) return ElMessage.warning('尚无渠道稿')
  try {
    await navigator.clipboard.writeText(text)
    if (sameContext(version)) ElMessage.success('已复制')
  } catch (e) {
    if (sameContext(version)) ElMessage.error(e.message || '复制失败')
  }
}

async function pushRow(row, mode) {
  if (busy.value || loading.value || !task.value) return
  const version = contextVersion
  if (!row.ready || !row.accountId) return ElMessage.warning(row.blockReasons.join('；') || '当前渠道不可推送')
  busy.value = `${mode}-${row.key}`
  try {
    await pushGeoVariantWebhook(taskId.value, {
      tenant_id: tenantId.value,
      channel: row.key,
      account_id: row.accountId,
      mode,
      create_publication: true,
    })
    if (!sameContext(version)) return
    ElMessage.success(mode === 'draft' ? '已推送草稿' : '已推送发布')
    await load()
  } catch (e) {
    if (sameContext(version)) ElMessage.error(e.message || '推送失败')
  } finally {
    if (sameContext(version)) busy.value = ''
  }
}

async function pushWebhook(mode) {
  if (busy.value || loading.value || !task.value) return
  const version = contextVersion
  const account = webhookAccounts.value.find((item) => item.id === webhookAccountId.value)
  const channel = channels.value.find((item) => item.id === account?.channel_id)
  if (!account || !channel) return ElMessage.warning('请选择 Webhook 账号')
  busy.value = `webhook-${mode}`
  try {
    await pushGeoVariantWebhook(taskId.value, {
      tenant_id: tenantId.value,
      channel: channel.channel_type,
      account_id: account.id,
      mode,
      published_url: webhookUrl.value.trim() || undefined,
      create_publication: true,
    })
    if (!sameContext(version)) return
    ElMessage.success(mode === 'draft' ? '已推送草稿' : '已推送发布')
    await load()
  } catch (e) {
    if (sameContext(version)) ElMessage.error(e.message || '推送失败')
  } finally {
    if (sameContext(version)) busy.value = ''
  }
}

async function backfill() {
  if (busy.value || loading.value || !task.value) return
  const version = contextVersion
  if (!backfillChannel.value) return ElMessage.warning('请选择回填渠道')
  if (backfillChannel.value === 'other') {
    const message = customChannelError(customChannelName.value)
    if (message) return ElMessage.warning(message)
  }
  if (needsBackfillSource.value && !backfillSourceVariantId.value) return ElMessage.warning('请选择实际发布的稿件')
  if (!isHttpsPublicationUrl(backfillUrl.value.trim())) return ElMessage.warning('请填写完整的 https:// 发布链接')
  busy.value = 'backfill'
  try {
    await publishGeoVariant(taskId.value, {
      tenant_id: tenantId.value,
      channel: backfillChannel.value,
      ...(backfillChannel.value === 'other' ? { custom_channel_name: customChannelName.value.trim() } : {}),
      ...(needsBackfillSource.value ? { source_variant_id: backfillSourceVariantId.value } : {}),
      published_url: backfillUrl.value.trim(),
      note: backfillNote.value || null,
    })
    if (!sameContext(version)) return
    ElMessage.success('已回填发布 URL')
    backfillUrl.value = ''
    await load()
  } catch (e) {
    if (sameContext(version)) ElMessage.error(e.message || '回填失败')
  } finally {
    if (sameContext(version)) busy.value = ''
  }
}

watch([tenantId, taskId], () => {
  contextVersion++
  busy.value = ''; error.value = ''
  webhookAccountId.value = null; webhookUrl.value = ''
  backfillChannel.value = ''; customChannelName.value = ''; backfillSourceVariantId.value = null
  backfillUrl.value = ''; backfillNote.value = ''
  load()
}, { flush: 'sync' })
onBeforeUnmount(() => { contextVersion++; loadVersion++ })
onMounted(load)
</script>

<template>
  <GeoWorkbenchPage title="分发记录" sub="按任务推送渠道稿、回填发布 URL，并查看当前信源状态" :loading="loading">
    <template #actions>
      <button class="gd-btn" type="button" @click="router.push(`/geo/tasks/${taskId}`)">返回编辑器</button>
      <button class="gd-btn" type="button" @click="load">刷新</button>
    </template>
    <div class="geo-dash">
      <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />
      <section class="gd-card mb" :class="{ focus: focusMode === 'auto' }">
        <div class="gd-hd">
          <h3>{{ task?.title || '任务分发' }}</h3>
          <span class="muted">推送草稿、发布或人工回填 URL</span>
        </div>
        <div class="gd-bd" style="padding:0">
          <el-table :data="distributionRows" empty-text="请先在编辑器生成渠道稿" class="full-table">
            <el-table-column label="渠道" prop="name" width="140" />
            <el-table-column label="标题" prop="title" min-width="200" />
            <el-table-column label="状态" min-width="260">
              <template #default="{ row }">
                <span>{{ row.status }}</span>
                <div v-if="!row.ready" class="push-block-reason">
                  <span>暂不能自动推送</span>
                  <el-tag v-for="label in pushBlockLabels(row)" :key="label" size="small" type="warning" effect="plain">{{ label }}</el-tag>
                  <el-button link type="primary" @click="openChannelSettings">去配置渠道</el-button>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="母稿同步" width="110">
              <template #default="{ row }">
                <span :class="row.stale ? 'warn' : 'ok'">{{ row.stale ? '落后母稿' : '已同步' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="280">
              <template #default="{ row }">
                <el-button link @click="copyVariant(row)">复制</el-button>
                <el-tooltip :disabled="row.ready" :content="pushBlockText(row)" placement="top">
                  <span class="push-action">
                    <el-button link type="primary" :disabled="!row.ready" :loading="busy === `draft-${row.key}`" @click="pushRow(row, 'draft')">推送草稿</el-button>
                  </span>
                </el-tooltip>
                <el-tooltip :disabled="row.ready" :content="pushBlockText(row)" placement="top">
                  <span class="push-action">
                    <el-button link type="primary" :disabled="!row.ready" :loading="busy === `publish-${row.key}`" @click="pushRow(row, 'publish')">推送发布</el-button>
                  </span>
                </el-tooltip>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </section>
      <GeoDeliveryRecovery :tenant-id="tenantId" :task-id="taskId" @resolved="load" />
      <GeoPublicationMonitor :tenant-id="tenantId" :task-id="taskId" :revision="publicationRevision" />
      <section class="gd-card" :class="{ focus: focusMode === 'manual' }">
        <div class="gd-hd"><h3>URL 回填</h3></div>
        <GeoReceiptImport v-if="task" :tenant-id="tenantId" :task="task" @imported="load" />
        <div class="actions">
          <el-select v-model="webhookAccountId" placeholder="Webhook 账号">
            <el-option v-for="account in webhookAccounts" :key="account.id" :label="account.display_name" :value="account.id" />
          </el-select>
          <el-input v-model="webhookUrl" placeholder="可选发布 URL" />
          <button class="gd-btn" type="button" :disabled="!webhookAccountId" @click="pushWebhook('draft')">Webhook 草稿</button>
          <button class="gd-btn primary" type="button" :disabled="!webhookAccountId" @click="pushWebhook('publish')">Webhook 发布</button>
          <el-select v-model="backfillChannel" placeholder="回填渠道">
            <el-option v-for="option in backfillOptions" :key="option.value" :label="option.label" :value="option.value" />
          </el-select>
          <el-input v-if="backfillChannel === 'other'" v-model="customChannelName" placeholder="请填写渠道名称（必填，最多30字）" aria-label="自定义渠道名称" maxlength="30" show-word-limit />
          <el-select v-if="backfillChannel && needsBackfillSource" v-model="backfillSourceVariantId" placeholder="请选择实际发布的稿件" aria-label="实际发布的稿件">
            <el-option v-for="variant in (task?.variants || [])" :key="variant.id" :label="`${backfillChannelLabel(variant.channel)}：${variant.title || '未命名稿件'}`" :value="variant.id" />
          </el-select>
          <el-input v-model="backfillUrl" placeholder="https:// 发布链接" />
          <el-input v-model="backfillNote" placeholder="备注" />
          <button class="gd-btn primary" type="button" :loading="busy === 'backfill'" @click="backfill">回填</button>
        </div>
      </section>
    </div>
    <GeoDistributionReport v-if="task" :tenant-id="tenantId" :task="task" mode="task" />
  </GeoWorkbenchPage>
</template>

<style scoped>
.mb { margin-bottom: 14px; }
.muted { color: #94a3b8; font-size: 12px; }
.full-table { width: 100%; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; padding: 12px 14px; }
.actions :deep(.el-select), .actions :deep(.el-input) { width: 180px; }
.ok { color: #059669; }
.warn { color: #d97706; }
.push-block-reason { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; margin-top: 4px; color: #b45309; font-size: 12px; line-height: 1.45; }
.push-block-reason :deep(.el-tag) { --el-tag-font-size: 11px; }
.push-block-reason :deep(.el-button) { margin-left: 4px; padding: 0; vertical-align: baseline; }
.push-action { display: inline-flex; }
.focus { outline: 2px solid #c7d2fe; border-radius: 12px; }
</style>
