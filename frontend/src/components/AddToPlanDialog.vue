<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { addCandidateToPlan } from '../api/expansion'
import { fetchAdgroupList, fetchCampaignList } from '../api/keywords'

const props = defineProps({
  tenantId: { type: [Number, String], required: true },
})
const emit = defineEmits(['success'])

const dialog = reactive({
  visible: false,
  row: null,
  campaignId: null,
  adgroupId: null,
  matchMode: 'phrase',
  price: null,
  submitting: false,
})
const campaigns = ref([])
const adgroups = ref([])
const word = computed(() => dialog.row?.word || '')

async function open(row) {
  Object.assign(dialog, {
    visible: true,
    row,
    campaignId: null,
    adgroupId: null,
    matchMode: row?.preset_match_mode || 'phrase',
    price: row?.preset_price ?? row?.ai_suggested_bid ?? row?.recommend_price_pc ?? null,
    submitting: false,
  })
  adgroups.value = []
  if (!campaigns.value.length) {
    try {
      campaigns.value = (await fetchCampaignList({ tenantId: props.tenantId })).campaigns || []
    } catch (e) {
      ElMessage.error('加载计划失败：' + (e.message || ''))
    }
  }
}

async function onCampaignChange(campaignId) {
  dialog.adgroupId = null
  adgroups.value = []
  if (!campaignId) return
  try {
    adgroups.value = (await fetchAdgroupList({ tenantId: props.tenantId, campaignId })).adgroups || []
  } catch (e) {
    ElMessage.error('加载单元失败：' + (e.message || ''))
  }
}

async function submit() {
  if (!dialog.adgroupId) return ElMessage.warning('请选择目标单元')
  if (!(Number(dialog.price) > 0)) return ElMessage.warning('请输入有效出价')
  dialog.submitting = true
  try {
    const res = await addCandidateToPlan({
      tenantId: props.tenantId,
      candidateId: dialog.row.id,
      adgroupId: dialog.adgroupId,
      price: Number(dialog.price),
      matchMode: dialog.matchMode,
    })
    if (res.dry_run) ElMessage.warning('演练模式：已记入台账，未真改线上（候选保留待处理）')
    else ElMessage.success(`「${word.value}」已加入计划`)
    dialog.visible = false
    emit('success', res)
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  } finally {
    dialog.submitting = false
  }
}

defineExpose({ open })
</script>

<template>
  <el-dialog v-model="dialog.visible" title="加入计划" width="440px">
    <div v-if="dialog.row" class="plan-form">
      <div class="pf-word">候选词：<b>{{ word }}</b></div>
      <el-form label-width="72px" label-position="left">
        <el-form-item label="计划">
          <el-select v-model="dialog.campaignId" placeholder="选择计划" style="width: 100%" @change="onCampaignChange">
            <el-option v-for="c in campaigns" :key="c.campaign_id" :label="c.campaign_name" :value="c.campaign_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="单元">
          <el-select v-model="dialog.adgroupId" placeholder="先选计划" style="width: 100%" :disabled="!dialog.campaignId">
            <el-option v-for="a in adgroups" :key="a.adgroup_id" :label="a.adgroup_name" :value="a.adgroup_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="匹配方式">
          <el-radio-group v-model="dialog.matchMode">
            <el-radio label="phrase">短语</el-radio>
            <el-radio label="exact">精确</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="出价">
          <el-input-number v-model="dialog.price" :min="0.01" :max="999.99" :step="0.1" :precision="2" />
          <span v-if="dialog.row.recommend_price_pc" class="pf-hint">指导价 ¥{{ dialog.row.recommend_price_pc }}</span>
        </el-form-item>
        <div v-if="dialog.row.ai_bid_reason" class="pf-ai">
          AI 建议 <b>¥{{ dialog.row.ai_suggested_bid }}</b>：{{ dialog.row.ai_bid_reason }}
        </div>
      </el-form>
      <div class="pf-tip">走 ±20% 区间校验并记台账；演练模式下不真改线上。</div>
    </div>
    <template #footer>
      <el-button @click="dialog.visible = false">取消</el-button>
      <el-button type="primary" :loading="dialog.submitting" @click="submit">确认加入</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.plan-form { font-size: 13px; }
.pf-word { margin-bottom: 12px; color: var(--sem-text); }
.pf-hint { margin-left: 10px; font-size: 12px; color: #909399; }
.pf-ai { margin: 4px 0 10px; padding: 8px 10px; border-radius: 6px; background: #f0f7ff; color: #185fa5; font-size: 12px; line-height: 1.6; }
.pf-tip { margin-top: 4px; font-size: 12px; color: #ba7517; }
</style>
