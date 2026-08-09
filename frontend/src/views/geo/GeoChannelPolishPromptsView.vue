<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  fetchChannelPolishPrompts,
  putChannelPolishPrompts,
} from '../../api/geoContent'
import { useGeoTenant } from '../../composables/useGeoTenant'

const { tenantId } = useGeoTenant()
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const activeTab = ref('website')
const systemPrompt = ref('')
const systemDefault = ref('')
const isCustomSystem = ref(false)
const channels = ref([])

const current = computed(() =>
  channels.value.find((c) => c.channel_key === activeTab.value) || null,
)

function applyPayload(data) {
  systemPrompt.value = data.system_prompt || ''
  systemDefault.value = data.system_prompt_default || ''
  isCustomSystem.value = !!data.is_custom_system
  channels.value = (data.channels || []).map((c) => ({
    channel_key: c.channel_key,
    display_name: c.display_name,
    voice_prompt: c.voice_prompt || '',
    voice_default: c.voice_default || '',
    min_body_chars: c.min_body_chars ?? 600,
    min_body_chars_default: c.min_body_chars_default ?? 600,
    is_custom_voice: !!c.is_custom_voice,
    is_custom_min_body_chars: !!c.is_custom_min_body_chars,
  }))
  if (!channels.value.some((c) => c.channel_key === activeTab.value) && channels.value[0]) {
    activeTab.value = channels.value[0].channel_key
  }
}

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    return
  }
  loading.value = true
  error.value = ''
  try {
    applyPayload(await fetchChannelPolishPrompts(tenantId.value))
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!tenantId.value) return
  saving.value = true
  try {
    const data = await putChannelPolishPrompts({
      tenant_id: tenantId.value,
      system_prompt: systemPrompt.value,
      channels: channels.value.map((c) => ({
        channel_key: c.channel_key,
        voice_prompt: c.voice_prompt,
        min_body_chars: Number(c.min_body_chars) || null,
      })),
    })
    applyPayload(data)
    ElMessage.success('已保存渠道成稿提示词')
  } catch (e) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function resetSystem() {
  if (!tenantId.value) return
  saving.value = true
  try {
    const data = await putChannelPolishPrompts({
      tenant_id: tenantId.value,
      reset_system: true,
    })
    applyPayload(data)
    ElMessage.success('已恢复系统提示词默认')
  } catch (e) {
    ElMessage.error(e.message || '恢复失败')
  } finally {
    saving.value = false
  }
}

async function resetChannel(key) {
  if (!tenantId.value || !key) return
  saving.value = true
  try {
    const data = await putChannelPolishPrompts({
      tenant_id: tenantId.value,
      channels: [{ channel_key: key, reset: true }],
    })
    applyPayload(data)
    ElMessage.success('已恢复该渠道默认提示词')
  } catch (e) {
    ElMessage.error(e.message || '恢复失败')
  } finally {
    saving.value = false
  }
}

function fillSystemDefault() {
  systemPrompt.value = systemDefault.value
}

function fillChannelDefaults() {
  const c = current.value
  if (!c) return
  c.voice_prompt = c.voice_default
  c.min_body_chars = c.min_body_chars_default
}

watch(tenantId, load)
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="geo-page">
    <div class="page-header">
      <div>
        <div class="page-title">渠道成稿提示词</div>
        <div class="page-desc">
          按平台差异配置「AI 生成正式渠道稿」的系统提示词与渠道语气；空覆盖则用代码默认。
        </div>
      </div>
      <div class="header-actions">
        <el-button type="primary" :loading="saving" @click="save">保存全部</el-button>
        <el-button @click="load">刷新</el-button>
        <router-link class="el-button" to="/geo/ai-settings">AI 配置</router-link>
        <router-link class="el-button" to="/geo/tasks">优化文章</router-link>
      </div>
    </div>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <el-card shadow="never" class="card mb">
      <template #header>
        <div class="card-head">
          <span>
            共享系统提示词
            <el-tag size="small" :type="isCustomSystem ? 'warning' : 'info'" class="tag">
              {{ isCustomSystem ? '已自定义' : '使用默认' }}
            </el-tag>
          </span>
          <div class="card-actions">
            <el-button size="small" @click="fillSystemDefault">填入默认</el-button>
            <el-button size="small" :disabled="!isCustomSystem" @click="resetSystem">
              恢复默认
            </el-button>
          </div>
        </div>
      </template>
      <el-input
        v-model="systemPrompt"
        type="textarea"
        :rows="10"
        placeholder="全渠道共用的 system prompt"
      />
    </el-card>

    <el-card shadow="never" class="card">
      <template #header>
        <span>分渠道语气（voice）</span>
      </template>
      <el-tabs v-model="activeTab">
        <el-tab-pane
          v-for="c in channels"
          :key="c.channel_key"
          :name="c.channel_key"
          :label="c.display_name"
        />
      </el-tabs>

      <template v-if="current">
        <div class="channel-meta mb">
          <el-tag size="small" :type="current.is_custom_voice ? 'warning' : 'info'">
            语气 {{ current.is_custom_voice ? '已自定义' : '使用默认' }}
          </el-tag>
          <el-tag size="small" :type="current.is_custom_min_body_chars ? 'warning' : 'info'">
            字数 {{ current.is_custom_min_body_chars ? '已自定义' : '使用默认' }}
          </el-tag>
          <el-button size="small" @click="fillChannelDefaults">填入默认</el-button>
          <el-button
            size="small"
            :disabled="!current.is_custom_voice && !current.is_custom_min_body_chars"
            @click="resetChannel(current.channel_key)"
          >
            恢复该渠道默认
          </el-button>
        </div>
        <el-form label-width="110px">
          <el-form-item label="最低成稿字数">
            <el-input-number
              v-model="current.min_body_chars"
              :min="100"
              :max="20000"
              :step="50"
            />
            <span class="hint">默认 {{ current.min_body_chars_default }}</span>
          </el-form-item>
          <el-form-item label="渠道语气">
            <el-input
              v-model="current.voice_prompt"
              type="textarea"
              :rows="12"
              :placeholder="`${current.display_name} 成稿语气与结构要求`"
            />
          </el-form-item>
        </el-form>
      </template>
    </el-card>
  </div>
</template>

<style scoped>
.geo-page { padding: 4px 2px 24px; }
.page-header {
  display: flex; justify-content: space-between; gap: 12px; margin-bottom: 14px; flex-wrap: wrap;
}
.page-title { font-size: 20px; font-weight: 700; }
.page-desc { font-size: 13px; color: #6b7280; margin-top: 4px; max-width: 640px; }
.header-actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.mb { margin-bottom: 12px; }
.card { border-radius: 12px; }
.card-head {
  display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap;
}
.card-actions { display: flex; gap: 8px; }
.tag { margin-left: 8px; vertical-align: middle; }
.channel-meta { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.hint { margin-left: 10px; font-size: 12px; color: #8b93a7; }
</style>
