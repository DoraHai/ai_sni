<script setup>
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  deleteGeoDistributionAsset,
  fetchGeoDistributionAssetContent,
  fetchTaskPushTargets,
  getGeoContentTask,
  listGeoDistributionAssets,
  listGeoChannelAccounts,
  listGeoPublishingChannels,
  publishGeoVariant,
  pushGeoVariantWebhook,
  uploadGeoDistributionAsset,
} from '../../api/geoContent'
import { fetchGeoProjects } from '../../api/geoProjects'
import GeoPublicationMonitor from '../../components/GeoPublicationMonitor.vue'
import GeoDeliveryRecovery from '../../components/GeoDeliveryRecovery.vue'
import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
import { useGeoTenant } from '../../composables/useGeoTenant'
import { pushBlockLabels } from '../../utils/geoPushBlockers'

const route = useRoute()
const router = useRouter()
const { tenantId, session } = useGeoTenant()
const loading = ref(false)
const busy = ref('')
const error = ref('')
const channels = ref([])
const accounts = ref([])
const task = ref(null)
const pushTargets = ref([])
const projects = ref([])
const distributionAssets = ref([])
const assetUrls = ref(new Map())
const assetError = ref('')
const assetBusy = ref('')
const assetInput = ref(null)
const webhookAccountId = ref(null)
const webhookUrl = ref('')
const backfillChannel = ref('')
const backfillUrl = ref('')
const backfillNote = ref('')
let pendingAssetSelection = null

const CHANNEL_CN = {
  website: '官网 CMS', docs: '文档', wechat: '微信公众号', zhihu: '知乎',
  xiaohongshu: '小红书图文', baijiahao: '百家号', toutiao: '头条', industry_media: '行业媒体',
}
const taskId = computed(() => Number(route.params.taskId || route.query.task_id || 0) || null)
const focusMode = computed(() => String(route.query.mode || ''))
const redVariant = computed(() => (task.value?.variants || []).find((item) => item.channel === 'xiaohongshu' && !item.stale) || null)
const canManageAssets = computed(() => session.canEdit('geo.assets') && session.canEdit('geo.content'))
const projectId = computed(() => {
  const requested = Number(route.query.project_id || 0)
  if (requested && projects.value.some((item) => Number(item.id) === requested)) return requested
  const businessId = Number(task.value?.business_id || 0)
  return Number(projects.value.find((item) => (item.business_scope?.business_ids || []).map(Number).includes(businessId))?.id || 0) || null
})
function channelLabel(key) { return CHANNEL_CN[key] || key || '—' }
function pushBlockText(row) {
  return pushBlockLabels(row).join(' · ')
}
function openChannelSettings() { router.push('/geo/publishing') }
const variantByChannel = computed(() => new Map((task.value?.variants || []).map((variant) => [variant.channel, variant])))
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
function clearAssetUrls() {
  for (const url of assetUrls.value.values()) URL.revokeObjectURL(url)
  assetUrls.value = new Map()
}
function clearAssetState() {
  clearAssetUrls()
  distributionAssets.value = []
}
function assetNumericId(asset) { return Number(String(asset.id || '').replace('geo-asset-', '')) || 0 }
function nextAssetOrder() {
  const used = new Set(distributionAssets.value.map((item) => Number(item.sort_order)))
  for (let value = 0; value < 20; value += 1) if (!used.has(value)) return value
  return null
}

async function loadAssets(version = contextVersion) {
  clearAssetUrls()
  distributionAssets.value = []
  assetError.value = ''
  if (!canManageAssets.value || !redVariant.value || !projectId.value || !tenantId.value) return
  const targetTenant = tenantId.value
  const targetScope = projectId.value
  const targetVariant = redVariant.value.id
  const loaded = new Map()
  try {
    const result = await listGeoDistributionAssets(targetTenant, targetScope, targetVariant)
    if (!sameContext(version)) return
    distributionAssets.value = result.assets || []
    await Promise.all(distributionAssets.value.map(async (asset) => {
      const id = assetNumericId(asset)
      if (!id) return
      const blob = await fetchGeoDistributionAssetContent(targetTenant, targetScope, targetVariant, id)
      if (sameContext(version)) loaded.set(asset.id, URL.createObjectURL(blob))
    }))
    if (!sameContext(version)) {
      for (const url of loaded.values()) URL.revokeObjectURL(url)
      return
    }
    assetUrls.value = loaded
  } catch (e) {
    for (const url of loaded.values()) URL.revokeObjectURL(url)
    if (sameContext(version)) assetError.value = e.message || '加载小红书配图失败'
  }
}

