<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { currentTenantId } from '../../store/session'
import { applyBuildDraft, generateBuildDraft } from '../../api/onboardingBuilder'

const form = reactive({
  landingUrl: '',
  landingText: '',
  businessSummary: '',
  goal: '获取高意向线索',
  budget: '',
  regions: '',
  schedulePreset: 'all',
  scheduleBlocks: [{ weekDays: [1, 2, 3, 4, 5, 6, 7], startHour: 0, endHour: 24 }],
  devicePreference: '不限',
})

const loading = ref(false)
const applying = ref(false)
const loadingPhaseIndex = ref(0)
const result = ref(null)
const applyResult = ref(null)
const landingMode = ref('url')
let loadingTimer = null
const weekOptions = [
  { label: '周一', value: 1 },
  { label: '周二', value: 2 },
  { label: '周三', value: 3 },
  { label: '周四', value: 4 },
  { label: '周五', value: 5 },
  { label: '周六', value: 6 },
  { label: '周日', value: 7 },
]
const hourOptions = Array.from({ length: 25 }, (_, hour) => ({
  label: `${String(hour).padStart(2, '0')}:00`,
  value: hour,
}))
const schedulePresets = [
  { label: '全天', value: 'all', blocks: [{ weekDays: [1, 2, 3, 4, 5, 6, 7], startHour: 0, endHour: 24 }] },
  { label: '工作日 9-18', value: 'workday', blocks: [{ weekDays: [1, 2, 3, 4, 5], startHour: 9, endHour: 18 }] },
  { label: '每天 9-22', value: 'daytime', blocks: [{ weekDays: [1, 2, 3, 4, 5, 6, 7], startHour: 9, endHour: 22 }] },
  { label: '自定义', value: 'custom', blocks: null },
]

const draft = computed(() => result.value?.draft || null)
const sourceLabel = computed(() => (result.value?.source === 'ai' ? 'AI 生成' : '规则草案'))
const effectiveTenantId = computed(() => currentTenantId.value || (import.meta.env.DEV && import.meta.env.VITE_API_KEY ? 1 : null))
const loadingPhases = [
  { title: '抓取落地页信息', desc: '正在读取页面标题、正文和可提取的业务词。' },
  { title: '预热拓词候选', desc: '首次接入时会调用百度规划师和 URL 拓词，时间会稍长。' },
  { title: '筛选高意向关键词', desc: '正在过滤通用词、否词和不相关词。' },
  { title: '生成搭建草案', desc: '正在整理计划、单元、关键词、创意和投放设置。' },
]
const loadingHint = computed(() => loadingPhases[loadingPhaseIndex.value] || loadingPhases[0])
const actionLabels = {
  build_campaign: '创建计划',
  build_adgroup: '创建单元',
  build_keyword: '添加关键词',
  build_creative: '添加创意',
}

function loadAssistantHandoff() {
  const tenantId = effectiveTenantId.value
  if (!tenantId) return
  const key = `sem_builder_handoff_${tenantId}`
  const raw = sessionStorage.getItem(key)
  if (!raw) return
  sessionStorage.removeItem(key)
  try {
    const handoff = JSON.parse(raw)
    if (handoff.tenantId !== tenantId || !handoff.result?.draft) return
    if (Date.now() - Number(handoff.createdAt || 0) > 24 * 60 * 60 * 1000) return

    const incoming = handoff.form || {}
    form.landingUrl = incoming.landingUrl || ''
    form.landingText = incoming.landingText || ''
    form.businessSummary = incoming.businessSummary || ''
    form.goal = incoming.goal || '获取高意向线索'
    form.budget = incoming.budget || ''
    form.regions = incoming.regions || ''
    form.schedulePreset = incoming.schedulePreset || 'all'
    form.scheduleBlocks = Array.isArray(incoming.scheduleBlocks) && incoming.scheduleBlocks.length
      ? cloneBlocks(incoming.scheduleBlocks)
      : cloneBlocks(schedulePresets[0].blocks)
    form.devicePreference = incoming.devicePreference || '不限'
    landingMode.value = form.landingUrl ? 'url' : 'text'
    result.value = handoff.result
    applyResult.value = null
    ElMessage.success('已载入 AI 助手生成的搭建草案')
  } catch {
    ElMessage.warning('AI 搭建草案读取失败，请重新生成')
  }
}

