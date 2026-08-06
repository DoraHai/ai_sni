<script setup>
/**
 * 发布渠道管理
 * 上：渠道目录（类型开关）— 渠道 ID
 * 下：渠道账号（按渠道页签）— 账号 ID；支持新增/改名/换 Webhook/禁用删除
 */
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createGeoChannelAccount,
  createGeoPublishingChannel,
  deleteGeoChannelAccount,
  listGeoChannelAccounts,
  listGeoPublishingChannels,
  patchGeoChannelAccount,
  patchGeoPublishingChannel,
} from '../../api/geoContent'
import { useGeoTenant } from '../../composables/useGeoTenant'

const { tenantId } = useGeoTenant()
const loading = ref(false)
const error = ref('')
const channels = ref([])
const accounts = ref([])
const activeTab = ref('all')

const createChOpen = ref(false)
const createAccOpen = ref(false)
const editAccOpen = ref(false)

const chForm = ref({
  channel_type: 'website',
  name: '',
  enabled: true,
})

const CHANNEL_TYPES = [
  { value: 'website', label: 'website · 官网' },
  { value: 'docs', label: 'docs · 文档' },
  { value: 'wechat', label: 'wechat · 公众号' },
  { value: 'zhihu', label: 'zhihu · 知乎' },
  { value: 'baijiahao', label: 'baijiahao · 百家号' },
  { value: 'toutiao', label: 'toutiao · 头条' },
  { value: 'industry_media', label: 'industry_media · 行业媒体' },
]

const accForm = ref({
  channel_id: null,
  display_name: '',
  auth_type: 'webhook',
  webhook_url: '',
})

const editForm = ref({
  id: null,
  display_name: '',
  auth_type: 'webhook',
  webhook_url: '',
  clear_credentials: false,
  status: 'active',
})

const channelTabs = computed(() => {
  const list = (channels.value || []).map((c) => ({
    key: String(c.id),
    id: c.id,
    label: c.name || c.channel_type,
    type: c.channel_type,
    enabled: c.enabled,
    count: (accounts.value || []).filter((a) => a.channel_id === c.id && a.status !== 'disabled')
      .length,
  }))
  return [{ key: 'all', id: null, label: '全部', type: '', enabled: true, count: accounts.value.length }, ...list]
})

const filteredAccounts = computed(() => {
  let rows = accounts.value || []
  if (activeTab.value !== 'all') {
    const cid = Number(activeTab.value)
    rows = rows.filter((a) => a.channel_id === cid)
  }
  return rows
})