async function load() {
  const version = contextVersion, request = ++loadVersion
  const current = () => sameContext(version) && request === loadVersion
  channels.value = []; accounts.value = []; task.value = null; pushTargets.value = []; projects.value = []
  clearAssetUrls(); distributionAssets.value = []; assetError.value = ''
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
    const [channelResult, accountResult, taskResult, targets, projectResult] = await Promise.all([
      listGeoPublishingChannels(tenantId.value, false),
      listGeoChannelAccounts(tenantId.value),
      getGeoContentTask(tenantId.value, taskId.value),
      fetchTaskPushTargets(tenantId.value, taskId.value).catch(() => ({ targets: [] })),
      fetchGeoProjects(tenantId.value),
    ])
    if (!current()) return
    channels.value = channelResult.items || []
    accounts.value = accountResult.items || []
    task.value = taskResult
    pushTargets.value = targets.targets || []
    projects.value = projectResult.projects || []
    if (!webhookAccountId.value && webhookAccounts.value.length) webhookAccountId.value = webhookAccounts.value[0].id
    if (!backfillChannel.value && taskResult.variants?.length) backfillChannel.value = taskResult.variants[0].channel
    await loadAssets(version)
  } catch (e) {
    if (current()) error.value = e.message || '加载分发记录失败'
  } finally {
    if (current()) loading.value = false
  }
}

function chooseAsset() {
  if (!canManageAssets.value) return ElMessage.warning('当前账号没有配图编辑权限')
  if (!redVariant.value) return ElMessage.warning('请先在编辑器生成小红书渠道稿')
  if (!projectId.value) return ElMessage.warning('当前任务未绑定可编辑 GEO 项目')
  if (distributionAssets.value.length >= 20) return ElMessage.warning('每个渠道稿最多 20 张图片')
  pendingAssetSelection = {
    version: contextVersion,
    tenant: tenantId.value,
    scope: projectId.value,
    variant: redVariant.value.id,
  }
  assetInput.value?.click()
}

async function uploadAsset(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  const selected = pendingAssetSelection
  pendingAssetSelection = null
  if (!file || !selected || assetBusy.value) return
  if (!sameContext(selected.version)
    || tenantId.value !== selected.tenant
    || projectId.value !== selected.scope
    || redVariant.value?.id !== selected.variant) {
    return ElMessage.warning('客户或项目已切换，请重新选择配图')
  }
  if (!['image/png', 'image/jpeg'].includes(file.type)) return ElMessage.warning('只能上传 PNG 或 JPEG')
  if (file.size > 20_000_000) return ElMessage.warning('单张图片不能超过 20MB')
  const order = nextAssetOrder()
  if (order === null) return ElMessage.warning('每个渠道稿最多 20 张图片')
  const version = selected.version
  assetBusy.value = 'upload'
  try {
    await uploadGeoDistributionAsset(selected.tenant, selected.scope, selected.variant, order, file)
    if (!sameContext(version)) return
    ElMessage.success('配图已保存，旧客户审核已作废，请重新提交客户审核')
    await load()
  } catch (e) {
    if (sameContext(version)) {
      clearAssetState()
      ElMessage.error(e.message || '上传配图失败')
    }
  } finally {
    if (sameContext(version)) assetBusy.value = ''
  }
}

