<script setup>
import { onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchGeoAiSettings, putGeoAiSettings, testGeoAiSettings } from '../../api/geoContent'
import NeedHintAlert from '../../components/NeedHintAlert.vue'
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
    <NeedHintAlert />

    <div class="geo-form-panel">
      <div class="form-section-title">模型与密钥</div>
      <el-form label-width="120px" label-position="right">
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
          <span class="form-hint inline">关闭后渠道润色/母稿生成将无法调用 LLM</span>
        </el-form-item>
        <el-form-item label="服务商">
          <el-select v-model="form.provider" style="width: 100%">
            <el-option label="阿里云百炼 DashScope" value="dashscope" />
            <el-option label="DeepSeek" value="deepseek" />
          </el-select>
        </el-form-item>
        <el-form-item label="应用预设">
          <div class="switch-row">
            <el-switch v-model="form.apply_preset" />
            <span class="form-hint inline">保存时写入该服务商默认 Base / Model</span>
          </div>
        </el-form-item>
        <el-form-item label="Base URL">
          <el-input v-model="form.base_url" placeholder="OpenAI 兼容接口地址" />
        </el-form-item>
        <el-form-item label="Model">
          <el-input v-model="form.model" placeholder="如 deepseek-chat / qwen-plus" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input
            v-model="form.api_key"
            type="password"
            show-password
            :placeholder="meta?.api_key_configured ? `已配置 ${meta.api_key_masked || ''}` : '粘贴密钥（不会明文回显）'"
          />
          <el-checkbox v-if="meta?.api_key_configured" v-model="form.clear_api_key" class="mt-check">
            清除已保存的 Key
          </el-checkbox>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.note" type="textarea" :rows="2" placeholder="可选：用途说明" />
        </el-form-item>
      </el-form>
      <div v-if="meta" class="meta-bar">
        来源：{{ meta.source || '—' }} · 更新于 {{ meta.updated_at || '—' }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.switch-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.form-hint.inline {
  margin-top: 0;
  margin-left: 4px;
}
.mt-check { margin-top: 8px; }
.meta-bar {
  margin: 4px 0 18px;
  padding: 10px 12px;
  font-size: 12px;
  color: #64748b;
  background: #f8fafc;
  border-radius: 10px;
  border: 1px solid #eef2f7;
}
</style>
