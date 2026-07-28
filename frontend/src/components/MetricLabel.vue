<script setup>
// 指标标签 + 「?」悬停提示。提示文案来自 metric（查 METRIC_HINTS）或显式 hint。
import { METRIC_HINTS } from '../constants/metrics'

defineProps({
  label: { type: String, required: true },
  metric: { type: String, default: '' },
  hint: { type: String, default: '' },
  placement: { type: String, default: 'top' },
})
</script>

<template>
  <span class="metric-label">
    <span>{{ label }}</span>
    <el-tooltip
      v-if="hint || METRIC_HINTS[metric]"
      :content="hint || METRIC_HINTS[metric]"
      :placement="placement"
      effect="dark"
      :show-after="100"
    >
      <span class="hint-icon">?</span>
    </el-tooltip>
  </span>
</template>

<style scoped>
.metric-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.hint-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  flex: none;
  border: 1px solid #c0c4cc;
  border-radius: 50%;
  color: #909399;
  font-size: 10px;
  font-weight: 600;
  font-style: normal;
  line-height: 1;
  cursor: help;
  user-select: none;
}
.hint-icon:hover {
  border-color: var(--el-color-primary, #185fa5);
  color: var(--el-color-primary, #185fa5);
}
</style>
