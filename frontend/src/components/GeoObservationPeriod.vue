<script setup>
import { useObservationPeriod } from '../composables/useObservationPeriod'

const {
  days,
  label,
  allowedDays,
  setDays,
} = useObservationPeriod()
</script>

<template>
  <div
    class="geo-obs-period"
    title="GEO 报表默认观察期（上海日历日）；全时段指标会在页面单独标注"
  >
    <span class="geo-obs-period-label">查询期</span>
    <el-select
      :model-value="days"
      size="small"
      class="geo-obs-period-select"
      @change="setDays"
    >
      <el-option
        v-for="d in allowedDays"
        :key="d"
        :label="`近 ${d} 天`"
        :value="d"
      />
    </el-select>
    <span class="geo-obs-period-range">{{ label }}</span>
  </div>
</template>

<style scoped>
.geo-obs-period {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px;
  border-radius: 8px;
  background: #f8fafc;
  border: 1px solid #e8edf5;
  font-size: 12px;
  color: #475569;
  flex-wrap: wrap;
}
.geo-obs-period-label {
  font-weight: 600;
  color: #64748b;
  white-space: nowrap;
}
.geo-obs-period-select {
  width: 96px;
}
.geo-obs-period-range {
  font-variant-numeric: tabular-nums;
  color: #64748b;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
@media (max-width: 640px) {
  .geo-obs-period-range { display: none; }
}
</style>
