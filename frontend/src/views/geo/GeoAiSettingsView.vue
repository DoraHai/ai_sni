<script setup>
import { onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchGeoAiSettings, putGeoAiSettings, testGeoAiSettings } from '../../api/geoContent'
import { useGeoTenant } from '../../composables/useGeoTenant'

const { tenantId } = useGeoTenant()
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const error = ref('')
const form = ref({
  provider: 'dashscope',
  base_url: '',
  model: '',
  api_key: '',
  clear_api_key: false,
  enabled: true,
  note: '',
  apply_preset: false,
})
const meta = ref(null)

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const data = await fetchGeoAiSettings(tenantId.value)
    meta.value = data
    form.value = {
      provider: data.provider || 'dashscope',
      base_url: data.base_url || '',
      model: data.model || '',
      api_key: '',
      clear_api_key: false,
      enabled: data.enabled !== false,
      note: data.note || '',
      apply_preset: false,
    }
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const body = {
      tenant_id: tenantId.value,
      provider: form.value.provider,
      base_url: form.value.base_url || null,
      model: form.value.model || null,
      enabled: form.value.enabled,
      note: form.value.note || null,
      apply_preset: form.value.apply_preset,
      clear_api_key: form.value.clear_api_key,
    }
    if (form.value.api_key && form.value.api_key.length >= 8) {
      body.api_key = form.value.api_key
    }
    meta.value = await putGeoAiSettings(body)
    form.value.api_key = ''
    form.value.clear_api_key = false
    ElMessage.success('已保存 AI 配置')
  } catch (e) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function test() {
  testing.value = true
  try {
    const r = await testGeoAiSettings(tenantId.value)
    ElMessage.success(r.message || r.status || '测试完成')
  } catch (e) {
    ElMessage.error(e.message || '测试失败')
  } finally {
    testing.value = false
  }
}

watch(tenantId, load)
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="geo-page">
    <div class="page-header">
      <div>
        <div class="page-title">AI 能力配置</div>
        <div class="page-desc">对应静态 ai-settings.html · 租户级生成/探测/审稿默认 LLM</div>
      </div>
      <div class="header-actions">
        <el-button :loading="testing" @click="test">测试连通</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
        <el-button @click="load">刷新</el-button>
        <router-link class="el-button" to="/geo/workbench">工作台</router-link>
      </div>
    </div>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <el-card shadow="never" class="card">
      <el-form label-width="120px" style="max-width: 560px">
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
        <el-form-item label="Provider">
          <el-select v-model="form.provider" style="width: 100%">
            <el-option label="阿里云百炼 DashScope" value="dashscope" />
            <el-option label="DeepSeek" value="deepseek" />
          </el-select>
        </el-form-item>
        <el-form-item label="应用预设">
          <el-switch v-model="form.apply_preset" />
          <span class="hint">保存时用 provider 默认 base/model</span>
        </el-form-item>
        <el-form-item label="Base URL">
          <el-input v-model="form.base_url" placeholder="OpenAI 兼容地址" />
        </el-form-item>
        <el-form-item label="Model">
          <el-input v-model="form.model" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input
            v-model="form.api_key"
            type="password"
            show-password
            :placeholder="meta?.api_key_configured ? `已配置 ${meta.api_key_masked || ''}` : '未配置'"
          />
          <el-checkbox v-if="meta?.api_key_configured" v-model="form.clear_api_key">清除 Key</el-checkbox>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.note" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <div v-if="meta" class="meta">
        来源提示：{{ meta.source || '—' }} · 更新于 {{ meta.updated_at || '—' }}
      </div>
    </el-card>
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
.card { border-radius: 12px; }
.hint { margin-left: 10px; font-size: 12px; color: #8b93a7; }
.meta { margin-top: 12px; font-size: 12px; color: #8b93a7; }
</style>
