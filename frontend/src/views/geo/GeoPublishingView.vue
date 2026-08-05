<script setup>
import { onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  createGeoChannelAccount,
  createGeoPublishingChannel,
  listGeoChannelAccounts,
  listGeoPublishingChannels,
  patchGeoPublishingChannel,
} from '../../api/geoContent'
import { useGeoTenant } from '../../composables/useGeoTenant'

const { tenantId } = useGeoTenant()
const loading = ref(false)
const error = ref('')
const channels = ref([])
const accounts = ref([])
const createChOpen = ref(false)
const createAccOpen = ref(false)
const chForm = ref({
  channel_type: 'website',
  name: '',
  enabled: true,
})
const accForm = ref({
  channel_id: null,
  display_name: '',
  auth_type: 'webhook',
  webhook_url: '',
})

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
    await load()
  } catch (e) {
    ElMessage.error(e.message || '更新失败')
  }
}

async function createAccount() {
  if (!accForm.value.channel_id || !accForm.value.display_name.trim()) {
    ElMessage.warning('请选择渠道并填写名称')
    return
  }
  if (!accForm.value.webhook_url.trim().startsWith('https://')) {
    ElMessage.warning('Webhook 需 HTTPS 公网 URL')
    return
  }
  try {
    await createGeoChannelAccount({
      tenant_id: tenantId.value,
      channel_id: accForm.value.channel_id,
      display_name: accForm.value.display_name.trim(),
      auth_type: 'webhook',
      credentials: {
        webhook_url: accForm.value.webhook_url.trim(),
        method: 'POST',
      },
    })
    ElMessage.success('已创建渠道账号')
    createAccOpen.value = false
    accForm.value.display_name = ''
    accForm.value.webhook_url = ''
    await load()
  } catch (e) {
    ElMessage.error(e.message || '创建失败')
  }
}

function channelName(id) {
  const c = channels.value.find((x) => x.id === id)
  return c ? `${c.name || c.channel_type} (#${id})` : `#${id}`
}

watch(tenantId, load)
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="geo-page">
    <div class="page-header">
      <div>
        <div class="page-title">发布渠道</div>
        <div class="page-desc">对应静态 publishing-channels.html · 渠道目录与 Webhook 账号</div>
      </div>
      <div class="header-actions">
        <el-button @click="createChOpen = true">新建渠道</el-button>
        <el-button type="primary" @click="createAccOpen = true">新建 Webhook 账号</el-button>
        <el-button @click="load">刷新</el-button>
        <router-link class="el-button" to="/geo/workbench">工作台</router-link>
      </div>
    </div>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <h3 class="sec">渠道目录</h3>
    <el-table :data="channels" stripe empty-text="暂无渠道" class="mb">
      <el-table-column prop="id" label="ID" width="72" />
      <el-table-column prop="channel_type" label="类型" width="110" />
      <el-table-column prop="name" label="名称" min-width="140" />
      <el-table-column label="启用" width="90">
        <template #default="{ row }">
          <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
            {{ row.enabled ? '是' : '否' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="100">
        <template #default="{ row }">
          <el-button link type="primary" @click="toggleChannel(row)">
            {{ row.enabled ? '禁用' : '启用' }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <h3 class="sec">渠道账号</h3>
    <el-table :data="accounts" stripe empty-text="暂无账号">
      <el-table-column prop="id" label="ID" width="72" />
      <el-table-column label="渠道" min-width="140">
        <template #default="{ row }">{{ channelName(row.channel_id) }}</template>
      </el-table-column>
      <el-table-column prop="display_name" label="显示名" min-width="160" />
      <el-table-column prop="auth_type" label="鉴权" width="100" />
    </el-table>

    <el-dialog v-model="createChOpen" title="新建发布渠道" width="420px">
      <el-form label-width="88px">
        <el-form-item label="类型">
          <el-select v-model="chForm.channel_type" style="width: 100%">
            <el-option label="website" value="website" />
            <el-option label="docs" value="docs" />
            <el-option label="wechat" value="wechat" />
            <el-option label="zhihu" value="zhihu" />
          </el-select>
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="chForm.name" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createChOpen = false">取消</el-button>
        <el-button type="primary" @click="createChannel">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="createAccOpen" title="新建 Webhook 账号" width="480px">
      <el-form label-width="100px">
        <el-form-item label="渠道" required>
          <el-select v-model="accForm.channel_id" style="width: 100%">
            <el-option
              v-for="c in channels"
              :key="c.id"
              :label="`${c.name || c.channel_type} (#${c.id})`"
              :value="c.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="显示名" required>
          <el-input v-model="accForm.display_name" />
        </el-form-item>
        <el-form-item label="Webhook URL" required>
          <el-input v-model="accForm.webhook_url" placeholder="https://..." />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createAccOpen = false">取消</el-button>
        <el-button type="primary" @click="createAccount">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.geo-page { padding: 4px 2px 24px; }
.page-header {
  display: flex; justify-content: space-between; gap: 12px; margin-bottom: 14px; flex-wrap: wrap;
}
.page-title { font-size: 20px; font-weight: 700; }
.page-desc { font-size: 13px; color: #6b7280; margin-top: 4px; }
.header-actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.mb { margin-bottom: 16px; }
.sec { font-size: 15px; font-weight: 600; margin: 8px 0 10px; color: #374151; }
</style>
