<script setup>
/**
 * 统一披露真采样 / 模拟 / 人工，以及是否可对外汇报。
 * 无真采样时不得把指标读成 0%。
 */
import { computed } from 'vue'

const props = defineProps({
  composition: { type: Object, default: null },
  windowLabel: { type: String, default: '' },
  enginesCovered: { type: [Number, String], default: null },
  sampledAt: { type: String, default: '' },
  compact: { type: Boolean, default: false },
})

const comp = computed(() => props.composition || {})
const visible = computed(() => Number(comp.value.total || 0) > 0 || comp.value.verdict)
const realN = computed(() => Number(comp.value.real || 0))
const simN = computed(() => Number(comp.value.simulated || 0))
const manN = computed(() => Number(comp.value.manual || 0))
const suitable = computed(() => !!comp.value.suitable_for_client)
const verdict = computed(() => comp.value.verdict || (realN.value > 0 ? '可复核' : '未形成有效结论'))
const reason = computed(() => comp.value.verdict_reason || '')
const alertType = computed(() => {
  if (realN.value <= 0) return 'warning'
  if (simN.value > 0) return 'warning'
  if (suitable.value) return 'success'
  return 'info'
})
</script>

<template>
  <el-alert
    v-if="visible"
    :type="alertType"
    :closable="false"
    show-icon
    class="mb cred-alert"
    :title="verdict"
    :description="compact ? undefined : (reason || undefined)"
  >
    <template #default>
      <div class="cred-line">
        <span>真采样 {{ realN }}</span>
        <span>模拟 {{ simN }}</span>
        <span>人工 {{ manN }}</span>
        <span v-if="enginesCovered != null">覆盖引擎 {{ enginesCovered }}</span>
        <span v-if="sampledAt">采样 {{ sampledAt }}</span>
        <span v-if="windowLabel">{{ windowLabel }}</span>
      </div>
      <div v-if="!compact && reason" class="cred-reason">{{ reason }}</div>
      <div class="cred-rule">
        模拟样本只用于流程演示和策略预判。客户交付默认只统计真采样。
        发布影响统一表述为「发布后观察到的相关变化」，不宣称确定因果。
      </div>
      <el-tag v-if="suitable" size="small" type="success">可对外汇报</el-tag>
      <el-tag v-else size="small" type="warning">不适合对外汇报</el-tag>
    </template>
  </el-alert>
</template>

<style scoped>
.mb { margin-bottom: 14px; }
.cred-line {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  font-size: 13px;
  color: #334155;
  margin-bottom: 6px;
}
.cred-reason { font-size: 12px; color: #64748b; line-height: 1.5; margin-bottom: 6px; }
.cred-rule { font-size: 12px; color: #64748b; line-height: 1.5; margin-bottom: 8px; }
</style>