function selectedStats() {
  const stats = { campaigns: 0, adgroups: 0, keywords: 0, creatives: 0 }
  for (const camp of draft.value?.campaigns || []) {
    if (camp.selected) stats.campaigns += 1
    for (const adg of camp.adgroups || []) {
      if (adg.selected) stats.adgroups += 1
      for (const kw of adg.keywords || []) if (kw.selected) stats.keywords += 1
      for (const cr of adg.creatives || []) if (cr.selected) stats.creatives += 1
    }
  }
  return stats
}

const stats = computed(selectedStats)
const scheduleText = computed(() => scheduleBlocksToText(form.scheduleBlocks))

function cloneBlocks(blocks) {
  return blocks.map((block) => ({
    weekDays: [...block.weekDays],
    startHour: block.startHour,
    endHour: block.endHour,
  }))
}

function weekdayText(days = []) {
  const ordered = [...days].sort((a, b) => a - b)
  if (ordered.length === 7) return '周一至周日'
  if (ordered.join(',') === '1,2,3,4,5') return '周一至周五'
  if (ordered.join(',') === '6,7') return '周六至周日'
  return ordered.map((day) => weekOptions.find((item) => item.value === day)?.label).filter(Boolean).join('、')
}

function scheduleBlocksToText(blocks = []) {
  const valid = blocks.filter((block) => block.weekDays?.length && block.startHour < block.endHour)
  if (!valid.length) return '投放时段未设置'
  return valid
    .map((block) => `${weekdayText(block.weekDays)} ${String(block.startHour).padStart(2, '0')}:00-${String(block.endHour).padStart(2, '0')}:00`)
    .join('、')
}

function applySchedulePreset(value) {
  form.schedulePreset = value
  const preset = schedulePresets.find((item) => item.value === value)
  if (preset?.blocks) form.scheduleBlocks = cloneBlocks(preset.blocks)
}

function addScheduleBlock() {
  form.schedulePreset = 'custom'
  form.scheduleBlocks.push({ weekDays: [1, 2, 3, 4, 5], startHour: 9, endHour: 18 })
}

function removeScheduleBlock(index) {
  form.scheduleBlocks.splice(index, 1)
  if (!form.scheduleBlocks.length) addScheduleBlock()
}

function normalizeScheduleBlock(block) {
  if (block.endHour <= block.startHour) block.endHour = Math.min(24, block.startHour + 1)
  if (!block.weekDays.length) block.weekDays = [1, 2, 3, 4, 5]
}

function toggleWeekDay(block, day) {
  form.schedulePreset = 'custom'
  const set = new Set(block.weekDays || [])
  if (set.has(day)) {
    if (set.size === 1) return
    set.delete(day)
  } else {
    set.add(day)
  }
  block.weekDays = [...set].sort((a, b) => a - b)
}

function startLoadingHint() {
  loadingPhaseIndex.value = 0
  clearInterval(loadingTimer)
  loadingTimer = setInterval(() => {
    if (loadingPhaseIndex.value < loadingPhases.length - 1) {
      loadingPhaseIndex.value += 1
    }
  }, 3500)
}

function stopLoadingHint() {
  clearInterval(loadingTimer)
  loadingTimer = null
  loadingPhaseIndex.value = 0
}

async function onGenerate() {
  if (!effectiveTenantId.value) {
    ElMessage.warning('请先选择客户')
    return
  }
  if (!form.businessSummary.trim() || !form.goal.trim()) {
    ElMessage.warning('请填写业务概述和投放目的')
    return
  }
  if (landingMode.value === 'url' && !form.landingUrl.trim()) {
    ElMessage.warning('请填写落地页链接，或切换为“没有链接”')
    return
  }
  if (landingMode.value === 'text' && !form.landingText.trim()) {
    ElMessage.warning('请把图片式落地页的主要文字贴进来')
    return
  }
  loading.value = true
  startLoadingHint()
  try {
    applyResult.value = null
    result.value = await generateBuildDraft({
      ...form,
      schedule: scheduleText.value,
      scheduleBlocks: form.scheduleBlocks,
      tenantId: effectiveTenantId.value,
    })
    if (result.value.fetch_warning) {
      ElMessage.warning(result.value.fetch_warning)
    } else {
      ElMessage.success('搭建草案已生成')
    }
  } catch (e) {
    ElMessage.error(e.message || '生成失败')
  } finally {
    loading.value = false
    stopLoadingHint()
  }
}

