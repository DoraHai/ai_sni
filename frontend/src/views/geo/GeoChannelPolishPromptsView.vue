<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  fetchChannelPolishPrompts,
  putChannelPolishPrompts,
} from '../../api/geoContent'
import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
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

const current = computed(
  () => channels.value.find((c) => c.channel_key === activeTab.value) || null,
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
    applyPayload(
      await putChannelPolishPrompts({
        tenant_id: tenantId.value,
        reset_system: true,
      }),
    )
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
    applyPayload(
      await putChannelPolishPrompts({
        tenant_id: tenantId.value,
        channels: [{ channel_key: key, reset: true }],
      }),
    )
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
  <GeoWorkbenchPage
    title="渠道成稿提示词"
    sub="官网 / 微信 / 知乎等渠道稿的系统提示、语气和最低字数。编辑器里「AI 生成正式渠道稿」会读这里。"
    :loading="loading"
  >
    <template #actions>
      <router-link class="gd-btn" to="/geo/ai-settings">AI 配置</router-link>
      <router-link class="gd-btn" to="/geo/tasks">优化文章</router-link>
      <button type="button" class="gd-btn" :disabled="loading" @click="load">刷新</button>
      <button type="button" class="gd-btn primary" :disabled="saving" @click="save">保存全部</button>
    </template>

    <div class="geo-v2 polish-page">
      <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

      <section class="gv2-panel">
        <div class="gv2-panel-head">
          <div>
            <span class="gv2-kicker">共用</span>
            <h2>系统提示词</h2>
            <p class="sub">全渠道共用的成稿约束。空则走代码默认；自定义后优先用租户配置。</p>
          </div>
          <div class="head-actions">
            <el-tag size="small" :type="isCustomSystem ? 'warning' : 'info'" effect="light">
              {{ isCustomSystem ? '已自定义' : '使用默认' }}
            </el-tag>
            <el-button size="small" @click="fillSystemDefault">填入默认</el-button>
            <el-button size="small" :disabled="!isCustomSystem" @click="resetSystem">
              恢复默认
            </el-button>
          </div>
        </div>
        <el-input
          v-model="systemPrompt"
          type="textarea"
          :rows="10"
          placeholder="全渠道共用的 system prompt（硬门控：完整成文 + GEO 品牌提及）"
        />
      </section>

      <section class="gv2-panel">
        <div class="gv2-panel-head">
          <div>
            <span class="gv2-kicker">分渠道</span>
            <h2>语气与字数</h2>
            <p class="sub">每个平台一篇成稿规范。字数不达标会被整篇驳回，不会存伪正稿。</p>
          </div>
        </div>
        <el-tabs v-model="activeTab" class="channel-tabs">
          <el-tab-pane
            v-for="c in channels"
            :key="c.channel_key"
            :name="c.channel_key"
            :label="c.display_name"
          />
        </el-tabs>
        <template v-if="current">
          <div class="channel-meta">
            <el-tag size="small" :type="current.is_custom_voice ? 'warning' : 'info'" effect="light">
              语气 {{ current.is_custom_voice ? '已自定义' : '使用默认' }}
            </el-tag>
            <el-tag
              size="small"
              :type="current.is_custom_min_body_chars ? 'warning' : 'info'"
              effect="light"
            >
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
          <el-form label-width="110px" class="channel-form">
            <el-form-item label="最低成稿字数">
              <el-input-number
                v-model="current.min_body_chars"
                :min="100"
                :max="20000"
                :step="50"
              />
              <span class="inline-hint">默认 {{ current.min_body_chars_default }}</span>
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
        <el-empty v-else description="暂无渠道配置，请先刷新或检查后端渠道注册表" />
      </section>
    </div>
  </GeoWorkbenchPage>
</template>

<style scoped>
.mb { margin-bottom: 14px; }
.head-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}
.channel-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
  padding: 10px 12px;
  margin-bottom: 14px;
  background: #f8fafc;
  border-radius: 10px;
  border: 1px solid #eef2f7;
}
.inline-hint {
  margin-left: 10px;
  font-size: 12px;
  color: #64748b;
}
.channel-form { max-width: 920px; }
.channel-tabs :deep(.el-tabs__header) { margin-bottom: 14px; }
</style>
