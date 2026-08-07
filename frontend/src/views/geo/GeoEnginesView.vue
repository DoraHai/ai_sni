<script setup>
import { onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { listGeoTrackingEngines, putGeoTrackingEngines } from '../../api/geoContent'
import { useGeoTenant } from '../../composables/useGeoTenant'

const { tenantId } = useGeoTenant()
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const items = ref([])

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    items.value = []
    return
  }
  loading.value = true
  error.value = ''
  try {
    const data = await listGeoTrackingEngines(tenantId.value, false)
    items.value = (data.items || []).map((it) => ({
      ...it,
      sample_mode: it.sample_mode || 'mock_persona',
      api_base_url: it.api_base_url || '',
      model: it.model || '',
      api_key: '',
      clear_api_key: false,
    }))
  } catch (e) {
    error.value = e.message || '加载失败'
    items.value = []
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!tenantId.value) return
  saving.value = true
  try {
    const payload = items.value.map((it, idx) => ({
      engine_key: it.engine_key,
      display_name: it.display_name,
      enabled: !!it.enabled,
      note: it.note || null,
      sort_order: it.sort_order ?? idx * 10,
      sample_mode: it.sample_mode || 'mock_persona',
      api_base_url: it.api_base_url || null,
      model: it.model || null,
      api_key: it.api_key && it.api_key.length >= 8 ? it.api_key : undefined,
      clear_api_key: !!it.clear_api_key,
    }))
    const data = await putGeoTrackingEngines(tenantId.value, payload)
    items.value = (data.items || []).map((it) => ({
      ...it,
      api_key: '',
      clear_api_key: false,
    }))
    ElMessage.success('已保存引擎配置')
  } catch (e) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

watch(tenantId, load)
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="geo-page">
    <div class="page-header">
      <div>
        <div class="page-title">引擎</div>
        <div class="page-desc">对应静态 engines.html · sample_mode 支持 openai_compat 真采样</div>
      </div>
      <div class="header-actions">
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
        <el-button @click="load">刷新</el-button>
        <router-link class="el-button" to="/geo/workbench">工作台</router-link>
      </div>
    </div>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <el-table :data="items" stripe empty-text="暂无引擎">
      <el-table-column prop="engine_key" label="Key" width="110" />
      <el-table-column label="显示名" min-width="120">
        <template #default="{ row }">
          <el-input v-model="row.display_name" size="small" />
        </template>
      </el-table-column>
      <el-table-column label="启用" width="80">
        <template #default="{ row }">
          <el-switch v-model="row.enabled" />
        </template>
      </el-table-column>
      <el-table-column label="采样模式" width="160">
        <template #default="{ row }">
          <el-select v-model="row.sample_mode" size="small" style="width: 100%">
            <el-option label="人设模拟" value="mock_persona" />
            <el-option label="OpenAI 兼容" value="openai_compat" />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column label="Base URL" min-width="160">
        <template #default="{ row }">
          <el-input v-model="row.api_base_url" size="small" placeholder="openai_compat" />
        </template>
      </el-table-column>
      <el-table-column label="Model" width="140">
        <template #default="{ row }">
          <el-input v-model="row.model" size="small" />
        </template>
      </el-table-column>
      <el-table-column label="API Key" min-width="140">
        <template #default="{ row }">
          <el-input
            v-model="row.api_key"
            size="small"
            type="password"
            show-password
            :placeholder="row.api_key_configured ? '已配置 · 留空保留' : '未配置'"
          />
          <el-checkbox v-if="row.api_key_configured" v-model="row.clear_api_key" size="small">
            清除 Key
          </el-checkbox>
        </template>
      </el-table-column>
      <el-table-column label="排序" width="90">
        <template #default="{ row }">
          <el-input-number v-model="row.sort_order" size="small" :step="10" controls-position="right" />
        </template>
      </el-table-column>
    </el-table>
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
.mb { margin-bottom: 12px; }
</style>