const webhookCapable = (channelId) => {
  const c = channels.value.find((x) => x.id === channelId)
  const t = (c?.channel_type || '').toLowerCase()
  return t === 'website' || t === 'docs'
}

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    channels.value = []
    accounts.value = []
    return
  }
  loading.value = true
  error.value = ''
  try {
    const [ch, acc] = await Promise.all([
      listGeoPublishingChannels(tenantId.value, false),
      listGeoChannelAccounts(tenantId.value),
    ])
    channels.value = ch.items || []
    accounts.value = acc.items || []
    if (!accForm.value.channel_id && channels.value.length) {
      accForm.value.channel_id = channels.value[0].id
    }
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function createChannel() {
  try {
    await createGeoPublishingChannel({
      tenant_id: tenantId.value,
      channel_type: chForm.value.channel_type,
      name: chForm.value.name.trim() || chForm.value.channel_type,
      enabled: chForm.value.enabled,
    })
    ElMessage.success('已创建渠道')
    createChOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(e.message || '创建失败')
  }
}

async function toggleChannel(row) {
  try {
    await patchGeoPublishingChannel(tenantId.value, row.id, { enabled: !row.enabled })
    ElMessage.success(row.enabled ? '已禁用渠道' : '已启用渠道')
    await load()
  } catch (e) {
    ElMessage.error(e.message || '更新失败')
  }
}

function openCreateAccount(prefillChannelId) {
  const cid =
    prefillChannelId ||
    (activeTab.value !== 'all' ? Number(activeTab.value) : null) ||
    channels.value[0]?.id ||
    null
  accForm.value = {
    channel_id: cid,
    display_name: '',
    auth_type: webhookCapable(cid) ? 'webhook' : 'manual',
    webhook_url: '',
  }
  createAccOpen.value = true
}

function onAccChannelChange(cid) {
  if (webhookCapable(cid)) {
    if (accForm.value.auth_type === 'manual') accForm.value.auth_type = 'webhook'
  } else {
    accForm.value.auth_type = 'manual'
    accForm.value.webhook_url = ''
  }
}

async function createAccount() {
  if (!accForm.value.channel_id || !accForm.value.display_name.trim()) {
    ElMessage.warning('请选择渠道并填写显示名')
    return
  }
  const isWh = accForm.value.auth_type === 'webhook'
  if (isWh && !accForm.value.webhook_url.trim().startsWith('https://')) {
    ElMessage.warning('Webhook 需公网 HTTPS URL（不能用 127.0.0.1）')
    return
  }
  try {
    const body = {
      tenant_id: tenantId.value,
      channel_id: accForm.value.channel_id,
      display_name: accForm.value.display_name.trim(),
      auth_type: accForm.value.auth_type,
      credentials: null,
    }
    if (isWh) {
      body.credentials = {
        webhook_url: accForm.value.webhook_url.trim(),
        method: 'POST',
      }
    }
    await createGeoChannelAccount(body)
    ElMessage.success('已创建渠道账号')
    createAccOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(e.message || '创建失败')
  }
}

function openEditAccount(row) {
  editForm.value = {
    id: row.id,
    display_name: row.display_name || '',
    auth_type: row.auth_type || 'manual',
    webhook_url: '',
    clear_credentials: false,
    status: row.status || 'active',
  }
  editAccOpen.value = true
}

async function saveEditAccount() {
  if (!editForm.value.display_name.trim()) {
    ElMessage.warning('显示名不能为空')
    return
  }
  try {
    const body = {
      display_name: editForm.value.display_name.trim(),
      auth_type: editForm.value.auth_type,
      status: editForm.value.status,
    }
    if (editForm.value.clear_credentials) {
      body.clear_credentials = true
    } else if (
      editForm.value.auth_type === 'webhook' &&
      editForm.value.webhook_url.trim()
    ) {
      if (!editForm.value.webhook_url.trim().startsWith('https://')) {
        ElMessage.warning('Webhook 需公网 HTTPS URL')
        return
      }
      body.credentials = {
        webhook_url: editForm.value.webhook_url.trim(),
        method: 'POST',
      }
    }
    await patchGeoChannelAccount(tenantId.value, editForm.value.id, body)
    ElMessage.success('账号已更新')
    editAccOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(e.message || '更新失败')
  }
}

async function disableAccount(row) {
  try {
    await patchGeoChannelAccount(tenantId.value, row.id, { status: 'disabled' })
    ElMessage.success('账号已禁用')
    await load()
  } catch (e) {
    ElMessage.error(e.message || '禁用失败')
  }
}

async function enableAccount(row) {
  try {
    await patchGeoChannelAccount(tenantId.value, row.id, { status: 'active' })
    ElMessage.success('账号已启用')
    await load()
  } catch (e) {
    ElMessage.error(e.message || '启用失败')
  }
}

async function removeAccount(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除账号「${row.display_name}」(账号 ID ${row.id})？此操作不可恢复。`,
      '删除渠道账号',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteGeoChannelAccount(tenantId.value, row.id, true)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(e.message || '删除失败')
  }
}

function channelName(id) {
  const c = channels.value.find((x) => x.id === id)
  return c ? `${c.name || c.channel_type}` : `渠道#${id}`
}

function statusLabel(s) {
  const map = {
    active: '有效',
    unconfigured: '未配置',
    expired: '过期',
    disabled: '已禁用',
  }
  return map[s] || s || '—'
}

watch(tenantId, load)
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="geo-page">
    <div class="page-header">
      <div>
        <div class="page-title">发布渠道</div>
        <div class="page-desc">
          上表管理<strong>渠道类型</strong>（开哪些口）；下表按页签管理各渠道的<strong>账号</strong>（Webhook / 人工）。
          两边 ID 独立编号，勿混用。
        </div>
      </div>
      <div class="header-actions">
        <el-button @click="createChOpen = true">新建渠道</el-button>
        <el-button type="primary" @click="openCreateAccount()">新建账号</el-button>
        <el-button @click="load">刷新</el-button>
        <router-link class="el-button" to="/geo/workbench">工作台</router-link>
      </div>
    </div>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <!-- ① 渠道目录 -->
    <section class="block">
      <div class="block-head">
        <h3 class="sec">① 渠道目录</h3>
        <span class="sec-hint">表主键列：<code>渠道 ID</code>（与下方账号 ID 无关）</span>
      </div>
      <el-table :data="channels" stripe empty-text="暂无渠道" class="mb" size="small">
        <el-table-column prop="id" label="渠道 ID" width="88" />
        <el-table-column prop="channel_type" label="类型" width="130" show-overflow-tooltip />
        <el-table-column prop="name" label="名称" min-width="160" show-overflow-tooltip />
        <el-table-column label="发布模式" width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.publish_mode || '—' }}</template>
        </el-table-column>
        <el-table-column label="启用" width="80" align="center">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
              {{ row.enabled ? '是' : '否' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="账号数" width="80" align="center">
          <template #default="{ row }">
            {{ accounts.filter((a) => a.channel_id === row.id).length }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="toggleChannel(row)">
              {{ row.enabled ? '禁用' : '启用' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <!-- ② 渠道账号 + 页签 -->
    <section class="block">
      <div class="block-head">
        <h3 class="sec">② 渠道账号</h3>
        <span class="sec-hint">表主键列：<code>账号 ID</code> · 按渠道页签筛选；官网/文档可配 Webhook</span>
      </div>

      <el-tabs v-model="activeTab" type="card" class="acc-tabs">
        <el-tab-pane
          v-for="t in channelTabs"
          :key="t.key"
          :name="t.key"
          :label="t.key === 'all' ? `全部 (${t.count})` : `${t.label} (${t.count})`"
        />
      </el-tabs>

      <div class="tab-actions">
        <el-button
          type="primary"
          size="small"
          :disabled="activeTab === 'all' && !channels.length"
          @click="openCreateAccount(activeTab === 'all' ? null : Number(activeTab))"
        >
          在当前渠道新建账号
        </el-button>
        <span v-if="activeTab !== 'all'" class="hint">
          当前渠道 ID {{ activeTab }} ·
          {{ webhookCapable(Number(activeTab)) ? '支持 Webhook 推送' : '建议鉴权=manual，发完后回填 URL' }}
        </span>
      </div>

      <el-table :data="filteredAccounts" stripe empty-text="该渠道下暂无账号，可点上方新建" size="small">
        <el-table-column prop="id" label="账号 ID" width="88" />
        <el-table-column label="所属渠道" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">
            {{ channelName(row.channel_id) }}
            <span class="muted">（渠道 ID {{ row.channel_id }}）</span>
          </template>
        </el-table-column>
        <el-table-column prop="display_name" label="显示名" min-width="160" show-overflow-tooltip />
        <el-table-column prop="auth_type" label="鉴权" width="100" />
        <el-table-column label="状态" width="96">
          <template #default="{ row }">
            <el-tag
              size="small"
              :type="
                row.status === 'active'
                  ? 'success'
                  : row.status === 'disabled'
                    ? 'info'
                    : 'warning'
              "
            >
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="凭证" width="80" align="center">
          <template #default="{ row }">
            {{ row.has_credentials ? '已配' : '无' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEditAccount(row)">编辑</el-button>
            <el-button
              v-if="row.status === 'disabled'"
              link
              type="success"
              @click="enableAccount(row)"
            >
              启用
            </el-button>
            <el-button v-else link type="warning" @click="disableAccount(row)">禁用</el-button>
            <el-button link type="danger" @click="removeAccount(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <!-- 新建渠道 -->
    <el-dialog v-model="createChOpen" title="新建发布渠道" width="440px">
      <el-form label-width="88px">
        <el-form-item label="类型">
          <el-select v-model="chForm.channel_type" style="width: 100%">
            <el-option
              v-for="t in CHANNEL_TYPES"
              :key="t.value"
              :label="t.label"
              :value="t.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="chForm.name" placeholder="可选，默认用类型名" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createChOpen = false">取消</el-button>
        <el-button type="primary" @click="createChannel">创建</el-button>
      </template>
    </el-dialog>

    <!-- 新建账号 -->
    <el-dialog v-model="createAccOpen" title="新建渠道账号" width="500px">
      <el-form label-width="110px">
        <el-form-item label="所属渠道" required>
          <el-select
            v-model="accForm.channel_id"
            style="width: 100%"
            @change="onAccChannelChange"
          >
            <el-option
              v-for="c in channels"
              :key="c.id"
              :label="`${c.name || c.channel_type} · 渠道 ID ${c.id}`"
              :value="c.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="显示名" required>
          <el-input v-model="accForm.display_name" placeholder="如：官网 CMS 生产" />
        </el-form-item>
        <el-form-item label="鉴权类型">
          <el-select v-model="accForm.auth_type" style="width: 100%">
            <el-option label="webhook（官网/文档推送）" value="webhook" />
            <el-option label="manual（人工发 + 回填 URL）" value="manual" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="accForm.auth_type === 'webhook'" label="Webhook URL" required>
          <el-input v-model="accForm.webhook_url" placeholder="https://cms.example.com/hooks/geo" />
          <div class="form-tip">必须公网 HTTPS；列表不会回显完整 URL</div>
        </el-form-item>
        <el-alert
          v-if="accForm.auth_type === 'manual'"
          type="info"
          :closable="false"
          show-icon
          title="人工渠道：账号仅作登记，发完后在任务编辑器「回填 URL」"
        />
      </el-form>
      <template #footer>
        <el-button @click="createAccOpen = false">取消</el-button>
        <el-button type="primary" @click="createAccount">创建</el-button>
      </template>
    </el-dialog>

    <!-- 编辑账号 -->
    <el-dialog v-model="editAccOpen" title="编辑渠道账号" width="500px">
      <el-form label-width="110px">
        <el-form-item label="账号 ID">
          <span>{{ editForm.id }}</span>
        </el-form-item>
        <el-form-item label="显示名" required>
          <el-input v-model="editForm.display_name" />
        </el-form-item>
        <el-form-item label="鉴权类型">
          <el-select v-model="editForm.auth_type" style="width: 100%">
            <el-option label="webhook" value="webhook" />
            <el-option label="manual" value="manual" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="editForm.status" style="width: 100%">
            <el-option label="有效 active" value="active" />
            <el-option label="未配置 unconfigured" value="unconfigured" />
            <el-option label="已禁用 disabled" value="disabled" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="editForm.auth_type === 'webhook'" label="新 Webhook">
          <el-input
            v-model="editForm.webhook_url"
            placeholder="留空=不改凭证；填写则覆盖为新 HTTPS URL"
          />
        </el-form-item>
        <el-form-item v-if="editForm.auth_type === 'webhook'" label="清除凭证">
          <el-checkbox v-model="editForm.clear_credentials">清空已存 Webhook</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editAccOpen = false">取消</el-button>
        <el-button type="primary" @click="saveEditAccount">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.geo-page { padding: 4px 2px 28px; }
.page-header {
  display: flex; justify-content: space-between; gap: 12px; margin-bottom: 14px; flex-wrap: wrap;
}
.page-title { font-size: 20px; font-weight: 700; color: #1e2330; }
.page-desc { font-size: 13px; color: #6b7280; margin-top: 4px; max-width: 640px; line-height: 1.5; }
.header-actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.mb { margin-bottom: 16px; }
.block {
  background: #fff;
  border: 1px solid #e8e4f5;
  border-radius: 12px;
  padding: 14px 16px 18px;
  margin-bottom: 16px;
}
.block-head {
  display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; margin-bottom: 10px;
}
.sec { font-size: 15px; font-weight: 700; margin: 0; color: #374151; }
.sec-hint { font-size: 12px; color: #9ca3af; }
.sec-hint code {
  background: #f5f0ff; padding: 1px 6px; border-radius: 4px; color: #6d28d9;
}
.acc-tabs { margin-bottom: 8px; }
.tab-actions {
  display: flex; align-items: center; gap: 12px; margin-bottom: 10px; flex-wrap: wrap;
}
.hint { font-size: 12px; color: #6b7280; }
.muted { font-size: 12px; color: #9ca3af; margin-left: 4px; }
.form-tip { font-size: 12px; color: #9ca3af; margin-top: 4px; }
</style>