async function deleteAsset(asset) {
  if (assetBusy.value || !redVariant.value || !projectId.value) return
  const selected = {
    version: contextVersion,
    tenant: tenantId.value,
    scope: projectId.value,
    variant: redVariant.value.id,
    assetId: assetNumericId(asset),
  }
  try {
    await ElMessageBox.confirm('删除配图会作废当前客户审核，删除后需重新提交客户审核。', '确认删除配图', { type: 'warning' })
  } catch {
    return
  }
  if (!sameContext(selected.version)
    || tenantId.value !== selected.tenant
    || projectId.value !== selected.scope
    || redVariant.value?.id !== selected.variant) return
  const version = selected.version
  assetBusy.value = asset.id
  try {
    await deleteGeoDistributionAsset(selected.tenant, selected.scope, selected.variant, selected.assetId)
    if (!sameContext(version)) return
    ElMessage.success('配图已删除，旧客户审核已作废')
    await load()
  } catch (e) {
    if (sameContext(version)) {
      clearAssetState()
      ElMessage.error(e.message || '删除配图失败')
    }
  } finally {
    if (sameContext(version)) assetBusy.value = ''
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
  if (!backfillChannel.value || !backfillUrl.value.trim().startsWith('http')) {
    return ElMessage.warning('请选择渠道并填写 http(s) 发布 URL')
  }
  busy.value = 'backfill'
  try {
    await publishGeoVariant(taskId.value, {
      tenant_id: tenantId.value,
      channel: backfillChannel.value,
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

watch([tenantId, taskId, canManageAssets], () => {
  contextVersion++
  pendingAssetSelection = null
  busy.value = ''; error.value = ''
  webhookAccountId.value = null; webhookUrl.value = ''
  backfillChannel.value = ''; backfillUrl.value = ''; backfillNote.value = ''
  load()
}, { flush: 'sync' })
onBeforeUnmount(() => { contextVersion++; loadVersion++; pendingAssetSelection = null; clearAssetUrls() })
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
      <section class="gd-card mb red-assets">
        <div class="gd-hd">
          <div>
            <h3>小红书配图</h3>
            <span class="muted">只使用当前小红书渠道稿的不可变 PNG/JPEG；增删配图后必须重新客户审核。</span>
          </div>
          <div>
            <input ref="assetInput" class="asset-input" type="file" accept="image/png,image/jpeg" @change="uploadAsset" />
            <el-button type="primary" :disabled="!canManageAssets || !redVariant || !projectId || distributionAssets.length >= 20" :loading="assetBusy === 'upload'" @click="chooseAsset">上传配图</el-button>
          </div>
        </div>
        <div class="gd-bd">
          <el-alert v-if="assetError" type="error" :title="assetError" show-icon class="mb" />
          <el-alert v-if="!canManageAssets" type="warning" title="当前账号没有 GEO 配图编辑权限。" show-icon class="mb" />
          <el-alert v-if="task && task.review_status !== 'approved'" type="warning" title="当前稿件未通过客户审核，配图不会进入正式分发清单。" show-icon class="mb" />
          <p v-if="!redVariant" class="muted">当前任务没有最新小红书渠道稿。请返回编辑器，在「选择渠道稿」中勾选小红书后生成。</p>
          <p v-else-if="!projectId" class="muted">当前任务未归属到可编辑的 GEO 项目，无法维护配图。</p>
          <p v-else-if="!distributionAssets.length" class="muted">尚无配图，上传后请返回编辑器走原有客户审核流程。</p>
          <div v-else class="asset-grid">
            <article v-for="asset in distributionAssets" :key="asset.id" class="asset-card">
              <img v-if="assetUrls.get(asset.id)" :src="assetUrls.get(asset.id)" :alt="`配图 ${asset.sort_order + 1}`" />
              <div class="asset-meta"><b>第 {{ asset.sort_order + 1 }} 张</b><span>{{ asset.mediaType }} · {{ Math.ceil(asset.bytes / 1024) }}KB</span></div>
              <el-button type="danger" plain size="small" :disabled="!canManageAssets" :loading="assetBusy === asset.id" @click="deleteAsset(asset)">删除</el-button>
            </article>
          </div>
        </div>
      </section>
      <GeoDeliveryRecovery :tenant-id="tenantId" :task-id="taskId" @resolved="load" />
      <GeoPublicationMonitor :tenant-id="tenantId" :task-id="taskId" :revision="task?.publications?.length || 0" />
      <section class="gd-card" :class="{ focus: focusMode === 'manual' }">
        <div class="gd-hd"><h3>URL 回填</h3></div>
        <div class="actions">
          <el-select v-model="webhookAccountId" placeholder="Webhook 账号">
            <el-option v-for="account in webhookAccounts" :key="account.id" :label="account.display_name" :value="account.id" />
          </el-select>
          <el-input v-model="webhookUrl" placeholder="可选发布 URL" />
          <button class="gd-btn" type="button" :disabled="!webhookAccountId" @click="pushWebhook('draft')">Webhook 草稿</button>
          <button class="gd-btn primary" type="button" :disabled="!webhookAccountId" @click="pushWebhook('publish')">Webhook 发布</button>
          <el-select v-model="backfillChannel" placeholder="回填渠道">
            <el-option v-for="variant in (task?.variants || [])" :key="variant.channel" :label="channelLabel(variant.channel)" :value="variant.channel" />
          </el-select>
          <el-input v-model="backfillUrl" placeholder="https:// 发布链接" />
          <el-input v-model="backfillNote" placeholder="备注" />
          <button class="gd-btn primary" type="button" :loading="busy === 'backfill'" @click="backfill">回填</button>
        </div>
      </section>
    </div>
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
.asset-input { display: none; }
.red-assets .gd-hd { align-items: flex-start; }
.asset-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; }
.asset-card { display: grid; gap: 8px; padding: 10px; border: 1px solid #e2e8f0; border-radius: 10px; background: #fff; }
.asset-card img { width: 100%; height: 150px; object-fit: cover; border-radius: 8px; background: #f8fafc; }
.asset-meta { display: flex; justify-content: space-between; gap: 8px; color: #64748b; font-size: 12px; }
.asset-meta b { color: #334155; }
</style>