onBeforeUnmount(stopLoadingHint)
onMounted(loadAssistantHandoff)

function exportDraft() {
  if (!draft.value) return
  const blob = new Blob([JSON.stringify(draft.value, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `sem-build-draft-${Date.now()}.json`
  a.click()
  URL.revokeObjectURL(url)
}

async function onApplyDraft() {
  if (!effectiveTenantId.value || !draft.value) return
  applying.value = true
  try {
    applyResult.value = await applyBuildDraft({
      tenantId: effectiveTenantId.value,
      draft: draft.value,
    })
    const failed = applyResult.value?.summary?.failed || 0
    if (failed) {
      ElMessage.warning(`演练完成，但有 ${failed} 个动作失败`)
    } else {
      ElMessage.success('演练完成：未真实写入百度')
    }
  } catch (e) {
    ElMessage.error(e.message || '演练搭建失败')
  } finally {
    applying.value = false
  }
}

function arrayText(values) {
  return Array.isArray(values) ? values.join('、') : (values || '')
}

function updateArrayField(target, field, value) {
  target[field] = String(value || '')
    .split(/[、,，]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}
</script>

<template>
  <div class="builder-page">
    <div class="page-header">
      <div>
        <div class="page-title">智能搭建</div>
        <div class="page-desc">落地页、业务目标输入后，生成计划、单元、关键词、创意、地域与时段草案。</div>
      </div>
      <el-tag type="warning" effect="plain">草案未写入百度</el-tag>
    </div>

    <div class="builder-layout">
      <section class="input-panel">
        <div class="panel-title">输入信息</div>
        <el-form label-position="top" class="builder-form">
          <el-form-item label="落地页内容" required>
            <el-radio-group v-model="landingMode" class="landing-mode">
              <el-radio-button value="url">有落地页链接</el-radio-button>
              <el-radio-button value="text">没有链接，粘贴文字</el-radio-button>
            </el-radio-group>
            <el-input v-if="landingMode === 'url'" v-model="form.landingUrl" placeholder="https://..." clearable />
            <el-input
              v-else
              v-model="form.landingText"
              type="textarea"
              :rows="4"
              placeholder="粘贴图片式落地页中的产品、服务与联系方式等主要文字"
            />
          </el-form-item>
          <el-form-item label="业务概述" required>
            <el-input
              v-model="form.businessSummary"
              type="textarea"
              :rows="5"
              placeholder="客户主营业务、核心产品、目标客户、服务范围"
            />
          </el-form-item>
          <div class="form-grid">
            <el-form-item label="投放目的" required>
              <el-select v-model="form.goal">
                <el-option label="获取高意向线索" value="获取高意向线索" />
                <el-option label="电话咨询" value="电话咨询" />
                <el-option label="表单提交" value="表单提交" />
                <el-option label="品牌曝光" value="品牌曝光" />
                <el-option label="电商成交" value="电商成交" />
              </el-select>
            </el-form-item>
            <el-form-item label="设备偏好">
              <el-select v-model="form.devicePreference">
                <el-option label="不限" value="不限" />
                <el-option label="移动优先" value="移动优先" />
                <el-option label="PC 优先" value="PC 优先" />
                <el-option label="只投移动" value="只投移动" />
                <el-option label="只投 PC" value="只投 PC" />
              </el-select>
            </el-form-item>
          </div>
          <div class="form-grid">
            <el-form-item label="预算">
              <el-input v-model="form.budget" placeholder="例如：日预算 300 元" />
            </el-form-item>
            <el-form-item label="区域">
              <el-input v-model="form.regions" placeholder="例如：北京、天津、河北" />
            </el-form-item>
          </div>
          <el-form-item label="投放时段">
            <div class="schedule-control">
              <div class="schedule-presets">
                <button
                  v-for="preset in schedulePresets"
                  :key="preset.value"
                  type="button"
                  class="preset-btn"
                  :class="{ active: form.schedulePreset === preset.value }"
                  @click="applySchedulePreset(preset.value)"
                >
                  {{ preset.label }}
                </button>
              </div>
              <div v-if="form.schedulePreset === 'custom'" class="custom-schedule">
                <div v-for="(block, index) in form.scheduleBlocks" :key="index" class="schedule-block">
                  <div class="week-toggle-row">
                    <button
                      v-for="day in weekOptions"
                      :key="day.value"
                      type="button"
                      class="week-btn"
                      :class="{ active: block.weekDays.includes(day.value) }"
                      @click="toggleWeekDay(block, day.value)"
                    >
                      {{ day.label.slice(1) }}
                    </button>
                  </div>
                  <div class="time-edit-row">
                    <div class="hour-range">
                      <el-select v-model="block.startHour" @change="normalizeScheduleBlock(block)">
                        <el-option v-for="hour in hourOptions.slice(0, 24)" :key="hour.value" :label="hour.label" :value="hour.value" />
                      </el-select>
                      <span>至</span>
                      <el-select v-model="block.endHour" @change="normalizeScheduleBlock(block)">
                        <el-option v-for="hour in hourOptions.slice(1)" :key="hour.value" :label="hour.label" :value="hour.value" />
                      </el-select>
                    </div>
                    <button type="button" class="icon-btn" @click="removeScheduleBlock(index)">删除</button>
                  </div>
                </div>
                <button type="button" class="add-time-btn" @click="addScheduleBlock">添加时段</button>
              </div>
              <div class="schedule-preview">{{ scheduleText }}</div>
            </div>
          </el-form-item>
          <el-button type="primary" class="generate-btn" :loading="loading" @click="onGenerate">
            {{ loading ? loadingHint.title : '生成搭建草案' }}
          </el-button>
          <div v-if="loading" class="loading-note">{{ loadingHint.desc }}</div>
        </el-form>
      </section>

      <section class="result-panel">
        <template v-if="loading && !draft">
          <div class="empty-state loading-state">
            <div class="loading-orbit">
              <span></span>
              <b>AI</b>
            </div>
            <div class="empty-title">{{ loadingHint.title }}</div>
            <div class="empty-desc">{{ loadingHint.desc }}</div>
            <div class="loading-steps">
              <span
                v-for="(phase, index) in loadingPhases"
                :key="phase.title"
                :class="{ active: index <= loadingPhaseIndex }"
              ></span>
            </div>
          </div>
        </template>

        <template v-else-if="!draft">
          <div class="empty-state">
            <div class="empty-mark">AI</div>
            <div class="empty-title">等待生成搭建草案</div>
            <div class="empty-desc">生成后可以直接修改计划、单元、关键词和创意，并勾选需要保留的内容。</div>
          </div>
        </template>

        <template v-else>
          <div v-if="loading" class="result-loading-bar">
            <span>{{ loadingHint.title }}</span>
            <em>{{ loadingHint.desc }}</em>
          </div>
          <div class="result-head">
            <div>
              <div class="result-title">搭建草案</div>
              <div class="result-meta">
                {{ sourceLabel }}
                <span v-if="result.fetched_title"> · {{ result.fetched_title }}</span>
              </div>
            </div>
            <div class="head-actions">
              <div class="selected-summary">
                已选 {{ stats.campaigns }} 计划 / {{ stats.adgroups }} 单元 / {{ stats.keywords }} 关键词 / {{ stats.creatives }} 创意
              </div>
              <el-button @click="exportDraft">导出 JSON</el-button>
              <el-button
                type="primary"
                :loading="applying"
                :disabled="!stats.campaigns || !stats.adgroups || !stats.keywords"
                @click="onApplyDraft"
              >
                {{ applying ? '演练写入中' : '一键搭建到百度（演练）' }}
              </el-button>
            </div>
          </div>

          <div v-if="applyResult" class="apply-result" :class="{ failed: applyResult.summary?.failed }">
            <div class="apply-result-head">
              <strong>{{ applyResult.dry_run ? '演练完成，未真实写入百度' : '写入完成' }}</strong>
              <span>
                共 {{ applyResult.summary?.total || 0 }} 条 ·
                演练 {{ applyResult.summary?.dry_run || 0 }} 条 ·
                成功 {{ applyResult.summary?.success || 0 }} 条 ·
                失败 {{ applyResult.summary?.failed || 0 }} 条
              </span>
            </div>
            <div class="apply-actions">
              <div v-for="action in applyResult.actions" :key="action.id" class="apply-action">
                <span class="action-type">{{ actionLabels[action.action_type] || action.action_type }}</span>
                <span class="action-word">{{ action.word }}</span>
                <span class="action-status" :class="action.status">{{ action.status === 'dry_run' ? '演练' : action.status === 'success' ? '成功' : '失败' }}</span>
                <span v-if="action.error_msg" class="action-error">{{ action.error_msg }}</span>
              </div>
            </div>
          </div>

          <div class="brief-box">
            <div class="brief-main">{{ draft.summary }}</div>
            <div v-if="draft.assumptions?.length" class="brief-list">
              <span v-for="item in draft.assumptions" :key="item">{{ item }}</span>
            </div>
          </div>

          <div class="campaign-stack">
            <article v-for="(camp, cidx) in draft.campaigns" :key="cidx" class="campaign-card">
              <div class="level-label">计划 {{ cidx + 1 }}</div>
              <div class="campaign-top">
                <el-checkbox v-model="camp.selected" />
                <el-input v-model="camp.name" class="campaign-name" />
                <span class="price-label">日预算</span>
                <el-input-number v-model="camp.budget" :min="0" :step="50" controls-position="right" />
              </div>
              <div class="campaign-settings">
                <label>
                  <span>投放地域</span>
                  <el-input
                    :model-value="arrayText(camp.regions)"
                    placeholder="不限，或输入北京、天津、河北"
                    @input="updateArrayField(camp, 'regions', $event)"
                  />
                </label>
                <label>
                  <span>投放时段</span>
                  <el-input
                    :model-value="arrayText(camp.schedule)"
                    placeholder="周一至周日 09:00-22:00"
                    @input="updateArrayField(camp, 'schedule', $event)"
                  />
                </label>
                <label>
                  <span>设备</span>
                  <el-select v-model="camp.device">
                    <el-option label="不限" value="不限" />
                    <el-option label="移动优先" value="移动优先" />
                    <el-option label="PC 优先" value="PC 优先" />
                    <el-option label="只投移动" value="只投移动" />
                    <el-option label="只投 PC" value="只投 PC" />
                  </el-select>
                </label>
              </div>

              <div v-for="(adg, aidx) in camp.adgroups" :key="aidx" class="adgroup-block">
                <div class="level-label unit">单元 {{ aidx + 1 }}</div>
                <div class="adgroup-head">
                  <el-checkbox v-model="adg.selected" />
                  <el-input v-model="adg.name" class="adgroup-name" />
                  <span class="price-label">单元出价</span>
                  <el-input-number v-model="adg.max_price" :min="0" :step="0.1" :precision="2" controls-position="right" />
                </div>
                <el-input v-model="adg.landing_page" class="landing-input" placeholder="单元落地页 URL" />

                <div class="sub-title">关键词</div>
                <div class="keyword-table-wrap">
                  <el-table :data="adg.keywords" size="small" border class="keyword-table">
                    <el-table-column width="46" fixed="left">
                      <template #default="{ row }"><el-checkbox v-model="row.selected" /></template>
                    </el-table-column>
                    <el-table-column prop="word" label="关键词" min-width="190">
                      <template #default="{ row }"><el-input v-model="row.word" /></template>
                    </el-table-column>
                    <el-table-column prop="match" label="匹配方式" width="130">
                      <template #default="{ row }"><el-input v-model="row.match" /></template>
                    </el-table-column>
                    <el-table-column prop="bid" label="关键词出价" width="150">
                      <template #default="{ row }">
                        <el-input-number v-model="row.bid" :min="0" :precision="2" :step="0.1" controls-position="right" />
                      </template>
                    </el-table-column>
                    <el-table-column prop="reason" label="生成依据" min-width="220">
                      <template #default="{ row }">
                        <span class="reason-text">{{ row.reason }}</span>
                      </template>
                    </el-table-column>
                  </el-table>
                </div>

                <div class="sub-title">创意</div>
                <div v-for="(cr, ridx) in adg.creatives" :key="ridx" class="creative-row">
                  <el-checkbox v-model="cr.selected" />
                  <el-input v-model="cr.title" placeholder="标题" />
                  <el-input v-model="cr.description1" placeholder="描述 1" />
                  <el-input v-model="cr.description2" placeholder="描述 2" />
                </div>

                <div v-if="adg.negative_words?.length" class="negative-line">
                  <span>否词</span>
                  <el-tag v-for="w in adg.negative_words" :key="w" size="small" type="danger" effect="plain">{{ w }}</el-tag>
                </div>
              </div>
            </article>
          </div>

          <div class="risk-row" v-if="draft.risks?.length || draft.next_steps?.length">
            <div v-if="draft.risks?.length">
              <div class="risk-title">风险提示</div>
              <p v-for="r in draft.risks" :key="r">{{ r }}</p>
            </div>
            <div v-if="draft.next_steps?.length">
              <div class="risk-title">下一步</div>
              <p v-for="s in draft.next_steps" :key="s">{{ s }}</p>
            </div>
          </div>
        </template>
      </section>
    </div>
  </div>
</template>

<style scoped>
.builder-page { padding-bottom: 24px; }
.page-header { margin-bottom: 14px; display: flex; justify-content: space-between; align-items: flex-end; }
.page-title { font-size: 20px; font-weight: 600; color: var(--sem-text); }
.page-desc { font-size: 12px; color: var(--sem-text-sub); margin-top: 4px; }
.builder-layout { display: grid; grid-template-columns: 360px minmax(0, 1fr); gap: 14px; align-items: start; }
.input-panel,
.result-panel {
  background: #fff;
  border: 1px solid var(--sem-border);
  border-radius: 8px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03);
}
.input-panel { padding: 16px; position: sticky; top: 14px; }
.result-panel { min-height: 620px; padding: 16px; }
.panel-title,
.result-title { font-size: 15px; font-weight: 700; color: var(--sem-text); }
.builder-form { margin-top: 14px; }
.guide-block {
  margin-bottom: 14px;
  padding: 12px;
  border: 1px solid #e6edf6;
  border-radius: 8px;
  background: #f8fafc;
}
.guide-question {
  color: var(--sem-text);
  font-size: 13px;
  font-weight: 700;
  margin-bottom: 9px;
}
.guide-options {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.guide-option {
  min-height: 58px;
  border: 1px solid #dce3ec;
  border-radius: 7px;
  background: #fff;
  padding: 9px 10px;
  text-align: left;
  cursor: pointer;
  display: grid;
  gap: 3px;
  transition: border-color 0.12s, background 0.12s, box-shadow 0.12s;
}
.guide-option:hover {
  border-color: #b8cbe2;
  background: #fbfdff;
}
.guide-option.active {
  border-color: var(--sem-primary);
  background: #edf4ff;
  box-shadow: inset 0 0 0 1px rgba(24, 95, 165, 0.12);
}
.guide-main {
  color: var(--sem-text);
  font-size: 13px;
  font-weight: 700;
}
.guide-option.active .guide-main { color: var(--sem-primary); }
.guide-sub {
  color: var(--sem-text-sub);
  font-size: 11px;
  line-height: 1.35;
}
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.schedule-control {
  width: 100%;
  display: grid;
  gap: 9px;
}
.schedule-presets {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}
.preset-btn,
.add-time-btn,
.icon-btn {
  border: 1px solid #dce3ec;
  background: #fff;
  color: #5f6f82;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 700;
  transition: border-color 0.12s, background 0.12s, color 0.12s;
}
.preset-btn {
  height: 32px;
  font-size: 12px;
}
.preset-btn:hover,
.add-time-btn:hover,
.icon-btn:hover {
  border-color: #b8cbe2;
  background: #fbfdff;
}
.preset-btn.active {
  border-color: var(--sem-primary);
  background: #edf4ff;
  color: var(--sem-primary);
}
.custom-schedule {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid #edf1f5;
  border-radius: 7px;
  background: #fafcff;
}
.schedule-block {
  display: grid;
  gap: 9px;
  padding: 9px;
  border: 1px solid #e7edf5;
  border-radius: 7px;
  background: #fff;
}
.week-toggle-row {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 4px;
}
.week-btn {
  height: 28px;
  border: 1px solid #dce3ec;
  border-radius: 6px;
  background: #fff;
  color: #6a7888;
  cursor: pointer;
  font-size: 12px;
  font-weight: 700;
  transition: border-color 0.12s, background 0.12s, color 0.12s;
}
.week-btn:hover {
  border-color: #b8cbe2;
  background: #fbfdff;
}
.week-btn.active {
  border-color: var(--sem-primary);
  background: #edf4ff;
  color: var(--sem-primary);
}
.time-edit-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 58px;
  gap: 8px;
  align-items: center;
}
.hour-range {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 18px minmax(0, 1fr);
  gap: 6px;
  align-items: center;
}
.hour-range span {
  color: var(--sem-text-sub);
  font-size: 12px;
  text-align: center;
}
.icon-btn {
  height: 32px;
  font-size: 12px;
}
.add-time-btn {
  height: 32px;
  font-size: 12px;
  color: var(--sem-primary);
}
.schedule-preview {
  min-height: 28px;
  padding: 6px 9px;
  border-radius: 6px;
  background: #f8fafc;
  color: #5f6f82;
  font-size: 12px;
  line-height: 1.5;
}
.generate-btn { width: 100%; margin-top: 2px; }
.loading-note {
  margin-top: 8px;
  padding: 8px 10px;
  border-radius: 6px;
  background: #f3f8ff;
  color: #5a7188;
  font-size: 12px;
  line-height: 1.5;
}
.empty-state {
  min-height: 560px;
  display: grid;
  place-content: center;
  justify-items: center;
  text-align: center;
  color: var(--sem-text-sub);
}
.empty-mark {
  width: 42px;
  height: 42px;
  border-radius: 8px;
  background: #eff4fb;
  color: var(--sem-primary);
  display: grid;
  place-items: center;
  font-weight: 800;
  margin-bottom: 12px;
}
.empty-title { color: var(--sem-text); font-size: 16px; font-weight: 700; }
.empty-desc { max-width: 360px; margin-top: 6px; font-size: 12px; line-height: 1.7; }
.loading-state {
  align-content: center;
}
.loading-orbit {
  position: relative;
  width: 54px;
  height: 54px;
  margin-bottom: 14px;
  display: grid;
  place-items: center;
}
.loading-orbit span {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  border: 2px solid #d8eaff;
  border-top-color: var(--sem-primary);
  animation: sem-spin 1s linear infinite;
}
.loading-orbit b {
  width: 38px;
  height: 38px;
  border-radius: 8px;
  background: #eff4fb;
  color: var(--sem-primary);
  display: grid;
  place-items: center;
  font-size: 14px;
}
.loading-steps {
  width: min(320px, 80%);
  margin-top: 16px;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 6px;
}
.loading-steps span {
  height: 4px;
  border-radius: 999px;
  background: #e4eaf1;
}
.loading-steps span.active {
  background: var(--sem-primary);
}
.result-loading-bar {
  margin-bottom: 12px;
  padding: 9px 11px;
  border: 1px solid #d8eaff;
  border-radius: 7px;
  background: #f3f8ff;
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}
.result-loading-bar span {
  color: var(--sem-primary);
  font-size: 13px;
  font-weight: 700;
}
.result-loading-bar em {
  color: #5a7188;
  font-size: 12px;
  font-style: normal;
}
@keyframes sem-spin {
  to { transform: rotate(360deg); }
}
.result-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 12px; }
.result-meta { margin-top: 4px; font-size: 12px; color: var(--sem-text-sub); }
.head-actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; flex-wrap: wrap; }
.selected-summary {
  height: 30px;
  padding: 0 10px;
  border-radius: 6px;
  background: #f8fafc;
  border: 1px solid #edf1f5;
  color: #5f6f82;
  font-size: 12px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  white-space: nowrap;
}
.apply-result {
  margin-bottom: 12px;
  padding: 11px 12px;
  border: 1px solid #d8eaff;
  border-radius: 8px;
  background: #f5f9ff;
}
.apply-result.failed {
  border-color: #ffd6d6;
  background: #fff7f7;
}
.apply-result-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 9px;
  color: var(--sem-text);
}
.apply-result-head strong {
  font-size: 13px;
}
.apply-result-head span {
  color: var(--sem-text-sub);
  font-size: 12px;
  white-space: nowrap;
}
.apply-actions {
  display: grid;
  gap: 6px;
  max-height: 178px;
  overflow: auto;
}
.apply-action {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr) 54px;
  gap: 8px;
  align-items: center;
  min-height: 30px;
  padding: 6px 8px;
  border: 1px solid #e7edf5;
  border-radius: 6px;
  background: #fff;
  color: #4b5d72;
  font-size: 12px;
}
.action-type {
  color: var(--sem-primary);
  font-weight: 700;
}
.action-word {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.action-status {
  justify-self: end;
  padding: 2px 7px;
  border-radius: 999px;
  background: #edf4ff;
  color: var(--sem-primary);
  font-weight: 700;
}
.action-status.success {
  background: #eaf8f1;
  color: #1d9e75;
}
.action-status.failed {
  background: #fff0f0;
  color: #d64b4b;
}
.action-error {
  grid-column: 2 / 4;
  color: #d64b4b;
  line-height: 1.5;
}
.brief-box {
  border: 1px solid #d8eaff;
  background: #f3f8ff;
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 12px;
}
.brief-main { color: var(--sem-text); font-weight: 600; line-height: 1.7; }
.brief-list { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px; }
.brief-list span { font-size: 12px; color: #41627f; background: #fff; border: 1px solid #d8eaff; border-radius: 999px; padding: 3px 8px; }
.campaign-stack { display: grid; gap: 12px; }
.campaign-card { border: 1px solid #dce8f6; border-radius: 8px; padding: 12px; background: #fff; }
.level-label {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 8px;
  margin-bottom: 10px;
  border-radius: 5px;
  background: #eaf3ff;
  color: var(--sem-primary);
  font-size: 12px;
  font-weight: 700;
}
.level-label.unit {
  background: #eef7f2;
  color: #1d9e75;
}
.campaign-top,
.adgroup-head {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr) auto 180px;
  gap: 10px;
  align-items: center;
}
.campaign-name :deep(.el-input__wrapper),
.adgroup-name :deep(.el-input__wrapper) { font-weight: 700; }
.campaign-settings {
  margin: 10px 0 4px 34px;
  padding: 10px;
  display: grid;
  grid-template-columns: minmax(220px, 1.25fr) minmax(220px, 1.25fr) 140px;
  gap: 10px;
  border: 1px solid #edf1f5;
  border-radius: 7px;
  background: #fafcff;
}
.campaign-settings label {
  min-width: 0;
  display: grid;
  gap: 5px;
}
.campaign-settings span {
  color: var(--sem-text-sub);
  font-size: 12px;
  font-weight: 700;
}
.adgroup-block { margin-top: 12px; padding: 12px; border-radius: 8px; background: #f8fafc; border: 1px solid #edf1f5; }
.price-label { font-size: 12px; color: var(--sem-text-sub); white-space: nowrap; }
.landing-input { margin: 10px 0 12px 34px; width: calc(100% - 34px); }
.sub-title { color: var(--sem-text-sub); font-size: 12px; font-weight: 700; margin: 10px 0 8px; }
.keyword-table-wrap {
  width: 100%;
  overflow-x: auto;
  border-radius: 6px;
}
.keyword-table { min-width: 820px; }
.reason-text {
  color: #6b7280;
  font-size: 12px;
  line-height: 1.5;
}
.creative-row {
  display: grid;
  grid-template-columns: 24px 170px minmax(0, 1fr) minmax(0, 1fr);
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}
.negative-line { display: flex; align-items: center; gap: 6px; margin-top: 10px; color: var(--sem-text-sub); font-size: 12px; }
.risk-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px; }
.risk-row > div { border: 1px solid var(--sem-border); border-radius: 8px; padding: 12px; background: #fff; }
.risk-title { color: var(--sem-text); font-size: 13px; font-weight: 700; margin-bottom: 6px; }
.risk-row p { margin: 4px 0; color: var(--sem-text-sub); font-size: 12px; line-height: 1.6; }
@media (max-width: 1100px) {
  .builder-layout { grid-template-columns: 1fr; }
  .input-panel { position: static; }
  .creative-row { grid-template-columns: 24px 1fr; }
  .result-head { display: grid; }
  .head-actions { justify-content: flex-start; }
  .campaign-settings { grid-template-columns: 1fr; }
  .schedule-presets,
  .schedule-block { grid-template-columns: 1fr; }
}
</style>
